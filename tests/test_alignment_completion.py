"""Focused R2/R4/R8 regressions; no desktop, network or input actions."""
import copy
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from wisp import config, stage_execute
from wisp.tools import desktop


class LiveActPointerDefaultsTest(unittest.TestCase):
    def test_act_receives_only_caller_detail_as_human_coordinate_authority(self):
        request = "click at 100,120@logical"
        cases = [
            ({"route": {"choice": "act"}}, request, request),
            ({"route": {"choice": "learn"}}, request, None),
            ({"app": {"choice": request}}, "", request),
        ]
        for answers, detail, task in cases:
            with self.subTest(answers=answers), \
                    mock.patch("wisp.platform.pointer_backend", return_value=None), \
                    mock.patch("wisp.act.run_act_loop", return_value="ACTED") as run:
                self.assertEqual(stage_execute.execute(
                    answers, {}, detail=detail, user_request=detail),
                                 "ACTED")
                self.assertEqual(run.call_args.kwargs.get("user_request"), detail)
                if task is None:
                    self.assertNotEqual(run.call_args.args[0], detail)
                else:
                    self.assertEqual(run.call_args.args[0], task)

    def test_direct_dispatch_does_not_infer_human_authority_from_task(self):
        with mock.patch("wisp.platform.pointer_backend", return_value=None), \
                mock.patch("wisp.act.run_act_loop", return_value="ACTED") as run:
            stage_execute.execute({"route": {"choice": "act"}}, {},
                                  detail="click at 100,120@logical")
        self.assertEqual(run.call_args.kwargs["user_request"], "")

    def test_correction_stage_keeps_original_request_separate_from_context(self):
        request = "click at 100,120@logical"
        detail = "[previous attempt: failed] " + request
        ctx = types.SimpleNamespace(
            state=mock.Mock(), cfg={}, token=mock.Mock(),
            answers={"route": {"choice": "act"}}, text=request,
            detail=detail, harness={}, wait_for_choice=None,
            shot_b64=None, interrupted=lambda: False, turn="synthetic",
            corr=None)
        with mock.patch("wisp.pipeline.execute", return_value="ACTED") as run, \
                mock.patch("wisp.state.action_add"), \
                mock.patch("wisp.state.action_set"), \
                mock.patch("wisp.trace.emit"):
            stage_execute.execute_stage(ctx)
        self.assertEqual(run.call_args.kwargs["detail"], detail)
        self.assertEqual(run.call_args.kwargs["user_request"], request)

    def test_fresh_config_uses_auto_only_for_the_act_turn(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            with mock.patch.object(config, "CFG_DIR", pathlib.Path(td)), \
                 mock.patch.object(config, "CFG_FILE", cfg_file):
                # Both first-load defaults and the persisted template must
                # distinguish an unset mode from a chosen guide mode.
                fresh = config.load_config()
                persisted = config.load_config()
                original_file = cfg_file.read_bytes()
                for cfg in (fresh, persisted):
                    with self.subTest(first_load=cfg is fresh):
                        original = copy.deepcopy(cfg)
                        with mock.patch("wisp.platform.pointer_backend",
                                        return_value="ydotool"), \
                             mock.patch("wisp.act.run_act_loop",
                                        return_value="ACTED") as run:
                            result = stage_execute.execute(
                                {"route": {"choice": "act"}}, cfg,
                                detail="click the settings button")
                        self.assertEqual(result, "ACTED")
                        turn_cfg = run.call_args.args[1]
                        self.assertEqual(
                            turn_cfg.get("pointer", {}).get("mode", "guide"),
                            "auto")
                        self.assertIsNot(turn_cfg, cfg)
                        self.assertIsNot(turn_cfg["pointer"], cfg["pointer"])
                        self.assertEqual(cfg, original)
                        self.assertEqual(cfg_file.read_bytes(), original_file)

    def test_unavailable_backend_keeps_default_guide(self):
        cfg = {"pointer": {"backend": "auto"}, "agent": {}}
        original = copy.deepcopy(cfg)
        with mock.patch("wisp.platform.pointer_backend",
                        return_value=None) as backend, \
             mock.patch("wisp.act.run_act_loop",
                        return_value="ACTED") as run:
            stage_execute.execute({"route": {"choice": "act"}}, cfg,
                                  detail="click settings")
        backend.assert_called_once_with(cfg)
        self.assertEqual(run.call_args.args[1]["pointer"].get("mode"),
                         "guide")
        self.assertEqual(cfg, original)

    def test_explicit_modes_are_preserved_without_backend_discovery(self):
        for mode in ("guide", "auto", "drive"):
            with self.subTest(mode=mode):
                cfg = {"pointer": {"mode": mode, "backend": "auto"}}
                original = copy.deepcopy(cfg)
                with mock.patch("wisp.platform.pointer_backend") as backend, \
                     mock.patch("wisp.act.run_act_loop",
                                return_value="ACTED") as run:
                    stage_execute.execute(
                        {"route": {"choice": "act"}}, cfg,
                        detail="click settings")
                backend.assert_not_called()
                self.assertEqual(run.call_args.args[1]["pointer"]["mode"],
                                 mode)
                self.assertEqual(cfg, original)

    def test_persisted_guide_is_preserved_even_if_legacy_default(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            # The old generated value and a user choice have identical
            # bytes. Neither may be silently treated as permission to drive.
            text = '[pointer]\nmode = "guide"\nbackend = "auto"\n'
            cfg_file.write_text(text, encoding="utf-8")
            with mock.patch.object(config, "CFG_FILE", cfg_file):
                cfg = config.load_config()
            with mock.patch("wisp.platform.pointer_backend") as backend, \
                 mock.patch("wisp.act.run_act_loop",
                            return_value="ACTED") as run:
                stage_execute.execute({"route": {"choice": "act"}}, cfg,
                                      detail="click settings")
            backend.assert_not_called()
            self.assertEqual(run.call_args.args[1]["pointer"]["mode"], "guide")
            self.assertEqual(cfg_file.read_text(encoding="utf-8"), text)


class NotionFallbackTest(unittest.TestCase):
    def test_tab_miss_launches_default_notion_url(self):
        with mock.patch.object(desktop, "_resolve_apps", return_value={}), \
             mock.patch("wisp.inventory.defaults", return_value={}), \
             mock.patch("wisp.platform.active_window", return_value={}), \
             mock.patch.object(desktop, "_wm_down", return_value=None), \
             mock.patch.object(desktop, "_cdp_get",
                               side_effect=OSError("no debug endpoint")), \
             mock.patch.object(desktop, "_web_browser",
                               return_value="chromium"), \
             mock.patch.object(desktop, "_exec_detached",
                               return_value=True) as launch:
            result = desktop.launch("go to my Notion", {})
        self.assertEqual(result, "OPENED https://www.notion.so -> chromium")
        launch.assert_called_once_with("chromium https://www.notion.so")

    def test_existing_notion_work_tab_prevents_duplicate_launch(self):
        def cdp_get(port, path):
            if path == "/json/list":
                pages = ([{"type": "page", "id": "work",
                           "title": "Notion — Work",
                           "url": "https://www.notion.so"}]
                         if port == 9223 else [])
                return json.dumps(pages).encode()
            return b"Target activated"

        with mock.patch.object(desktop, "_resolve_apps", return_value={}), \
             mock.patch("wisp.inventory.defaults", return_value={}), \
             mock.patch.object(desktop, "_wm_down", return_value=None), \
             mock.patch.object(desktop, "_cdp_get",
                               side_effect=cdp_get) as cdp, \
             mock.patch.object(desktop, "_focus_browser"), \
             mock.patch.object(desktop, "_exec_detached") as launch:
            result = desktop.launch("go to my Notion for work", {})
        self.assertEqual(result,
                         "SWITCHED tab 'Notion — Work' -> www.notion.so")
        self.assertIn(mock.call(9223, "/json/activate/work"),
                      cdp.call_args_list)
        launch.assert_not_called()


class BrowserPortDiscoveryTest(unittest.TestCase):
    def test_discovers_profile_tabs_on_required_and_existing_ports(self):
        pages = {
            9108: [{"id": "chromium", "type": "page", "title": "Notion",
                    "url": "https://www.notion.so"}],
            9107: [{"id": "shim", "type": "page", "title": "Notion",
                    "url": "https://www.notion.so"}],
            9222: [{"id": "default", "type": "page", "title": "Notion",
                    "url": "https://www.notion.so"}],
            9100: [{"id": "personal", "type": "page",
                    "title": "Notion — Personal",
                    "url": "https://www.notion.so"}],
            9223: [{"id": "work", "type": "page", "title": "Notion — Work",
                    "url": "https://www.notion.so"}],
        }
        calls = []

        def cdp_get(port, path):
            calls.append((port, path))
            if path == "/json/list":
                if port not in pages:
                    raise OSError("debug endpoint unavailable")
                return json.dumps(pages[port]).encode()
            return b"Target activated"

        with mock.patch.object(desktop, "_cdp_get", side_effect=cdp_get), \
             mock.patch("wisp.platform.active_window", return_value={
                 "class": "chromium", "title": "Inbox — Personal"}), \
             mock.patch.object(desktop, "_focus_browser") as focus:
            work = desktop.tab("notion for work")
            personal = desktop.tab("notion")
        self.assertIn("Notion — Work", work)
        self.assertIn("Notion — Personal", personal)
        self.assertIn((9223, "/json/activate/work"), calls)
        self.assertIn((9100, "/json/activate/personal"), calls)
        for port in pages:
            self.assertIn((port, "/json/list"), calls)
        self.assertEqual(focus.call_args_list, [
            mock.call("Notion — Work", profile="work"),
            mock.call("Notion — Personal", profile="personal"),
        ])

if __name__ == "__main__":
    unittest.main()
