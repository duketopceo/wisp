"""B32: four questions seed the profile and offer three starters; a routine
starter is only scheduled after a yes; skip ends cleanly."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import agent_home, onboard, routines, starter_pack as sp  # noqa: E402

ANSWERS = ["I am a nurse", "Epiphany and Slack", "slow logins", "short"]


def script(answers, yes=()):
    """ask returns `answers` in order; confirm says yes to offers whose
    text contains one of `yes`."""
    it = iter(answers)
    asked = []

    def ask(q):
        asked.append(q)
        return next(it, None)

    return ask, (lambda prompt: any(y in prompt for y in yes)), asked


class Interview(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.store = routines.RoutineStore(self.tmp / "r.json")
        self.profile, self.notes, self.said, self.marks = [], [], [], []

    def go(self, answers, yes=()):
        ask, confirm, self.asked = script(answers, yes)

        def make_routine(spec):
            return routines.teach_routine(
                spec, store=self.store, confirm=lambda *a, **k: True,
                install_units=False)

        return sp.run(
            ask, confirm, self.said.append,
            write_profile=self.profile.extend,
            make_helper=lambda h: agent_home.create(
                h["name"], h["role"], root=self.tmp / "agents"),
            make_routine=make_routine, note=self.notes.append,
            mark=lambda: self.marks.append(1), log=lambda s: None)

    def test_scripted_interview_writes_profile_and_offers_three_kinds(self):
        offers = []
        ask, _c, _ = script(ANSWERS)
        res = sp.run(ask, lambda p: offers.append(p) or False, self.said.append,
                     write_profile=self.profile.extend,
                     make_helper=lambda h: 0, make_routine=lambda r: 0,
                     mark=lambda: self.marks.append(1), log=lambda s: None)
        self.assertEqual(res["status"], "done")
        self.assertEqual(len(self.profile), 4)
        self.assertIn("Works as: I am a nurse", self.profile)
        self.assertEqual(len(offers), 3)
        kinds = [s["kind"] for s in sp.starters(res["answers"])]
        self.assertEqual(sorted(kinds), sorted(sp.KINDS))
        self.assertEqual(self.marks, [1])

    def test_four_questions_are_asked_in_order(self):
        self.go(ANSWERS)
        self.assertEqual(self.asked, [q for _k, q in sp.QUESTIONS])

    def test_routine_is_not_scheduled_until_the_yes(self):
        self.go(ANSWERS, yes=())
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.has_opted_in())
        res = self.go(ANSWERS, yes=("This will repeat",))
        self.assertEqual(res["accepted"], ["morning"])
        got = self.store.list()
        self.assertEqual(len(got), 1)
        self.assertIn("Epiphany", got[0].name)

    def test_repeating_offer_asks_to_keep_it_going(self):
        work = [s for s in sp.starters({"apps": "Epiphany"})
                if s["kind"] == "work"][0]
        self.assertTrue(work["repeats"])
        self.assertIn("This will repeat. Keep it going?", work["offer"])

    def test_helper_and_answer_starters_do_not_schedule(self):
        res = self.go(ANSWERS, yes=("Scout", "straight answer"))
        self.assertEqual(res["accepted"], ["helper", "tryit"])
        self.assertTrue(agent_home.exists("Scout", root=self.tmp / "agents"))
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(self.store.list(), [])

    def test_skip_at_any_point_ends_cleanly_and_writes_nothing(self):
        for n in range(4):
            self.setUp()
            res = self.go(ANSWERS[:n] + ["skip"], yes=("",))
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(self.profile, [])
            self.assertEqual(self.marks, [], "offered again next run")
            self.assertEqual(self.store.list(), [])

    def test_silence_counts_as_skip(self):
        res = self.go(ANSWERS[:2])      # then nothing heard
        self.assertEqual(res["status"], "skipped")

    def test_a_long_answer_with_a_skip_word_is_an_answer(self):
        self.assertFalse(sp.wants_skip("I check mail later in the evening"))
        self.assertTrue(sp.wants_skip("Skip."))
        self.assertTrue(sp.wants_skip("not now"))

    def test_profile_lines_are_capped(self):
        lines = sp.profile_lines({k: "x " * 300 for k, _ in sp.QUESTIONS})
        self.assertTrue(all(len(l) < 200 for l in lines))


class Plumbing(unittest.TestCase):
    def test_transcripts_since_reads_the_decision_log(self):
        p = pathlib.Path(tempfile.mkdtemp()) / "d.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in [
            {"ts": "2026-01-01T00:00:00+00:00", "transcript": "old"},
            {"ts": "2026-01-01T00:00:09+00:00", "transcript": "new"},
            {"ts": "2026-01-01T00:00:10+00:00"}]) + "\nnot json\n")
        self.assertEqual(sp.transcripts_since("2026-01-01T00:00:05", p), ["new"])
        self.assertEqual(sp.transcripts_since("x", p / "missing"), [])

    def test_progress_records_the_pack_so_it_is_offered_once(self):
        pr = onboard.Progress(pathlib.Path(tempfile.mkdtemp()) / "o.json")
        self.assertFalse(pr.starter_done)
        pr.starter_mark()
        self.assertTrue(pr.starter_done)


if __name__ == "__main__":
    unittest.main()
