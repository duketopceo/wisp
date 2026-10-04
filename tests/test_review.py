"""Reviewer tier — staged proposals from underperforming trajectories."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import review, train


def _rec(ok=False, **kw):
    r = {"task": "click ALPHA", "verified": ok,
         "surface": "browser-dom", "model": "m1",
         "verdict": "ACTED (3 steps): hmm",
         "judge": {"success": ok, "waste": "re_aim", "first_fault": 1},
         "flake": "model" if not ok else "none",
         "steps": [{"tool": "click", "arg": "1,2",
                    "result": "CLICKED wrong"}],
         "ms": 1000, "ts": 1.0}
    r.update(kw)
    return r


_REPLY = json.dumps({
    "first_fault": 0, "why": "clicked before aiming",
    "counterfactual": [{"tool": "click", "arg": "50,60"}],
    "skill": {"name": "aim-first", "when": "button tasks",
              "steps": [{"tool": "click", "arg": "50,60"}]},
    "confidence": 0.8})


class ReviewRun(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.results = self.dir / "clicklab.jsonl"
        self.props = self.dir / "proposals.jsonl"
        self.bank = self.dir / "bank.json"
        mock.patch.object(train, "RESULTS", self.results).start()
        mock.patch.object(train, "BANK_FILE", self.bank).start()
        mock.patch.object(review, "PROPOSALS", self.props).start()
        self.addCleanup(mock.patch.stopall)

    def _seed(self, recs):
        self.results.write_text(
            "".join(json.dumps(r) + "\n" for r in recs))

    def test_failed_record_gets_proposal(self):
        self._seed([_rec()])
        with mock.patch("wisp.brain.chat",
                        return_value={"content": _REPLY}) as ch:
            out = review.run({"agent": {}}, limit=5)
        self.assertEqual(out["proposed"], 1)
        p = json.loads(self.props.read_text().strip())
        self.assertEqual(p["counterfactual"][0]["arg"], "50,60")
        self.assertEqual(p["status"], "staged")
        self.assertEqual(p["task"], "click ALPHA")
        # reviewer sees the judge's first_fault
        self.assertIn("first_fault_step=1",
                      ch.call_args[0][0][0]["content"])

    def test_clean_pass_not_reviewed(self):
        self._seed([_rec(ok=True, efficiency=1.0)])
        with mock.patch("wisp.brain.chat") as ch:
            out = review.run({"agent": {}})
        self.assertEqual(out["reviewed"], 0)
        ch.assert_not_called()

    def test_inefficient_pass_reviewed(self):
        self._seed([_rec(ok=True, efficiency=0.4)])
        with mock.patch("wisp.brain.chat",
                        return_value={"content": _REPLY}):
            out = review.run({"agent": {}})
        self.assertEqual(out["reviewed"], 1)

    def test_malformed_reply_skipped_others_continue(self):
        self._seed([_rec(), _rec(task="click BETA")])
        replies = [{"content": "not json at all"},
                   {"content": _REPLY}]
        with mock.patch("wisp.brain.chat", side_effect=replies):
            out = review.run({"agent": {}})
        self.assertEqual(out["proposed"], 1)
        self.assertEqual(out["skipped"], 1)

    def test_reviewer_unreachable_no_crash(self):
        self._seed([_rec()])
        with mock.patch("wisp.brain.chat",
                        side_effect=RuntimeError("offline")):
            out = review.run({"agent": {}})
        self.assertEqual(out["proposed"], 0)
        self.assertTrue(any("failed" in n for n in out["notes"]))

    def test_reviewer_provider_override(self):
        self._seed([_rec()])
        cfg = {"agent": {},
               "brain": {"reviewer": "llama_local:big",
                         "default": "openrouter:small"}}
        with mock.patch("wisp.brain.chat",
                        return_value={"content": _REPLY}) as ch:
            review.run(cfg)
        seen = ch.call_args[0][1]["brain"]["default"]
        self.assertEqual(seen, "llama_local:big")


class ApproveFlow(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.props = self.dir / "proposals.jsonl"
        self.bank = self.dir / "bank.json"
        mock.patch.object(train, "BANK_FILE", self.bank).start()
        mock.patch.object(review, "PROPOSALS", self.props).start()
        self.addCleanup(mock.patch.stopall)
        self.props.write_text(json.dumps({
            "task": "click ALPHA", "model": "m1",
            "surface": "browser-dom", "status": "staged",
            "counterfactual": [{"tool": "click", "arg": "50,60"}],
            "skill": None, "confidence": 0.7}) + "\n")

    def test_approve_copies_to_bank_as_candidate(self):
        msg = review.approve(1)
        self.assertIn("candidate", msg)
        e = train.load_bank()["browser-dom|_|click alpha|m1"]
        self.assertEqual(e["status"], "candidate")
        self.assertEqual(e["streak"], 0)
        self.assertEqual(e["steps"], [{"tool": "click", "arg": "50,60"}])
        self.assertEqual(e["source"], "reviewer")

    def test_approved_proposal_no_longer_staged(self):
        review.approve(1)
        self.assertIn("nothing staged", review.list_text())

    def test_reject_distills_nothing(self):
        review.reject(1)
        self.assertEqual(train.load_bank(), {})
        self.assertIn("nothing staged", review.list_text())

    def test_out_of_range_index(self):
        self.assertIn("no staged", review.approve(9))
        self.assertIn("no staged", review.reject(0))

    def test_list_shows_staged(self):
        txt = review.list_text()
        self.assertIn("click ALPHA", txt)
        self.assertIn("counterfactual: 1", txt)


if __name__ == "__main__":
    unittest.main()
