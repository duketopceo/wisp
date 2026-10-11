#!/usr/bin/env python3
"""state.js: the pure reducer behind WispService.qml (W17).

Runs shell-plugin/lib/state.js under node. Covers contract versioning
(contract_version, seq, turn_id), diff events, gap and restart handling,
graceful degradation (bad JSON, missing fields, unknown status or error
code, newer contract), the 5 s stale flag and reconnect backoff.
Contract: docs/IPC_CONTRACT.md.
"""
import json
import unittest

import jsnode


def js(expr):
    return jsnode.call(expr, S="state")


def snap(**kw):
    base = {"status": "idle", "seq": 1, "turn_id": "t1",
            "contract_version": 2, "started_at": "2026-10-04T10:00:00Z",
            "updated_at": "2026-10-04T10:00:01Z"}
    base.update(kw)
    return base


def run(steps):
    """Fold a list of ops over initial(); returns the last result.
    op = ["snap", obj, ms] | ["event", obj, ms] | ["msg", str, ms]
       | ["offline", ms]"""
    return js("""(function(steps){
      var r = {view: S.initial(), resync: false, ok: true};
      steps.forEach(function(op){
        if (op[0] === "snap") r = S.applySnapshot(r.view, op[1], op[2], "file");
        else if (op[0] === "event") r = S.applyEvent(r.view, op[1], op[2]);
        else if (op[0] === "msg") r = S.applyMessage(r.view, op[1], op[2], "stream");
        else if (op[0] === "offline") r = {view: S.markOffline(r.view, op[1]), resync: false, ok: true};
      });
      return r;
    })(%s)""" % json.dumps(steps))


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestSnapshot(unittest.TestCase):
    def test_initial_is_offline_and_empty(self):
        v = js("S.initial()")
        self.assertEqual(v["status"], "offline")
        self.assertEqual(v["connection"], "none")
        self.assertEqual(v["choices"], [])
        self.assertEqual(v["points"], [])
        self.assertIsNone(v["seq"])
        self.assertFalse(v["stale"])

    def test_full_snapshot_maps_every_field(self):
        s = snap(status="awaiting_choice", transcript="open firefox",
                 answer="a", result="r", choices=["yes", "no"],
                 prompt_id="p1", points=[{"x": 1, "y": 2}], steps=["s"],
                 guide={"x": 1, "y": 2, "label": "l", "mode": "guide",
                        "seq": 1},
                 focus={"app": "kitty", "title": "t"},
                 goal={"text": "ship", "status": "open"}, level=0.4,
                 tasks={"a": "running"}, error="", error_code="",
                 health={"jev": {"ok": True}}, seq=7, turn_id="t9",
                 actions=[{"id": "a1", "kind": "tool", "label": "click",
                           "status": "done", "target": "1,2",
                           "reason": "ok", "undo_ref": None,
                           "at": "2026-10-04T10:00:00Z"}],
                 heartbeat_at="2026-10-04T10:00:02Z")
        v = run([["snap", s, 1000]])["view"]
        self.assertEqual(v["status"], "awaiting_choice")
        self.assertEqual(v["transcript"], "open firefox")
        self.assertEqual(v["choices"], ["yes", "no"])
        self.assertEqual(v["promptId"], "p1")
        self.assertEqual(v["points"], [{"x": 1, "y": 2}])
        self.assertEqual(v["steps"], ["s"])
        self.assertEqual(v["guide"]["mode"], "guide")
        self.assertEqual(v["focus"]["app"], "kitty")
        self.assertEqual(v["goal"], "ship")
        self.assertEqual(v["goalStatus"], "open")
        self.assertEqual(v["level"], 0.4)
        self.assertEqual(v["tasks"], {"a": "running"})
        self.assertEqual(v["health"], {"jev": {"ok": True}})
        self.assertEqual(v["actions"][0]["id"], "a1")
        self.assertEqual((v["seq"], v["turnId"], v["contractVersion"]),
                         (7, "t9", 2))
        self.assertEqual(v["heartbeatAt"], "2026-10-04T10:00:02Z")
        self.assertFalse(v["offline"])

    def test_legacy_snapshot_without_additive_fields(self):
        v = run([["snap", {"status": "done", "answer": "hi"}, 5]])["view"]
        self.assertEqual(v["status"], "done")
        self.assertEqual(v["contractVersion"], 1)  # absent means v1
        self.assertIsNone(v["seq"])
        self.assertEqual(v["goal"], "")
        self.assertEqual(v["focus"], {})
        self.assertEqual(v["health"], {})
        self.assertEqual(v["errorCode"], "")

    def test_goal_string_form(self):
        v = run([["snap", snap(goal="plain goal"), 1]])["view"]
        self.assertEqual(v["goal"], "plain goal")

    def test_unknown_status_is_idle_equivalent(self):
        v = run([["snap", snap(status="levitating"), 1]])["view"]
        self.assertEqual(v["status"], "idle")
        self.assertEqual(v["rawStatus"], "levitating")

    def test_unknown_error_code_reads_internal(self):
        v = run([["snap", snap(status="error", error_code="zzz"), 1]])["view"]
        self.assertEqual(v["errorCode"], "internal")
        v = run([["snap", snap(status="error", error_code="timeout"), 1]])["view"]
        self.assertEqual(v["errorCode"], "timeout")

    def test_malformed_fields_degrade(self):
        v = run([["snap", snap(choices="nope", points={"x": 1}, tasks=[1],
                               level="loud", focus=None, steps=5), 1]])["view"]
        self.assertEqual(v["choices"], [])
        self.assertEqual(v["points"], [])
        self.assertEqual(v["tasks"], {})
        self.assertEqual(v["level"], 0)
        self.assertEqual(v["focus"], {})
        self.assertEqual(v["steps"], [])

    def test_level_is_clamped(self):
        self.assertEqual(run([["snap", snap(level=3), 1]])["view"]["level"], 1)
        self.assertEqual(run([["snap", snap(level=-1), 1]])["view"]["level"], 0)

    def test_newer_contract_flagged_but_still_read(self):
        v = run([["snap", snap(contract_version=3, status="acting"), 1]])["view"]
        self.assertTrue(v["contractNewer"])
        self.assertEqual(v["status"], "acting")
        v = run([["snap", snap(contract_version=2), 1]])["view"]
        self.assertFalse(v["contractNewer"])

    def test_older_seq_same_daemon_is_dropped(self):
        r = run([["snap", snap(seq=10, answer="new"), 1],
                 ["snap", snap(seq=9, answer="old"), 2]])
        self.assertEqual(r["view"]["answer"], "new")
        self.assertFalse(r["ok"])

    def test_same_seq_is_a_noop_that_does_not_refresh(self):
        r = run([["snap", snap(seq=10), 1000], ["snap", snap(seq=10), 4000]])
        self.assertEqual(r["view"]["changedAtMs"], 1000)

    def test_daemon_restart_resets_seq(self):
        r = run([["snap", snap(seq=50, answer="old"), 1],
                 ["snap", snap(seq=2, answer="fresh",
                               started_at="2026-10-04T11:00:00Z"), 2]])
        self.assertEqual(r["view"]["answer"], "fresh")
        self.assertEqual(r["view"]["seq"], 2)
        self.assertTrue(r["ok"])

    def test_snapshot_without_seq_always_applies(self):
        r = run([["snap", {"status": "idle", "answer": "a"}, 1],
                 ["snap", {"status": "idle", "answer": "b"}, 2]])
        self.assertEqual(r["view"]["answer"], "b")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestEvents(unittest.TestCase):
    base = [["snap", snap(seq=5, status="idle"), 1000]]

    def diff(self, seq, **d):
        d.update(seq=seq)
        return ["event", {"type": "state", "seq": seq, "diff": d}, 2000]

    def test_diff_with_next_seq_merges(self):
        r = run(self.base + [self.diff(6, status="deciding",
                                       transcript="hello", turn_id="t2")])
        v = r["view"]
        self.assertEqual((v["status"], v["transcript"], v["seq"],
                          v["turnId"]), ("deciding", "hello", 6, "t2"))
        self.assertEqual(v["answer"], "")  # untouched fields survive
        self.assertFalse(r["resync"])

    def test_diff_keeps_other_fields(self):
        r = run([["snap", snap(seq=5, answer="keep"), 1], self.diff(6, level=0.5)])
        self.assertEqual(r["view"]["answer"], "keep")
        self.assertEqual(r["view"]["level"], 0.5)

    def test_gap_requests_resync_and_does_not_apply(self):
        r = run(self.base + [self.diff(9, status="acting")])
        self.assertTrue(r["resync"])
        self.assertEqual(r["view"]["status"], "idle")
        self.assertEqual(r["view"]["seq"], 5)

    def test_duplicate_or_old_diff_is_dropped(self):
        r = run(self.base + [self.diff(5, status="acting")])
        self.assertEqual(r["view"]["status"], "idle")
        self.assertFalse(r["resync"])
        self.assertFalse(r["ok"])

    def test_diff_before_any_snapshot_requests_resync(self):
        r = run([self.diff(6, status="acting")])
        self.assertTrue(r["resync"])
        self.assertEqual(r["view"]["status"], "offline")

    def test_health_changed_event(self):
        r = run(self.base + [["event", {"type": "event", "name":
                "health_changed", "data": {"name": "jev", "ok": False,
                                           "code": "jev_down"}}, 2000]])
        h = r["view"]["health"]["jev"]
        self.assertFalse(h["ok"])
        self.assertEqual(h["code"], "jev_down")
        self.assertEqual(r["view"]["seq"], 5)  # events never bump seq

    def test_spend_field_is_carried_into_the_view(self):
        spend = {"today_usd": 0.5, "cap_usd": 2.0, "month_usd": 3.0,
                 "monthly_cap_usd": 20.0, "blocked": False}
        r = run([["snap", snap(spend=spend), 1000]])
        self.assertEqual(r["view"]["spend"], spend)
        r = run([["snap", snap(), 1000]])
        self.assertEqual(r["view"]["spend"], {})

    def test_overflow_requests_resync(self):
        r = run(self.base + [["event", {"type": "event", "name": "overflow"}, 2]])
        self.assertTrue(r["resync"])

    def test_unknown_event_is_ignored_but_counts_as_alive(self):
        r = run(self.base + [["event", {"type": "event", "name":
                                        "something_new"}, 3000]])
        self.assertTrue(r["ok"])
        self.assertEqual(r["view"]["status"], "idle")
        self.assertEqual(r["view"]["lastMessageMs"], 3000)

    def test_stale_marker_after_event_gap_resolved_by_snapshot(self):
        r = run(self.base + [self.diff(9, status="acting"),
                             ["snap", snap(seq=9, status="acting"), 2500]])
        self.assertEqual(r["view"]["status"], "acting")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestMessages(unittest.TestCase):
    def test_reply_envelope_with_state(self):
        line = json.dumps({"ok": True, "state": snap(status="done")})
        v = run([["msg", line, 1]])["view"]
        self.assertEqual(v["status"], "done")
        self.assertEqual(v["connection"], "stream")

    def test_typed_snapshot_and_diff_lines(self):
        a = json.dumps({"type": "snapshot", "state": snap(seq=3)})
        b = json.dumps({"type": "state", "seq": 4,
                        "diff": {"status": "listening", "seq": 4}})
        v = run([["msg", a, 1], ["msg", b, 2]])["view"]
        self.assertEqual((v["status"], v["seq"]), ("listening", 4))

    def test_bare_state_object(self):
        v = run([["msg", json.dumps(snap(status="speaking")), 1]])["view"]
        self.assertEqual(v["status"], "speaking")

    def test_bad_json_is_survivable(self):
        good = json.dumps(snap(status="done", seq=2))
        r = run([["msg", good, 1], ["msg", "{not json", 2]])
        self.assertFalse(r["ok"])
        self.assertEqual(r["view"]["status"], "done")
        self.assertEqual(r["view"]["parseErrors"], 1)

    def test_server_refusal_marks_unsupported(self):
        r = run([["msg", json.dumps({"ok": False,
                                     "error": "unknown cmd"}), 1]])
        self.assertFalse(r["ok"])
        self.assertTrue(r["refused"])

    def test_hello_ok_records_contract_and_is_not_an_error(self):
        r = run([["msg", json.dumps({"type": "hello", "ok": True,
                 "contract_version": 1, "topics": ["state"]}), 1]])
        self.assertTrue(r["ok"])
        self.assertFalse(r["refused"])
        self.assertEqual(r["view"]["connection"], "stream")

    def test_hello_newer_contract_flags(self):
        r = run([["msg", json.dumps({"type": "hello", "ok": True,
                                     "contract_version": 3}), 1]])
        self.assertTrue(r["view"]["contractNewer"])

    def test_hello_refused_means_fall_back(self):
        r = run([["msg", json.dumps({"type": "hello", "ok": False,
                                     "error": "nope"}), 1]])
        self.assertTrue(r["refused"])
        self.assertEqual(r["view"]["connection"], "none")

    def test_ping_refreshes_liveness_only(self):
        r = run([["snap", snap(status="acting", seq=1), 1000],
                 ["msg", json.dumps({"type": "ping"}), 9000]])
        self.assertTrue(r["ok"])
        self.assertEqual(r["view"]["lastMessageMs"], 9000)
        self.assertEqual(r["view"]["status"], "acting")

    def test_subscribe_request(self):
        req = js("S.subscribeRequest()")
        self.assertEqual(req["cmd"], "subscribe")
        self.assertEqual(req["topics"],
                         ["state", "health", "tasks", "events"])

    def test_empty_line_ignored(self):
        self.assertTrue(run([["msg", "", 1]])["view"]["status"] == "offline")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestStaleAndOffline(unittest.TestCase):
    def stale(self, steps, now, after=None):
        a = "" if after is None else f", {after}"
        return js("(function(){var v=%s; return S.isStale(v, %d%s)})()" % (
            json.dumps(run(steps)["view"]), now, a))

    def test_ping_does_not_hide_a_stuck_turn(self):
        # a ping proves the socket is up, not that the turn is moving
        steps = [["snap", snap(status="acting", seq=1), 10000],
                 ["msg", json.dumps({"type": "ping"}), 14000]]
        self.assertTrue(self.stale(steps, 30001))

    def test_busy_snapshot_goes_stale_after_twenty_seconds(self):
        steps = [["snap", snap(status="deciding", seq=1), 10000]]
        self.assertFalse(self.stale(steps, 29900))
        self.assertTrue(self.stale(steps, 30001))

    def test_activity_refreshes_freshness(self):
        steps = [["snap", snap(status="acting", seq=1), 10000],
                 ["event", {"type": "state", "seq": 2,
                            "diff": {"level": 0.2, "seq": 2}}, 14000]]
        self.assertFalse(self.stale(steps, 33900))
        self.assertTrue(self.stale(steps, 34100))

    def test_heartbeat_change_refreshes_freshness(self):
        steps = [["snap", snap(status="acting", seq=1,
                               heartbeat_at="a"), 10000],
                 ["snap", snap(status="acting", seq=2,
                               heartbeat_at="b"), 14000]]
        self.assertFalse(self.stale(steps, 18000))

    def test_idle_and_done_are_never_stale(self):
        for st in ("idle", "done", "error", "awaiting_choice"):
            steps = [["snap", snap(status=st), 0]]
            self.assertFalse(self.stale(steps, 600000), st)

    def test_offline_is_not_stale_it_is_offline(self):
        steps = [["snap", snap(status="acting"), 0], ["offline", 1]]
        self.assertFalse(self.stale(steps, 600000))
        v = run(steps)["view"]
        self.assertEqual(v["status"], "offline")
        self.assertTrue(v["offline"])
        self.assertEqual(v["connection"], "none")

    def test_threshold_is_configurable(self):
        steps = [["snap", snap(status="acting"), 0]]
        self.assertTrue(self.stale(steps, 2500, 2000))
        self.assertFalse(self.stale(steps, 2500, 3000))

    def test_default_threshold_is_five_seconds(self):
        self.assertEqual(js("S.STALE_AFTER_MS"), 20000)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestReconnect(unittest.TestCase):
    def test_backoff_doubles_and_caps(self):
        got = [js(f"S.backoffMs({n})") for n in range(8)]
        self.assertEqual(got, [500, 1000, 2000, 4000, 8000, 15000, 15000,
                               15000])

    def test_backoff_handles_junk(self):
        self.assertEqual(js("S.backoffMs(-3)"), 500)
        self.assertEqual(js("S.backoffMs(undefined)"), 500)

    def test_disconnect_keeps_content_until_proven_offline(self):
        v = js("""(function(){var r=S.applySnapshot(S.initial(),%s,1,"stream");
          return S.markDisconnected(r.view)})()""" % json.dumps(
              snap(status="acting", answer="x")))
        self.assertEqual((v["status"], v["answer"], v["connection"],
                          v["offline"]), ("acting", "x", "none", False))

    def test_reconnect_replay_replaces_baseline(self):
        r = run([["snap", snap(seq=40, answer="before"), 1],
                 ["offline", 2],
                 ["msg", json.dumps({"type": "snapshot", "state":
                                     snap(seq=40, answer="before2")}), 3]])
        self.assertEqual(r["view"]["status"], "idle")
        self.assertFalse(r["view"]["offline"])
        self.assertEqual(r["view"]["connection"], "stream")

    def test_connection_label_follows_source(self):
        v = run([["snap", snap(), 1]])["view"]
        self.assertEqual(v["connection"], "file")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestCuaTarget(unittest.TestCase):
    """cua.target stream event (W21 ghost cursor input; W13 emits it)."""

    EV = {"type": "event", "name": "cua.target",
          "data": {"x": 640, "y": 360, "window": "Settings",
                   "label": "night light", "confidence": 0.9}}

    def acting(self, **kw):
        return ["snap", snap(status="acting", seq=2, **kw), 1]

    def test_target_is_normalized_with_defaults(self):
        r = run([self.acting(), ["event", self.EV, 2]])
        self.assertEqual(r["view"]["cuaTarget"], {
            "x": 640, "y": 360, "window": "Settings",
            "label": "night light", "confidence": 0.9, "phase": "aim",
            "delivery": ""})

    def test_absent_by_default(self):
        self.assertIsNone(run([self.acting()])["view"]["cuaTarget"])
        self.assertIsNone(js("S.initial().cuaTarget"))

    def test_malformed_is_ignored_and_keeps_current(self):
        bad = {"type": "event", "name": "cua.target",
               "data": {"x": "5", "y": 2}}
        r = run([self.acting(), ["event", self.EV, 2], ["event", bad, 3]])
        self.assertEqual(r["view"]["cuaTarget"]["x"], 640)
        self.assertFalse(r["ok"])

    def test_explicit_clear(self):
        clear = {"type": "event", "name": "cua.target",
                 "data": {"x": None, "y": None}}
        r = run([self.acting(), ["event", self.EV, 2], ["event", clear, 3]])
        self.assertIsNone(r["view"]["cuaTarget"])

    def test_confidence_clamped_phase_closed_set(self):
        ev = {"type": "event", "name": "cua.target",
              "data": {"x": 1, "y": 2, "confidence": 7, "phase": "weird"}}
        t = run([self.acting(), ["event", ev, 2]])["view"]["cuaTarget"]
        self.assertEqual((t["confidence"], t["phase"]), (1, "aim"))
        ev["data"]["phase"] = "click"
        t = run([self.acting(), ["event", ev, 2]])["view"]["cuaTarget"]
        self.assertEqual(t["phase"], "click")

    def test_dropped_when_status_leaves_acting(self):
        diff = {"type": "state", "seq": 3,
                "diff": {"status": "done", "seq": 3}}
        r = run([self.acting(), ["event", self.EV, 2], ["event", diff, 3]])
        self.assertIsNone(r["view"]["cuaTarget"])

    def test_ignored_when_not_acting(self):
        r = run([["snap", snap(status="idle"), 1], ["event", self.EV, 2]])
        self.assertIsNone(r["view"]["cuaTarget"])

    def test_dropped_on_new_turn_and_offline(self):
        s2 = ["snap", snap(status="acting", seq=3, turn_id="t2"), 3]
        r = run([self.acting(), ["event", self.EV, 2], s2])
        self.assertIsNone(r["view"]["cuaTarget"])
        r = run([self.acting(), ["event", self.EV, 2], ["offline", 3]])
        self.assertIsNone(r["view"]["cuaTarget"])

    def test_event_does_not_bump_seq(self):
        r = run([self.acting(), ["event", self.EV, 2]])
        self.assertEqual(r["view"]["seq"], 2)

    def test_message_path(self):
        r = run([self.acting(), ["msg", json.dumps(self.EV), 2]])
        self.assertEqual(r["view"]["cuaTarget"]["label"], "night light")


CARD = {"prompt_id": "p7", "prompt": "run close: w1?", "timeout_s": 120}


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestConfirmCard(unittest.TestCase):
    """W25: additive `confirm` object and the UI-side prompt id guard."""

    def pending(self, **kw):
        return run([["snap", snap(status="awaiting_choice", seq=2,
                                  choices=["run close: w1? \u2014 yes", "no"],
                                  prompt_id="p7", confirm=CARD, **kw), 1]])["view"]

    def test_confirm_defaults_to_null(self):
        self.assertIsNone(js("S.initial()")["confirm"])
        v = run([["snap", snap(status="idle"), 1]])["view"]
        self.assertIsNone(v["confirm"])

    def test_confirm_maps_and_clamps(self):
        c = self.pending()["confirm"]
        self.assertEqual(c, {"promptId": "p7", "prompt": "run close: w1?",
                             "detail": "",
                             "timeoutS": 120, "kind": "confirm",
                             "options": ["run close: w1? — yes", "no"],
                             "allow": "run close: w1? — yes",
                             "deny": "no", "middle": []})

    def test_card_picks_survive_a_diff_that_empties_choices(self):
        # the race U1 repairs: a state diff between render and click may
        # empty `choices`; the card's snapshotted picks must not blank
        diff = {"type": "state", "seq": 3, "diff": {"choices": [], "seq": 3}}
        r = run([["snap", snap(status="awaiting_choice", seq=2,
                               choices=["a", "no"], prompt_id="p7",
                               confirm=CARD), 1], ["event", diff, 2]])
        c = r["view"]["confirm"]
        self.assertEqual((c["allow"], c["deny"]), ("a", "no"))
        # a fresh pick set for the same prompt still wins the snapshot
        diff = {"type": "state", "seq": 3,
                "diff": {"choices": ["go", "stop"], "seq": 3}}
        r = run([["snap", snap(status="awaiting_choice", seq=2,
                               choices=["a", "no"], prompt_id="p7",
                               confirm=CARD), 1], ["event", diff, 2]])
        c = r["view"]["confirm"]
        self.assertEqual((c["allow"], c["deny"]), ("go", "stop"))

    def test_malformed_confirm_is_dropped(self):
        for bad in ("yes", 3, [], {"prompt": "x"}, {"prompt_id": ""}):
            v = run([["snap", snap(status="awaiting_choice", seq=2,
                                   confirm=bad), 1]])["view"]
            self.assertIsNone(v["confirm"], repr(bad))

    def test_diff_clears_the_card(self):
        diff = {"type": "state", "seq": 3,
                "diff": {"status": "acting", "confirm": None,
                         "choices": [], "prompt_id": "", "seq": 3}}
        r = run([["snap", snap(status="awaiting_choice", seq=2,
                               choices=["a", "no"], prompt_id="p7",
                               confirm=CARD), 1], ["event", diff, 2]])
        self.assertIsNone(r["view"]["confirm"])

    def test_accept_choice_matches_prompt_id_and_option(self):
        v = self.pending()
        f = lambda pick, pid: js(
            "S.acceptChoice(%s, %s, %s)" % (json.dumps(v), json.dumps(pick),
                                            json.dumps(pid)))
        self.assertTrue(f("no", "p7"))
        self.assertTrue(f("run close: w1? \u2014 yes", "p7"))

    def test_accept_choice_ignores_mismatch_stale_and_unknown(self):
        v = self.pending()
        f = lambda pick, pid: js(
            "S.acceptChoice(%s, %s, %s)" % (json.dumps(v), json.dumps(pick),
                                            json.dumps(pid)))
        self.assertFalse(f("no", "p6"))          # another prompt's id
        self.assertFalse(f("no", ""))            # no id at all
        self.assertFalse(f("maybe", "p7"))       # not offered
        idle = run([["snap", snap(status="acting", seq=3), 2]])["view"]
        self.assertFalse(js("S.acceptChoice(%s, 'no', 'p7')"
                            % json.dumps(idle)))  # nothing pending now


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestAcceptSuggestion(unittest.TestCase):
    """acceptChoice for suggestion: picks — they carry no prompt id and
    the daemon resolves them before the broker, so they must pass the
    UI gate instead of dying on it (U1)."""

    SUGGEST = ["suggestion:automate", "suggestion:not now",
               "suggestion:never"]

    def f(self, view, pick, pid=""):
        return js("S.acceptChoice(%s, %s, %s)"
                  % (json.dumps(view), json.dumps(pick), json.dumps(pid)))

    def test_bare_pick_passes_only_while_the_card_is_live(self):
        sug = run([["snap", snap(status="suggestion", seq=2,
                                 choices=self.SUGGEST), 1]])["view"]
        self.assertTrue(self.f(sug, "suggestion:automate"))
        self.assertTrue(self.f(sug, "suggestion:never"))
        # a pick the card never offered still drops
        self.assertFalse(self.f(sug, "suggestion:later"))

    def test_bare_pick_drops_without_a_live_card(self):
        idle = run([["snap", snap(status="idle", seq=2), 1]])["view"]
        self.assertFalse(self.f(idle, "suggestion:automate"))
        waiting = run([["snap", snap(status="awaiting_choice", seq=2,
                                     choices=["a", "no"],
                                     prompt_id="p7"), 1]])["view"]
        self.assertFalse(self.f(waiting, "suggestion:automate"))

    def test_keyed_pick_passes_at_any_time(self):
        # suggestion:<act>:<key> addresses a suggestions.jsonl row — a
        # stale key ends in a safe SKIP server-side, so the UI may pass
        # it regardless of what is on screen (the debug shell's list)
        idle = run([["snap", snap(status="idle", seq=2), 1]])["view"]
        self.assertTrue(self.f(idle, "suggestion:automate:abc123"))
        self.assertTrue(self.f(idle, "suggestion:never:zz"))
        sug = run([["snap", snap(status="suggestion", seq=2,
                                 choices=self.SUGGEST), 1]])["view"]
        self.assertTrue(self.f(sug, "suggestion:not now:k1"))

    def test_malformed_picks_stay_refused(self):
        idle = run([["snap", snap(status="idle", seq=2), 1]])["view"]
        self.assertFalse(self.f(idle, ""))
        self.assertFalse(self.f(idle, "suggestion:"))
        self.assertFalse(self.f(idle, "suggestion:automate:"))  # empty key
        self.assertFalse(self.f(idle, "suggestion::k"))         # empty act
        self.assertFalse(self.f(None, "x"))
        self.assertFalse(self.f(idle, 3))


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestQuestionChoice(unittest.TestCase):
    """acceptChoice free-text gate (U8): a live question card with no
    offered picks resolves on ANY non-empty pick — the typed or spoken
    answer goes through verbatim. The gate is the prompt KIND, so a
    normal confirm card whose choices list emptied never turns into an
    unrestricted input."""

    def qview(self, **kw):
        kw.setdefault("status", "awaiting_choice")
        kw.setdefault("prompt_id", "p9")
        return run([["snap", snap(**kw), 1]])["view"]

    def f(self, view, pick, pid="p9"):
        return js("S.acceptChoice(%s, %s, %s)"
                  % (json.dumps(view), json.dumps(pick), json.dumps(pid)))

    def test_question_card_accepts_any_nonempty_pick(self):
        v = self.qview(choices=[],
                       confirm={"prompt_id": "p9", "prompt": "which file?",
                                "timeout_s": 60, "kind": "question"})
        self.assertTrue(self.f(v, "the second one"))
        self.assertFalse(self.f(v, "arbitrary", "p8"))   # another prompt
        self.assertFalse(self.f(v, ""))                  # empty refused

    def test_awaiting_question_entry_alone_opens_free_text(self):
        # the card may live only in the stream (no confirm block)
        q = {"id": "a1", "kind": "question", "label": "which file?",
             "status": "awaiting", "target": "", "reason": "",
             "undo_ref": None, "prompt_id": "p9",
             "at": "2026-10-10T01:00:00Z"}
        v = self.qview(choices=[], actions=[q])
        self.assertTrue(self.f(v, "free text"))

    def test_confirm_with_empty_choices_is_not_free_text(self):
        v = self.qview(choices=[],
                       confirm={"prompt_id": "p9", "prompt": "run?",
                                "timeout_s": 60})
        self.assertFalse(self.f(v, "arbitrary"))

    def test_question_with_options_takes_only_those(self):
        v = self.qview(choices=["work", "personal"],
                       confirm={"prompt_id": "p9", "prompt": "which?",
                                "timeout_s": 60, "kind": "question"})
        self.assertTrue(self.f(v, "work"))
        self.assertFalse(self.f(v, "unlisted"))


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestRunCard(unittest.TestCase):
    """lib/run.js (U8): the action stream -> the run card — intent, step
    cursor, in-flight step, outcome, mutation accounting, live question.
    A settled status or stale heartbeat resolves open entries cancelled
    so nothing ever ghosts as running."""

    def card(self, actions, status="acting", prompt_id="", stale=False,
             intent="", now=0):
        return jsnode.call("R.card(%s, %s, %s, %s, %s, %s)"
                           % (json.dumps(actions), json.dumps(status),
                              json.dumps(prompt_id), json.dumps(stale),
                              json.dumps(intent), now), R="run")

    def ent(self, i, **kw):
        e = {"id": f"a{i}", "kind": "tool", "label": f"tool{i}",
             "status": "done", "target": "", "reason": "", "undoRef": None,
             "at": "2026-10-10T01:00:00Z"}
        e.update(kw)
        return e

    def boundary(self, **kw):
        b = {"id": "a1", "kind": "route", "label": "act",
             "status": "in_flight", "target": "open discord",
             "reason": "", "undoRef": None, "at": "2026-10-10T01:00:00Z"}
        b.update(kw)
        return b

    def test_empty_stream_and_chatter_only_are_not_runs(self):
        self.assertFalse(self.card([])["present"])
        self.assertFalse(self.card(None)["present"])
        chatter = [self.ent(1, kind="label"),
                   self.ent(2, kind="suggestion")]
        self.assertFalse(self.card(chatter)["present"])

    def test_active_run(self):
        c = self.card([self.boundary(),
                       self.ent(2, status="done", undoRef="switch back"),
                       self.ent(3, status="in_flight", label="type",
                                target="hey"),
                       self.ent(4, status="queued", label="key")])
        self.assertTrue(c["present"] and c["active"])
        self.assertEqual(c["intent"], "open discord")
        self.assertEqual((c["steps"], c["stepAt"]), (3, 2))
        self.assertEqual(c["current"], "type hey")
        self.assertEqual(c["outcome"], "")
        self.assertEqual(c["key"], "a1")

    def test_terminal_run_outcome_mutations_duration(self):
        c = self.card([self.boundary(status="done"),
                       self.ent(2, status="done", undoRef="switch back",
                                delivery="background",
                                at="2026-10-10T01:00:01Z"),
                       self.ent(3, status="done",
                                at="2026-10-10T01:00:03Z")],
                      status="done")
        self.assertTrue(c["present"] and not c["active"])
        self.assertEqual(c["outcome"], "done")
        self.assertEqual(c["steps"], 2)
        self.assertEqual(c["mutations"], 1)
        self.assertEqual(c["undoRefs"], ["switch back"])
        self.assertEqual(c["durationS"], 3)
        # the boundary's verdict IS the run's: a failed step inside a
        # run the daemon still reported done does not fail the card
        recovered = self.card([self.boundary(status="done"),
                               self.ent(2, status="failed")], status="done")
        self.assertEqual(recovered["outcome"], "done")
        failed = self.card([self.boundary(status="failed"),
                            self.ent(2, status="failed")], status="error")
        self.assertEqual(failed["outcome"], "failed")

    def test_settled_and_stale_resolve_open_entries_cancelled(self):
        acts = [self.boundary(), self.ent(2, status="in_flight")]
        for status in ("idle", "done", "error", "offline"):
            c = self.card(acts, status=status)
            self.assertTrue(c["present"] and not c["active"], status)
            self.assertEqual(c["outcome"], "cancelled", status)
        c = self.card(acts, status="acting", stale=True)
        self.assertFalse(c["active"])
        self.assertEqual(c["outcome"], "cancelled")
        # a dead boundary alone resolves cancelled too
        c = self.card([self.boundary(), self.ent(2, status="done")],
                      status="idle")
        self.assertEqual(c["outcome"], "cancelled")

    def test_live_question(self):
        q = self.ent(2, kind="question", status="awaiting",
                     label="which account?", promptId="p9",
                     options=["work", "personal"])
        c = self.card([self.boundary(), q], status="awaiting_choice",
                      prompt_id="p9")
        self.assertEqual(c["question"]["text"], "which account?")
        self.assertEqual(c["question"]["options"], ["work", "personal"])
        # no offered picks -> free-text affordance; wrong prompt id ->
        # not the live card
        q.pop("options")
        c = self.card([self.boundary(), q], status="awaiting_choice",
                      prompt_id="p9")
        self.assertEqual(c["question"]["options"], [])
        c = self.card([self.boundary(), q], status="awaiting_choice",
                      prompt_id="p8")
        self.assertIsNone(c["question"])

    def test_newest_boundary_wins_and_intent_fallbacks(self):
        # an older run's entries don't pollute the newest run
        old = [{"id": "a0", "kind": "route", "label": "act",
                "status": "done", "target": "old task", "reason": "",
                "undoRef": None, "at": "2026-10-10T00:00:00Z"},
               self.ent(0, label="old", status="done")]
        c = self.card(old + [self.boundary(id="a9"),
                             self.ent(3, status="in_flight")])
        self.assertEqual(c["key"], "a9")
        self.assertEqual(c["steps"], 1)
        # act-kind boundary: label wins (minus run:), then target
        c = self.card([{"id": "a1", "kind": "act",
                        "label": "run: rename shots", "status": "in_flight",
                        "target": "", "reason": "", "undoRef": None,
                        "at": "2026-10-10T01:00:00Z"}])
        self.assertEqual(c["intent"], "rename shots")
        # no boundary: whole stream is the cluster, intent falls back
        c = self.card([self.ent(1, status="in_flight")], intent="do it")
        self.assertEqual(c["intent"], "do it")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestActionStream(unittest.TestCase):
    """state.actions (contract v2, U2): the unified lifecycle stream the
    step display and the demoted confirm card read. Entries normalize to
    camelCase view fields, cap at the last 50 like the daemon's list,
    and ride the same snapshot+diff path as every other field."""

    def entry(self, i, **kw):
        e = {"id": f"a{i}", "kind": "tool", "label": f"tool{i}",
             "status": "done", "target": "", "reason": "",
             "undo_ref": None, "at": "2026-10-10T01:00:00Z"}
        e.update(kw)
        return e

    def test_absent_is_empty_and_initial_is_empty(self):
        v = run([["snap", snap(), 1]])["view"]
        self.assertEqual(v["actions"], [])
        self.assertEqual(js("S.initial()")["actions"], [])

    def test_entries_normalize_with_defaults(self):
        a = self.entry(1, status="in_flight", target="640,360",
                       options=["yes", "no"], prompt_id="p1",
                       undo_ref="u9")
        v = run([["snap", snap(actions=[a]), 1]])["view"]
        e = v["actions"][0]
        self.assertEqual(e["id"], "a1")
        self.assertEqual(e["kind"], "tool")
        self.assertEqual(e["status"], "in_flight")
        self.assertEqual(e["target"], "640,360")
        self.assertEqual(e["options"], ["yes", "no"])
        self.assertEqual(e["promptId"], "p1")
        self.assertEqual(e["undoRef"], "u9")
        self.assertEqual(e["at"], "2026-10-10T01:00:00Z")

    def test_unknown_status_reads_done_and_junk_drops(self):
        v = run([["snap", snap(actions=[self.entry(1, status="weird"),
                                        "junk", None, 4,
                                        self.entry(2)]), 1]])["view"]
        self.assertEqual([e["id"] for e in v["actions"]], ["a1", "a2"])
        self.assertEqual(v["actions"][0]["status"], "done")
        v = run([["snap", snap(actions="nope"), 1]])["view"]
        self.assertEqual(v["actions"], [])

    def test_ordering_preserved_and_capped_at_fifty(self):
        entries = [self.entry(i) for i in range(1, 61)]
        v = run([["snap", snap(actions=entries), 1]])["view"]
        self.assertEqual(len(v["actions"]), 50)
        self.assertEqual(v["actions"][0]["id"], "a11")
        self.assertEqual(v["actions"][-1]["id"], "a60")

    def test_diff_replaces_the_stream_wholesale(self):
        base = [["snap", snap(seq=2, actions=[self.entry(1)]), 1]]
        diff = {"type": "state", "seq": 3,
                "diff": {"actions": [self.entry(1),
                                     self.entry(2, status="awaiting",
                                                prompt_id="p9")],
                         "seq": 3}}
        r = run(base + [["event", diff, 2]])
        self.assertEqual([e["id"] for e in r["view"]["actions"]],
                         ["a1", "a2"])
        # a later diff mutating the same entry lands the new list
        diff2 = {"type": "state", "seq": 4,
                 "diff": {"actions": [self.entry(1),
                                      self.entry(2, status="done")],
                          "seq": 4}}
        r = run(base + [["event", diff, 2], ["event", diff2, 3]])
        self.assertEqual(r["view"]["actions"][-1]["status"], "done")

    def test_awaiting_confirm_entry_drives_the_card(self):
        entry = self.entry(1, kind="confirm", status="awaiting",
                           label="run close: w1?",
                           options=["run close: w1? — yes", "no"],
                           prompt_id="p7")
        v = run([["snap", snap(status="awaiting_choice", seq=2,
                               prompt_id="p7", actions=[entry]), 1]])["view"]
        c = v["confirm"]
        self.assertEqual(c["promptId"], "p7")
        self.assertEqual(c["prompt"], "run close: w1?")
        self.assertEqual((c["allow"], c["deny"]),
                         ("run close: w1? — yes", "no"))

    def test_confirm_entry_inherits_timeout_from_the_legacy_object(self):
        entry = self.entry(1, kind="confirm", status="awaiting",
                           label="run?", options=["y", "n"],
                           prompt_id="p7")
        v = run([["snap", snap(status="awaiting_choice", seq=2,
                               prompt_id="p7", confirm=CARD,
                               actions=[entry]), 1]])["view"]
        self.assertEqual(v["confirm"]["timeoutS"], 120)

    def test_stale_awaiting_entry_does_not_hold_a_dead_card(self):
        # the prompt already resolved elsewhere (prompt_id cleared or
        # another prompt live) — an unresolved entry can't park a card
        entry = self.entry(1, kind="confirm", status="awaiting",
                           options=["y", "n"], prompt_id="p7")
        v = run([["snap", snap(status="acting", seq=2, prompt_id="",
                               actions=[entry]), 1]])["view"]
        self.assertIsNone(v["confirm"])
        v = run([["snap", snap(status="awaiting_choice", seq=2,
                               prompt_id="p8", actions=[entry]), 1]])["view"]
        self.assertIsNone(v["confirm"])

    def test_only_confirm_entries_demote_to_the_card(self):
        for kind in ("clarify", "suggestion", "question", "choice"):
            entry = self.entry(1, kind=kind, status="awaiting",
                               options=["a", "b"], prompt_id="p7")
            v = run([["snap", snap(status="awaiting_choice", seq=2,
                                   prompt_id="p7",
                                   actions=[entry]), 1]])["view"]
            self.assertIsNone(v["confirm"], kind)

    def test_resolved_confirm_entry_falls_back_to_legacy_field(self):
        entry = self.entry(1, kind="confirm", status="cancelled",
                           reason="denied", prompt_id="p7")
        v = run([["snap", snap(status="acting", seq=2,
                               actions=[entry]), 1]])["view"]
        self.assertIsNone(v["confirm"])
        self.assertEqual(v["actions"][0]["reason"], "denied")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestActionResult(unittest.TestCase):
    """actionResult: one-shot action subprocess output ->
    {ok, error, text}; every refusal path ends in a message, not
    silence (U1)."""

    def ar(self, code, out="", err=""):
        return js("S.actionResult(%d, %s, %s)"
                  % (code, json.dumps(out), json.dumps(err)))

    def test_json_envelope_success(self):
        r = self.ar(0, '{"ok":true,"command":"label set","data":'
                    '{"result":"labeled correct: t1"}}')
        self.assertTrue(r["ok"])
        self.assertEqual(r["text"], "labeled correct: t1")

    def test_json_envelope_typed_error(self):
        r = self.ar(1, '{"ok":false,"error":{"code":"E_STALE_PROMPT",'
                    '"message":"That prompt expired.","try":"wispd watch"}}')
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "stale_prompt")
        self.assertEqual(r["text"], "That prompt expired.")

    def test_raw_daemon_error_reply(self):
        # an unwrapped daemon reply line ({"ok":false,"error":"x"})
        r = self.ar(1, '{"ok":false,"error":"stale_prompt"}')
        self.assertEqual(r["error"], "stale_prompt")

    def test_e_code_on_stderr(self):
        r = self.ar(1, "", "E_BUSY: Busy with another request.\n"
                    "Try: wispd interrupt, then try again")
        self.assertEqual(r["error"], "busy")
        self.assertEqual(r["text"], "Busy with another request.")

    def test_wispd_stderr_line(self):
        r = self.ar(1, "", "wispd: busy")
        self.assertEqual(r["error"], "busy")
        r = self.ar(1, "", "wispd: daemon closed without a reply")
        self.assertEqual(r["error"], "")
        self.assertEqual(r["text"], "daemon closed without a reply")

    def test_nonzero_without_output_still_reports(self):
        r = self.ar(3, "", "spawn blew up\nmore detail")
        self.assertEqual(r["text"], "spawn blew up")
        self.assertEqual(self.ar(3)["text"], "exit 3")

    def test_success_reports_first_stdout_line(self):
        r = self.ar(0, "labeled correct: t1\n")
        self.assertTrue(r["ok"])
        self.assertEqual(r["text"], "labeled correct: t1")


if __name__ == "__main__":
    unittest.main()
