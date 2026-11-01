#!/usr/bin/env python3
"""Dev tuning mode U4: drift flags, run reports, the review sample and
the dev_runs read command. Nothing here touches the desktop, a key or
the network."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import agents, config, devreport, ipc, learn, skills  # noqa: E402
from wisp import state as state_mod  # noqa: E402


def _load_wispd():
    path = str(ROOT / "wispd")
    loader = importlib.machinery.SourceFileLoader("wispd_u4_test", path)
    spec = importlib.util.spec_from_loader("wispd_u4_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


WISPD = _load_wispd()


def step(tool, arg="", result="ok", verify_failed=False):
    s = {"tool": tool, "arg": arg, "result": result, "ms": 5}
    if verify_failed:
        s["verify_failed"] = True
    return s


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        for obj, name, val in (
                (config, "DATA_DIR", self.dir),
                (config, "DECISIONS", self.dir / "decisions.jsonl"),
                (learn, "LABELS_FILE", self.dir / "labels.jsonl")):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.n = 0

    def write_run(self, run_id, rows):
        d = self.dir / "dev_runs"
        d.mkdir(exist_ok=True)
        with (d / f"{run_id}.jsonl").open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def row(self, run_id="r1", goal="open firefox", judge="success",
            outcome="success", steps=None, drift=None, task_usd=0.01,
            judge_usd=0.002, timing=None, decide=True, **kw):
        i = self.n
        self.n += 1
        turn = f"t{run_id}{i}"
        if decide:
            with (self.dir / "decisions.jsonl").open("a") as f:
                f.write(json.dumps({"ts": f"2026-10-30T00:00:{i:02d}+00:00",
                                    "turn": turn, "transcript": goal,
                                    "result": "ACTED (1 steps): ok"}) + "\n")
        j = ({"outcome": judge, "reason": f"reason {i}",
              "model": "google/gemini-2.5-flash", "cost_usd": judge_usd}
             if judge else None)
        r = {"run_id": run_id, "index": i, "goal": goal, "turn": turn,
             "route": "act", "result": "ACTED (1 steps): ok",
             "steps": steps if steps is not None else [step("media")],
             "outcome": outcome,
             "timing_ms": timing or {"route": 100, "act": 400, "wall": 700},
             "started": "2026-10-30T00:00:00+00:00",
             "ended": "2026-10-30T00:00:01+00:00",
             "judge": j, "drift": drift,
             "cost": {"task_usd": task_usd, "judge_usd": judge_usd}}
        r.update(kw)
        return r

    def label(self, row, label):
        out = learn.label_last(label, "", turn=row["turn"])
        self.assertTrue(out.startswith("labeled"), out)


class TestDrift(Base):
    SPOTIFY = {"spotify", "firefox"}

    def test_flagged_with_an_app_skill_and_a_failed_verify(self):
        steps = [step("click", "play", "CLICKED x - verify FAILED: aimed",
                      verify_failed=True),
                 step("click", "play button", "CLICKED play"),
                 step("media", "play", "playing")]
        d = devreport.drift("play something on spotify", steps, "success",
                            self.SPOTIFY)
        self.assertTrue(d["suspected"])
        self.assertEqual(d["apps"], ["spotify"])
        self.assertEqual(d["reason"], "verify_failed")
        self.assertEqual(d["step"], 0)
        self.assertIn("click", d["next"])
        self.assertTrue(d["recovered"])

    def test_not_flagged_without_an_app_skill(self):
        steps = [step("click", "play", "x", verify_failed=True)]
        d = devreport.drift("play something on napster", steps, "success",
                            self.SPOTIFY)
        self.assertFalse(d["suspected"])
        d = devreport.drift("play something", steps, "success", set())
        self.assertFalse(d["suspected"])

    def test_not_flagged_when_nothing_failed(self):
        d = devreport.drift("open spotify", [step("launch", "spotify")],
                            "success", self.SPOTIFY)
        self.assertFalse(d["suspected"])

    def test_missed_verdict_json_counts_as_a_failed_verify(self):
        steps = [step("click", "a",
                      'CLICKED a - verify {"verdict":"missed"}')]
        d = devreport.drift("open spotify", steps, "incomplete",
                            self.SPOTIFY)
        self.assertTrue(d["suspected"])
        self.assertFalse(d["recovered"])
        self.assertIsNone(d["next"])

    def test_wrong_tries_with_a_reaimed_click_is_flagged(self):
        steps = [step("click", "a"), step("click", "b")]
        d = devreport.drift("open spotify", steps, "wrong_tries",
                            self.SPOTIFY)
        self.assertTrue(d["suspected"])
        self.assertEqual(d["reason"], "wrong_tries")

    def test_wrong_tries_without_a_click_is_not_drift(self):
        d = devreport.drift("open spotify", [step("launch", "spotify")],
                            "wrong_tries", self.SPOTIFY)
        self.assertFalse(d["suspected"])


class TestAppSkills(Base):
    def test_names_come_from_saved_app_skills_and_their_classes(self):
        sd = self.dir / "skills"
        (sd / "apps" / "notion").mkdir(parents=True)
        (sd / "apps" / "notion" / "SKILL.md").write_text(
            "---\nname: notion\napp_classes: Notion, notion-app\n---\nbody\n")
        (sd / "omarchy").mkdir()
        (sd / "omarchy" / "SKILL.md").write_text(
            "---\nname: omarchy\n---\nbody\n")
        empty = self.dir / "seed"
        empty.mkdir()
        with mock.patch.object(skills, "SKILLS_DIR", sd), \
                mock.patch.object(skills, "_seed_dir", return_value=empty):
            names = devreport.app_skills()
        self.assertIn("notion", names)
        self.assertIn("notion-app", names)
        self.assertNotIn("omarchy", names)

    def test_bundled_app_skills_count(self):
        empty = self.dir / "skills"
        empty.mkdir()
        with mock.patch.object(skills, "SKILLS_DIR", empty):
            self.assertIn("spotify", devreport.app_skills())


class TestReport(Base):
    def make_run(self):
        rows = [
            self.row(judge="success"),
            self.row(judge="success",
                     drift={"suspected": True, "apps": ["spotify"],
                            "reason": "verify_failed", "step": 0,
                            "next": "click: play", "recovered": True}),
            self.row(judge="incomplete", outcome="incomplete",
                     timing={"route": 50, "act": 150, "wall": 300},
                     task_usd=0.02),
            self.row(judge="unjudged", judge_usd=0.0),
        ]
        rows[3]["judge"] = {"outcome": "unjudged", "reason": "cap",
                            "model": None, "cost_usd": 0.0}
        self.write_run("r1", rows)
        self.label(rows[0], "correct")
        self.label(rows[2], "incorrect")
        return rows

    def test_numbers_match_the_records(self):
        self.make_run()
        rep = devreport.build("r1")
        run = rep["runs"][0]
        self.assertEqual(run["run_id"], "r1")
        self.assertEqual(run["tasks"], 4)
        self.assertEqual(run["mix"]["judged"],
                         {"success": 2, "stopped": 0, "incomplete": 1,
                          "wrong_tries": 0, "unjudged": 1})
        self.assertEqual(run["mix"]["confirmed"],
                         {"correct": 1, "incorrect": 1, "unreviewed": 2})
        self.assertAlmostEqual(run["accuracy"]["judged"], 2 / 3)
        self.assertAlmostEqual(run["accuracy"]["confirmed"], 0.5)
        self.assertEqual(run["drift_count"], 1)
        self.assertAlmostEqual(run["cost"]["task_usd"], 0.01 * 3 + 0.02)
        self.assertAlmostEqual(run["cost"]["judge_usd"], 0.006)
        self.assertAlmostEqual(run["cost"]["total_usd"], 0.056)
        self.assertEqual(run["stage_ms"], {"route": 350, "act": 1350,
                                           "wall": 2400})
        self.assertTrue(run["judge_capped"])
        self.assertEqual(run["unjudged"], 1)

    def test_per_task_rows_join_the_owner_label(self):
        rows = self.make_run()
        run = devreport.build("r1")["runs"][0]
        r = run["rows"]
        self.assertEqual([x["judged"] for x in r],
                         ["success", "success", "incomplete", "unjudged"])
        self.assertEqual([x["confirmed"] for x in r],
                         ["correct", None, "incorrect", None])
        self.assertEqual(r[0]["goal"], rows[0]["goal"])
        self.assertEqual(r[1]["drift"]["reason"], "verify_failed")
        self.assertEqual(r[0]["turn"], rows[0]["turn"])

    def test_judge_alone_never_counts_as_confirmed(self):
        self.write_run("r1", [self.row(judge="success")])
        run = devreport.build("r1")["runs"][0]
        self.assertEqual(run["mix"]["confirmed"]["correct"], 0)
        self.assertIsNone(run["accuracy"]["confirmed"])
        self.assertFalse(learn.LABELS_FILE.exists())

    def test_list_without_id_is_newest_first_and_unknown_id_is_empty(self):
        self.write_run("20260101-000000-aaaa", [self.row("a")])
        self.write_run("20260102-000000-bbbb", [self.row("b")])
        ids = [r["run_id"] for r in devreport.build()["runs"]]
        self.assertEqual(ids, ["20260102-000000-bbbb",
                               "20260101-000000-aaaa"])
        self.assertEqual(devreport.build("nope")["runs"], [])

    def test_bad_run_id_is_not_a_path(self):
        self.assertEqual(devreport.build("../../etc/passwd")["runs"], [])

    def test_ab_pairs_per_task(self):
        a = [self.row("ab", goal="open firefox", judge="success", arm="a",
                      vs="brain.default=x/y"),
             self.row("ab", goal="pause youtube", judge="incomplete",
                      outcome="incomplete", arm="a", vs="brain.default=x/y")]
        b = [self.row("ab", goal="open firefox", judge="incomplete",
                      outcome="incomplete", arm="b", vs="brain.default=x/y"),
             self.row("ab", goal="pause youtube", judge="success", arm="b",
                      vs="brain.default=x/y")]
        for i, r in enumerate(a):
            r["index"] = i
        for i, r in enumerate(b):
            r["index"] = i
        self.write_run("ab", a + b)
        run = devreport.build("ab")["runs"][0]
        self.assertEqual(run["vs"], "brain.default=x/y")
        self.assertEqual(sorted(run["arms"]), ["a", "b"])
        self.assertEqual(run["arms"]["a"]["tasks"], 2)
        self.assertEqual(len(run["pairs"]), 2)
        p0, p1 = run["pairs"]
        self.assertEqual((p0["goal"], p0["a"], p0["b"], p0["better"]),
                         ("open firefox", "success", "incomplete", "a"))
        self.assertEqual((p1["a"], p1["b"], p1["better"]),
                         ("incomplete", "success", "b"))


class TestRedaction(Base):
    def test_goals_reasons_and_step_text_are_blanked(self):
        self.write_run("r1", [self.row(goal="open my stripe tab",
                                       steps=[step("click", "secret")])])
        out = devreport.redact(devreport.build("r1"))
        r = out["runs"][0]["rows"][0]
        self.assertEqual(r["goal"], "")
        self.assertEqual(r["reason"], "")
        self.assertNotIn("secret", json.dumps(out))
        self.assertNotIn("stripe", json.dumps(out))
        # numbers stay
        self.assertEqual(out["runs"][0]["tasks"], 1)
        self.assertEqual(r["judged"], "success")

    def test_ab_pairs_are_blanked_too(self):
        a = self.row("ab", goal="private thing", arm="a", vs="k=v")
        b = self.row("ab", goal="private thing", arm="b", vs="k=v")
        b["index"] = a["index"]
        self.write_run("ab", [a, b])
        out = devreport.redact(devreport.build("ab"))
        self.assertNotIn("private thing", json.dumps(out))
        self.assertEqual(out["runs"][0]["pairs"][0]["goal"], "")


class TestReview(Base):
    def seed(self):
        rows = ([self.row(judge="success") for _ in range(6)]
                + [self.row(judge="incomplete", outcome="incomplete")
                   for _ in range(3)]
                + [self.row(judge="unjudged")])
        rows[-1]["judge"]["reason"] = "cap"
        self.write_run("r1", rows)
        return rows

    def test_sample_is_at_most_five_judged_and_mixes_outcomes(self):
        self.seed()
        run = devreport.build("r1")["runs"][0]
        pick = devreport.pick_review(run["rows"])
        self.assertEqual(len(pick), 5)
        kinds = {p["judged"] for p in pick}
        self.assertIn("success", kinds)
        self.assertIn("incomplete", kinds)
        self.assertNotIn("unjudged", kinds)
        self.assertEqual(len(devreport.pick_review(run["rows"], 2)), 2)

    def test_reviewed_tasks_are_not_offered_again(self):
        rows = self.seed()
        self.label(rows[0], "correct")
        run = devreport.build("r1")["runs"][0]
        turns = [p["turn"] for p in devreport.pick_review(run["rows"], 9)]
        self.assertNotIn(rows[0]["turn"], turns)

    def test_confirm_a_success_writes_a_turn_scoped_correct(self):
        rows = self.seed()
        # the owner label must land on THAT turn even though it is not
        # the latest decision
        out = devreport.review_apply("r1", rows[1]["turn"], "confirm")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["label"], "correct")
        lab = [json.loads(x) for x in
               learn.LABELS_FILE.read_text().splitlines()]
        self.assertEqual(len(lab), 1)
        self.assertEqual(lab[0]["label"], "correct")
        self.assertEqual(lab[0]["ref"], "2026-10-30T00:00:01+00:00")

    def test_flip_a_success_writes_incorrect(self):
        rows = self.seed()
        out = devreport.review_apply("r1", rows[2]["turn"], "flip")
        self.assertEqual(out["label"], "incorrect")
        lab = json.loads(learn.LABELS_FILE.read_text().splitlines()[0])
        self.assertEqual((lab["label"], lab["ref"]),
                         ("incorrect", "2026-10-30T00:00:02+00:00"))

    def test_confirm_and_flip_a_failure(self):
        rows = self.seed()
        self.assertEqual(devreport.review_apply(
            "r1", rows[6]["turn"], "confirm")["label"], "incorrect")
        self.assertEqual(devreport.review_apply(
            "r1", rows[7]["turn"], "flip")["label"], "correct")

    def test_the_label_goes_through_the_injected_label_path(self):
        rows = self.seed()
        seen = []

        def label_fn(label, note, turn):
            seen.append((label, turn))
            return "labeled"
        devreport.review_apply("r1", rows[0]["turn"], "confirm",
                               label_fn=label_fn)
        self.assertEqual(seen, [("correct", rows[0]["turn"])])

    def test_set_writes_the_owners_choice_for_a_dev_turn_only(self):
        rows = self.seed()
        out = devreport.set_label("r1", rows[0]["turn"], "incorrect")
        self.assertTrue(out["ok"])
        self.assertEqual(out["label"], "incorrect")
        bad = devreport.set_label("r1", "not-a-dev-turn", "correct")
        self.assertFalse(bad["ok"])
        bad = devreport.set_label("r1", rows[0]["turn"], "maybe")
        self.assertFalse(bad["ok"])

    def test_unjudged_tasks_cannot_be_reviewed(self):
        rows = self.seed()
        out = devreport.review_apply("r1", rows[-1]["turn"], "confirm")
        self.assertFalse(out["ok"])

    def test_nothing_judge_made_lands_in_labels_jsonl(self):
        self.seed()
        devreport.build("r1")
        devreport.pick_review(devreport.build("r1")["runs"][0]["rows"])
        self.assertFalse(learn.LABELS_FILE.exists())
        # the report reads labels but a judge outcome is never one
        raw = (self.dir / "dev_runs" / "r1.jsonl").read_text()
        self.assertIn("judge", raw)


class TestIpc(Base):
    def handler(self):
        st = state_mod.StateBus(state_file=self.dir / "s.json",
                                autostart=False)
        self.addCleanup(st.close)
        ctl = {"stop": threading.Event(), "busy": threading.Event(),
               "interrupt": threading.Event(),
               "choice_event": threading.Event(), "choice_pick": "",
               "broker": None, "token": None, "rec": None,
               "rec_lock": threading.Lock()}
        return WISPD._handler(st, config._default_cfg_dict(), ctl,
                              tasks_file=self.dir / "tasks.jsonl")

    def test_dev_runs_is_a_read_command(self):
        self.assertIn("dev_runs", ipc.READ_CMDS)
        self.assertNotIn("dev_runs", ipc.MUTATING_CMDS)
        self.assertEqual(ipc.classify_cmd("dev_runs"), "read")

    def test_owner_gets_goals_and_a_marked_peer_gets_them_blanked(self):
        self.write_run("r1", [self.row(goal="open my stripe tab")])
        h = self.handler()
        me = {"pid": os.getpid(), "uid": os.getuid()}
        r = h({"cmd": "dev_runs", "run_id": "r1"}, me)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["runs"][0]["rows"][0]["goal"],
                         "open my stripe tab")
        with mock.patch.object(agents, "classify_peer",
                               return_value={"marked": True}):
            r = h({"cmd": "dev_runs", "run_id": "r1"}, me)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["runs"][0]["rows"][0]["goal"], "")
        self.assertNotIn("stripe", json.dumps(r))

    def test_works_with_the_daemons_default_tasks_file(self):
        # the live daemon builds its handler with no tasks_file (#249)
        st = state_mod.StateBus(state_file=self.dir / "s2.json",
                                autostart=False)
        self.addCleanup(st.close)
        ctl = {"stop": threading.Event(), "busy": threading.Event(),
               "interrupt": threading.Event(), "rec": None,
               "rec_lock": threading.Lock(), "token": None}
        h = WISPD._handler(st, config._default_cfg_dict(), ctl)
        with mock.patch.object(config, "TASKS_FILE",
                               self.dir / "tasks.jsonl"):
            r = h({"cmd": "dev_runs"}, {"pid": os.getpid(),
                                        "uid": os.getuid()})
        self.assertTrue(r["ok"], r)


class TestImportLabels(Base):
    """`wispd dev import-labels`: only the owner's own labels on gauntlet
    turns reach the owner's data, once (R20, KTD11)."""

    def setUp(self):
        super().setUp()
        self.src = self.dir / "gauntlet-data"
        self.src.mkdir()

    def put(self, name, rows):
        with (self.src / name).open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def dec(self, ts, turn):
        return {"ts": ts, "turn": turn, "transcript": "open firefox",
                "result": "ACTED (1 steps): ok"}

    def lab(self, ref, label, note="dev review"):
        return {"ts": "2026-11-01T00:00:00+00:00", "ref": ref,
                "label": label, "note": note}

    def seed(self):
        self.put("decisions.jsonl", [self.dec("t1", "a"), self.dec("t2", "b"),
                                     self.dec("t3", "c"), self.dec("t4", "d")])
        self.put("labels.jsonl", [
            self.lab("t1", "correct"), self.lab("t2", "incorrect"),
            # t3 is judge-only: no label row; t4 has only the automatic mark
            self.lab("t4", "corrected-by-retry", "ACTED (3 steps)")])

    def dest(self, name):
        return learn._read_jsonl(self.dir / name)

    def test_copies_only_owner_labelled_turns_and_their_labels(self):
        self.seed()
        out = devreport.import_labels(self.src)
        self.assertEqual(out, {"copied": 2, "present": 0, "unlabelled": 2})
        self.assertEqual([d["ts"] for d in self.dest("decisions.jsonl")],
                         ["t1", "t2"])
        self.assertEqual([(x["ref"], x["label"])
                          for x in self.dest("labels.jsonl")],
                         [("t1", "correct"), ("t2", "incorrect")])

    def test_second_run_is_a_no_op(self):
        self.seed()
        devreport.import_labels(self.src)
        again = devreport.import_labels(self.src)
        self.assertEqual(again["copied"], 0)
        self.assertEqual(again["present"], 2)
        self.assertEqual(len(self.dest("decisions.jsonl")), 2)
        self.assertEqual(len(self.dest("labels.jsonl")), 2)

    def test_a_later_owner_label_wins_and_counts_in_the_gate(self):
        self.seed()
        self.put("labels.jsonl", [self.lab("t1", "incorrect")])
        devreport.import_labels(self.src)
        rep = learn.eval_report(decisions_file=self.dir / "decisions.jsonl",
                                labels_file=self.dir / "labels.jsonl")
        self.assertEqual((rep["total"]["labelled"], rep["total"]["incorrect"]), (2, 2))

    def test_refuses_your_own_data_directory(self):
        with self.assertRaises(ValueError):
            devreport.import_labels(self.dir)

    def test_missing_source_copies_nothing(self):
        out = devreport.import_labels(self.dir / "nope")
        self.assertEqual(out["copied"], 0)


class TestCli(unittest.TestCase):
    RUN = {"run_id": "r1", "tasks": 2, "rows": [
        {"index": 0, "turn": "t0", "goal": "open firefox",
         "judged": "success", "reason": "open", "confirmed": None},
        {"index": 1, "turn": "t1", "goal": "pause youtube",
         "judged": "incomplete", "reason": "still playing",
         "confirmed": None}]}

    def handler(self, cmd):
        if cmd.get("cmd") == "dev_runs":
            return {"ok": True, "runs": [self.RUN]}
        if cmd.get("cmd") == "dev_run":
            return {"ok": True, "run_id": "r9", "tasks": 4}
        return {"ok": True, "result": "labeled correct: x"}

    def run_cli(self, *argv):
        from cli_env import CliEnv
        with CliEnv() as env:
            env.start_daemon(self.handler)
            code, out, err = env.run(list(argv))
            return code, out, err, list(env.ipc)

    def test_dev_runs_json_asks_for_the_report(self):
        code, out, err, ipc_log = self.run_cli("dev", "runs", "--json",
                                               "r1")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["data"]["runs"][0]["run_id"], "r1")
        self.assertEqual(ipc_log[-1], {"cmd": "dev_runs", "run_id": "r1"})

    def test_review_json_lists_judged_tasks_without_labelling(self):
        code, out, err, ipc_log = self.run_cli("dev", "review", "--json")
        self.assertEqual(code, 0, err)
        tasks = json.loads(out)["data"]["tasks"]
        self.assertEqual({t["turn"] for t in tasks}, {"t0", "t1"})
        self.assertEqual([c["cmd"] for c in ipc_log], ["dev_runs"])

    def test_review_set_writes_the_owners_label_for_that_turn(self):
        code, out, err, ipc_log = self.run_cli(
            "dev", "review", "--set", "t1", "correct")
        self.assertEqual(code, 0, err)
        lab = ipc_log[-1]
        self.assertEqual((lab["cmd"], lab["turn"], lab["label"]),
                         ("label", "t1", "correct"))

    def test_review_set_refuses_unknown_turns_and_bad_labels(self):
        for argv in (("t9", "correct"), ("t1", "maybe")):
            code, out, err, ipc_log = self.run_cli(
                "dev", "review", "--set", *argv)
            self.assertNotEqual(code, 0)
            self.assertNotIn("label", [c["cmd"] for c in ipc_log])

    def test_run_profiles_are_sent_with_the_sandbox_windows(self):
        code, out, err, ipc_log = self.run_cli(
            "dev", "run", "x.txt", "--profile", "hybrid", "--profile",
            "openrouter", "--window", "0xaaa1", "--cap", "4")
        self.assertEqual(code, 0, err)
        msg = ipc_log[-1]
        self.assertEqual(msg["profiles"], ["hybrid", "openrouter"])
        self.assertEqual(msg["windows"], ["0xaaa1"])
        self.assertEqual(msg["cap_usd"], 4.0)
        code, out, err, ipc_log = self.run_cli(
            "dev", "run", "x.txt", "--profile", "nope")
        self.assertNotEqual(code, 0)

    def test_import_labels_reports_what_it_copied(self):
        code, out, err, _ = self.run_cli(
            "dev", "import-labels", "--json", "/nonexistent-gauntlet-dir")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["data"]["copied"], 0)

    def test_run_vs_is_sent_to_the_daemon(self):
        code, out, err, ipc_log = self.run_cli(
            "dev", "run", "x.txt", "--vs", "brain.default=a:b")
        self.assertEqual(code, 0, err)
        self.assertEqual(ipc_log[-1]["vs"], "brain.default=a:b")
        code, out, err, ipc_log = self.run_cli("dev", "run", "x.txt")
        self.assertNotIn("vs", ipc_log[-1])


if __name__ == "__main__":
    unittest.main()
