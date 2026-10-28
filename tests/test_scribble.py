"""B7: scribble to ask. Strokes drawn while listening reach the model's
screenshot, once, and only then."""
import base64
import contextlib
import io
import json
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402

from wisp import scribble, stage_capture, stage_ctx, stage_speak  # noqa: E402

PINK = scribble.STROKE_RGB


def png_url(w=200, h=100, color=(20, 20, 20), jpeg=False):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG" if jpeg else "PNG")
    kind = "jpeg" if jpeg else "png"
    return f"data:image/{kind};base64," + base64.b64encode(
        buf.getvalue()).decode()


def decode(url):
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    img.load()
    return img


DOC = {"strokes": [[[20, 50], [100, 20], [180, 50], [100, 80], [20, 50]]],
       "w": 200, "h": 100}


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.run_dir = pathlib.Path(td.name)
        p = mock.patch.object(scribble.config, "RUN_DIR", self.run_dir)
        p.start()
        self.addCleanup(p.stop)


class Normalize(unittest.TestCase):
    def test_a_good_doc_survives(self):
        got = scribble.normalize(DOC)
        self.assertEqual(len(got["strokes"]), 1)
        self.assertEqual((got["w"], got["h"]), (200, 100))

    def test_junk_is_dropped_not_raised(self):
        for bad in (None, 5, "x", {}, {"strokes": [], "w": 1, "h": 1},
                    {"strokes": [[[1, 2]]], "w": 10, "h": 10},   # one point
                    {"strokes": [[[1, 2], [3, 4]]], "w": 0, "h": 10},
                    {"strokes": [[[1, 2], [3, 4]]], "w": float("nan"),
                     "h": 10},
                    {"strokes": [[["a", 2], [None, 4]]], "w": 10, "h": 10},
                    {"strokes": "no", "w": 10, "h": 10}):
            self.assertIsNone(scribble.normalize(bad), bad)

    def test_points_are_clamped_and_counts_capped(self):
        many = [[[i, i], [i + 1, i + 1]] for i in range(40)]
        got = scribble.normalize({"strokes": many, "w": 50, "h": 50})
        self.assertEqual(len(got["strokes"]), scribble.MAX_STROKES)
        long = [[i % 50, i % 50] for i in range(1000)]
        got = scribble.normalize({"strokes": [long], "w": 50, "h": 50})
        self.assertEqual(len(got["strokes"][0]), scribble.MAX_POINTS)
        got = scribble.normalize({"strokes": [[[-30, 500], [900, -9]]],
                                  "w": 50, "h": 50})
        self.assertEqual(got["strokes"][0], [[0.0, 50.0], [50.0, 0.0]])


class Store(Base):
    def test_save_then_take_returns_the_strokes_once(self):
        res = scribble.save(DOC, now=1000.0)
        self.assertEqual(res, {"strokes": 1, "points": 5})
        self.assertEqual(scribble.take(now=1005.0)["w"], 200)
        self.assertIsNone(scribble.take(now=1005.0))      # consumed
        self.assertFalse(scribble.path().exists())

    def test_file_is_private(self):
        scribble.save(DOC)
        mode = stat.S_IMODE(scribble.path().stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_a_later_save_replaces_the_earlier_one(self):
        scribble.save(DOC, now=1.0)
        other = {"strokes": [[[1, 1], [9, 9]]], "w": 10, "h": 10}
        scribble.save(other, now=2.0)
        self.assertEqual(scribble.take(now=3.0)["w"], 10)

    def test_stale_strokes_are_ignored_and_deleted(self):
        scribble.save(DOC, now=1000.0)
        self.assertIsNone(scribble.take(now=1000.0 + scribble.MAX_AGE_S + 1))
        self.assertFalse(scribble.path().exists())

    def test_an_empty_save_clears(self):
        scribble.save(DOC)
        self.assertEqual(scribble.save({"strokes": [], "w": 1, "h": 1}),
                         {"strokes": 0, "points": 0})
        self.assertIsNone(scribble.take())

    def test_a_corrupt_file_is_just_nothing(self):
        scribble.path().write_text("{not json")
        self.assertIsNone(scribble.take())
        self.assertFalse(scribble.path().exists())

    def test_take_with_nothing_stored(self):
        self.assertIsNone(scribble.take())


class Apply(unittest.TestCase):
    def test_the_strokes_are_drawn_into_the_shot(self):
        out, hint = scribble.apply(png_url(), DOC)
        img = decode(out)
        self.assertEqual(img.size, (200, 100))
        self.assertEqual(img.getpixel((60, 35)), PINK)      # mid-stroke
        self.assertEqual(img.getpixel((100, 50)), (20, 20, 20))  # inside
        self.assertEqual(img.getpixel((5, 95)), (20, 20, 20))    # outside
        self.assertIn("1 stroke ", hint)
        self.assertIn("x 20-180, y 20-80", hint)

    def test_a_scaled_shot_gets_scaled_strokes(self):
        out, hint = scribble.apply(png_url(400, 200), DOC)
        img = decode(out)
        self.assertEqual(img.getpixel((120, 70)), PINK)
        self.assertIn("x 40-360, y 40-160", hint)

    def test_encoding_is_kept(self):
        out, _ = scribble.apply(png_url(jpeg=True), DOC)
        self.assertTrue(out.startswith("data:image/jpeg;base64,"))
        self.assertEqual(decode(out).format, "JPEG")
        out, _ = scribble.apply(png_url(), DOC)
        self.assertTrue(out.startswith("data:image/png;base64,"))
        raw = png_url().split(",", 1)[1]
        out, _ = scribble.apply(raw, DOC)
        self.assertFalse(out.startswith("data:"))
        Image.open(io.BytesIO(base64.b64decode(out)))

    def test_nothing_to_draw_changes_nothing(self):
        shot = png_url()
        self.assertEqual(scribble.apply(shot, None), (shot, ""))
        self.assertEqual(scribble.apply(None, DOC), (None, ""))
        self.assertEqual(scribble.apply("data:image/png;base64,AAAA", DOC),
                         ("data:image/png;base64,AAAA", ""))

    def test_the_hint_says_the_pink_is_the_users_mark(self):
        _, hint = scribble.apply(png_url(), DOC)
        self.assertIn("circled", hint)
        self.assertIn("their mark", hint)


class IntoTheTurn(Base):
    """context_stage: the strokes land in the screenshot the model gets."""

    def ctx(self, text, shot):
        sp = mock.MagicMock()
        sp.timed.side_effect = lambda *_a, **_k: contextlib.nullcontext()
        c = stage_ctx.TurnCtx({"agent": {"screenshots": "true"}},
                              mock.MagicMock(), None, None, None, sp,
                              "t1", None, None, 1.0, "m")
        c.text = text
        self.shot = shot
        return c

    def run_stage(self, c):
        pl = mock.MagicMock()
        pl.active_window.return_value = {"class": "foot", "title": "t"}
        pl.turn_screenshot.side_effect = lambda cfg, spec: self.shot
        with mock.patch.object(stage_capture, "_pl", lambda: pl), \
                mock.patch("wisp.tools.adapters.best_catalog",
                           return_value={}), \
                mock.patch("wisp.tools.adapters.context", return_value=""), \
                mock.patch("wisp.goals.join_or_new",
                           return_value=({"text": "g"}, False)), \
                mock.patch("wisp.goals.context_text", return_value=""), \
                mock.patch("wisp.session.tail", return_value=[]), \
                mock.patch("wisp.session.as_text", return_value=""), \
                mock.patch("wisp.memory.context_block", return_value=""), \
                mock.patch("wisp.learn.correction_context",
                           return_value=None), \
                mock.patch("wisp.docread.context_for", return_value=""):
            stage_capture.context_stage(c)
        return pl

    def test_strokes_made_while_listening_are_in_the_shot_and_the_context(self):
        scribble.save(DOC)
        c = self.ctx("what is this", png_url())
        self.run_stage(c)
        self.assertEqual(decode(c.shot_b64).getpixel((60, 35)), PINK)
        self.assertIn("The user drew", c.scribble_hint)
        self.assertIn("The user drew", c.context)

    def test_no_strokes_means_the_shot_is_untouched(self):
        shot = png_url()
        c = self.ctx("what is this", shot)
        self.run_stage(c)
        self.assertEqual(c.shot_b64, shot)
        self.assertEqual(c.scribble_hint, "")
        self.assertNotIn("The user drew", c.context)

    def test_the_next_turn_does_not_see_them(self):
        scribble.save(DOC)
        self.run_stage(self.ctx("what is this", png_url()))
        shot = png_url()
        c = self.ctx("and this", shot)
        self.run_stage(c)
        self.assertEqual(c.shot_b64, shot)

    def test_a_bare_question_still_gets_a_screen_when_scribbled(self):
        scribble.save(DOC)
        c = self.ctx("what time is it", png_url())
        pl = self.run_stage(c)
        pl.turn_screenshot.assert_called_once()
        self.assertTrue(c.scribble_hint)

    def test_strokes_are_consumed_even_without_screenshots(self):
        scribble.save(DOC)
        c = self.ctx("what is this", None)
        c.cfg = {"agent": {"screenshots": "false"}}
        self.run_stage(c)
        self.assertFalse(scribble.path().exists())
        self.assertIsNone(c.shot_b64)


class IntoTheAnswer(unittest.TestCase):
    def messages(self, **kw):
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": "that is a button"}
        with mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=True), \
                mock.patch("wisp.memory.context_block", return_value=""):
            stage_speak.ask_chat("what is this", {}, image_b64=png_url(),
                                 **kw)
        return seen["m"]

    def test_the_model_is_told_about_the_marks(self):
        system = self.messages(scribble_hint="The user drew 1 stroke")[0]
        self.assertIn("The user drew 1 stroke", system["content"])

    def test_without_marks_the_prompt_is_unchanged(self):
        system = self.messages()[0]["content"]
        self.assertNotIn("The user drew", system)


class Cli(Base):
    def run_cli(self, *argv):
        from wisp import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(list(argv) + ["--json"])
        return rc, out.getvalue()

    def test_set_then_clear(self):
        rc, out = self.run_cli("scribble", "set", json.dumps(DOC))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["data"]["strokes"], 1)
        self.assertTrue(scribble.path().exists())
        rc, _ = self.run_cli("scribble", "clear")
        self.assertEqual(rc, 0)
        self.assertFalse(scribble.path().exists())

    def test_bad_json_is_a_usage_error(self):
        rc, _ = self.run_cli("scribble", "set", "{nope")
        self.assertNotEqual(rc, 0)
        self.assertFalse(scribble.path().exists())


if __name__ == "__main__":
    unittest.main()
