"""Episodic act-loop memory: record, retrieve, inject."""
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
        mock.patch.object(T, "FILE", self.file).start()
        import wisp.learn as learn
        mock.patch.object(learn, "LABELS_FILE", self.labels).start()
        self.addCleanup(mock.patch.stopall)

    def _rec(self, task="open vscode", app="code",
             outcome="ACTED (3 steps): done",
             ts="2026-01-01T00:00:00+00:00", steps=None):
        return {"ts": ts, "task": task, "app": app,
                "steps": steps or [{"tool": "launch", "arg": "code",
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

    def test_label_joins_via_decision_transcript(self):
        # production path: label.ref is the *decision* ts, not the
        # trajectory ts — bridge through decisions.jsonl transcript
        r = self._rec(steps=[{"tool": "launch", "arg": "a",
                              "result": "ok"},
                             {"tool": "type_text", "arg": "b",
                              "result": "ok"},
                             {"tool": "click", "arg": "c",
                              "result": "ok"}])
        self._write([r])
        decs = self.dir / "decisions.jsonl"
        decs.write_text(json.dumps(
            {"ts": "dec-ts", "transcript": r["task"]}) + "\n")
        self.labels.write_text(json.dumps(
            {"ts": "lab1", "ref": "dec-ts", "label": "incorrect"}) + "\n")
        import wisp.config as cfg
        with mock.patch.object(cfg, "DECISIONS", decs):
            hits = T.similar(r["task"], r["app"], records=T._read_all())
        self.assertTrue(hits[0]["corrected"])


if __name__ == "__main__":
    unittest.main()
