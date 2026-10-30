"""Release feedback regressions; no live desktop, drivers or network."""
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import cua_safety, delivery, platform, points, policy
from wisp.tools import system


class SensitiveTitles(unittest.TestCase):
    def test_billing_and_checkout_titles_require_action_confirmation(self):
        for title in ("Billing", "Checkout"):
            with self.subTest(title=title), mock.patch.object(
                    platform, "active_window", return_value={
                        "class": "chromium", "title": title}):
                for name, arg in (("click", "10,20"), ("type_text", "hello"),
                                  ("key", "Return"), ("fill", "field hello")):
                    self.assertEqual(
                        policy.gate(name, arg, {}, None),
                        f"SKIPPED ({name} needs user confirmation)")


class AutoGuide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.audit = root / "cua.jsonl"
        self.kill = root / "cua.kill"
        monitor = {"x": 0, "y": 0, "width": 100, "height": 100, "scale": 1}
        patch = mock.patch.object(points, "monitors", return_value=[monitor])
        patch.start()
        self.addCleanup(patch.stop)

    def guard(self, cfg):
        return cua_safety.Guard(
            cfg, window=lambda: {"app": "firefox", "title": "Ordinary page"},
            limiter=cua_safety.Limiter(), audit_path=self.audit,
            kill_path=self.kill)

    def test_no_backend_auto_guide_is_not_suppressed_by_dry_run(self):
        cfg = {"pointer": {"mode": "auto", "backend": "none"},
               "cua": {"dry_run": "true"}}
        for name, runner, prefix in (
                ("click", system.click, "GUIDE("),
                ("move", system.move, "MOVE-GUIDE(")):
            with self.subTest(tool=name):
                guard = self.guard(cfg)
                out = guard.run(name, "10,20@logical",
                                lambda: runner("10,20@logical", cfg))
                self.assertTrue(out.startswith(prefix), out)
                self.assertEqual(guard.last_delivery, "guide")
                self.assertEqual(guard.turn_count, 0)
        self.assertFalse(self.audit.exists())

    def test_auto_guide_does_not_consume_or_require_input_budget(self):
        cfg = {"pointer": {"mode": "auto", "backend": "none"},
               "cua": {"max_per_turn": "1", "max_clicks_per_min": "1"}}
        guard = self.guard(cfg)
        guard.turn_count = 1
        guard.limiter.record("firefox")
        out = guard.run(
            "click", "10,20@logical", lambda: system.click("10,20@logical", cfg))
        self.assertTrue(out.startswith("GUIDE("), out)
        self.assertEqual(guard.turn_count, 1)
        self.assertEqual(guard.limiter.count("firefox"), 1)
        self.assertFalse(self.audit.exists())

    def test_available_cua_is_guarded_without_native_pointer_injection(self):
        for blocking in ("dry_run", "turn_limit", "rolling_limit"):
            with self.subTest(blocking=blocking):
                cfg = {"pointer": {"mode": "auto"},
                       "cua": {"dry_run": "true" if blocking == "dry_run" else "false",
                               "max_per_turn": "1", "max_clicks_per_min": "1"}}
                guard = self.guard(cfg)
                if blocking == "turn_limit":
                    guard.turn_count = 1
                elif blocking == "rolling_limit":
                    guard.limiter.record("firefox")
                runner = mock.Mock(return_value="SHOULD NOT INJECT")
                # Real Registry/CuaBackend selection: native binaries absent,
                # Cua available. No driver or network operation is dispatched.
                with mock.patch.object(platform, "_which", return_value=None), \
                        mock.patch.object(platform, "_cua_live", return_value=True):
                    self.assertEqual(delivery.resolve_backend(cfg, "click"), "cua")
                    out = guard.run("click", "10,20@logical", runner)
                runner.assert_not_called()
                expected = ("DRYRUN" if blocking == "dry_run" else "REFUSED")
                self.assertTrue(out.startswith(expected), out)
                self.assertNotEqual(guard.last_delivery, "guide")

    def test_auto_dom_input_does_not_take_the_no_backend_guide_exception(self):
        cfg = {"pointer": {"mode": "auto", "backend": "none"},
               "screen": {"dom_page": "test-page"},
               "cua": {"dry_run": "true"}}
        runner = mock.Mock()
        with mock.patch.object(delivery, "resolve_backend",
                               side_effect=AssertionError("DOM bypasses registry")):
            out = self.guard(cfg).run("click", "10,20@logical", runner)
        self.assertTrue(out.startswith("DRYRUN"), out)
        runner.assert_not_called()

    def test_background_cua_click_is_guarded_while_move_guides(self):
        cfg = {"pointer": {"mode": "auto"},
               "cua": {"dry_run": "true", "delivery": "background"}}
        guard = self.guard(cfg)
        click_runner = mock.Mock()
        with mock.patch.object(platform, "_which", return_value=None), \
                mock.patch.object(platform, "_cua_live", return_value=True):
            self.assertEqual(delivery.resolve_backend(cfg, "click"), "cua")
            click_out = guard.run("click", "10,20@logical", click_runner)
            self.assertIsNone(delivery.resolve_backend(cfg, "move"))
            move_out = guard.run(
                "move", "10,20@logical",
                lambda: system.move("10,20@logical", cfg))
        click_runner.assert_not_called()
        self.assertTrue(click_out.startswith("DRYRUN"), click_out)
        self.assertTrue(move_out.startswith("MOVE-GUIDE("), move_out)
        self.assertEqual(guard.last_delivery, "guide")

    def test_scroll_stays_guarded_when_pointer_guide_has_no_backend(self):
        cfg = {"pointer": {"mode": "auto", "backend": "none"},
               "cua": {"dry_run": "true"}}
        runner = mock.Mock()
        out = self.guard(cfg).run("scroll", "down", runner)
        self.assertTrue(out.startswith("DRYRUN"), out)
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
