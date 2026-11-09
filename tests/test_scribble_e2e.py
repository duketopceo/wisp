"""Circle-to-ask end to end: a stroke saved while listening reaches the
request the brain receives (pink pixels in the screenshot plus the text
hint), is consumed by that one turn, and the answer's point lands in the
circled box. Hermetic: Pillow fixture shot, fake brain, temp RUN_DIR."""
import base64
import contextlib
import io
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw  # noqa: E402

from wisp import points, scribble, stage_capture, stage_ctx, stage_speak  # noqa: E402

PINK = scribble.STROKE_RGB
BG = (20, 20, 20)
BUTTON_RGB = (60, 120, 200)
SHOT_W, SHOT_H = 400, 200          # screenshot; overlay below is half size
# A circle drawn around the "button" in overlay coordinates (200x100).
DOC = {"strokes": [[[40, 30], [100, 15], [160, 30], [160, 70], [100, 85],
                    [40, 70], [40, 30]]], "w": 200, "h": 100}
BOX = (80, 30, 320, 170)           # DOC's bounding box in shot pixels
BUTTON = (200, 100)                # centre of the circled "button"


def shot_url():
    """Dark screen with one light 'button' inside the circled region."""
    img = Image.new("RGB", (SHOT_W, SHOT_H), BG)
    ImageDraw.Draw(img).rectangle([170, 85, 230, 115], fill=BUTTON_RGB)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def decode(url):
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    img.load()
    return img.convert("RGB")


def has_pink(img):
    return any(img.getpixel((x, y)) == PINK
               for x in range(img.width) for y in range(img.height))


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = mock.patch.object(scribble.config, "RUN_DIR",
                              pathlib.Path(td.name))
        p.start()
        self.addCleanup(p.stop)

    def ask(self, text, reply="That is the Save button [POINT:200,100:Save]."):
        """One whole turn: capture stage (consumes the stroke), then the
        brain request. Returns (request messages, answer text)."""
        sp = mock.MagicMock()
        sp.timed.side_effect = lambda *_a, **_k: contextlib.nullcontext()
        ctx = stage_ctx.TurnCtx({"agent": {"screenshots": "true"}},
                                mock.MagicMock(), None, None, None, sp,
                                "t1", None, None, 1.0, "m")
        ctx.text = text
        pl = mock.MagicMock()
        pl.active_window.return_value = {"class": "app", "title": "t"}
        pl.turn_screenshot.side_effect = lambda cfg, spec: shot_url()
        seen = {}

        def chat(messages, cfg, timeout=0):
            seen["m"] = messages
            return {"content": reply}
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
                mock.patch("wisp.docread.context_for", return_value=""), \
                mock.patch("wisp.brain.chat", chat), \
                mock.patch("wisp.brain.supports_vision", return_value=True):
            stage_capture.context_stage(ctx)
            answer = stage_speak.ask_chat(
                text, {}, image_b64=ctx.shot_b64,
                scribble_hint=ctx.scribble_hint)
        return seen["m"], answer

    @staticmethod
    def sent_image(messages):
        parts = messages[-1]["content"]
        urls = [p["image_url"]["url"] for p in parts
                if isinstance(p, dict) and p.get("type") == "image_url"]
        return decode(urls[0]) if urls else None

    @staticmethod
    def sent_hint_box(messages):
        """(x0, y0, x1, y1) the hint in the request names, or None."""
        m = re.search(r"around x (\d+)-(\d+), y (\d+)-(\d+)",
                      messages[0]["content"])
        if not m:
            return None
        x0, x1, y0, y1 = (int(g) for g in m.groups())
        return (x0, y0, x1, y1)


class CircleToAsk(Base):
    def test_the_image_sent_has_pink_inside_the_stroke_box(self):
        scribble.save(DOC)
        messages, _ = self.ask("what is this")
        img = self.sent_image(messages)
        self.assertIsNotNone(img, "no image in the request")
        x0, y0, x1, y1 = BOX
        pink = [(x, y) for x in range(x0 - 4, x1 + 5)
                for y in range(y0 - 4, y1 + 5)
                if img.getpixel((x, y)) == PINK]
        self.assertGreater(len(pink), 100)
        # each drawn vertex is pink, scaled from overlay to shot pixels
        for sx, sy in DOC["strokes"][0][:-1]:
            self.assertEqual(img.getpixel((sx * 2, sy * 2)), PINK)
        # the circled button itself is not painted over
        self.assertEqual(img.getpixel(BUTTON), BUTTON_RGB)

    def test_the_hint_box_matches_the_stroke(self):
        scribble.save(DOC)
        messages, _ = self.ask("what is this")
        self.assertEqual(self.sent_hint_box(messages), BOX)
        self.assertIn("circled or underlined", messages[0]["content"])

    def test_the_stroke_is_consumed_once(self):
        scribble.save(DOC)
        first, _ = self.ask("what is this")
        self.assertIsNotNone(self.sent_hint_box(first))
        self.assertFalse(scribble.path().exists())
        second, _ = self.ask("and this")
        self.assertIsNone(self.sent_hint_box(second))
        self.assertNotIn("The user drew", second[0]["content"])
        self.assertFalse(has_pink(self.sent_image(second)))

    def test_a_stale_stroke_is_ignored(self):
        scribble.save(DOC, now=scribble.time.time() - scribble.MAX_AGE_S - 5)
        messages, _ = self.ask("what is this")
        self.assertIsNone(self.sent_hint_box(messages))
        self.assertNotIn("The user drew", messages[0]["content"])
        self.assertFalse(has_pink(self.sent_image(messages)))
        self.assertFalse(scribble.path().exists())

    def test_the_answers_point_is_inside_the_circled_box(self):
        scribble.save(DOC)
        messages, answer = self.ask("what is this")
        _, pts = points.extract(answer)
        self.assertEqual(len(pts), 1)
        x0, y0, x1, y1 = self.sent_hint_box(messages)
        self.assertTrue(x0 <= pts[0]["x"] <= x1 and y0 <= pts[0]["y"] <= y1,
                        pts[0])


if __name__ == "__main__":
    unittest.main()
