#!/usr/bin/env python3
"""Autonomy tier policy (U3, KTD9): tools declare T0-T3 in REGISTRY,
act._gate consults wisp/policy.py, T2 checkpoints batch into one card,
T3 hands off, `agent.autonomy` picks the session mode, and the
"always" pick grants the session the ("*","*") key in state.confirmed.
"""
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import act, policy, tools  # noqa: E402


def _call(name, arg=""):
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"arg": arg})}}


def _msg(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


class Confirm:
    """A rich fake confirm callable — same kwargs surface
    confirm.make() exposes (prompt, kind=, always=) plus .last."""

    def __init__(self, answer=True):
        self.answer = answer
        self.prompts = []
        self.kinds = []
        self.last = ""
        self.rich = True

    def __call__(self, prompt, kind="confirm", always=False):
        self.prompts.append(prompt)
        self.kinds.append(kind)
        self.last = {True: "yes", "always": "always", False: "no"}[
            self.answer]
        return self.answer is not False


STATIC = {"screenshot", "ground", "focus", "launch", "notify",
          "recall", "codegraph", "search_files", "task_status",
          "skill_view", "post", "click", "move", "type_text", "key",
          "scroll", "fill", "workspace", "agent_spawn", "close",
          "task_cancel", "memory", "skill_manage", "mcp_call",
          "post_send", "shell"}


class TierTable(unittest.TestCase):
    """KTD9 lint: the registry's autonomy metadata is load-bearing —
    every static entry declares a valid T-tier, reversibility and
    externality; dynamic/legacy entries still resolve through the
    risk-tier mapping."""

    def test_every_static_entry_has_tier_metadata(self):
        for name in STATIC:
            with self.subTest(tool=name):
                entry = tools.REGISTRY[name]
                self.assertGreater(len(entry), 3, name)
                meta = entry[3]
                self.assertIn(meta["tier"], tools.AUTONOMY_TIERS, name)
                self.assertIsInstance(meta["reversible"], bool, name)
                self.assertIsInstance(meta["external"], bool, name)
                self.assertEqual(tools.meta_of(name), meta, name)

    def test_every_registered_name_resolves_a_tier(self):
        for name in tools.REGISTRY:
            with self.subTest(tool=name):
                self.assertIn(policy.declared_tier(name),
                              tools.AUTONOMY_TIERS, name)

    def test_declared_table_matches_the_plan(self):
        t0 = {"screenshot", "ground", "focus", "launch", "notify",
              "recall", "codegraph", "search_files", "task_status",
              "skill_view", "post"}
        t1 = {"click", "move", "type_text", "key", "scroll", "fill",
              "workspace", "agent_spawn"}
        t2 = {"close", "task_cancel", "memory", "skill_manage",
              "mcp_call", "post_send", "shell"}
        self.assertEqual(STATIC, t0 | t1 | t2)
        for name in t0:
            self.assertEqual(tools.meta_of(name)["tier"], "T0", name)
        for name in t1:
            self.assertEqual(tools.meta_of(name)["tier"], "T1", name)
        for name in t2:
            self.assertEqual(tools.meta_of(name)["tier"], "T2", name)

    def test_t0_tools_never_confirm_under_any_mode(self):
        for mode in ("autonomous", "guided"):
            cfg = {"agent": {"autonomy": mode}}
            for name, entry in tools.REGISTRY.items():
                if entry[3]["tier"] != "T0":
                    continue
                self.assertEqual(
                    policy.decide(name, "", cfg), "run", (name, mode))

    def test_unknown_and_untiered_names_fail_closed(self):
        self.assertEqual(policy.declared_tier("bogus"), "T2")
        self.assertEqual(policy.decide("bogus", "x", {}), "confirm")


class TierRefinements(unittest.TestCase):
    """Per-call tier resolution — the declared tier is the ceiling a
    refinement can lower for read/reversible shapes."""

    def test_memory_add_is_t1_the_rest_stays_t2(self):
        for arg in ("memory|add|fact", "user|add|prefers dark mode"):
            self.assertEqual(policy.tier_of("memory", arg), "T1", arg)
        for arg in ("memory|remove|f", "memory|replace|o|n",
                    "memory|write|whole|body", "", "garbage"):
            self.assertEqual(policy.tier_of("memory", arg), "T2", arg)

    def test_mcp_read_shape_is_t0(self):
        for arg in ("dayflow get_today", "browseros tabs "
                    "{\"action\":\"list\"}",
                    "gmail gmail/list_messages {}",
                    "server search_files {}"):
            self.assertEqual(policy.tier_of("mcp_call", arg), "T0", arg)

    def test_mcp_write_shape_is_t2(self):
        for arg in ("browseros tabs {\"action\":\"close\"}",
                    "gmail gmail/send_message {}",
                    "server execute_action {}",
                    "server frobnicate"):
            self.assertEqual(policy.tier_of("mcp_call", arg), "T2", arg)

    def test_mcp_credential_shape_is_t3(self):
        for arg in ("strata google/oauth_start {}",
                    "auth login_flow {}",
                    "shop payment/charge {}",
                    "svc checkout {}"):
            self.assertEqual(policy.tier_of("mcp_call", arg), "T3", arg)

    def test_mcp_t3_needs_only_the_tool_name_not_the_args(self):
        # a "payment history" lookup must not pause the run — hints
        # bind the server+tool names, not the JSON body
        self.assertEqual(
            policy.tier_of("mcp_call",
                           "bank list_tx {\"of\":\"payments\"}"), "T0")

    def test_skill_manage_list_is_t0(self):
        self.assertEqual(policy.tier_of("skill_manage", "list"), "T0")
        self.assertEqual(policy.tier_of("skill_manage", "delete|x"),
                         "T2")

    def test_cua_confirm_always_promotes_t1(self):
        cfg = {"cua": {"confirm": "always"}}
        self.assertEqual(policy.tier_of("click", "1,2", cfg), "T2")
        self.assertEqual(policy.tier_of("type_text", "hi", cfg), "T2")
        # non-guarded T1 tools stay T1; T0 stays T0
        self.assertEqual(policy.tier_of("workspace", "3", cfg), "T1")
        self.assertEqual(policy.tier_of("launch", "x", cfg), "T0")


class Modes(unittest.TestCase):
    def test_default_mode_is_autonomous(self):
        for cfg in ({}, {"agent": {}}, {"agent": {"autonomy": "weird"}},
                    None):
            self.assertEqual(policy.mode_of(cfg), "autonomous", cfg)

    def test_modes_parse(self):
        for m in policy.MODES:
            cfg = {"agent": {"autonomy": m}}
            self.assertEqual(policy.mode_of(cfg), m)

    def test_autonomous_t1_free_t2_confirms(self):
        cfg = {"agent": {"autonomy": "autonomous"}}
        self.assertEqual(policy.decide("click", "1,2", cfg), "run")
        self.assertEqual(policy.decide("close", "w", cfg), "confirm")

    def test_guided_confirms_t1_too(self):
        cfg = {"agent": {"autonomy": "guided"}}
        self.assertEqual(policy.decide("click", "1,2", cfg), "confirm")
        self.assertEqual(policy.decide("launch", "x", cfg), "run")

    def test_always_ask_confirms_everything(self):
        cfg = {"agent": {"autonomy": "always_ask"}}
        self.assertEqual(policy.decide("launch", "x", cfg), "confirm")
        self.assertEqual(policy.decide("click", "1,2", cfg), "confirm")

    def test_t3_is_a_handoff_under_every_mode(self):
        for mode in policy.MODES:
            cfg = {"agent": {"autonomy": mode}}
            self.assertEqual(
                policy.decide("mcp_call", "a oauth/b {}", cfg),
                "handoff", mode)


class Gate(unittest.TestCase):
    """act._gate now consults policy.gate — denylist preempts first,
    then tier+mode, then the confirm-once/grant sets."""

    def test_t1_runs_confirm_free(self):
        assert act._gate("click", "10,10", {"agent": {}}, None) is None
        assert act._gate("type_text", "hi", {"agent": {}}, None) is None

    def test_t0_never_confirms(self):
        assert act._gate("launch", "x", {"agent": {}}, None) is None
        assert act._gate("screenshot", "", {"agent": {}}, None) is None

    def test_t2_confirms(self):
        cfg = {"agent": {}}
        ask = Confirm(answer=True)
        self.assertIsNone(act._gate("close", "w", cfg, ask))
        self.assertEqual(ask.prompts, ["run close: w?"])

    def test_t2_skips_without_a_confirm_channel(self):
        out = act._gate("close", "w", {"agent": {}}, None)
        self.assertIn("SKIPPED", out)

    def test_denylist_preempts_before_policy(self):
        cfg = {"agent": {"allow_shell": "true"}}
        out = act._gate("shell", "rm -rf /", cfg, lambda p: True)
        self.assertIn("REFUSED", out)
        out = act._gate("type_text", "rm -rf /", {"agent": {}}, None)
        self.assertIn("REFUSED", out)

    def test_shell_still_needs_allow_shell(self):
        out = act._gate("shell", "ls", {"agent": {}}, lambda p: True)
        self.assertIn("SKIPPED", out)

    def test_confirm_once_per_tool_and_app(self):
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        ask = Confirm()
        cfg = {"agent": {}}
        self.assertIsNone(act._gate("close", "w1", cfg, ask, state=st))
        self.assertIsNone(act._gate("close", "w2", cfg, ask, state=st))
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn(("close", "firefox"), st.confirmed)

    def test_always_pick_grants_the_session_wildcard(self):
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        ask = Confirm(answer="always")
        cfg = {"agent": {}}
        self.assertIsNone(act._gate("close", "w", cfg, ask, state=st))
        self.assertIn(("*", "*"), st.confirmed)
        # every later gated call is covered — a different tool too
        self.assertIsNone(
            act._gate("shell", "ls",
                      {"agent": {"allow_shell": "true"}}, ask, state=st))
        self.assertEqual(len(ask.prompts), 1)

    def test_guided_mode_confirms_t1(self):
        cfg = {"agent": {"autonomy": "guided"}}
        ask = Confirm(answer=False)
        out = act._gate("click", "1,2", cfg, ask)
        self.assertIn("declined", out)

    def test_always_ask_confirms_t0(self):
        cfg = {"agent": {"autonomy": "always_ask"}}
        ask = Confirm(answer=True)
        self.assertIsNone(act._gate("launch", "x", cfg, ask))
        self.assertTrue(ask.prompts)

    def test_cua_confirm_always_promotes_through_policy(self):
        cfg = {"agent": {}, "cua": {"confirm": "always"}}
        ask = Confirm(answer=False)
        out = act._gate("click", "1,2", cfg, ask)
        self.assertIn("declined", out)

    def test_t3_hands_off_and_the_tool_never_runs(self):
        ask = Confirm(answer=True)
        out = act._gate("mcp_call", "strata oauth/start {}", {},
                        ask)
        self.assertEqual(out, "HANDED_OFF (mcp_call done by the user)")
        self.assertEqual(ask.kinds, ["handoff"])

    def test_t3_handoff_declined_skips(self):
        ask = Confirm(answer=False)
        out = act._gate("mcp_call", "svc payment/charge {}", {}, ask)
        self.assertIn("SKIPPED", out)
        self.assertIn("declined", out)

    def test_t3_handoff_needs_a_channel(self):
        out = act._gate("mcp_call", "svc oauth/x {}", {}, None)
        self.assertIn("SKIPPED", out)

    def test_t3_never_takes_a_grant(self):
        # the ("*","*") wildcard must not turn a human-only step into a
        # silent run — handoff is checked before the grant lookup
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = {("*", "*")}
        ask = Confirm(answer=True)
        out = act._gate("mcp_call", "svc oauth/x {}", {}, ask, state=st)
        self.assertTrue(out.startswith("HANDED_OFF"))

    def test_decline_is_remembered_for_the_run(self):
        ctx = policy.gate_ctx()
        ask = Confirm(answer=False)
        out = act._gate("close", "w1", {"agent": {}}, ask, ctx=ctx)
        self.assertIn("declined", out)
        out = act._gate("close", "w2", {"agent": {}}, ask, ctx=ctx)
        self.assertIn("declined", out)
        self.assertEqual(len(ask.prompts), 1)

    def test_timeout_maps_to_the_timeout_result(self):
        def fake(prompt, kind="confirm", always=False):
            return False
        fake.last = "timeout"
        fake.rich = True
        out = act._gate("close", "w", {"agent": {}}, fake)
        self.assertEqual(out, "SKIPPED (close confirmation timed out)")


class Checkpoints(unittest.TestCase):
    """T2 batching: one card per reply covering every gated step still
    queued — the card names the steps, not just the first tool."""

    def test_batch_prompt_names_every_step(self):
        p = policy.checkpoint_prompt(
            [("close", "w1"), ("task_cancel", "fix"), ("shell", "ls")])
        self.assertIn("3 steps", p)
        for s in ("close w1", "task_cancel fix", "shell ls"):
            self.assertIn(s, p)

    def test_single_step_keeps_the_old_shape(self):
        self.assertEqual(
            policy.checkpoint_prompt([("close", "w1")]),
            "run close: w1?")
        self.assertEqual(
            policy.checkpoint_prompt([("close", "")]),
            "run close: (no arg)?")

    def test_one_card_covers_a_gated_batch(self):
        # model proposes two gated calls in one reply -> one card; a
        # yes grants both
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = set()
        ctx = policy.gate_ctx()
        ask = Confirm()
        batch = [("task_cancel", "fix")]
        cfg = {"agent": {}}
        self.assertIsNone(
            act._gate("close", "w", cfg, ask, state=st,
                      batch=batch, ctx=ctx))
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("close w", ask.prompts[0])
        self.assertIn("task_cancel fix", ask.prompts[0])
        # the queued call's own gate consults the grant — no second card
        self.assertIsNone(
            act._gate("task_cancel", "fix", cfg, ask, state=st, ctx=ctx))
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn(("task_cancel", "firefox"), st.confirmed)

    def test_batch_skips_already_granted_and_nongated_calls(self):
        st = mock.Mock()
        st.focus = {"app": "firefox"}
        st.confirmed = {("task_cancel", "firefox")}
        ctx = policy.gate_ctx()
        ask = Confirm()
        # shell joins the card only when allow_shell=true — otherwise
        # the preempt refuses it outright and it isn't a "pending step"
        cfg = {"agent": {"allow_shell": "true"}}
        # click is T1 (runs free under autonomous), task_cancel is
        # already granted — the card should list only close + shell
        self.assertIsNone(
            act._gate("close", "w", cfg, ask, state=st,
                      batch=[("click", "1,2"), ("task_cancel", "x"),
                             ("shell", "ls")], ctx=ctx))
        self.assertIn("close w", ask.prompts[0])
        self.assertIn("shell ls", ask.prompts[0])
        self.assertNotIn("task_cancel", ask.prompts[0])
        self.assertNotIn("click", ask.prompts[0])

    def test_a_no_declines_every_step_in_the_batch(self):
        ctx = policy.gate_ctx()
        ask = Confirm(answer=False)
        cfg = {"agent": {"allow_shell": "true"}}
        out = act._gate("close", "w", cfg, ask,
                        batch=[("shell", "ls")], ctx=ctx)
        self.assertIn("declined", out)
        out = act._gate("shell", "ls", cfg, ask, ctx=ctx)
        self.assertIn("declined", out)
        self.assertEqual(len(ask.prompts), 1)


class LoopPaths(unittest.TestCase):
    """run_act_loop with a faked confirm callable — each tier's path
    through the real loop."""

    def setUp(self):
        self.cfg = {"agent": {}}
        self.st = mock.Mock()
        self.st.focus = {"app": "firefox"}
        self.st.confirmed = set()

    def test_t1_steps_run_without_a_card(self):
        ask = Confirm()
        replies = [_msg(calls=[_call("click", "1,2"),
                               _call("type_text", "hi")]),
                   _msg(content="done")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok") as run:
            r = act.run_act_loop("t", self.cfg, state=self.st,
                                 confirm=ask, initial_image="aGk=")
        self.assertTrue(r.startswith("ACTED"), r)
        self.assertEqual(ask.prompts, [])
        self.assertEqual(run.call_count, 2)

    def test_t2_batch_card_covers_the_reply(self):
        ask = Confirm()
        replies = [_msg(calls=[_call("close", "w1"),
                               _call("task_cancel", "fix")]),
                   _msg(content="done")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run", return_value="ok") as run:
            r = act.run_act_loop("t", self.cfg, state=self.st,
                                 confirm=ask, initial_image="aGk=")
        self.assertTrue(r.startswith("ACTED"), r)
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("close w1", ask.prompts[0])
        self.assertIn("task_cancel fix", ask.prompts[0])
        self.assertEqual(run.call_count, 2)

    def test_t3_pauses_and_resumes_on_done(self):
        ask = Confirm()
        replies = [_msg(calls=[_call("mcp_call", "svc oauth/x {}")]),
                   _msg(content="user signed in")]
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch.object(tools, "run") as run:
            r = act.run_act_loop("t", self.cfg, state=self.st,
                                 confirm=ask, initial_image="aGk=")
        self.assertTrue(r.startswith("ACTED"), r)
        self.assertEqual(ask.kinds, ["handoff"])
        run.assert_not_called()   # the human did the step, not the tool

    def test_t1_entries_carry_an_undo_ref(self):
        added = {}

        def action_add(state, kind, label, **kw):
            if kind == "tool":
                added[kw.get("target", "")] = kw.get("undo_ref")
            return "a1"

        replies = [_msg(calls=[_call("click", "1,2"),
                               _call("close", "w")]),
                   _msg(content="done")]
        ask = Confirm()
        with mock.patch.object(act, "_post", side_effect=replies), \
             mock.patch("wisp.act._state.action_add",
                        side_effect=action_add), \
             mock.patch.object(tools, "run", return_value="ok"):
            act.run_act_loop("t", self.cfg, state=self.st,
                             confirm=ask, initial_image="aGk=")
        self.assertEqual(added.get("1,2"), "undo in the app")
        self.assertIsNone(added.get("w"))   # T2 carries no undo hint


if __name__ == "__main__":
    unittest.main()
