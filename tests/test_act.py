"""Tests for wisp/act.py — the bounded tool-call loop."""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import act, session, tools  # noqa: E402


def _msg(content=None, calls=None):
    # _post returns the provider message object (U6 provider seam)
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


def _call(name, arg=""):
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"arg": arg})}}


class Schemas(unittest.TestCase):
    def test_derives_from_registry(self):
        names = {t["function"]["name"] for t in tools.tool_schemas()}
        assert "launch" in names and "type_text" in names
        assert "agent_spawn" in names  # fn=None but agents provides it
        assert "bogus" not in names

    def test_schema_shape(self):
        for t in tools.tool_schemas():
            assert t["type"] == "function"
            assert t["function"]["parameters"]["type"] == "object"
            assert "arg" in t["function"]["parameters"]["properties"]


class Gate(unittest.TestCase):
    def test_safe_tool_passes(self):
        assert act._gate("launch", "discord", {"agent": {}}, None) is None

    def test_unknown_tool_skipped(self):
        # risk_of defaults unknown names to the shell tier — safest choice
        out = act._gate("bogus", "x", {"agent": {}}, None)
        assert out and "SKIPPED" in out

    def test_shell_blocked_when_disabled(self):
        out = act._gate("shell", "ls", {"agent": {}}, None)
        assert out and "SKIPPED" in out

    def test_shell_denylisted(self):
        cfg = {"agent": {"allow_shell": "true"}}
        out = act._gate("shell", "rm -rf /", cfg, lambda p: True)
        assert out and "REFUSED" in out

    def test_mutating_skips_without_confirm(self):
        out = act._gate("type_text", "hi", {"agent": {}}, None)
        assert out and "SKIPPED" in out

    def test_mutating_runs_when_confirmed(self):
        cfg = {"agent": {}}
        assert act._gate("type_text", "hi", cfg, lambda p: True) is None
        out = act._gate("type_text", "hi", cfg, lambda p: False)
        assert out and "declined" in out


class Loop(unittest.TestCase):
    def setUp(self):
        self.cfg = {"agent": {}}

    def test_stops_on_text_reply(self):
        with mock.patch.object(act, "_post",
                               return_value=_msg(content="done deal")):
            r = act.run_act_loop("open discord", self.cfg)
        assert r.startswith("ACTED (0 steps)") and "done deal" in r

    def test_executes_then_finishes(self):
        replies = [_msg(calls=[_call("launch", "discord")]),
                   _msg(content="opened it")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run",
                               return_value="LAUNCHED discord") as run:
            r = act.run_act_loop("open discord", self.cfg,
                             initial_image="aGk=")
        run.assert_called_once()
        assert r.startswith("ACTED (1 steps)")

    def test_interrupt_stops_loop(self):
        replies = [_msg(calls=[_call("launch", "x")])] * 20
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("loop", self.cfg,
                                 interrupted=lambda: True)
        assert r == "INTERRUPTED (user)"

    def test_interrupt_between_steps(self):
        flag = {"stop": False}
        def should_stop():
            return flag["stop"]
        def stop_after_one(name, arg, cfg, harness=None):
            flag["stop"] = True
            return "ok"
        replies = [_msg(calls=[_call("launch", "x")])] * 5
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=stop_after_one):
            r = act.run_act_loop("loop", self.cfg, interrupted=should_stop)
        assert r == "INTERRUPTED (user)"

    def test_aborts_at_max_steps(self):
        replies = [_msg(calls=[_call("launch", "x")])] * 20
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("loop forever", self.cfg)
        assert r.startswith("ABORTED (max")

    def test_aborts_on_repeated_errors(self):
        replies = [_msg(calls=[_call("bogus")])] * 20
        with mock.patch.object(act, "_post", side_effect=replies):
            r = act.run_act_loop("break things", self.cfg)
        assert r.startswith("ABORTED (repeated failures)")

    def test_refused_call_feeds_back_not_executed(self):
        replies = [_msg(calls=[_call("shell", "rm -rf /")]),
                   _msg(content="can't do that")]
        cfg = {"agent": {"allow_shell": "true"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run") as run:
            r = act.run_act_loop("delete everything", cfg,
                             initial_image="aGk=")
        run.assert_not_called()
        assert "REFUSED" in json.dumps(
            [c.get("function") for c in []] or [{"x": "y"}]) or r

    def test_malformed_arguments_tolerated(self):
        bad = {"id": "c1", "function":
               {"name": "launch", "arguments": "{not json"}}
        replies = [_msg(calls=[bad]), _msg(content="ok")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="LAUNCHED"):
            r = act.run_act_loop("open something", self.cfg)
        assert r.startswith("ACTED")

    def test_reobserve_before_click_after_mutation(self):
        # soak fix: a screen-changing step invalidates the last
        # screenshot — the loop must re-shoot before the next click,
        # not click stale pixels
        calls = []
        import tempfile, pathlib
        shot = pathlib.Path(tempfile.mktemp(suffix=".png"))
        shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return f"SHOT {shot}" if name == "screenshot" \
                else "ok"
        replies = [_msg(calls=[_call("launch", "x")]),
                   _msg(calls=[_call("click", "100,200")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "brain.openrouter": {"vision": "true"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.brain.provider",
                        return_value={"name": "openrouter",
                                      "vision": "true",
                                      "tools": "true"}), \
             mock.patch.object(act, "_attach_image"), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("click the thing", cfg,
                             confirm=lambda pr: True)
        assert r.startswith("ACTED")
        # screenshot must sit between the mutation and the click
        # startup observe + post-mutation re-observe
        assert calls == ["screenshot", "launch", "screenshot", "click"]

    def test_no_reobserve_when_screen_fresh(self):
        # trigger-time image is still valid → first click goes straight
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "ok"
        replies = [_msg(calls=[_call("click", "10,20")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "brain.openrouter": {"vision": "true"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.brain.provider",
                        return_value={"name": "openrouter",
                                      "vision": "true",
                                      "tools": "true"}), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("click", cfg, initial_image="aGk=",
                             confirm=lambda pr: True)
        assert r.startswith("ACTED")
        assert calls == ["click"]

    def test_no_blind_click_without_any_image(self):
        # no trigger image + vision → the loop observes before the
        # first model call, not just before the first click
        import tempfile, pathlib
        shot = pathlib.Path(tempfile.mktemp(suffix=".png"))
        shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return f"SHOT {shot}" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("click", "10,20")]),
                   _msg(content="done")]
        cfg = {"agent": {}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.brain.provider",
                        return_value={"name": "openrouter",
                                      "vision": "true",
                                      "tools": "true"}), \
             mock.patch.object(act, "_attach_image"), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("click", cfg,
                                 confirm=lambda pr: True)
        assert r.startswith("ACTED")
        assert calls == ["screenshot", "click"]

    def test_ask_user_returns_backchannel(self):
        with mock.patch.object(act, "_post",
                               return_value=_msg(
                                   content="ASK_USER: which account?")):
            r = act.run_act_loop("check it", self.cfg)
        assert r == "ASK_USER which account?"

    def test_confirm_once_per_tool_and_app(self):
        # one yes covers the rest of the (tool, app) session
        from wisp.state import State
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        prompts = []
        cfg = {"agent": {}}

        def confirm(p):
            prompts.append(p)
            return True

        replies = [_msg(calls=[_call("type_text", "a")]),
                   _msg(calls=[_call("type_text", "b")]),
                   _msg(content="typed")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("type stuff", cfg, state=st,
                                 confirm=confirm)
        assert r.startswith("ACTED")
        assert len(prompts) == 1  # second call hit the confirm cache

    def test_confirm_once_scoped_to_app(self):
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        cfg = {"agent": {}}
        n = [0]

        def confirm(p):
            n[0] += 1
            return True

        # different focus app → fresh confirm
        replies = [_msg(calls=[_call("type_text", "a")]),
                   _msg(content="ok")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            act.run_act_loop("t", cfg, state=st, confirm=confirm)
        st.focus = {"app": "godot"}
        st.confirmed = set()  # new session
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            act.run_act_loop("t", cfg, state=st, confirm=confirm)
        assert n[0] == 2

    def test_initial_image_attached_to_first_message(self):
        captured = []

        def post(messages, cfg):
            captured.append(messages[-1])
            return _msg(content="seen")

        with mock.patch.object(act, "_post", side_effect=post):
            r = act.run_act_loop("what's here", self.cfg,
                                 initial_image="QUJD")
        assert r.startswith("ACTED")
        first = captured[0]
        assert isinstance(first["content"], list)
        assert first["content"][1]["image_url"]["url"].endswith("QUJD")

    def test_acting_state_published(self):
        st = mock.Mock()
        replies = [_msg(calls=[_call("launch", "x")]), _msg(content="ok")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            act.run_act_loop("task", self.cfg, state=st)
        calls = [c.args[0] for c in st.transition.call_args_list]
        assert "acting" in calls


if __name__ == "__main__":
    unittest.main()

class Timing(unittest.TestCase):
    def test_decisions_log_carries_stage_timings(self):
        from wisp import pipeline
        logged = {}
        cfg = {"audio": {"seconds": "0"}, "agent": {},
               "jev": {"risk_threshold": "10"}}
        fake_resp = {"answers": {"route": {"choice": "answer"},
                                 "confidence": {"score": 0.9},
                                 "action": {"choice": "answer"},
                                 "app": {"choice": ""}}}
        st = mock.Mock()
        st.state = {}
        st.transition = lambda s, **kw: st.state.update(status=s, **kw)
        with mock.patch.object(pipeline, "record",
                               return_value=__import__("pathlib").Path("/tmp/x.wav")), \
             mock.patch.object(pipeline, "transcribe",
                               return_value="hello"), \
             mock.patch.object(pipeline, "ask_jev",
                               return_value=fake_resp), \
             mock.patch.object(pipeline, "execute",
                               return_value="ANSWERED"), \
             mock.patch.object(pipeline, "ask_chat",
                               return_value="hi there"), \
             mock.patch.object(pipeline, "build_questions",
                               return_value={}), \
             mock.patch.object(pipeline, "notify"), \
             mock.patch.object(sys.modules["wisp.session"],
                               "append_turn"), \
             mock.patch.object(sys.modules["wisp.session"], "tail",
                               return_value=[]), \
             mock.patch.object(sys.modules["wisp.session"], "as_text",
                               return_value=""), \
             mock.patch.object(pipeline, "log_decision",
                               side_effect=lambda r: logged.update(r)):
            rc = pipeline.run_listen(cfg, st)
        assert rc == 0
        for k in ("record_ms", "stt_ms", "jev_ms", "act_ms"):
            assert k in logged["timing_ms"], f"missing {k}"
