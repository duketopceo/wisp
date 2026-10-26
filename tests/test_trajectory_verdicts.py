"""U6 — verdicts into trajectories.

Trajectory step records carry the verify ladder's verdict fields
(`verdict`, `verify_source`, `corroborated`, `turn_dir`, `pack`);
`action_stats` buckets landed/missed/solo/refused/unverifiable/
suppressed/not_recorded instead of crediting dispatch; `learn` owns the
corroboration weighting the consumers share.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import action_stats, learn, trajectories as T  # noqa: E402


def _step(tool="click", result="CLICKED(10,20)", **kw):
    s = {"tool": tool, "arg": "10,20@logical", "result": result}
    s.update(kw)
    return s


class TestStepBuckets(unittest.TestCase):
    """learn.step_bucket / terminal_evidence — the shared evidence
    policy (the old step_weight wrapper folded into it)."""

    def test_verdict_buckets(self):
        self.assertEqual(learn.step_bucket(
            _step(verdict="landed", corroborated=True)), "landed")
        self.assertEqual(learn.step_bucket(
            _step(verdict="missed", corroborated=True)), "missed")
        for v in ("refused", "unverifiable", "suppressed",
                  "not_recorded"):
            self.assertEqual(learn.step_bucket(_step(verdict=v)), v)

    def test_single_source_splits_off(self):
        # R2a symmetric: a lone rung's landed AND missed both flag solo
        self.assertEqual(learn.step_bucket(
            _step(verdict="landed", corroborated=False)), "landed_solo")
        self.assertEqual(learn.step_bucket(
            _step(verdict="missed", corroborated=False)), "missed_solo")
        # verdict without a corroboration flag reads as unprovenanced —
        # conservatively single-source, never full-weight
        self.assertEqual(
            learn.step_bucket(_step(verdict="landed")), "landed_solo")
        # in-memory act steps carry the flag inside the verify dict
        self.assertEqual(learn.step_bucket(_step(
            verdict="landed",
            verify={"verdict": "landed", "corroborated": True,
                    "source": "pixel+control"})), "landed")

    def test_legacy_bucket_for_dispatch_only(self):
        self.assertEqual(learn.step_bucket(_step()), "legacy")
        self.assertEqual(learn.step_bucket({}), "legacy")
        self.assertEqual(
            learn.step_bucket(_step(verdict="bogus")), "legacy")

    def test_weights(self):
        # the bucket -> weight mapping lives in terminal_evidence:
        # corroborated outcomes weigh 1.0, a solo rung SOLO_WEIGHT,
        # no-signal buckets and legacy weigh nothing
        _, w = learn.terminal_evidence(
            [_step(verdict="landed", corroborated=True)])
        self.assertEqual(w, 1.0)
        b, w = learn.terminal_evidence(
            [_step(verdict="missed", corroborated=False)])
        self.assertEqual((b, w), ("missed_solo", learn.SOLO_WEIGHT))
        for v in ("refused", "unverifiable", "suppressed",
                  "not_recorded"):
            self.assertEqual(
                learn.terminal_evidence([_step(verdict=v)]),
                (None, 0.0))
        self.assertEqual(learn.terminal_evidence([_step()]),
                         (None, 0.0))

    def test_terminal_evidence_picks_last_outcome(self):
        steps = [_step(verdict="landed", corroborated=True),
                 _step(tool="type_text", verdict="not_recorded",
                       turn_dir=None),
                 _step(verdict="missed", corroborated=True)]
        # the last OUTCOME-bearing step wins — the not_recorded tail
        # after a landed click doesn't erase it, and the final missed
        # does
        b, w = learn.terminal_evidence(steps)
        self.assertEqual((b, w), ("missed", 1.0))
        b, w = learn.terminal_evidence(steps[:2])
        self.assertEqual((b, w), ("landed", 1.0))

    def test_terminal_evidence_none_without_outcome(self):
        b, w = learn.terminal_evidence(
            [_step(verdict="not_recorded"), _step()])
        self.assertEqual((b, w), (None, 0.0))
        self.assertEqual(learn.terminal_evidence([]), (None, 0.0))
        self.assertEqual(learn.terminal_evidence(None), (None, 0.0))


class TestTrajectoryFields(unittest.TestCase):
    """record() persists the U6 verdict fields; old rows still parse."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.file = self.dir / "trajectories.jsonl"
        mock.patch.object(T, "FILE", self.file).start()
        self.addCleanup(mock.patch.stopall)

    def _rows(self):
        return T._read_all(self.file)

    def test_verdict_fields_round_trip(self):
        turn = str(self.dir / "rec" / "t1" / "turn-00001")
        T.record("click the button", "filmcraft", [
            _step(verdict="landed",
                  verify={"verdict": "landed", "source": "pixel+control",
                          "corroborated": True, "evidence": turn},
                  turn_dir=turn),
            _step(tool="type_text", arg="hi", result="TYPED",
                  verdict="not_recorded", turn_dir=None),
            _step(tool="screenshot", result="SHOT /tmp/x.png"),
        ], "ACTED (3 steps)", surface="desktop")
        steps = self._rows()[0]["steps"]
        self.assertEqual(steps[0]["verdict"], "landed")
        self.assertEqual(steps[0]["verify_source"], "pixel+control")
        self.assertIs(steps[0]["corroborated"], True)
        # F15: only the evidence dir NAME persists — never the path
        self.assertEqual(steps[0]["turn_dir"], "turn-00001")
        # the non-cua tool keeps its explicit not_recorded + null dir
        self.assertEqual(steps[1]["verdict"], "not_recorded")
        self.assertIsNone(steps[1]["turn_dir"])
        # read-only steps carry none of the new keys
        self.assertNotIn("verdict", steps[2])
        self.assertNotIn("turn_dir", steps[2])

    def test_flat_fields_and_pack(self):
        T.record("t", "app", [
            _step(verdict="missed", verify_source="pixel",
                  corroborated=False, turn_dir="/rec/t2/turn-00003",
                  pack="/packs/t2"),
        ], "ACTED", pack="/packs/t2")
        r = self._rows()[0]
        s = r["steps"][0]
        self.assertEqual(s["verdict"], "missed")
        self.assertEqual(s["verify_source"], "pixel")
        self.assertIs(s["corroborated"], False)
        self.assertEqual(s["pack"], "t2")          # F15: basename only
        self.assertEqual(r["pack"], "t2")

    def test_pack_kwarg_stamps_steps_lacking_one(self):
        T.record("t", "app", [
            _step(verdict="landed", corroborated=True,
                  turn_dir="/rec/t3/turn-00001"),
            _step(verdict="landed", corroborated=True,
                  turn_dir="/rec/t3/turn-00002", pack="/packs/other"),
        ], "ACTED", pack="/packs/t3")
        steps = self._rows()[0]["steps"]
        self.assertEqual(steps[0]["pack"], "t3")
        # a step's own pack ref wins over the record-level stamp
        self.assertEqual(steps[1]["pack"], "other")

    def test_old_records_parse_unchanged(self):
        self.file.write_text(json.dumps({
            "ts": "2026-01-01T00:00:00+00:00", "task": "open vscode",
            "app": "code",
            "steps": [{"tool": "launch", "arg": "code",
                       "result": "LAUNCHED"}],
            "outcome": "ACTED", "ref": ""}) + "\n")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        s = rows[0]["steps"][0]
        self.assertNotIn("verdict", s)
        self.assertEqual(learn.step_bucket(s), "legacy")
        self.assertEqual(learn.terminal_evidence([s]), (None, 0.0))

    def test_old_style_record_call_still_works(self):
        # pre-U6 call shape: no verdict fields anywhere
        T.record("t", "app", [{"tool": "x", "arg": "a",
                               "result": "ok"}], "ACTED")
        s = self._rows()[0]["steps"][0]
        self.assertEqual(set(s), {"tool", "arg", "result"})


class TestActionStats(unittest.TestCase):
    """landed != missed != not_recorded; legacy is its own bucket."""

    def _traj(self, app, *steps):
        return {"app": app, "task": "t", "steps": list(steps),
                "outcome": "ACTED"}

    def test_verdict_buckets_per_tool(self):
        recs = [self._traj(
            "filmcraft",
            _step(verdict="landed", corroborated=True),
            _step(verdict="landed", corroborated=False),
            _step(verdict="missed", corroborated=True),
            _step(verdict="missed", corroborated=False),
            _step(verdict="refused"),
            _step(verdict="unverifiable"),
            _step(verdict="suppressed"),
            _step(tool="type_text", verdict="not_recorded"),
            _step(tool="launch"),  # legacy dispatch-only row
        )]
        b = action_stats.stats(records=recs)["filmcraft"]
        self.assertEqual(b["click"]["landed"], 1)
        self.assertEqual(b["click"]["landed_solo"], 1)
        self.assertEqual(b["click"]["missed"], 1)
        self.assertEqual(b["click"]["missed_solo"], 1)
        self.assertEqual(b["click"]["refused"], 1)
        self.assertEqual(b["click"]["unverifiable"], 1)
        self.assertEqual(b["click"]["suppressed"], 1)
        self.assertNotIn("not_recorded", b["click"])
        self.assertEqual(b["type_text"]["not_recorded"], 1)
        self.assertEqual(b["launch"]["legacy"], 1)
        self.assertEqual(b["launch"]["legacy_ok"], 1)

    def test_legacy_never_counts_as_landed(self):
        recs = [self._traj("godot", _step(result="CLICKED(10,20)"))
                for _ in range(3)]
        b = action_stats.stats(records=recs)["godot"]["click"]
        self.assertEqual(b.get("landed", 0), 0)
        self.assertEqual(b["legacy"], 3)

    def test_block_for_verdicted_vs_legacy(self):
        recs = [self._traj(
            "filmcraft",
            _step(verdict="landed", corroborated=True),
            _step(verdict="landed", corroborated=True),
            _step(verdict="landed", corroborated=False),
            _step(verdict="missed", corroborated=True),
            _step(tool="type_text", verdict="not_recorded"),
            _step(tool="type_text", verdict="not_recorded"),
        )]
        blk = action_stats.block_for("filmcraft", records=recs)
        self.assertIn("filmcraft", blk)
        self.assertIn("click 3/4", blk)     # solo counted in display
        self.assertIn("1 solo", blk)        # but flagged single-source
        self.assertIn("unverified: type_text×2", blk)

    def test_block_for_legacy_fallback(self):
        recs = [self._traj("godot", _step(result="ok"))
                for _ in range(4)] \
            + [self._traj("godot", _step(result="FAIL"))]
        blk = action_stats.block_for("godot", records=recs)
        self.assertIn("click 4/5", blk)

    def test_block_for_suspect_on_verified_misses(self):
        recs = [self._traj("app",
                           _step(verdict="missed", corroborated=True))
                for _ in range(3)]
        blk = action_stats.block_for("app", records=recs)
        self.assertIn("suspect: click 0/3", blk)


class TestLearnConsumers(unittest.TestCase):
    """trajectories.similar/context_for apply the verdict policy."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.file = self.dir / "trajectories.jsonl"
        self.labels = self.dir / "labels.jsonl"
        mock.patch.object(T, "FILE", self.file).start()
        mock.patch.object(learn, "LABELS_FILE", self.labels).start()
        self.addCleanup(mock.patch.stopall)

    def _rec(self, steps, outcome="ACTED (2 steps): done",
             task="click the modal ok", app="filmcraft",
             ts="2026-01-01T00:00:00+00:00"):
        return {"ts": ts, "task": task, "app": app, "steps": steps,
                "outcome": outcome, "ref": ""}

    def test_corroborated_terminal_miss_marks_failed(self):
        rec = self._rec([
            _step(verdict="missed", corroborated=True,
                  turn_dir="/rec/t/turn-00001")])
        hits = T.similar("click the modal ok", "filmcraft",
                         records=[rec])
        self.assertTrue(hits[0]["failed"])
        self.assertTrue(hits[0]["verified_miss"])
        self.assertFalse(hits[0]["outcome_failed"])  # ACTED — verdict
        # alone flipped it; dispatch success is not the outcome

    def test_single_source_miss_is_suspect_not_failed(self):
        rec = self._rec([
            _step(verdict="missed", corroborated=False)])
        hits = T.similar("click the modal ok", "filmcraft",
                         records=[rec])
        self.assertFalse(hits[0]["failed"])
        self.assertTrue(hits[0]["suspect_miss"])

    def test_not_recorded_tail_is_neither(self):
        # a run of uninstrumented mutations is not a success and not a
        # failure — the outcome string still governs
        rec = self._rec([
            _step(verdict="not_recorded", turn_dir=None)],
            outcome="ACTED (1 step)")
        hits = T.similar("click the modal ok", "filmcraft",
                         records=[rec])
        self.assertFalse(hits[0]["failed"])
        self.assertFalse(hits[0]["verified_miss"])
        self.assertFalse(hits[0]["suspect_miss"])

    def test_context_for_warns_on_verified_miss(self):
        rec = self._rec([
            _step(verdict="missed", corroborated=True)])
        ctx = T.context_for("click the modal ok", "filmcraft",
                            cfg={"traj": {"enabled": "true"}},
                            records=[rec], labels={})
        self.assertIn("FAILED run", ctx)
        self.assertIn("verified missed", ctx)

    def test_context_caution_on_solo_miss(self):
        rec = self._rec([_step(verdict="missed", corroborated=False)])
        ctx = T.context_for("click the modal ok", "filmcraft",
                            cfg={"traj": {"enabled": "true"}},
                            records=[rec], labels={})
        self.assertIn("caution", ctx)
        self.assertNotIn("FAILED run", ctx)


if __name__ == "__main__":
    unittest.main()
