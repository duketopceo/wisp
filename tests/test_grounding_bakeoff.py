#!/usr/bin/env python3
"""U8: the grounding bake-off scorer, split, spend cap and the letterbox
round trip. Fake providers only; urlopen is patched to fail the test if
anything reaches for the network."""
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from wisp import grounding  # noqa: E402

try:
    from PIL import Image  # noqa: F401
except ImportError:
    Image = None

needs_pil = unittest.skipIf(Image is None, "Pillow not installed")

_spec = importlib.util.spec_from_file_location(
    "grounding_bakeoff", ROOT / "scripts" / "grounding_bakeoff.py")
bo = importlib.util.module_from_spec(_spec)
if Image is not None:
    sys.modules["grounding_bakeoff"] = bo   # dataclasses look it up
    _spec.loader.exec_module(bo)

FIXTURES = ROOT / "tests" / "fixtures" / "images"


def _no_net(*a, **k):
    raise AssertionError("network call in an offline test")


@needs_pil
class Split(unittest.TestCase):
    def test_deterministic_from_the_seed(self):
        self.assertEqual(bo.split(7), bo.split(7))
        self.assertNotEqual(bo.split(7)[1], bo.split(8)[1])

    def test_never_overlaps_and_covers_the_pool(self):
        for seed in (0, 1, 20261105):
            tuning, held = bo.split(seed)
            self.assertFalse(set(tuning) & set(held))
            self.assertEqual(sorted(tuning + held), list(range(bo.POOL)))
            self.assertTrue(held and tuning)

    def test_case_content_does_not_depend_on_the_split_seed(self):
        self.assertEqual(bo.make_case(5), bo.make_case(5))

    def test_cases_have_one_target_inside_the_canvas(self):
        for i in range(bo.POOL):
            c = bo.make_case(i)
            self.assertIn(c.target, c.labels)
            self.assertEqual(len(set(c.labels)), len(c.labels))
            x0, y0, x1, y1 = c.rect
            self.assertTrue(0 <= x0 < x1 <= c.width, i)
            self.assertTrue(0 <= y0 < y1 <= c.height, i)

    def test_every_canvas_shape_is_drawn(self):
        shapes = {(bo.make_case(i).width, bo.make_case(i).height)
                  for i in range(len(bo.CANVASES))}
        self.assertEqual(shapes, set(bo.CANVASES))
        self.assertTrue(any(h > w for w, h in shapes))      # portrait
        png = bo.render(bo.make_case(4))
        self.assertEqual(grounding.Shot.from_bytes(png).width, 1080)


@needs_pil
class Scoring(unittest.TestCase):
    def setUp(self):
        p = mock.patch("urllib.request.urlopen", _no_net)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, *providers, cap=1.0, n=40):
        cases = [bo.make_case(i) for i in range(n)]
        return bo.run(cases, list(providers), modes=("direct",),
                      cap_usd=cap)

    def test_ranks_eight_of_ten_above_five_of_ten(self):
        res = self._run(bo.FakeProvider("five", 5),
                        bo.FakeProvider("eight", 8))
        rows = {r["model"]: r for r in res["rows"]}
        self.assertEqual(rows["eight"]["accuracy"], 0.8)
        self.assertEqual(rows["five"]["accuracy"], 0.5)
        self.assertEqual([r["model"] for r in res["rows"]],
                         ["eight", "five"])

    def test_equal_accuracy_ranks_the_cheaper_first(self):
        res = self._run(bo.FakeProvider("dear", 8, 0.01),
                        bo.FakeProvider("cheap", 8, 0.0001))
        self.assertEqual(res["rows"][0]["model"], "cheap")

    def test_per_case_cost_is_reported(self):
        res = self._run(bo.FakeProvider("a", 8, 0.002), n=10)
        self.assertAlmostEqual(res["rows"][0]["cost_per_case_usd"], 0.002)
        self.assertAlmostEqual(res["rows"][0]["cost_total_usd"], 0.02)

    def test_none_and_garbage_replies_are_misses(self):
        c = bo.make_case(0)
        box = grounding.Shot.from_bytes(bo.render(c)).letterboxed()
        for text in ("", "NONE", "I cannot see it", "[POINT:99999,5:x]"):
            self.assertFalse(bo.score(c, box, text)["hit"], text)

    def test_stops_at_the_cap_and_keeps_the_partial_table(self):
        res = self._run(bo.FakeProvider("a", 8, 0.01),
                        bo.FakeProvider("b", 5, 0.01), cap=0.05)
        self.assertTrue(res["stopped"])
        self.assertLessEqual(res["spent_usd"], 0.05)
        self.assertEqual(sum(r["n"] for r in res["rows"]), 5)
        self.assertIn("STOPPED AT THE CAP", bo.render_table(res))

    def test_cap_holds_before_any_cost_is_known(self):
        res = self._run(bo.FakeProvider("a", 8), cap=0.001)
        self.assertTrue(res["stopped"])
        self.assertEqual(res["rows"][0]["n"], 0)
        self.assertEqual(res["spent_usd"], 0)

    def test_prompt_lists_labels_only_in_labels_mode(self):
        c = bo.make_case(1)
        box = grounding.Shot.from_bytes(bo.render(c)).letterboxed()
        self.assertNotIn("Accessibility labels",
                         bo.build_prompt(c, box, "direct"))
        self.assertIn(c.target, bo.build_prompt(c, box, "labels"))
        self.assertIn("Accessibility labels",
                      bo.build_prompt(c, box, "labels"))

    def test_live_refuses_without_a_key(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}), \
                mock.patch("sys.stderr"):
            self.assertEqual(bo.main(["--live", "--models", "m/x"]), 2)

    def test_fake_cli_runs_offline(self):
        with mock.patch("builtins.print"):
            self.assertEqual(bo.main(["--fake", "--cases", "4"]), 0)


@needs_pil
class LetterboxRoundTrip(unittest.TestCase):
    """src -> sent (p * scale + pad) -> Letterbox.to_shot -> src."""

    def _round(self, w, h):
        from PIL import Image as I
        import io
        buf = io.BytesIO()
        I.new("RGB", (w, h), (9, 9, 9)).save(buf, format="PNG")
        box = grounding.Shot.from_bytes(buf.getvalue()).letterboxed()
        for fx, fy in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.13, 0.91)):
            sx, sy = round(fx * w), round(fy * h)
            px = sx * box.scale_x + box.pad_x
            py = sy * box.scale_y + box.pad_y
            got = box.to_shot(px, py)
            self.assertIsNotNone(got, (w, h, fx, fy))
            # one sent pixel is 1/scale source pixels; allow that plus 1
            self.assertLessEqual(abs(got[0] - sx), 1 / box.scale_x + 1)
            self.assertLessEqual(abs(got[1] - sy), 1 / box.scale_y + 1)
        return box

    def test_landscape_with_pad(self):
        self.assertTrue(self._round(2560, 1080).padded)

    def test_portrait_with_pad(self):
        box = self._round(1080, 1920)
        self.assertTrue(box.padded)
        self.assertGreater(box.pad_x, 0)

    def test_exact_aspect_has_no_pad(self):
        self.assertFalse(self._round(1440, 900).padded)

    def test_recorded_fixture_images(self):
        for name in ("landscape.png", "portrait.png"):
            shot = grounding.Shot.from_bytes((FIXTURES / name).read_bytes())
            box = shot.letterboxed()
            mid = box.to_shot(box.pad_x + shot.width * box.scale_x / 2,
                              box.pad_y + shot.height * box.scale_y / 2)
            self.assertLessEqual(abs(mid[0] - shot.width / 2), 2, name)
            self.assertLessEqual(abs(mid[1] - shot.height / 2), 2, name)

    def test_a_point_in_the_padding_is_refused(self):
        box = self._round(1080, 1920)
        self.assertIsNone(box.to_shot(1.0, 100.0))

    def test_oracle_through_the_whole_path_scores_a_hit(self):
        # the fake answers in sent-image coordinates, so a hit on every
        # canvas (portrait and letterboxed included) proves the round trip
        res = bo.run([bo.make_case(i) for i in range(len(bo.CANVASES))],
                     [bo.FakeProvider("oracle", 10)], modes=("direct",))
        self.assertEqual(res["rows"][0]["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
