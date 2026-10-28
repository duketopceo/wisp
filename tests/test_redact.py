"""B9: every visible sensitive window is painted black in a screenshot."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import cua_safety, redact, verify  # noqa: E402

try:
    from PIL import Image
except ImportError:           # pragma: no cover
    Image = None

MON = [{"name": "A", "x": 0, "y": 0, "width": 400, "height": 200,
        "scale": 1, "activeWorkspace": {"id": 1}}]


def win(cls, title, at, size, ws=1, mapped=True, hidden=False):
    return {"class": cls, "title": title, "at": list(at),
            "size": list(size), "workspace": {"id": ws}, "mapped": mapped,
            "hidden": hidden}


FOCUSED = win("firefox", "News", (0, 0), (200, 200))
BANK = win("chrome", "My Bank - Accounts", (200, 0), (200, 100))
CFG = {"cua": {"deny_titles": "bank"}}


@unittest.skipUnless(Image, "Pillow not installed")
class Blanking(unittest.TestCase):
    def shot(self, size=(400, 200)):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = pathlib.Path(td.name) / "s.png"
        Image.new("RGB", size, (255, 255, 255)).save(p)
        return p

    def px(self, p, x, y):
        with Image.open(p) as im:
            return im.convert("RGB").getpixel((x, y))

    def test_a_banking_window_behind_the_focused_one_is_blanked(self):
        p = self.shot()
        why = redact.apply(p, CFG, clients=[FOCUSED, BANK], monitors=MON)
        self.assertEqual(why, "")
        self.assertEqual(self.px(p, 300, 50), (0, 0, 0))      # inside bank
        self.assertEqual(self.px(p, 100, 100), (255, 255, 255))  # focused
        self.assertEqual(self.px(p, 300, 150), (255, 255, 255))  # below it

    def test_a_denied_app_class_is_blanked_without_any_title_rule(self):
        p = self.shot()
        vault = win("1password", "Vault", (0, 100), (400, 100))
        redact.apply(p, {}, clients=[FOCUSED, vault], monitors=MON)
        self.assertEqual(self.px(p, 10, 150), (0, 0, 0))
        self.assertEqual(self.px(p, 10, 50), (255, 255, 255))

    def test_focused_only_handling_is_unchanged(self):
        # nothing sensitive besides what capture_blocked already covers
        p = self.shot()
        before = p.read_bytes()
        self.assertEqual(
            redact.apply(p, CFG, clients=[FOCUSED], monitors=MON), "")
        self.assertEqual(p.read_bytes(), before)

    def test_windows_on_hidden_workspaces_and_unmapped_ones_are_ignored(self):
        p = self.shot()
        far = win("chrome", "bank", (200, 0), (200, 100), ws=7)
        gone = win("chrome", "bank", (200, 0), (200, 100), mapped=False)
        redact.apply(p, CFG, clients=[far, gone], monitors=MON)
        self.assertEqual(self.px(p, 300, 50), (255, 255, 255))

    def test_hidpi_shots_scale_the_region(self):
        p = self.shot(size=(800, 400))            # 2x the logical size
        redact.apply(p, CFG, clients=[BANK], monitors=MON)
        self.assertEqual(self.px(p, 600, 100), (0, 0, 0))
        self.assertEqual(self.px(p, 100, 100), (255, 255, 255))

    def test_a_monitor_offset_is_respected(self):
        mons = [{**MON[0], "x": 100}]
        p = self.shot()
        bank = win("chrome", "bank", (300, 0), (100, 100))   # logical x=300
        redact.apply(p, CFG, clients=[bank], monitors=mons)
        self.assertEqual(self.px(p, 250, 50), (0, 0, 0))     # 300-100+...
        self.assertEqual(self.px(p, 50, 50), (255, 255, 255))

    def test_a_window_outside_the_captured_area_needs_no_blanking(self):
        p = self.shot()
        out = win("chrome", "bank", (5000, 5000), (100, 100))
        self.assertEqual(redact.apply(p, CFG, clients=[out], monitors=MON),
                         "")

    def test_safety_off_disables_it(self):
        p = self.shot()
        cfg = {"cua": {"deny_titles": "bank", "safety": "false"}}
        redact.apply(p, cfg, clients=[BANK], monitors=MON)
        self.assertEqual(self.px(p, 300, 50), (255, 255, 255))

    def test_an_unreadable_window_list_changes_nothing(self):
        p = self.shot()
        before = p.read_bytes()

        def boom():
            raise OSError("no socket")
        self.assertEqual(redact.apply(p, CFG, clients=boom, monitors=MON),
                         "")
        self.assertEqual(p.read_bytes(), before)


class Refusal(unittest.TestCase):
    def test_a_shot_that_cannot_be_blanked_is_refused(self):
        with mock.patch.object(redact, "blank", return_value=False), \
                mock.patch.object(redact, "_size", return_value=(400, 200)):
            why = redact.apply("x.png", CFG, clients=[BANK], monitors=MON)
        self.assertIn("could not be blanked", why)

    def test_a_shot_that_cannot_be_measured_is_refused(self):
        with mock.patch.object(redact, "_size", return_value=None):
            why = redact.apply("x.png", CFG, clients=[BANK], monitors=MON)
        self.assertIn("could not be mapped", why)

    def test_capture_screen_returns_nothing_when_refused(self):
        from wisp import stage_capture
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = pathlib.Path(tmp.name)

        def fake_run(cmd, **kw):
            (run / "screen.png").write_bytes(b"png")
            return mock.Mock(returncode=0)
        with mock.patch.object(stage_capture.config, "RUN_DIR", run), \
                mock.patch.object(cua_safety, "capture_blocked",
                                  return_value=""), \
                mock.patch("wisp.platform.screenshot_cmd",
                           return_value=["grim"]), \
                mock.patch.object(stage_capture._cancel, "run", fake_run), \
                mock.patch("wisp.tools.system._normalize_shot"), \
                mock.patch.object(redact, "apply",
                                  return_value="hidden window"):
            out = stage_capture.capture_screen()
        self.assertIsNone(out)
        self.assertFalse((run / "screen.png").exists())


class TitlePolicy(unittest.TestCase):
    def test_deny_titles_match_the_title_not_the_class(self):
        s = cua_safety.settings(CFG)
        self.assertTrue(cua_safety.deny_match("chrome", "My Bank", CFG, s=s))
        self.assertFalse(cua_safety.deny_match("chrome", "News", CFG, s=s))
        self.assertFalse(cua_safety.deny_match("chrome", "My Bank", {}))

    def test_a_focused_titled_window_blocks_capture_as_before(self):
        why = cua_safety.capture_blocked(
            CFG, {"app": "chrome", "title": "Online Banking"})
        self.assertIn("bank", why)

    def test_visible_deny_still_returns_the_first_offender(self):
        off, readable = verify.visible_deny(CFG, [FOCUSED, BANK], MON)
        self.assertEqual((off, readable), (BANK, True))
        found, _ = verify.visible_deny_all(CFG, [BANK, BANK], MON)
        self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()
