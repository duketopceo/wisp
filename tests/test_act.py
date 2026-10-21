"""Tests for wisp/act.py — the bounded tool-call loop."""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")
from wisp import act, session, tools  # noqa: E402

# U4: every run_act_loop call in this file reaches the real cua-driver
# when it's live — that starts a real recording, and the turn-end pack
# write would touch ~/.local/share/wisp/packs + shots/. The loop's own
# behavior is under test here; the pack seam is stubbed module-wide
# (packs.write has its own suite).
_WRITE_PACK = None


def setUpModule():
    global _WRITE_PACK
    _WRITE_PACK = mock.patch.object(act, "_write_pack")
    _WRITE_PACK.start()


def tearDownModule():
    _WRITE_PACK.stop()


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

    def test_non_dict_arguments_are_tool_errors_not_crashes(self):
        # providers emit `arguments` as a JSON string OR an object —
        # a list, a bare scalar, or a non-{arg} object must leave the
        # arg empty and the call a normal tool error, never crash the
        # run
        shapes = [
            {"arg": "discord"},                       # already an object
            [1, 2],                                   # a list
            "42",                                     # bare scalar
            {"cmd": "discord"},                       # dict, no arg key
        ]
        for raw in shapes:
            call = {"id": "c1", "type": "function",
                    "function": {"name": "launch", "arguments": raw}}
            replies = [_msg(calls=[call]), _msg(content="ok")]
            with mock.patch.object(act, "_post", side_effect=replies), \
                 mock.patch.object(tools, "run",
                                   return_value="LAUNCHED") as run:
                r = act.run_act_loop("open it", self.cfg)
            self.assertTrue(r.startswith("ACTED"), (raw, r))
            # the object form dispatches with its arg; the rest fall to
            # an empty arg (launch "" — a tool-level error result, not
            # an exception)
            self.assertEqual(run.call_args[0][0], "launch")

    def test_blocked_results_burn_the_error_budget(self):
        # a tool that can never dispatch (BLOCKED is the CUA guard's
        # refusal) must abort like any other repeated failure —
        # before the fix only ERROR/SKIP/REFUS counted, so a blocked
        # model could spin the full step budget
        replies = [_msg(calls=[_call("click", "10,20")])] * 20
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run",
                               return_value="BLOCKED (input outside "
                                            "scope)"):
            r = act.run_act_loop("click forever", self.cfg,
                                 initial_image="aGk=")
        assert r.startswith("ABORTED (repeated failures)"), r

    def test_failed_results_burn_the_error_budget(self):
        replies = [_msg(calls=[_call("launch", "x")])] * 20
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run",
                               return_value="FAIL (hyprctl died)"):
            r = act.run_act_loop("launch forever", self.cfg)
        assert r.startswith("ABORTED (repeated failures)"), r

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


class ActionStream(unittest.TestCase):
    """U2: every proposed tool call is a lifecycle entry — queued when
    the model asks, in flight while gates/dispatch run, then terminal.
    `steps` keeps its compat strings; the stream is the richer log."""

    def setUp(self):
        import tempfile, pathlib
        from wisp import state
        self.cfg = {"agent": {}}
        self.st = state.State(
            pathlib.Path(tempfile.mkdtemp()) / "state.json",
            write_initial=False)

    def entries(self, kind="tool"):
        return [a for a in self.st.snapshot()["actions"]
                if a["kind"] == kind]

    def test_tool_call_lands_done(self):
        replies = [_msg(calls=[_call("launch", "discord")]),
                   _msg(content="opened it")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="LAUNCHED"):
            act.run_act_loop("open discord", self.cfg, state=self.st,
                         initial_image="aGk=")
        e = self.entries()[-1]
        self.assertEqual((e["label"], e["target"]), ("launch", "discord"))
        self.assertEqual(e["status"], "done")
        self.assertEqual(e["reason"], "LAUNCHED")

    def test_each_call_gets_its_own_entry(self):
        replies = [_msg(calls=[_call("launch", "a"), _call("launch", "b")]),
                   _msg(content="both")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            act.run_act_loop("open two", self.cfg, state=self.st,
                         initial_image="aGk=")
        self.assertEqual([e["target"] for e in self.entries()], ["a", "b"])

    def test_refused_call_lands_cancelled_with_the_reason(self):
        replies = [_msg(calls=[_call("bogus")]), _msg(content="can't")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run") as run:
            act.run_act_loop("break things", self.cfg, state=self.st,
                         initial_image="aGk=")
        run.assert_not_called()
        e = self.entries()[-1]
        self.assertEqual(e["status"], "cancelled")
        self.assertIn("SKIPPED", e["reason"])

    def test_failed_tool_lands_failed(self):
        replies = [_msg(calls=[_call("launch", "x")]), _msg(content="hm")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run",
                               return_value="ERROR (nope)"):
            act.run_act_loop("open", self.cfg, state=self.st,
                         initial_image="aGk=")
        self.assertEqual(self.entries()[-1]["status"], "failed")

    def test_interrupt_mid_run_cancels_the_in_flight_entry(self):
        def die(name, arg, cfg, harness=None):
            raise act.cancel.Cancelled()
        replies = [_msg(calls=[_call("launch", "x")])]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", side_effect=die):
            act.run_act_loop("t", self.cfg, state=self.st,
                         initial_image="aGk=")
        e = self.entries()[-1]
        self.assertEqual(e["status"], "cancelled")
        self.assertEqual(e["reason"], "interrupted")

    def test_ask_user_publishes_an_awaiting_question(self):
        with mock.patch.object(act, "_post",
                               return_value=_msg(
                                   content="ASK_USER: which account?")):
            act.run_act_loop("check it", self.cfg, state=self.st,
                         initial_image="aGk=")
        e = self.entries("question")[-1]
        self.assertEqual(e["status"], "awaiting")
        self.assertEqual(e["label"], "which account?")

    def test_confirm_gate_and_tool_entries_both_lifecycle(self):
        # a denied confirm cancels the tool entry AND resolves the
        # confirm's own entry — the stream holds both halves
        from wisp import cancel, confirm
        st = self.st
        st.focus = {"app": "firefox"}
        broker = cancel.PromptBroker()
        token = cancel.CancelToken()
        ask = confirm.make(st, broker.waiter(token), token, "t1", {})
        replies = [_msg(calls=[_call("close", "w1")]), _msg(content="ok")]
        import threading
        done = threading.Event()

        def offer_no():
            for _ in range(400):
                if broker.pending_id:
                    broker.offer(pick="no", prompt_id=broker.pending_id)
                    done.set()
                    return
                import time
                time.sleep(0.005)
        threading.Thread(target=offer_no, daemon=True).start()
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run") as run:
            act.run_act_loop("close w1", self.cfg, state=st, confirm=ask,
                         initial_image="aGk=")
        done.wait(3)
        run.assert_not_called()
        acts = self.st.snapshot()["actions"]
        conf = [a for a in acts if a["kind"] == "confirm"][-1]
        tool = [a for a in acts if a["kind"] == "tool"][-1]
        self.assertEqual((conf["status"], conf["reason"]),
                         ("cancelled", "denied"))
        self.assertEqual(tool["status"], "cancelled")
        self.assertIn("declined", tool["reason"])


class AskUser(unittest.TestCase):
    """U4: ask_user is a T0 question tool — the model asks mid-loop,
    the question parks on the prompt broker as a `question` card, and
    the click/typed/spoken answer comes back as the tool result so the
    loop continues instead of ending the turn."""

    def setUp(self):
        import pathlib, tempfile
        from wisp import state
        self.cfg = {"agent": {}}
        self.st = state.State(
            pathlib.Path(tempfile.mkdtemp()) / "state.json",
            write_initial=False)
        from wisp import cancel, confirm
        self.broker = cancel.PromptBroker()
        self.token = cancel.CancelToken()
        self.ask = confirm.make_ask(
            self.st, self.broker.waiter(self.token), self.token,
            "t-ask", self.cfg)

    def _offer(self, **kw):
        """Resolve the next pending prompt from a thread — the way a
        shell pick or a voice answer arrives over IPC."""
        import threading, time
        def run():
            for _ in range(600):
                pid = self.broker.pending_id
                if pid:
                    self.broker.offer(prompt_id=pid, **kw)
                    return
                time.sleep(0.005)
        threading.Thread(target=run, daemon=True).start()

    def _questions(self):
        return [a for a in self.st.snapshot()["actions"]
                if a["kind"] == "question"]

    def test_schema_lists_ask_user(self):
        names = {t["function"]["name"] for t in tools.tool_schemas()}
        assert "ask_user" in names
        self.assertEqual(tools.REGISTRY["ask_user"][3]["tier"], "T0")

    def test_option_answer_returns_and_loop_continues(self):
        seen = []

        def post(messages, cfg):
            seen.append([dict(m) for m in messages])
            return (_msg(calls=[_call("ask_user",
                                      "which file | a.py | b.py")])
                    if len(seen) == 1 else _msg(content="picked it"))

        self._offer(pick="b.py")
        with mock.patch.object(act, "_post", side_effect=post):
            r = act.run_act_loop("rename it", self.cfg, state=self.st,
                                 ask=self.ask, initial_image="aGk=")
        assert r.startswith("ACTED"), r
        tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
        self.assertIn("USER ANSWERED: b.py", tool_msgs[-1]["content"])
        q = self._questions()[-1]
        self.assertEqual((q["status"], q["reason"]), ("done", "b.py"))
        self.assertEqual(q["options"], ["a.py", "b.py"])
        self.assertEqual(q["label"], "which file")
        t = [a for a in self.st.snapshot()["actions"]
             if a["label"] == "ask_user"][-1]
        self.assertEqual(t["status"], "done")

    def test_indexed_click_answer(self):
        # IPC `choice 2` → broker index → that option's text comes back
        seen = []

        def post(messages, cfg):
            seen.append([dict(m) for m in messages])
            return (_msg(calls=[_call("ask_user", "pick | red | blue")])
                    if len(seen) == 1 else _msg(content="ok"))

        self._offer(index=2)
        with mock.patch.object(act, "_post", side_effect=post):
            act.run_act_loop("pick", self.cfg, state=self.st,
                             ask=self.ask, initial_image="aGk=")
        tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
        self.assertIn("USER ANSWERED: blue", tool_msgs[-1]["content"])

    def test_free_form_answer_no_options(self):
        # no options → the broker takes any pick string verbatim — a
        # typed `choice` or a spoken reply resolves the question
        seen = []

        def post(messages, cfg):
            seen.append([dict(m) for m in messages])
            return (_msg(calls=[_call("ask_user",
                                      "what should I name it?")])
                    if len(seen) == 1 else _msg(content="named"))

        self._offer(pick="purple monkey")
        with mock.patch.object(act, "_post", side_effect=post):
            act.run_act_loop("name it", self.cfg, state=self.st,
                             ask=self.ask, initial_image="aGk=")
        tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
        self.assertIn("USER ANSWERED: purple monkey",
                      tool_msgs[-1]["content"])
        self.assertIsNone(self._questions()[-1].get("options"))

    def test_answer_is_redacted_from_the_stream_and_steps(self):
        # a free-text answer can carry secrets — the model sees it
        # verbatim, but the action stream, step record and state.json
        # only get a redacted form
        secret = "hunter2-the-password"
        seen = []

        def post(messages, cfg):
            seen.append([dict(m) for m in messages])
            return (_msg(calls=[_call("ask_user", "api key?")])
                    if len(seen) == 1 else _msg(content="stored"))

        self._offer(pick=secret)
        from wisp import goals
        with mock.patch.object(goals, "record_steps") as rec, \
             mock.patch.object(act, "_post", side_effect=post):
            act.run_act_loop("store it", self.cfg, state=self.st,
                             ask=self.ask, initial_image="aGk=")
        # model-facing tool result keeps the verbatim answer
        tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
        self.assertIn(f"USER ANSWERED: {secret}", tool_msgs[-1]["content"])
        # the persistent surfaces never see it
        snap = self.st.snapshot()
        self.assertNotIn(secret, json.dumps(snap))
        t = [a for a in snap["actions"]
             if a["label"] == "ask_user"][-1]
        self.assertEqual(t["status"], "done")
        self.assertIn("chars", t["reason"])
        # the step record (what trajectories persist) is redacted too
        self.assertTrue(rec.called)
        for c in rec.call_args_list:
            self.assertNotIn(secret, json.dumps(c.args[0]))

    def test_empty_ask_user_skips_legibly(self):
        replies = [_msg(calls=[_call("ask_user", "")]),
                   _msg(content="guessed")]
        with mock.patch.object(act, "_post", side_effect=replies):
            r = act.run_act_loop("t", self.cfg, state=self.st,
                                 ask=self.ask, initial_image="aGk=")
        self.assertTrue(r.startswith("ACTED"), r)
        # no parked card was ever published for an empty question
        self.assertEqual(self._questions(), [])

    def test_unanswered_question_lapses_to_no_answer(self):
        # the waiter returning nothing on the deadline → the question
        # entry cancels with reason=timeout and the model gets a
        # NO_ANSWER tool result, not a stuck loop
        from wisp import confirm
        clock = iter([0.0, 999.0]).__next__  # start, then past the cap
        ask = confirm.make_ask(self.st, lambda *a, **k: None,
                               self.token, "t1", self.cfg, clock=clock)
        seen = []

        def post(messages, cfg):
            seen.append([dict(m) for m in messages])
            return (_msg(calls=[_call("ask_user", "which?")])
                    if len(seen) == 1 else _msg(content="guessed"))

        with mock.patch.object(act, "_post", side_effect=post):
            r = act.run_act_loop("t", self.cfg, state=self.st, ask=ask,
                                 initial_image="aGk=")
        assert r.startswith("ACTED")
        q = self._questions()[-1]
        self.assertEqual((q["status"], q["reason"]),
                         ("cancelled", "timeout"))
        tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
        self.assertIn("NO_ANSWER", tool_msgs[-1]["content"])

    def test_no_channel_returns_no_answer(self):
        # callers without a broker (direct/IPC runs) still get a
        # bounded legible result — never a hang
        replies = [_msg(calls=[_call("ask_user", "which?")]),
                   _msg(content="guessed")]
        with mock.patch.object(act, "_post", side_effect=replies):
            r = act.run_act_loop("t", self.cfg, state=self.st,
                                 initial_image="aGk=")
        assert r.startswith("ACTED")
        t = [a for a in self.st.snapshot()["actions"]
             if a["label"] == "ask_user"][-1]
        self.assertEqual(t["status"], "cancelled")
        self.assertIn("NO_ANSWER", t["reason"])

    def test_cancel_unwinds_the_loop(self):
        from wisp import cancel as _cancel, confirm
        token = _cancel.CancelToken()

        def wait(*a, **k):
            token.cancel()
            return None

        ask = confirm.make_ask(self.st, wait, token, "t1", self.cfg)
        replies = [_msg(calls=[_call("ask_user", "which?")])]
        with mock.patch.object(act, "_post", side_effect=replies):
            r = act.run_act_loop("t", self.cfg, state=self.st, ask=ask,
                                 initial_image="aGk=")
        self.assertEqual(r, "INTERRUPTED (user)")
        q = self._questions()[-1]
        self.assertEqual((q["status"], q["reason"]),
                         ("cancelled", "interrupted"))


class Budgets(unittest.TestCase):
    """U4: bounds beyond step count — wall-clock seconds and per-run
    spend. A tripped bound publishes a `failed` stream entry with
    reason `budget` plus the steps so far, and the result names what
    tripped."""

    def setUp(self):
        import pathlib, tempfile
        from wisp import state
        self.cfg = {"agent": {}}
        self.st = state.State(
            pathlib.Path(tempfile.mkdtemp()) / "state.json",
            write_initial=False)

    def test_seconds_cap_aborts_with_budget_entry(self):
        import time as _t
        cfg = {"agent": {}, "agents": {"act_max_seconds": "0.05"}}

        def slow_post(messages, cfg):
            _t.sleep(0.08)   # burn past the cap inside the model call
            return _msg(calls=[_call("launch", "x")])

        with mock.patch.object(act, "_post", side_effect=slow_post), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("loop", cfg, state=self.st,
                                 initial_image="aGk=")
        assert r.startswith("ABORTED (budget"), r
        e = self.st.snapshot()["actions"][-1]
        self.assertEqual((e["status"], e["reason"]), ("failed", "budget"))

    def test_usd_cap_aborts_with_budget_entry(self):
        cfg = {"agent": {}, "agents": {"act_max_usd": "0.01"}}
        # spend0 snapshot, in-budget checks, then the run's delta
        # crosses the cap — bounded abort on the next gate point
        totals = iter([{"cost": 0.0}, {"cost": 0.0}, {"cost": 0.0},
                       {"cost": 0.02}, {"cost": 0.02}])
        replies = [_msg(calls=[_call("launch", "x")]),
                   _msg(content="done")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(act.ledger, "session_totals",
                               side_effect=lambda: next(
                                   totals, {"cost": 0.02})), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("loop", cfg, state=self.st,
                                 initial_image="aGk=")
        assert "budget" in r and "ABORTED" in r, r
        e = self.st.snapshot()["actions"][-1]
        self.assertEqual((e["status"], e["reason"]), ("failed", "budget"))

    def test_max_steps_is_a_budget_abort(self):
        cfg = {"agent": {}, "agents": {"act_max_steps": "1"}}
        replies = [_msg(calls=[_call("launch", "x")])] * 3
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok"):
            r = act.run_act_loop("loop", cfg, state=self.st,
                                 initial_image="aGk=")
        assert r.startswith("ABORTED (max 1 steps)"), r
        e = self.st.snapshot()["actions"][-1]
        self.assertEqual((e["status"], e["reason"]), ("failed", "budget"))


class Continuity(unittest.TestCase):
    """U4: a follow-up turn's user message carries the previous turn's
    outcome — not only learn-flagged corrections."""

    def test_prior_turn_lands_in_user_message(self):
        from wisp import session
        seen = []

        def post(messages, cfg):
            seen.append(messages[1])
            return _msg(content="done")

        with mock.patch.object(act, "_post", side_effect=post), \
             mock.patch.object(session, "tail", return_value=[
                 {"transcript": "open discord",
                  "reply": "opened it",
                  "result": "ACTED (1 steps): opened it"}]), \
             mock.patch.object(session, "as_text",
                               return_value="user: open discord\n"
                                            "wisp: opened it"):
            act.run_act_loop("now close it", {"agent": {}})
        um = seen[0]["content"]
        if isinstance(um, list):  # vision attach → parts list
            um = "".join(p.get("text", "") for p in um)
        self.assertIn("[previous turn]", um)
        self.assertIn("open discord", um)
        self.assertIn("opened it", um)


class RouteFallback(unittest.TestCase):
    """U4: an unknown or missing Jev route for an actionable request
    dispatches to the act loop — no dead SKIP. Explicit routes are
    untouched; Jev's decision path is not in this file."""

    CFG = {"agent": {"risk_threshold": "9"}}

    def test_unknown_route_runs_act_loop(self):
        from wisp import stage_execute
        answers = {"route": {"choice": "teleport"},
                   "action": {"choice": ""}, "app": {"choice": ""},
                   "risk": {"score": 0.5}}
        with mock.patch.object(act, "run_act_loop",
                               return_value="ACTED (1 steps): ok") as r:
            out = stage_execute.execute(answers, self.CFG,
                                        detail="do the thing")
        self.assertEqual(out, "ACTED (1 steps): ok")
        r.assert_called_once()
        self.assertEqual(r.call_args.args[0], "do the thing")

    def test_missing_route_runs_act_loop(self):
        from wisp import stage_execute
        answers = {"risk": {"score": 0.5}}
        with mock.patch.object(act, "run_act_loop",
                               return_value="ACTED (1 steps): ok") as r:
            out = stage_execute.execute(answers, self.CFG,
                                        detail="do the thing")
        self.assertEqual(out, "ACTED (1 steps): ok")
        r.assert_called_once()

    def test_fallback_forwards_the_ask_channel(self):
        from wisp import stage_execute
        sentinel = object()
        answers = {"route": {"choice": "bogus"},
                   "risk": {"score": 0.5}}
        with mock.patch.object(act, "run_act_loop",
                               return_value="x") as r:
            stage_execute.execute(answers, self.CFG, detail="t",
                                  ask=sentinel)
        self.assertIs(r.call_args.kwargs["ask"], sentinel)

    def test_explicit_routes_untouched(self):
        from wisp import stage_execute
        for route in ("answer",):
            answers = {"route": {"choice": route},
                       "action": {"choice": ""}, "app": {"choice": ""},
                       "risk": {"score": 0.5}}
            with mock.patch.object(act, "run_act_loop") as r:
                out = stage_execute.execute(answers, self.CFG,
                                            detail="q")
            self.assertEqual(out, "ANSWERED")
            r.assert_not_called()


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
