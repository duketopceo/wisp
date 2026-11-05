"""B4: tone under a mark, the pen's pace, and parity with lib/ink.js."""
import base64
import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jsnode  # noqa: E402
from PIL import Image  # noqa: E402
from wisp import ink, speech  # noqa: E402
from test_stage_speak import StageBase, DRAW_REPLY  # noqa: E402


def png_b64(w, h, left, right, split):
    img = Image.new("RGB", (w, h), right)
    img.paste(Image.new("RGB", (split, h), left), (0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Tone(unittest.TestCase):
    def test_text_colour_flips_with_the_background(self):
        self.assertEqual(ink.text_on(ink.luminance(8, 8, 12)), "light")
        self.assertEqual(ink.text_on(ink.luminance(250, 250, 245)), "dark")
        self.assertEqual(ink.tone(ink.luminance(8, 8, 12)), "dark")
        self.assertEqual(ink.tone(ink.luminance(250, 250, 245)), "light")

    def test_the_crossover_gives_equal_contrast(self):
        # white on L and black on L meet at about 0.179
        l_ = ink.LIGHT_BELOW
        self.assertAlmostEqual((1.05) / (l_ + 0.05), (l_ + 0.05) / 0.05,
                               delta=0.02)

    def test_a_mark_over_a_dark_region_and_over_a_light_one(self):
        img = Image.open(io.BytesIO(base64.b64decode(
            png_b64(400, 300, (10, 10, 14), (240, 240, 236), 200))))
        marks = [{"kind": "ring", "x": 60, "y": 100, "r": 30},
                 {"kind": "hl", "x": 260, "y": 40, "w": 100, "h": 60},
                 {"kind": "arrow", "x1": 20, "y1": 20, "x2": 300, "y2": 150},
                 {"x": 50, "y": 50, "label": "a point"},
                 {"kind": "ring", "x": 9000, "y": 9000, "r": 5}]
        self.assertEqual(ink.tones_for(img, marks),
                         ["dark", "light", "light", "dark", ""])

    def test_no_screenshot_means_no_tone(self):
        self.assertEqual(ink.tones_for(None, [{"kind": "ring", "x": 1,
                                               "y": 1, "r": 5}]), [""])
        self.assertIsNone(ink.open_image("not an image"))
        self.assertIsNone(ink.open_image(None))
        self.assertIsNotNone(ink.open_image(
            "data:image/png;base64," + png_b64(8, 8, "black", "white", 4)))

    def test_matches_the_qml_lib_for_every_grey(self):
        if not jsnode.NODE:
            self.skipTest("node not installed")
        greys = list(range(0, 256, 5))
        got = jsnode.call(
            "[" + ",".join(f"[Ink.luminance({g},{g},{g}),"
                           f"Ink.tone(Ink.luminance({g},{g},{g})),"
                           f"Ink.textOn(Ink.luminance({g},{g},{g}))]"
                           for g in greys) + "]", Ink="ink")
        for g, (lum, t, txt) in zip(greys, got):
            self.assertAlmostEqual(lum, ink.luminance(g, g, g), places=9)
            self.assertEqual(t, ink.tone(ink.luminance(g, g, g)), g)
            self.assertEqual(txt, ink.text_on(ink.luminance(g, g, g)), g)


class Pace(unittest.TestCase):
    def test_longer_sentences_take_longer_and_speed_scales_it(self):
        short = speech.sentence_ms("Look here.", {})
        long_ = speech.sentence_ms("Look over here at the second row.", {})
        self.assertGreater(long_, short)
        slow = speech.sentence_ms("Look here.", {"voice": {"speed": "0.5"}})
        self.assertAlmostEqual(slow / short, 2.0, delta=0.05)
        self.assertEqual(speech.sentence_ms("", {}), 0)


class InTheTurn(StageBase):
    def test_each_drawing_gets_the_tone_of_the_screen_under_it(self):
        ctx = self.ctx({"voice": {"enabled": "false"}, "agent": {}})
        # ring at (100,200) over the dark left; arrow tip (300,400) over
        # the light right
        ctx.shot_b64 = png_b64(500, 500, (6, 6, 10), (245, 245, 240), 200)
        from unittest import mock
        from wisp import pipeline, stage_speak
        with mock.patch.object(pipeline, "ask_chat",
                               return_value=DRAW_REPLY), \
                mock.patch.object(pipeline.speech, "speak",
                                  return_value=None):
            stage_speak._answer(ctx)
        sent = [c for c in self.emit.call_args_list
                if c.args[1] == "points"]
        drawings = sent[0].args[3]["drawings"]
        self.assertEqual([(d["kind"], d["tone"]) for d in drawings],
                         [("ring", "dark"), ("arrow", "light")])

    def test_no_screenshot_adds_no_tone(self):
        ctx = self.ctx({"voice": {"enabled": "false"}, "agent": {}})
        from unittest import mock
        from wisp import pipeline, stage_speak
        with mock.patch.object(pipeline, "ask_chat",
                               return_value=DRAW_REPLY), \
                mock.patch.object(pipeline.speech, "speak",
                                  return_value=None):
            stage_speak._answer(ctx)
        sent = [c for c in self.emit.call_args_list
                if c.args[1] == "points"]
        for d in sent[0].args[3]["drawings"]:
            self.assertNotIn("tone", d)


if __name__ == "__main__":
    unittest.main()
