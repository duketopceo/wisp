"""scripts/click_probe.py offline: scoring, the page's button table, the
run loop over a fake rig, the spend file and the CLI. Never launches a
browser, touches the compositor or calls a model."""
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "click_probe", ROOT / "scripts" / "click_probe.py")
probe = importlib.util.module_from_spec(_spec)
sys.modules["click_probe"] = probe      # dataclasses resolves its module
_spec.loader.exec_module(probe)

EDP = {"name": "eDP-1", "x": 0, "y": 0, "width": 3456, "height": 2160,
       "scale": 2.0}
DP3 = {"name": "DP-3", "x": 1728, "y": 0, "width": 3440, "height": 1440,
       "scale": 1.0}


class FakeRig:
    """A desktop where every page fills its monitor and `grounder` decides
    where the model points. A click inside a button's 40px radius
    reports it in the window title, as targets.html does."""

    def __init__(self, grounder, monitors=(EDP, DP3), fullscreen=True,
                 cost=0.0):
        self.grounder, self.mons = grounder, list(monitors)
        self.fullscreen, self.cost = fullscreen, cost
        self.mon = None
        self.seq = 0
        self.title_now = "probe-ready:0"
        self.spent = 0.0
        self.clicks, self.closed = [], 0

    def rig(self):
        return probe.Rig(
            monitors=lambda: self.mons, open_page=self.open_page,
            window_rect=self.window_rect, ground=self.ground,
            click=self.click, title=lambda h: self.title_now,
            close=self.close, spend=lambda: self.spent,
            sleep=lambda s: None)

    def open_page(self, mon):
        self.mon = mon
        self.title_now = "probe-ready:0"
        return "h"

    def window_rect(self, h):
        x, y, w, hh = probe.logical_rect(self.mon)
        return (x, y, w, hh) if self.fullscreen else (x, y, w / 2, hh)

    def ground(self, name):
        self.spent += self.cost
        n = int(re.search(r"(\d+)$", name).group(1))
        return self.grounder(self.mon, n)

    def click(self, x, y):
        self.clicks.append((x, y))
        for n, fx, fy in probe.TARGETS:
            ex, ey = probe.expected_point(self.mon, fx, fy)
            if abs(x - ex) <= 40 and abs(y - ey) <= 40:
                self.seq += 1
                self.title_now = f"hit:{n}:{self.seq}"
        return True

    def close(self, h):
        self.closed += 1


def perfect(mon, n):
    fx, fy = next((fx, fy) for k, fx, fy in probe.TARGETS if k == n)
    return probe.expected_point(mon, fx, fy)


def halved(mon, n):
    x, y = perfect(mon, n)
    return x // 2, y // 2


class Scoring(unittest.TestCase):
    def row(self, got, after, before="probe-ready:0", number=5):
        return probe.score_row(
            monitor="DP-3", config="hybrid", model="m", number=number,
            expected=(100, 100), got=got, title_before=before,
            title_after=after)

    def test_hit_when_the_title_names_this_button(self):
        r = self.row((103, 104), "hit:5:1")
        self.assertEqual((r["outcome"], r["dist_px"]), ("hit", 5.0))

    def test_miss_when_the_title_did_not_change(self):
        r = self.row((300, 100), "hit:5:1", before="hit:5:1")
        self.assertEqual((r["outcome"], r["dist_px"]), ("miss", 200.0))

    def test_rehitting_the_same_button_still_counts(self):
        r = self.row((100, 100), "hit:5:2", before="hit:5:1")
        self.assertEqual(r["outcome"], "hit")

    def test_wrong_button(self):
        self.assertEqual(self.row((100, 100), "hit:2:1")["outcome"],
                         "wrong")

    def test_ungrounded_has_no_distance(self):
        r = self.row(None, "probe-ready:0")
        self.assertEqual((r["outcome"], r["dist_px"], r["grounded"]),
                         ("ungrounded", None, False))

    def test_title_parse(self):
        self.assertEqual(probe.parse_title("hit:7:3 - Chromium"), (7, 3))
        self.assertIsNone(probe.parse_title("probe-ready:0"))
        self.assertIsNone(probe.parse_title(""))


class Geometry(unittest.TestCase):
    def test_expected_points_use_each_monitors_logical_rect(self):
        # eDP-1 is 1728x1080 logical, DP-3 3440x1440 at x=1728
        self.assertEqual(probe.expected_point(EDP, 0.5, 0.5), (864, 540))
        self.assertEqual(probe.expected_point(DP3, 0.2, 0.2),
                         (1728 + 688, 288))

    def test_page_button_table_matches_the_probe(self):
        html = (ROOT / "scripts" / "probe" / "targets.html").read_text()
        found = re.findall(
            r"\[(\d), ([\d.]+), ([\d.]+)\]", html.split("var BUTTONS")[1])
        self.assertEqual([(int(n), float(a), float(b))
                          for n, a, b in found], probe.TARGETS)

    def test_page_sets_the_title_the_probe_parses(self):
        html = (ROOT / "scripts" / "probe" / "targets.html").read_text()
        self.assertIn('"hit:" + b[0] + ":" + seq', html)


class RunLoop(unittest.TestCase):
    def run_it(self, grounder, **kw):
        fake = FakeRig(grounder, **kw.pop("rig", {}))
        rows = probe.run_probe(fake.rig(), ["eDP-1", "DP-3"],
                               config="hybrid", model="m", **kw)
        return fake, rows

    def test_perfect_grounding_hits_every_button_on_both_monitors(self):
        fake, rows = self.run_it(perfect)
        self.assertEqual(len(rows), 18)
        self.assertTrue(all(r["outcome"] == "hit" and r["dist_px"] == 0
                            for r in rows))
        self.assertEqual(fake.closed, 2)

    def test_the_halved_click_bug_shows_as_large_misses(self):
        _, rows = self.run_it(halved)
        far = [r for r in rows if r["dist_px"] > 100]
        self.assertGreater(len(far), 12)
        self.assertEqual(sum(r["outcome"] == "hit" for r in rows), 0)

    def test_summary_is_per_monitor_config_and_model(self):
        _, rows = self.run_it(perfect)
        s = probe.summarize(rows)
        self.assertEqual([(r["monitor"], r["hits"], r["hit_rate"],
                           r["median_miss_px"]) for r in s],
                         [("DP-3", 9, 1.0, 0.0), ("eDP-1", 9, 1.0, 0.0)])

    def test_a_grounding_exception_is_a_row_not_a_crash(self):
        def boom(mon, n):
            raise RuntimeError("model down")
        _, rows = self.run_it(boom, numbers={1})
        self.assertEqual({r["outcome"] for r in rows}, {"ungrounded"})
        self.assertIn("model down", rows[0]["error"])

    def test_numbers_filter(self):
        _, rows = self.run_it(perfect, numbers={2, 8})
        self.assertEqual(sorted({r["target"] for r in rows}), [2, 8])

    def test_per_run_spend_stop_ends_the_run_early(self):
        fake, rows = self.run_it(perfect, max_usd=0.05,
                                 rig={"cost": 0.02})
        self.assertEqual(len(rows), 3)       # stops once 3 calls cost .06
        self.assertEqual(fake.closed, 1)

    def test_unknown_monitor_is_an_environment_error(self):
        fake = FakeRig(perfect)
        with self.assertRaises(probe.ProbeError):
            probe.run_probe(fake.rig(), ["HDMI-A-9"], config="c", model="m")

    def test_a_window_that_is_not_fullscreen_aborts_the_monitor(self):
        fake = FakeRig(perfect, fullscreen=False)
        with self.assertRaises(probe.ProbeError):
            probe.run_probe(fake.rig(), ["DP-3"], config="c", model="m")
        self.assertEqual(fake.closed, 1)


class SpendFile(unittest.TestCase):
    def test_record_and_total(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "sub" / "spend.jsonl"
            self.assertEqual(probe.spend_total(f), 0.0)
            probe.record_spend(f, 0.25, "hybrid", "m")
            probe.record_spend(f, 0.5, "openrouter", "m2")
            self.assertAlmostEqual(probe.spend_total(f), 0.75)
            rows = [json.loads(x) for x in f.read_text().splitlines()]
            self.assertEqual(rows[0]["source"], "click_probe")


class Cli(unittest.TestCase):
    def main(self, argv, fake=None):
        out, err = io.StringIO(), io.StringIO()
        factory = (lambda cfg: fake.rig()) if fake else \
            (lambda cfg: self.fail("a live rig was built"))
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = probe.main(argv, rig_factory=factory)
        return code, out.getvalue(), err.getvalue()

    def test_without_live_only_the_plan_prints(self):
        code, out, _ = self.main(["--config", "hybrid", "--ground-brain",
                                  "ollama:qwen2.5vl:3b-q8_0"])
        self.assertEqual(code, 0)
        self.assertIn("pass --live", out)
        self.assertIn("ollama:qwen2.5vl:3b-q8_0", out)

    def test_live_run_writes_rows_spend_and_summary(self):
        fake = FakeRig(perfect, cost=0.01)
        with tempfile.TemporaryDirectory() as d:
            out, spend = pathlib.Path(d) / "o.jsonl", pathlib.Path(d) / "s"
            code, text, _ = self.main(
                ["--live", "--config", "hybrid", "--monitors", "DP-3",
                 "--targets", "1,2", "--out", str(out),
                 "--spend-file", str(spend), "--max-usd", "0"], fake)
            self.assertEqual(code, 0)
            self.assertEqual(len(out.read_text().splitlines()), 2)
            self.assertAlmostEqual(probe.spend_total(spend), 0.02)
            self.assertEqual(json.loads(text)["summary"][0]["hits"], 2)

    def test_zero_hits_exits_one(self):
        fake = FakeRig(halved)
        with tempfile.TemporaryDirectory() as d:
            code, _, _ = self.main(
                ["--live", "--monitors", "DP-3", "--targets", "5",
                 "--out", str(pathlib.Path(d) / "o.jsonl")], fake)
        self.assertEqual(code, 1)

    def test_cap_reached_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as d:
            spend = pathlib.Path(d) / "s"
            probe.record_spend(spend, 10.0, "x", "y")
            code, _, err = self.main(
                ["--live", "--spend-file", str(spend)])
        self.assertEqual(code, 2)
        self.assertIn("cap", err)

    def test_bad_targets_and_unknown_monitor_exit_two(self):
        self.assertEqual(self.main(["--targets", "12"])[0], 2)
        self.assertEqual(
            self.main(["--live", "--monitors", "NOPE"], FakeRig(perfect))[0],
            2)

    def test_overrides_set_the_ground_brain_without_mutating_input(self):
        base = {"ground": {"providers": "vlm"}}
        out = probe.apply_overrides(base, "ollama:x", {"brain": {"a": "b"}})
        self.assertEqual(out["ground"]["vlm_brain"], "ollama:x")
        self.assertEqual(out["brain"], {"a": "b"})
        self.assertNotIn("vlm_brain", base["ground"])


ISO = {"HYPRLAND_INSTANCE_SIGNATURE": "ISO_SIG",
       "WAYLAND_DISPLAY": "wayland-iso",
       "XDG_RUNTIME_DIR": "/run/user/1000/wisp-iso-x",
       "DBUS_SESSION_BUS_ADDRESS": "unix:path=/iso/bus",
       "WISP_ISOLATED_SESSION": "1", "WISP_LIVE_SIGNATURE": "LIVE_SIG"}


class Isolated(unittest.TestCase):
    """`--session isolated` (U3): the instance only, behind the canary."""

    def setUp(self):
        import os
        from unittest import mock
        p = mock.patch.dict(os.environ, {
            "HYPRLAND_INSTANCE_SIGNATURE": "LIVE_SIG", "DISPLAY": ":0",
            "WAYLAND_DISPLAY": "wayland-1"})
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.envfile = pathlib.Path(self.tmp.name) / "iso.env"
        probe.isolated.write_env_file(self.envfile, ISO)
        self.cfgs, self.canaries = [], []

    def main(self, argv, fake=None, canary=(True, "ok"), envfile=None):
        out, err = io.StringIO(), io.StringIO()

        def factory(cfg):
            self.cfgs.append(cfg)
            return fake.rig()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = probe.main(
                ["--session", "isolated", "--isolated-env",
                 str(envfile or self.envfile), *argv],
                rig_factory=factory,
                canary=lambda iso: (self.canaries.append(iso) or canary))
        return code, out.getvalue(), err.getvalue()

    def test_run_config_is_isolated_and_drives(self):
        fake = FakeRig(perfect)
        out = pathlib.Path(self.tmp.name) / "o.jsonl"
        code, _, err = self.main(["--live", "--monitors", "DP-3",
                                  "--targets", "1", "--out", str(out),
                                  "--max-usd", "0"], fake)
        self.assertEqual(code, 0, err)
        cfg = self.cfgs[0]
        self.assertEqual(cfg["dev"]["isolated_session"], "true")
        self.assertEqual(cfg["cua"]["delivery"], "background")
        self.assertEqual(cfg["pointer"]["mode"], "drive")
        self.assertEqual(len(self.canaries), 1)

    def test_a_failed_canary_runs_no_target_and_exits_2(self):
        code, _, err = self.main(["--live"], FakeRig(perfect),
                                 canary=(False, "live cursor moved"))
        self.assertEqual(code, 2)
        self.assertIn("canary failed", err)
        self.assertEqual(self.cfgs, [])             # no rig was built

    def test_missing_env_file_names_the_start_command(self):
        code, _, err = self.main(
            ["--live"], envfile=pathlib.Path(self.tmp.name) / "none.env")
        self.assertEqual(code, 2)
        self.assertIn("scripts/isolated_session.py start", err)

    def test_a_target_equal_to_the_live_signature_is_refused(self):
        probe.isolated.write_env_file(self.envfile, {
            **ISO, "HYPRLAND_INSTANCE_SIGNATURE": "LIVE_SIG"})
        code, _, err = self.main(["--live"])
        self.assertEqual(code, 2)
        self.assertIn("equals the live", err)

    def test_plan_only_prints_the_session_and_runs_no_canary(self):
        code, out, _ = self.main([])
        self.assertEqual(code, 0)
        self.assertIn("session=isolated", out)
        self.assertEqual(self.canaries, [])

    def test_live_rig_opens_pages_and_reads_titles_in_the_instance(self):
        import os
        import shutil
        from unittest import mock
        from wisp import hypr
        seen = {}

        def query(name, *a, **k):
            seen["sig"] = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
            seen["wl"] = os.environ["WAYLAND_DISPLAY"]
            return [{"title": "hit:3:1", "at": [0, 0], "size": [10, 10]}]
        popen = mock.Mock()
        with probe.isolated.applied_env(ISO), \
                mock.patch.object(shutil, "which",
                                  return_value="/usr/bin/chromium"), \
                mock.patch.object(hypr, "available", return_value=True), \
                mock.patch.object(hypr, "query", side_effect=query), \
                mock.patch.object(hypr, "run_lua") as run_lua, \
                mock.patch.object(probe.subprocess, "Popen", popen), \
                mock.patch.object(probe.tempfile, "mkdtemp",
                                  return_value=self.tmp.name + "/prof"):
            rig = probe.live_rig(probe.isolate_config({}))
            handle = rig.open_page(EDP)
            title = rig.title(handle)
        argv, kw = popen.call_args[0][0], popen.call_args[1]
        self.assertIn("--ozone-platform=wayland", argv)
        self.assertEqual(kw["env"]["WAYLAND_DISPLAY"], "wayland-iso")
        self.assertEqual(kw["env"]["DBUS_SESSION_BUS_ADDRESS"],
                         "unix:path=/iso/bus")
        self.assertNotIn("DISPLAY", kw["env"])
        run_lua.assert_not_called()             # no cursor warp
        self.assertEqual(title, "hit:3:1")
        self.assertEqual(seen, {"sig": "ISO_SIG", "wl": "wayland-iso"})

    def test_isolation_is_opt_in_for_the_config(self):
        self.assertNotIn("dev", probe.apply_overrides({}, "", {}))


if __name__ == "__main__":
    unittest.main()
