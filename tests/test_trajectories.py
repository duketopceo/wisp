"""Episodic act-loop memory: record, retrieve, inject, distill."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import trajectories as T


class TrajTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.file = self.dir / "trajectories.jsonl"
        self.labels = self.dir / "labels.jsonl"
        self.proposals = self.dir / "proposals"
        mock.patch.object(T, "FILE", self.file).start()
        import wisp.learn as learn
        mock.patch.object(learn, "LABELS_FILE", self.labels).start()
        mock.patch.object(learn, "PROPOSALS_DIR", self.proposals).start()
        self.addCleanup(mock.patch.stopall)

    def _rec(self, task="open vscode", app="code",
             outcome="ACTED (3 steps): done", ts="2026-01-01T00:00:00+00:00"):
        return {"ts": ts, "task": task, "app": app,
                "steps": [{"tool": "launch", "arg": "code",
                           "result": "LAUNCHED"}],
                "outcome": outcome, "ref": ""}

    def _write(self, recs, path=None):
        path = path or self.file
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))

    def test_record_appends(self):
        T.record("t", "app", [{"tool": "x", "arg": "a",
                             "result": "ok"}], "ACTED")
        self.assertEqual(len(self.file.read_text().splitlines()), 1)

    def test_similar_retrieves_related(self):
        self._write([self._rec(task="install the kubernetes extension "
                               "in vscode"),
                     self._rec(task="install the kubernetes extension "
                               "in vscode", outcome="ABORTED (max)")])
        hits = T.similar("install kubernetes extension in vs code",
                         app="code", records=T._read_all())
        self.assertTrue(hits)
        self.assertTrue(any(h["failed"] for h in hits))

    def test_context_marks_wrong_branch(self):
        self._write([self._rec(task="install kubernetes in vscode",
                               outcome="ABORTED (max 12 steps): "
                                       "click→FAIL")])
        ctx = T.context_for("install kubernetes in vscode", "code",
                            cfg={"traj": {"enabled": "true",
                                          "max_inject": "3"}})
        self.assertIn("FAILED run", ctx)
        self.assertIn("do not repeat", ctx)

    def test_context_empty_when_disabled(self):
        self._write([self._rec()])
        self.assertEqual(
            T.context_for("open vscode", "code",
                          cfg={"traj": {"enabled": "false"}}), "")

    def test_corrected_via_label(self):
        r = self._rec()
        self._write([r])
        self.labels.write_text(json.dumps(
            {"ts": "t", "ref": r["ts"], "label": "incorrect"}) + "\n")
        hits = T.similar("open vscode", "code", records=T._read_all())
        self.assertTrue(hits[0]["corrected"])

    def test_recipe_proposal_after_failure_then_success(self):
        self._write([
            self._rec(ts="t1", outcome="ABORTED (max 12 steps)"),
            self._rec(ts="t2", outcome="ACTED (4 steps): installed")])
        out = T.propose_recipes(out_dir=self.proposals)
        self.assertEqual(len(out), 1)
        body = pathlib.Path(out[0]).read_text()
        self.assertIn("recipe-", body)
        self.assertIn("Wrong branches", body)
        # nothing installed — proposal only
        self.assertFalse((self.proposals / "x").exists() and
                         "skills" in str(out[0]))

    def test_no_recipe_for_clean_success(self):
        self._write([self._rec()])
        self.assertEqual(T.propose_recipes(out_dir=self.proposals), [])

    def test_no_recipe_when_success_itself_labeled_bad(self):
        r = self._rec(ts="t2", outcome="ACTED")
        bad = self._rec(ts="t1", outcome="ABORTED")
        self._write([bad, r])
        self.labels.write_text(json.dumps(
            {"ts": "x", "ref": "t2", "label": "incorrect"}) + "\n")
        self.assertEqual(T.propose_recipes(out_dir=self.proposals), [])


if __name__ == "__main__":
    unittest.main()
