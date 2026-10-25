"""Decision-model replay in evalroute (mocked HTTP)."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import evalroute  # noqa: E402


def _resp(route, conf=0.9, clarify="no", cost=0.001):
    return {
        "answers": {
            "route": {"choice": route, "confidence": conf},
            "needs_clarify": {"choice": clarify},
        },
        "usage": {"cost": cost},
    }


class EvalDecisionsReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.decisions = base / "decisions.jsonl"
        self.labels = base / "labels.jsonl"
        p1 = mock.patch.object(evalroute, "DECISIONS", self.decisions)
        p2 = mock.patch.object(evalroute, "LABELS", self.labels)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def _seed(self, decisions, labels=None):
        self.decisions.write_text(
            "".join(json.dumps(d) + "\n" for d in decisions))
        self.labels.write_text(
            "".join(json.dumps(l) + "\n" for l in (labels or [])))

    def test_report_agreement_and_no_transcript_without_out(self):
        self._seed([
            {"ts": "t1", "transcript": "open firefox",
             "answers": {"route": {"choice": "launch"}}},
            {"ts": "t2", "transcript": "what time is it",
             "answers": {"route": {"choice": "answer"}}},
        ])
        calls = []

        def fake_call(model, transcript, questions, key):
            calls.append((model, transcript))
            route = "launch" if "firefox" in transcript else "answer"
            return _resp(route)

        with mock.patch.object(evalroute, "_eval_key", return_value="k"), \
             mock.patch.object(evalroute, "_call_decisions",
                               side_effect=fake_call):
            text = evalroute.run_decisions({}, limit=0)
        self.assertNotIn("open firefox", text)
        self.assertIn("decisions replay", text)
        self.assertEqual(text.count("agree 2/2"), 3)
        self.assertEqual(len(calls), 6)

    def test_out_writes_transcripts(self):
        self._seed([
            {"ts": "t1", "transcript": "secret phrase",
             "answers": {"route": {"choice": "answer"}}},
        ])
        out = pathlib.Path(self.tmp.name) / "out.json"

        with mock.patch.object(evalroute, "_eval_key", return_value="k"), \
             mock.patch.object(evalroute,
                               "_call_decisions",
                               return_value=_resp("answer")):
            evalroute.run_decisions({}, models=["m"], out_path=str(out))
        payload = json.loads(out.read_text())
        self.assertEqual(payload["detail"][0]["transcript"], "secret phrase")

    def test_api_error_does_not_abort(self):
        self._seed([
            {"ts": "t1", "transcript": "hi",
             "answers": {"route": {"choice": "answer"}}},
        ])

        def boom(*a, **k):
            raise OSError("timeout")

        with mock.patch.object(evalroute, "_eval_key", return_value="k"), \
             mock.patch.object(evalroute, "_call_decisions", side_effect=boom):
            text = evalroute.run_decisions({}, models=["m"])
        self.assertIn("agree 0/1", text)
        self.assertIn("decisions replay", text)

    def test_label_correct_accuracy(self):
        self._seed(
            [{"ts": "t1", "transcript": "hi",
              "answers": {"route": {"choice": "answer"}}}],
            [{"ref": "t1", "label": "correct"}],
        )
        with mock.patch.object(evalroute, "_eval_key", return_value="k"), \
             mock.patch.object(evalroute, "_call_decisions",
                               return_value=_resp("launch")):
            text = evalroute.run_decisions({}, models=["m"])
        self.assertIn("accuracy vs logged route", text)
        self.assertIn("0/1", text)


if __name__ == "__main__":
    unittest.main()
