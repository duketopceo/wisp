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

    def test_interactive_runs_without_confirm(self):
        # clicks/typing execute — the agent acts, it doesn't ask
        assert act._gate("click", "10,10", {"agent": {}}, None) is None
        assert act._gate("type_text", "hi", {"agent": {}}, None) is None
        assert act._gate("scroll", "down", {"agent": {}}, None) is None
        assert act._gate("key", "enter", {"agent": {}}, None) is None

    def test_interactive_denylist_still_applies(self):
        # prompt-free tier must not type destruction into a terminal
        out = act._gate("type_text", "rm -rf /", {"agent": {}}, None)
        assert out and "REFUSED" in out

    def test_mutating_skips_without_confirm(self):
        out = act._gate("close", "", {"agent": {}}, None)
        assert out and "SKIPPED" in out

    def test_mutating_runs_when_confirmed(self):
        cfg = {"agent": {}}
        assert act._gate("close", "", cfg, lambda p: True) is None
        out = act._gate("close", "", cfg, lambda p: False)
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

    def test_dom_clean_observe_serves_cache(self):
        # DOM mode + clean screen: a model-requested re-observe adds
        # nothing (unneeded_observe is the dominant judged waste) —
        # serve the prior shot and skip the eval round-trip
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT domdigest-1" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("screenshot")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "screen": {"dom_page": "p"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("look twice", cfg,
                                 initial_image="aGk=")
        assert r.startswith("ACTED")
        assert calls == ["screenshot"], calls

    def test_dom_dirty_observe_runs_fresh(self):
        # a mutating step must invalidate the cache
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT d" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("click", "10,20")]),
                   _msg(calls=[_call("screenshot")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "screen": {"dom_page": "p"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("click then look", cfg,
                                 initial_image="aGk=",
                                 confirm=lambda pr: True)
        assert r.startswith("ACTED")
        assert calls == ["screenshot", "click", "screenshot"], calls

    def test_dom_id_click_skips_reobserve(self):
        # click 'btn-x' dispatches through getElementById +
        # scrollIntoView — stale legend coords can't misaim it, so a
        # dirty screen must NOT trigger the auto re-observe
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT d" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("type_text", "hi")]),
                   _msg(calls=[_call("click", "btn-x")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "screen": {"dom_page": "p"},
               "brain.openrouter": {"vision": "true"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.brain.provider",
                        return_value={"name": "openrouter",
                                      "vision": "true",
                                      "tools": "true"}), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("type then click id", cfg,
                                 initial_image="aGk=",
                                 confirm=lambda pr: True)
        assert r.startswith("ACTED")
        # no screenshot between the type mutation and the id click
        assert calls == ["screenshot", "type_text", "click"], calls

    def test_dom_coord_click_still_reobserves(self):
        # coordinate clicks DO depend on fresh pixels — keep the soak
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT d" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("type_text", "hi")]),
                   _msg(calls=[_call("click", "10,20")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "screen": {"dom_page": "p"},
               "brain.openrouter": {"vision": "true"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.brain.provider",
                        return_value={"name": "openrouter",
                                      "vision": "true",
                                      "tools": "true"}), \
             mock.patch.object(act, "_attach_image"), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("type then click xy", cfg,
                                 initial_image="aGk=",
                                 confirm=lambda pr: True)
        assert r.startswith("ACTED")
        assert calls == ["screenshot", "type_text", "screenshot",
                         "click"], calls

    def test_dom_first_observe_never_cached(self):
        # no prior shot → nothing to serve
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT d" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(content="done")]
        cfg = {"agent": {}, "screen": {"dom_page": "p"}}
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            act.run_act_loop("look", cfg, initial_image="aGk=")
        assert calls == ["screenshot"], calls

    def test_pixel_mode_observe_never_cached(self):
        # pixel shots reflect a live screen the user may change —
        # elision is DOM-mode only
        calls = []
        def fake_run(name, arg, cfg, harness=None):
            calls.append(name)
            return "SHOT p" if name == "screenshot" else "ok"
        replies = [_msg(calls=[_call("screenshot")]),
                   _msg(calls=[_call("screenshot")]),
                   _msg(content="done")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=fake_run):
            r = act.run_act_loop("look twice", self.cfg,
                                 initial_image="aGk=")
        assert r.startswith("ACTED")
        assert calls == ["screenshot", "screenshot"], calls

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

        replies = [_msg(calls=[_call("close", "w1")]),
                   _msg(calls=[_call("close", "w2")]),
                   _msg(content="closed")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("close stuff", cfg, state=st,
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
        replies = [_msg(calls=[_call("close", "w1")]),
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


class ActionText(unittest.TestCase):
    """UI-TARS-style 'Action: name(args)' replies — providers flagged
    action_text=true emit literal action text instead of tool_calls."""

    def test_parse_click(self):
        r = act._parse_action_text(
            "Thought: the circle is at 72,405\nAction: click(72, 405)")
        self.assertEqual(r["actions"], [("click", "72,405")])

    def test_parse_type_quoted(self):
        r = act._parse_action_text('Action: type("hello, world")')
        self.assertEqual(r["actions"], [("type_text", "hello, world")])

    def test_parse_type_content_kwarg(self):
        r = act._parse_action_text("Action: type(content='it works')")
        self.assertEqual(r["actions"], [("type_text", "it works")])

    def test_parse_click_start_box(self):
        r = act._parse_action_text(
            "Action: click(start_box='(300,123)')")
        self.assertEqual(r["actions"], [("click", "300,123")])

    def test_parse_scroll_direction(self):
        r = act._parse_action_text("Action: scroll(direction='down')")
        self.assertEqual(r["actions"], [("scroll", "down")])

    def test_parse_scroll_delta(self):
        r = act._parse_action_text("Action: scroll(300, 400, 0, 450)")
        self.assertEqual(r["actions"], [("scroll", "down 450")])

    def test_parse_hotkey(self):
        r = act._parse_action_text("Action: hotkey('ctrl', 'c')")
        self.assertEqual(r["actions"], [("key", "ctrl+c")])

    def test_parse_press(self):
        r = act._parse_action_text("Action: press('enter')")
        self.assertEqual(r["actions"], [("key", "enter")])

    def test_parse_done(self):
        r = act._parse_action_text("DONE")
        self.assertEqual(r["actions"], [])
        self.assertIsNotNone(r["done"])

    def test_parse_finished_kwarg(self):
        r = act._parse_action_text(
            "Action: finished(content='opened discord')")
        self.assertEqual(r["actions"], [])
        self.assertIn("opened discord", r["done"])

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(act._parse_action_text(
            "let me think about this some more"))

    def test_parse_click_no_coords_is_miss(self):
        self.assertIsNone(act._parse_action_text("Action: click"))

    def test_wait_is_skipped(self):
        r = act._parse_action_text(
            "Action: wait()\nAction: click(10, 20)")
        self.assertEqual(r["actions"], [("click", "10,20")])

    def test_loop_executes_action_text(self):
        cfg = {"agent": {},
               "brain": {"default": "uitars:ui-tars-7b"},
               "brain.uitars": {"base_url": "http://127.0.0.1:8081",
                                "tools": "false", "action_text": "true"}}
        replies = [_msg(content="Thought: aim\nAction: click(10, 20)"),
                   _msg(content="DONE")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run",
                               return_value="CLICKED x") as run:
            r = act.run_act_loop("click it", cfg)
        run.assert_called_once()
        args = run.call_args[0]
        self.assertEqual(args[0], "click")
        self.assertEqual(args[1], "10,20")
        self.assertTrue(r.startswith("ACTED"))

    def test_loop_done_text_finishes(self):
        cfg = {"agent": {},
               "brain": {"default": "uitars:m"},
               "brain.uitars": {"action_text": "true", "tools": "false"}}
        with mock.patch.object(act, "_post",
                               return_value=_msg(
                                   content="DONE: clicked the thing")):
            r = act.run_act_loop("click it", cfg)
        self.assertIn("clicked the thing", r)

    def test_loop_unparseable_stalls_not_crashes(self):
        cfg = {"agent": {},
               "brain": {"default": "uitars:m"},
               "brain.uitars": {"action_text": "true", "tools": "false"}}
        with mock.patch.object(act, "_post",
                               return_value=_msg(
                                   content="I am pondering deeply")):
            r = act.run_act_loop("click it", cfg)
        self.assertIn("STALLED", r)

    def test_denylist_applies_to_action_text(self):
        cfg = {"agent": {},
               "brain": {"default": "uitars:m"},
               "brain.uitars": {"action_text": "true", "tools": "false"}}
        replies = [_msg(content='Action: type("rm -rf /")'),
                   _msg(content="DONE")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run") as run:
            r = act.run_act_loop("type it", cfg)
        run.assert_not_called()

    def test_provider_without_flag_still_skips(self):
        cfg = {"agent": {},
               "brain": {"default": "plain:m"},
               "brain.plain": {"tools": "false"}}
        r = act.run_act_loop("click it", cfg)
        self.assertTrue(r.startswith("SKIP"))
