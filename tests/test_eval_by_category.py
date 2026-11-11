#!/usr/bin/env python3
"""U2: `wispd eval --by-category` rolls owner labels and gauntlet
failures into failure categories."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import learn  # noqa: E402


class Categorize(unittest.TestCase):
    def test_each_category(self):
        c = learn.categorize
        self.assertEqual(c("ACTED (2 steps): done",
                           note="typed a guessed path"), "guessed input")
        self.assertEqual(c("ACTED (3 steps): ok",
                           note="clicked the back arrow"), "wrong target")
        self.assertEqual(c("ACTED (3 steps): ok",
                           note="it was in a browser, not a file manager"),
                         "wrong app/window")
        self.assertEqual(c("ABORTED (max 12 steps): screenshot"),
                         "timeout/max steps")
        self.assertEqual(c("BLOCKED (policy)"), "refused by policy")
        self.assertEqual(c("ACTED (1 steps): x",
                           note="it misheard me, garbled transcript"),
                         "speech garbage")
        self.assertEqual(c("ACTED (1 steps): x", note="meh"),
                         learn.OTHER_CATEGORY)

    def test_typed_absolute_path_that_failed_is_guessed_input(self):
        steps = [{"tool": "type_text", "arg": "/home/someone/Projects",
                  "result": "TYPED"},
                 {"tool": "screenshot", "arg": "",
                  "result": "no such file or directory"}]
        self.assertEqual(learn.categorize("ACTED (2 steps): done",
                                          steps=steps), "guessed input")

    def test_policy_refusal_beats_wrong_target(self):
        steps = [{"tool": "click", "arg": "1,1", "result": "CLICKED x"},
                 {"tool": "shell", "arg": "grep", "result": "REFUSED (x)"}]
        self.assertEqual(learn.categorize("ACTED (2 steps): ok",
                                          steps=steps),
                         "refused by policy")


class RollUp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.decs = self.dir / "decisions.jsonl"
        self.labs = self.dir / "labels.jsonl"

    def write(self, path, rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_owner_labels_roll_up_biggest_first(self):
        self.write(self.decs, [
            {"ts": "T1", "result": "ACTED (2 steps): x", "transcript": "a"},
            {"ts": "T2", "result": "ACTED (2 steps): x", "transcript": "b"},
            {"ts": "T3", "result": "ABORTED (max 8 steps): y",
             "transcript": "c"},
            {"ts": "T4", "result": "ANSWERED", "transcript": "d"}])
        self.write(self.labs, [
            {"ref": "T1", "label": "incorrect", "note": "guessed the path"},
            {"ref": "T2", "label": "incorrect", "note": "invented a folder"},
            {"ref": "T3", "label": "incorrect", "note": ""},
            {"ref": "T4", "label": "correct", "note": ""}])
        rep = learn.eval_by_category(self.decs, self.labs)
        self.assertEqual(rep["total"], 3)
        self.assertEqual(rep["owner"], 3)
        top = rep["categories"][0]
        self.assertEqual((top["category"], top["count"]), ("guessed input", 2))
        self.assertAlmostEqual(top["share"], 2 / 3)
        self.assertEqual(top["examples"], ["a", "b"])
        self.assertEqual(rep["categories"][1]["category"],
                         "timeout/max steps")

    def test_gauntlet_rows_roll_in_and_skip_passes_and_unrun(self):
        self.write(self.decs, [])
        self.write(self.labs, [])
        run = self.dir / "gauntlet-x"
        run.mkdir()

        def rec(case, passed, result, reason, steps=()):
            return {"case": case, "rep": 1, "goal": case, "passed": passed,
                    "row": {"result": result, "steps": list(steps),
                            "judge": {"reason": reason}}}
        self.write(run / "rows.jsonl", [
            rec("ok", True, "ACTED (1 steps): done", "fine"),
            rec("skipped", False, "SKIP (route walkthrough is not run in "
                "dev mode)", "not run"),
            rec("files-new-folder", False, "ACTED (3 steps): made it",
                "The action appears to have opened a search bar."),
            rec("terminal-grep-word", False, "ACTED (2 steps): done",
                "The system refused to execute the grep command."),
            rec("files-open-second-folder", False,
                "ABORTED (max 12 steps): screenshot", "not open"),
            {"case": "nodata", "passed": False, "row": None}])
        rep = learn.eval_by_category(self.decs, self.labs, gauntlet=[run])
        self.assertEqual((rep["total"], rep["gauntlet"], rep["owner"]),
                         (3, 3, 0))
        got = {c["category"]: c["count"] for c in rep["categories"]}
        self.assertEqual(got, {"wrong target": 1, "refused by policy": 1,
                               "timeout/max steps": 1})
        # the rows file path itself works too
        rep2 = learn.eval_by_category(self.decs, self.labs,
                                      gauntlet=[run / "rows.jsonl"])
        self.assertEqual(rep2["total"], 3)

    def test_text_and_empty(self):
        self.write(self.decs, [])
        self.write(self.labs, [])
        rep = learn.eval_by_category(self.decs, self.labs)
        self.assertIn("no misses", learn.by_category_text(rep))
        self.write(self.decs, [{"ts": "T1", "result": "BLOCKED (x)"}])
        self.write(self.labs, [{"ref": "T1", "label": "incorrect"}])
        text = learn.by_category_text(
            learn.eval_by_category(self.decs, self.labs))
        self.assertIn("refused by policy", text)
        self.assertIn("100%", text)


if __name__ == "__main__":
    unittest.main()
