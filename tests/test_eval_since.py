"""`[eval] since` limits the v1 gate to turns from the build being shipped,
and a dry-run act turn says so instead of claiming it clicked."""
import json
import pathlib
import tempfile
import unittest

from wisp import act, learn


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class EvalSinceTest(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.dec, self.lab = d / "decisions.jsonl", d / "labels.jsonl"
        old, new = "2026-10-02T03:11:00+00:00", "2026-11-03T18:00:00+00:00"
        _write(self.dec, [{"ts": old, "result": "ACTED (1 steps): x"},
                          {"ts": new, "result": "ANSWERED"}])
        _write(self.lab, [{"ts": old, "ref": old, "label": "incorrect"},
                          {"ts": new, "ref": new, "label": "correct"}])

    def report(self, since=None):
        ev = {"gate_rate": "60%", "gate_min_turns": "1"}
        if since is not None:
            ev["since"] = since
        return learn.eval_report({"eval": ev}, self.dec, self.lab)

    def test_unset_counts_every_label(self):
        rep = self.report()
        self.assertEqual(rep["total"]["labelled"], 2)
        self.assertEqual(rep["since"], "")

    def test_since_drops_older_turns(self):
        rep = self.report("2026-11-03")
        self.assertEqual(rep["total"]["labelled"], 1)
        self.assertEqual(rep["total"]["correct"], 1)
        self.assertEqual(rep["gate"]["status"], "PASS")
        self.assertIn("since 2026-11-03", learn.eval_text(rep))

    def test_since_accepts_a_date_time(self):
        self.assertEqual(self.report("2026-11-03T19:00")["total"]["labelled"], 0)

    def test_invalid_since_counts_everything(self):
        rep = self.report("last tuesday")
        self.assertEqual(rep["total"]["labelled"], 2)
        self.assertEqual(rep["since"], "")


class DryRunNoteTest(unittest.TestCase):
    def test_dry_run_steps_are_named(self):
        steps = [{"tool": "screenshot", "result": "ok"},
                 {"tool": "click", "result": "DRYRUN would click 10,10"}]
        self.assertEqual(act._dry_run_note(steps), act.DRY_RUN_NOTE)

    def test_real_steps_get_no_note(self):
        steps = [{"tool": "click", "result": "CLICKED btn"}, {"tool": "x"}]
        self.assertEqual(act._dry_run_note(steps), "")


if __name__ == "__main__":
    unittest.main()
