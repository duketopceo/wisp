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
            "contract_version": 1, "started_at": "2026-10-04T10:00:00Z",
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
        self.assertEqual((v["seq"], v["turnId"], v["contractVersion"]),
                         (7, "t9", 1))
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
        v = run([["snap", snap(contract_version=2, status="acting"), 1]])["view"]
        self.assertTrue(v["contractNewer"])
        self.assertEqual(v["status"], "acting")
        v = run([["snap", snap(contract_version=1), 1]])["view"]
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
            "label": "night light", "confidence": 0.9, "phase": "aim"})

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
                             "timeoutS": 120})

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


if __name__ == "__main__":
    unittest.main()
