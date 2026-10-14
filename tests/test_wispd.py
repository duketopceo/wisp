#!/usr/bin/env python3
"""Headless unit tests for the wisp package's pure decision logic."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import config, pipeline  # noqa: E402


def _with_os(os_name):
    """Pin the platform seam so adapter assertions are host-independent."""
    return mock.patch.dict(os.environ, {"WISP_OS": os_name})


class TestLoadConfig(unittest.TestCase):
    def test_parses_toml_subset(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            cfg_file.write_text(
                '[audio]\nseconds = 7\n\n[agent]\nmodel = "m"\n'
                'risk_threshold = "1.5" # trailing comment\n')
            with mock.patch.object(config, "CFG_FILE", cfg_file):
                cfg = config.load_config()
        self.assertEqual(cfg["audio"]["seconds"], "7")
        self.assertEqual(cfg["agent"]["risk_threshold"], "1.5")

    def test_writes_default_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            # [apps] defaults are host-specific — pin the seam so the
            # assertion means the same thing on every dev machine.
            with _with_os("linux"), \
                 mock.patch.object(config, "CFG_FILE", cfg_file), \
                 mock.patch.object(config, "CFG_DIR", pathlib.Path(td)):
                cfg = config.load_config()
            self.assertTrue(cfg_file.exists())
            self.assertEqual(cfg["apps"]["terminal"], "ghostty")
            self.assertEqual(cfg["audio"]["whisper_model"],
                             "ggml-small.en.bin")

    def test_default_config_written_for_host(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = pathlib.Path(td) / "config.toml"
            with _with_os("macos"), \
                 mock.patch.object(config, "CFG_FILE", cfg_file), \
                 mock.patch.object(config, "CFG_DIR", pathlib.Path(td)):
                cfg = config.load_config()
            self.assertEqual(cfg["apps"]["terminal"], "open -a 'Terminal'")
            self.assertIn('[apps]', cfg_file.read_text())


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {"risk_threshold": "1.5"},
                    "apps": {"terminal": "ghostty"}}

    def answers(self, action="launch", app="terminal", risk=1.2):
        return {"action": {"choice": action},
                "app": {"choice": app},
                "risk": {"score": risk}}

    def test_blocks_high_risk(self):
        out = pipeline.execute(self.answers(action="type_text", risk=2.0),
                               self.cfg)
        self.assertTrue(out.startswith("BLOCKED"))

    def test_launch_route_not_risk_gated(self):
        # "open discord" scored risk 1.6 live — launches are never blocked
        from wisp import tools
        with mock.patch.object(tools, "run", return_value="LAUNCHED"):
            out = pipeline.execute(
                self.answers(action="launch", app="browser", risk=2.5),
                self.cfg)
        self.assertEqual(out, "LAUNCHED")

    def test_unhandled_action_falls_back_to_act_loop(self):
        # an actionable turn with no usable route/action no longer
        # dead-ends on SKIP — the act loop gets the transcript
        from wisp import act
        with mock.patch.object(act, "run_act_loop",
                               return_value="ACTED (1 steps): ok") as r:
            out = pipeline.execute(self.answers(action="bogus"),
                                   self.cfg, detail="do the thing")
        self.assertEqual(out, "ACTED (1 steps): ok")
        r.assert_called_once()

    def test_close_dispatches_tool(self):
        from wisp import tools
        with mock.patch.object(tools, "run", return_value="CLOSED") as r:
            out = pipeline.execute(self.answers(action="close"), self.cfg)
        self.assertEqual(out, "CLOSED")
        r.assert_called_once()

    def test_answer_route_never_executes(self):
        out = pipeline.execute(self.answers(action="answer", app="none"),
                               self.cfg)
        self.assertEqual(out, "ANSWERED")

    def test_skips_unknown_app(self):
        out = pipeline.execute(self.answers(app="emacs"), self.cfg)
        self.assertIn("unknown app", out)

    def test_skips_missing_binary(self):
        with mock.patch.dict(os.environ, {"WISP_OS": "linux"}):
            with mock.patch.object(pipeline.shutil, "which", return_value=None), \
                 mock.patch.object(pipeline.pathlib.Path, "exists",
                                   return_value=False):
                out = pipeline.execute(self.answers(), self.cfg)
            self.assertIn("not installed", out)

    def test_dictation_route_types_transcript(self):
        # execute delegates to dictate.run; raw mode inserts the
        # stripped transcript via the type_text fallback chain
        from wisp import dictate, tools
        ans = {"route": {"choice": "dictation"},
               "action": {"choice": ""}, "app": {"choice": "none"},
               "risk": {"score": 1.0}}
        cfg = dict(self.cfg, dictation={"mode": "raw"})
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(dictate, "FILE",
                               pathlib.Path(td) / "d.json"), \
             mock.patch.object(dictate.platform, "active_window",
                               return_value={}), \
             mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run", return_value="TYPED") as r:
            out = pipeline.execute(ans, cfg, detail="dictate hello there")
        self.assertEqual(out, "INSERTED: hello there")
        r.assert_called_once_with("type_text", "hello there", cfg)

    def test_dictation_not_risk_gated(self):
        # dictation is self-confirming: transcript is the user's own
        # instruction — high Jev risk score must not block it
        from wisp import dictate, tools
        ans = {"route": {"choice": "dictation"},
               "action": {"choice": ""}, "app": {"choice": "none"},
               "risk": {"score": 2.0}}
        cfg = dict(self.cfg, dictation={"mode": "raw"})
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(dictate, "FILE",
                               pathlib.Path(td) / "d.json"), \
             mock.patch.object(dictate.platform, "active_window",
                               return_value={}), \
             mock.patch.dict("sys.modules", {"wordink": None}), \
             mock.patch.object(tools, "run", return_value="TYPED") as r:
            out = pipeline.execute(ans, cfg, detail="dictate x")
        self.assertEqual(out, "INSERTED: x")
        r.assert_called_once()

    def test_dictation_text_strips_prefix(self):
        cases = {
            "dictate hello": "hello",
            "Dictate: buy milk": "buy milk",
            "please type this, ok": "ok",
            "take dictation meeting notes": "meeting notes",
            "write this down - the thing": "the thing",
            "typesetter is an app": "typesetter is an app",
            "dictated": "dictated",
            "dictate": "dictate",  # prefix-only → keep original
            "hello world": "hello world",
        }
        for raw, want in cases.items():
            self.assertEqual(pipeline.dictation_text(raw), want, raw)

    def test_launch_uses_lua_dispatcher(self):
        from wisp import hypr
        with _with_os("linux"), \
             mock.patch.dict(os.environ, {"WISP_DESKTOP": "hyprland"}), \
             mock.patch.object(pipeline.shutil, "which",
                               return_value="/usr/bin/ghostty"), \
             mock.patch.object(hypr, "available", return_value=True), \
             mock.patch.object(hypr, "run_lua",
                               return_value=True) as ev, \
             mock.patch.object(pipeline.subprocess, "run") as run:
            out = pipeline.execute(self.answers(), self.cfg)
        self.assertIn("LAUNCHED", out)
        lua = ev.call_args[0][0]
        self.assertIn('hl.dsp.exec_cmd("ghostty")', lua)
        run.assert_not_called()  # socket eval, never hyprctl

    def test_launch_fails_fast_when_hypr_down(self):
        from wisp import hypr
        with _with_os("linux"), \
             mock.patch.dict(os.environ, {"WISP_DESKTOP": "hyprland"}), \
             mock.patch.object(pipeline.shutil, "which",
                               return_value="/usr/bin/ghostty"), \
             mock.patch.object(hypr, "available", return_value=False), \
             mock.patch.object(pipeline.subprocess, "run") as run:
            out = pipeline.execute(self.answers(), self.cfg)
        self.assertIn("tool_failed", out)
        run.assert_not_called()


class TestConfidenceGate(unittest.TestCase):
    """Gate is on app/target confidence only — low action confidence must
    not kill a correct launch (the 'retro-large' regression)."""

    def cfg(self, thresh="0.8"):
        return {"agent": {"confidence_ambiguous": thresh}}

    def answers(self, app_conf, act_conf):
        return {"app": {"choice": "retroarch", "confidence": app_conf,
                        "probabilities": {"retroarch": app_conf}},
                "action": {"choice": "launch", "confidence": act_conf,
                           "probabilities": {"launch": act_conf}}}

    def test_high_app_low_action_not_low_confidence(self):
        self.assertFalse(
            pipeline.is_low_confidence(self.answers(0.9, 0.49), self.cfg()))

    def test_low_app_is_low_confidence(self):
        self.assertTrue(
            pipeline.is_low_confidence(self.answers(0.4, 0.9), self.cfg()))


class TestChoiceFlow(unittest.TestCase):
    def answers(self):
        return {"app": {"choice": "terminal", "confidence": 0.5,
                        "probabilities": {"terminal": 0.5, "browser": 0.3}},
                "action": {"choice": "launch", "confidence": 0.5,
                           "probabilities": {"launch": 0.5}}}

    def test_choices_list_top_candidates(self):
        labels = pipeline.ambiguous_choices(self.answers(), {})
        self.assertIn("app:terminal", labels)
        self.assertIn("app:browser", labels)
        self.assertIn("action:launch", labels)

    def test_apply_choice_corrects_answers(self):
        out = pipeline.apply_choice(self.answers(), "app:browser")
        self.assertEqual(out["app"]["choice"], "browser")
        self.assertTrue(out["corrected_by_user"])

class TestLogDecision(unittest.TestCase):
    def test_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            target = pathlib.Path(td) / "decisions.jsonl"
            pipeline.log_decision({"ts": "t1", "result": "LAUNCHED"},
                                  log_file=target)
            pipeline.log_decision({"ts": "t2", "result": "BLOCKED"},
                                  log_file=target)
            rows = [json.loads(l) for l in target.read_text().splitlines()]
        self.assertEqual([r["result"] for r in rows], ["LAUNCHED", "BLOCKED"])


class TestSttProvider(unittest.TestCase):
    def test_openai_provider_posts_multipart(self):
        wav = pathlib.Path(tempfile.mktemp(suffix=".wav"))
        wav.write_bytes(b"RIFFfake")
        self.addCleanup(wav.unlink, True)
        captured = {}

        class Resp:
            def read(self):
                return b'{"text": "hello  world "}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            captured["ctype"] = req.headers.get("Content-type")
            captured["body"] = req.data
            return Resp()

        cfg = {"stt": {"provider": "openai",
                       "base_url": "https://api.groq.com/openai/v1/",
                       "model": "whisper-large-v3-turbo",
                       "key_env": "GROQ_API_KEY"}}
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gk-test"}), \
             mock.patch.object(pipeline.urllib.request, "urlopen",
                               fake_urlopen):
            out = pipeline.transcribe(wav, cfg)
        self.assertEqual(out, "hello world")
        self.assertEqual(captured["url"],
                         "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertEqual(captured["auth"], "Bearer gk-test")
        self.assertIn("multipart/form-data", captured["ctype"])
        self.assertIn(b'name="model"', captured["body"])
        self.assertIn(b"RIFFfake", captured["body"])

    def test_missing_key_raises(self):
        cfg = {"stt": {"provider": "openai", "key_env": "NO_SUCH_KEY_XYZ"}}
        with self.assertRaises(RuntimeError):
            pipeline.transcribe(pathlib.Path("/tmp/x.wav"), cfg)

class TestListenSpans(unittest.TestCase):
    """U1: the daemon builds press/release spans from the client t0."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        import threading
        path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_mod", path)
        spec = importlib.util.spec_from_loader("wispd_mod", loader)
        self.w = importlib.util.module_from_spec(spec)
        loader.exec_module(self.w)
        self.st = mock.Mock()
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "rec": None, "rec_lock": threading.Lock()}
        self.handle = self.w._handler(self.st, {}, self.ctl)

    def test_press_then_release_hand_spans_to_the_pipeline(self):
        import time
        seen = {}
        rec = {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
               "t0": time.monotonic() - 2}

        def fake_run(st, cfg, ctl, wav=None, spans=None, turn_id=None):
            seen["spans"] = spans
            ctl["busy"].clear()
        with mock.patch.object(self.w.pipeline, "record_start",
                               return_value=rec), \
             mock.patch.object(self.w.pipeline, "record_stop",
                               return_value="x.wav"), \
             mock.patch.object(self.w.speech, "stop"), \
             mock.patch.object(self.w, "_rec_watchdog"), \
             mock.patch.object(self.w, "_run_listen", fake_run), \
             mock.patch.object(self.w, "dlog"):
            r1 = self.handle({"cmd": "listen", "phase": "start",
                              "t0": time.time_ns() - 5_000_000})
            self.assertTrue(r1["ok"])
            sp = self.ctl["spans"]
            self.assertEqual(sp.t0_source, "client")
            self.assertGreaterEqual(sp.ms["press"], 5)
            self.assertLess(sp.ms["press"], 500)
            r2 = self.handle({"cmd": "listen", "phase": "stop",
                              "t0": time.time_ns()})
            self.assertTrue(r2["ok"])
            for _ in range(100):
                if "spans" in seen:
                    break
                time.sleep(0.01)
        self.assertIs(seen["spans"], sp)
        self.assertEqual(sp.rel0_source, "client")
        self.assertNotIn("spans", self.ctl)

    def test_press_begins_a_bus_turn_and_hands_its_id_to_the_pipeline(self):
        import tempfile
        import time
        from wisp import state as state_mod
        bus = state_mod.StateBus(
            state_file=pathlib.Path(tempfile.mkdtemp()) / "state.json")
        self.addCleanup(bus.close)
        handle = self.w._handler(bus, {}, self.ctl)
        seen = {}
        rec = {"proc": mock.Mock(), "sampler_stop": mock.Mock(),
               "t0": time.monotonic() - 2}

        def fake_run(st, cfg, ctl, wav=None, spans=None, turn_id=None):
            seen["turn_id"] = turn_id
            ctl["busy"].clear()
        before = bus.current_turn()
        with mock.patch.object(self.w.pipeline, "record_start",
                               return_value=rec), \
             mock.patch.object(self.w.pipeline, "record_stop",
                               return_value="x.wav"), \
             mock.patch.object(self.w.speech, "stop"), \
             mock.patch.object(self.w, "_rec_watchdog"), \
             mock.patch.object(self.w, "_run_listen", fake_run), \
             mock.patch.object(self.w, "dlog"):
            handle({"cmd": "listen", "phase": "start"})
            started = bus.current_turn()
            self.assertNotEqual(started, before)
            self.assertEqual(bus.snapshot()["status"], "listening")
            self.assertEqual(bus.snapshot()["turn_id"], started)
            handle({"cmd": "listen", "phase": "stop"})
            for _ in range(100):
                if "turn_id" in seen:
                    break
                time.sleep(0.01)
        self.assertEqual(seen["turn_id"], started)

    def test_cmd_trigger_sends_client_timestamp(self):
        sent = {}
        with mock.patch.object(self.w.ipc, "send",
                               side_effect=lambda c, **k: sent.update(c)
                               or {"ok": True}):
            self.w.cmd_trigger({}, "start")
        self.assertIsInstance(sent["t0"], int)
        self.assertGreater(sent["t0"], 1_600_000_000_000_000_000)


class TestHandlerActionStream(unittest.TestCase):
    """U2: command-line surfaces are stream events too — a pick, a
    spoken-style interrupt, a label verdict each land as a terminal
    entry, so the shell log explains what the daemon did."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        import threading
        path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_mod", path)
        spec = importlib.util.spec_from_loader("wispd_mod", loader)
        self.w = importlib.util.module_from_spec(spec)
        loader.exec_module(self.w)
        import tempfile
        from wisp import state as state_mod, cancel
        self.bus = state_mod.StateBus(
            state_file=pathlib.Path(tempfile.mkdtemp()) / "state.json")
        self.addCleanup(self.bus.close)
        self.cancel = cancel
        self.threading = threading

    def handle(self, ctl=None):
        c = {"stop": self.threading.Event(),
             "busy": self.threading.Event(),
             "interrupt": self.threading.Event(),
             "choice_event": self.threading.Event(),
             "choice_pick": ""}
        if ctl:
            c.update(ctl)
        return self.w._handler(self.bus, {}, c)

    def actions(self, kind=None):
        acts = self.bus.snapshot()["actions"]
        return acts if kind is None else \
            [a for a in acts if a["kind"] == kind]

    def test_a_resolved_pick_lands_done(self):
        broker = self.cancel.PromptBroker()
        out_box = {}

        def wait():
            out_box["pick"] = broker.waiter()(5, prompt_id="p1",
                                              options=["yes", "no"])
        th = self.threading.Thread(target=wait, daemon=True)
        th.start()
        for _ in range(100):
            if broker.pending_id:
                break
            import time
            time.sleep(0.01)
        r = self.handle({"broker": broker})(
            {"cmd": "choice", "pick": "yes", "prompt_id": "p1"})
        self.assertTrue(r["ok"])
        th.join(2)
        e = self.actions("choice")[-1]
        self.assertEqual(e["status"], "done")
        self.assertEqual(e["label"], "yes")

    def test_a_stale_pick_is_a_visible_failed_event(self):
        broker = self.cancel.PromptBroker()  # nothing pending
        r = self.handle({"broker": broker})(
            {"cmd": "choice", "pick": "yes", "prompt_id": "p9"})
        self.assertFalse(r["ok"])
        e = self.actions("choice")[-1]
        self.assertEqual(e["status"], "failed")
        self.assertEqual(e["reason"], "stale_prompt")

    def test_bad_index_records_the_refusal(self):
        broker = self.cancel.PromptBroker()
        r = self.handle({"broker": broker})(
            {"cmd": "choice", "index": "bogus"})
        self.assertEqual(r["error"], "bad_index")
        self.assertEqual(self.actions("choice")[-1]["reason"],
                         "bad_index")

    def test_interrupt_lands_as_a_done_event(self):
        with mock.patch.object(self.w.speech, "stop"):
            r = self.handle()({"cmd": "interrupt"})
        self.assertTrue(r["ok"])
        e = self.actions("interrupt")[-1]
        self.assertEqual(e["status"], "done")

    def test_label_lands_with_its_result(self):
        with mock.patch("wisp.learn.label_last",
                        return_value="labeled correct: t1") as lab:
            r = self.handle()({"cmd": "label", "label": "correct"})
        lab.assert_called_once()
        self.assertTrue(r["ok"])
        e = self.actions("label")[-1]
        self.assertEqual((e["status"], e["reason"]),
                         ("done", "labeled correct: t1"))

    def test_label_refusal_is_failed_not_silent(self):
        with mock.patch("wisp.learn.label_last",
                        return_value="SKIP (no completed turn)"):
            r = self.handle()({"cmd": "label", "label": "wrong"})
        self.assertTrue(r["ok"])  # command ran; the outcome failed
        self.assertEqual(self.actions("label")[-1]["status"], "failed")

    def test_suggestion_pick_resolves_the_card_entry(self):
        # the card's stream entry resolves by kind when the pick lands
        self.bus.action_add("suggestion", "try x", status="awaiting",
                            options=["suggestion:not now",
                                     "suggestion:never"])
        with mock.patch("wisp.suggest._mark"):  # keep the run test-only
            r = self.handle()({"cmd": "choice",
                               "pick": "suggestion:not now"})
        self.assertTrue(r["ok"])
        e = self.actions("suggestion")[-1]
        self.assertEqual((e["status"], e["reason"]),
                         ("cancelled", "snoozed"))

    def test_index_pick_records_the_option_not_dismiss(self):
        # an index pick resolved against the pending options lands in
        # the stream as the picked label, never "(dismiss)"
        broker = self.cancel.PromptBroker()
        out_box = {}

        def wait():
            out_box["pick"] = broker.waiter()(
                5, prompt_id="p1", options=["alpha", "beta", "gamma"])
        th = self.threading.Thread(target=wait, daemon=True)
        th.start()
        for _ in range(200):
            if broker.pending_id == "p1":
                break
            import time
            time.sleep(0.005)
        r = self.handle({"broker": broker})(
            {"cmd": "choice", "prompt_id": "p1", "index": 2})
        self.assertTrue(r["ok"])
        th.join(2)
        e = self.actions("choice")[-1]
        self.assertEqual((e["status"], e["label"]), ("done", "beta"))

    def test_dictate_correct_failure_carries_an_error_key(self):
        # contract: an ok:false reply must also carry `error` — shells
        # read it for the refusal toast
        with mock.patch("wisp.dictate.add_correction",
                        return_value="SKIP (heard and meant are empty)"):
            r = self.handle()({"cmd": "dictate_correct",
                               "heard": "", "meant": ""})
        self.assertFalse(r["ok"])
        self.assertIn("SKIP", r["error"])
        e = self.actions("dictation")[-1]
        self.assertEqual(e["status"], "failed")

    def test_dictate_correct_ok_has_no_error_payload(self):
        with mock.patch("wisp.dictate.add_correction",
                        return_value="learned: teh -> the"):
            r = self.handle()({"cmd": "dictate_correct",
                               "heard": "teh", "meant": "the"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["error"], "")


class TestSuggestionRun(unittest.TestCase):
    """_run_suggestion: interrupt edge-detection (a stale shared latch
    must not abort the run; a mid-run stop still cancels), terminal
    transitions clear the prompt surface, busy always releases."""

    def setUp(self):
        import importlib.machinery
        import importlib.util
        import threading
        path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
        loader = importlib.machinery.SourceFileLoader("wispd_sug", path)
        spec = importlib.util.spec_from_loader("wispd_sug", loader)
        self.w = importlib.util.module_from_spec(spec)
        loader.exec_module(self.w)
        import tempfile
        from wisp import state as state_mod, cancel
        self.bus = state_mod.StateBus(
            state_file=pathlib.Path(tempfile.mkdtemp()) / "state.json")
        self.addCleanup(self.bus.close)
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "broker": cancel.PromptBroker(),
                    "rec_lock": threading.Lock(),
                    "token": cancel.CancelToken()}

    def _run(self):
        self.w._run_suggestion(self.bus, {"agent": {}}, self.ctl, "do x")

    def test_stale_interrupt_latch_does_not_abort_the_run(self):
        # a leftover `interrupt` from a previous turn's stop is a level,
        # not an edge — the suggestion run must still execute
        self.w._interrupt(self.ctl)          # stale latch + seq bump
        with mock.patch("wisp.act.run_act_loop",
                        return_value="ACTED (1 steps): ok") as run:
            self._run()
        run.assert_called_once()
        self.assertEqual(self.bus.status, "done")
        e = [a for a in self.bus.snapshot()["actions"]
             if a["kind"] == "route"][-1]
        self.assertEqual(e["status"], "done")

    def test_interrupt_during_the_run_cancels_it(self):
        # an interrupt ARRIVING mid-run (seq edge) cancels the run's
        # token — observed through `interrupted=`
        seen = {}

        def fake_loop(*a, **kw):
            seen["interrupted"] = kw.get("interrupted")
            self.w._interrupt(self.ctl)      # the edge mid-run
            import time
            time.sleep(0.3)                  # let the bridge thread fire
            return "INTERRUPTED (user)" if seen["interrupted"]() \
                else "ACTED (0 steps): missed the stop"

        with mock.patch("wisp.act.run_act_loop", side_effect=fake_loop):
            self._run()
        self.assertEqual(self.bus.result, "INTERRUPTED (user)")

    def test_prompt_surface_cleared_on_terminal(self):
        # a parked card's fields can't outlive the run — choices,
        # prompt_id and confirm are cleared on the done transition
        with mock.patch("wisp.act.run_act_loop",
                        return_value="ACTED (1 steps): ok"):
            self._run()
        snap = self.bus.snapshot()
        self.assertEqual(snap["choices"], [])
        self.assertEqual(snap["prompt_id"], "")
        self.assertIsNone(snap["confirm"])

    def test_busy_releases_even_on_error(self):
        self.ctl["busy"].set()   # dispatch set it before spawning
        with mock.patch("wisp.act.run_act_loop",
                        side_effect=RuntimeError("boom")):
            self._run()
        self.assertFalse(self.ctl["busy"].is_set())
        self.assertEqual(self.bus.status, "error")


if __name__ == "__main__":
    unittest.main()
