"""B28: a blank or protected capture is detected, retried, read as text,
and said out loud; wisp never answers about a screen it did not see."""
import contextlib
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import blank, pipeline, platform, stage_capture, stage_ctx  # noqa: E402

W, H = 320, 200
DARK = (26, 27, 38)           # a real dark theme background


def png(rows) -> bytes:
    """An RGB PNG from rows of (r, g, b) tuples."""
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px)
                   for row in rows)

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def canvas(bg):
    return [[bg] * W for _ in range(H)]


def rect(rows, x, y, w, h, c):
    for j in range(y, y + h):
        for i in range(x, x + w):
            rows[j][i] = c


def text_lines(rows, y0, n, fg=(200, 205, 220), x0=20):
    """Rows of glyph-like blocks with anti-aliased edges."""
    for k in range(n):
        y = y0 + k * 14
        x = x0
        for g in range(30 + (k * 7) % 20):
            if (g * 7 + k) % 5 == 0:
                x += 6
                continue
            rect(rows, x, y, 4, 9, fg)
            rect(rows, x + 4, y, 1, 9, tuple(v // 2 + 13 for v in fg))
            x += 6


def black():
    return canvas((0, 0, 0))


def black_with_cursor():
    r = black()
    rect(r, 150, 90, 7, 11, (255, 255, 255))
    return r


def dark_ui():
    r = canvas(DARK)
    rect(r, 0, 0, W, 14, (36, 40, 59))            # bar
    rect(r, 0, 14, 70, H - 14, (31, 35, 53))      # sidebar
    text_lines(r, 24, 11)
    rect(r, 90, 170, 200, 18, (65, 72, 104))      # input box
    return r


def dark_terminal_with_prompt():
    r = canvas(DARK)
    text_lines(r, 6, 1)
    return r


class Files(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def save(self, rows, name="s.png"):
        p = self.d / name
        p.write_bytes(png(rows))
        return p


class Verdict(Files):
    def test_black_frame_is_blank(self):
        self.assertEqual(blank.blank_reason(self.save(black())), "black")

    def test_black_with_a_mouse_cursor_is_still_blank(self):
        self.assertEqual(
            blank.blank_reason(self.save(black_with_cursor())), "black")

    def test_single_colour_frames_are_blank(self):
        self.assertEqual(blank.blank_reason(
            self.save(canvas((255, 255, 255)))), "white")
        self.assertEqual(blank.blank_reason(
            self.save(canvas((90, 90, 90)))), "a single colour")

    def test_a_real_dark_ui_is_not_flagged(self):
        self.assertEqual(blank.blank_reason(self.save(dark_ui())), "")

    def test_a_dark_terminal_with_one_prompt_line_is_not_flagged(self):
        self.assertEqual(
            blank.blank_reason(self.save(dark_terminal_with_prompt())), "")

    def test_an_unreadable_or_missing_frame_is_not_flagged(self):
        junk = self.d / "junk.png"
        junk.write_bytes(b"not a png")
        for p in (junk, self.d / "missing.png", None):
            self.assertEqual(blank.blank_reason(p), "")
        self.assertEqual(blank.verdict(None), "")
        self.assertEqual(blank.verdict({}), "")

    def test_the_pure_python_reader_agrees_with_the_verdicts(self):
        for rows, want in ((black(), "black"), (dark_ui(), ""),
                           (canvas((255, 255, 255)), "white")):
            p = self.save(rows)
            self.assertEqual(blank.verdict(blank._png_levels(p)), want)

    @unittest.skipUnless(shutil.which("magick"), "no ImageMagick")
    def test_magick_agrees_with_the_pure_python_reader(self):
        for rows in (black(), black_with_cursor(), dark_ui(),
                     dark_terminal_with_prompt()):
            p = self.save(rows)
            self.assertEqual(blank.verdict(blank._magick_levels(p)),
                             blank.verdict(blank._png_levels(p)))

    def test_filtered_png_rows_decode(self):
        """A PNG with Sub/Up/Paeth rows (what real encoders write)."""
        w, h = 16, 4
        rows = [bytes([(x * 9 + y * 31) & 255 for x in range(w)])
                for y in range(h)]
        raw = bytearray()
        prev = bytes(w)
        for y, row in enumerate(rows):
            f = (1, 2, 4, 3)[y]
            raw.append(f)
            for i, v in enumerate(row):
                a = row[i - 1] if i else 0
                b = prev[i]
                c = prev[i - 1] if i else 0
                if f == 1:
                    pred = a
                elif f == 2:
                    pred = b
                elif f == 3:
                    pred = (a + b) >> 1
                else:
                    pred = blank._paeth(a, b, c)
                raw.append((v - pred) & 255)
            prev = row

        def chunk(kind, body):
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body)))
        data = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw)))
                + chunk(b"IEND", b""))
        p = self.d / "g.png"
        p.write_bytes(data)
        want = {}
        for row in rows:
            for v in row:
                want[v] = want.get(v, 0) + 1
        self.assertEqual(blank._png_levels(p), want)


class Vet(Files):
    def test_a_frame_with_content_is_used_and_nothing_is_retried(self):
        p = self.save(dark_ui())
        retry = mock.Mock()
        self.assertEqual(blank.vet(p, retry), p)
        retry.assert_not_called()

    def test_nothing_captured_stays_nothing(self):
        self.assertIsNone(blank.vet(None, mock.Mock()))

    def test_black_frame_retries_once_then_gives_up_blind(self):
        p = self.save(black())
        again = self.save(black(), "w.png")
        retry = mock.Mock(return_value=again)
        events = []
        got = blank.vet(p, retry, trace=lambda e, f: events.append(e))
        retry.assert_called_once_with()
        self.assertIsInstance(got, blank.Blind)
        self.assertFalse(got)
        self.assertEqual(got.reason, "black")
        self.assertTrue(got.retried)
        self.assertFalse(p.exists() or again.exists())   # no blank left behind
        self.assertEqual(events, ["screen_blank"])

    def test_the_window_retry_can_recover(self):
        p = self.save(black())
        good = self.save(dark_ui(), "w.png")
        events = []
        got = blank.vet(p, lambda: good, trace=lambda e, f: events.append(e))
        self.assertEqual(got, good)
        self.assertEqual(events, ["screen_blank", "screen_blank_recovered"])

    def test_a_failing_or_missing_retry_is_blind_not_a_crash(self):
        for retry in (None, lambda: None, mock.Mock(side_effect=OSError)):
            got = blank.vet(self.save(black()), retry)
            self.assertIsInstance(got, blank.Blind)
        self.assertFalse(blank.vet(self.save(black()), lambda: None).retried)


class WindowText(unittest.TestCase):
    class Client:
        def __init__(self, tree, wins=None):
            self.tree = tree
            self.calls = []
            self.wins = wins if wins is not None else [
                {"window_id": 7, "pid": 42, "class": "foot", "title": "t"}]

        def call(self, tool, args, timeout=None, session=None, **kw):
            self.calls.append((tool, args))
            if tool == "list_windows":
                return {"windows": self.wins}
            return self.tree

    WIN = {"class": "foot", "title": "t"}

    def test_reads_names_and_values_once_and_asks_for_the_tree(self):
        tree = {"tree": {"name": "Terminal", "children": [
            {"name": "Account balance", "value": "1,204.10"},
            {"name": "Account balance", "children": [
                {"label": "Pay now"}]}]}}
        c = self.Client(tree)
        text = blank.window_text(self.WIN, c)
        self.assertEqual(text.splitlines(), [
            "Terminal", "Account balance", "1,204.10", "Pay now"])
        tool, args = c.calls[-1]
        self.assertEqual(tool, "get_window_state")
        self.assertTrue(args["include_accessibility_tree"])
        self.assertFalse(args["include_screenshot"])
        self.assertEqual(args["window_id"], 7)

    def test_nothing_to_read_is_empty(self):
        self.assertEqual(blank.window_text(None, self.Client({})), "")
        self.assertEqual(blank.window_text(self.WIN, self.Client({})), "")
        self.assertEqual(blank.window_text(
            self.WIN, self.Client({}, wins=[])), "")

        class Broken:
            def call(self, *a, **k):
                raise RuntimeError("driver down")
        self.assertEqual(blank.window_text(self.WIN, Broken()), "")

    def test_the_text_is_capped(self):
        tree = {"tree": [{"name": f"line number {i} " + "x" * 40}
                         for i in range(300)]}
        self.assertLessEqual(
            len(blank.window_text(self.WIN, self.Client(tree))),
            blank.TEXT_CAP)


class Platform(unittest.TestCase):
    def test_window_cmd_crops_to_the_rectangle(self):
        with mock.patch.object(platform, "_which",
                               lambda b: b == "grim"), \
                mock.patch.object(platform, "desktop",
                                  return_value="hyprland"):
            cmd = platform.window_screenshot_cmd(
                pathlib.Path("/tmp/o.png"), (10, 20, 300, 200))
        self.assertEqual(cmd, ["grim", "-g", "10,20 300x200", "/tmp/o.png"])

    def test_no_geometry_or_a_tiny_one_means_no_retry(self):
        for g in (None, (), (0, 0, 2, 2)):
            self.assertIsNone(platform.window_screenshot_cmd(
                pathlib.Path("/tmp/o.png"), g))

    def test_active_geometry_reads_the_compositor(self):
        with mock.patch.object(platform.hypr, "query", return_value={
                "at": [5, 6], "size": [700, 400]}):
            self.assertEqual(platform.active_geometry(), (5, 6, 700, 400))
        with mock.patch.object(platform.hypr, "query", return_value={}):
            self.assertIsNone(platform.active_geometry())

    def test_capture_screen_window_uses_the_window_command(self):
        run = mock.Mock(return_value=mock.Mock(returncode=0))
        with mock.patch("wisp.cua_safety.capture_blocked", return_value=""), \
                mock.patch.object(platform, "active_geometry",
                                  return_value=(1, 2, 300, 200)), \
                mock.patch.object(platform, "window_screenshot_cmd",
                                  return_value=["grim", "-g", "x"]) as wc, \
                mock.patch.object(platform, "screenshot_cmd") as full, \
                mock.patch.object(stage_capture._cancel, "run", run), \
                mock.patch("wisp.config.RUN_DIR", pathlib.Path(
                    tempfile.mkdtemp())):
            self.assertIsNone(stage_capture.capture_screen(window=True))
        wc.assert_called_once()
        full.assert_not_called()


class Vetted(Files):
    def pl(self, first, again=None):
        pl = mock.MagicMock()
        pl.capture_screen.side_effect = (
            lambda window=False: again if window else first)
        return pl

    def run_vetted(self, pl):
        with mock.patch.object(stage_capture, "_pl", lambda: pl), \
                mock.patch.object(stage_capture, "_png_b64",
                                  lambda p: "data:image/png;base64,OK"):
            return stage_capture._vetted_b64()

    def test_a_dark_theme_frame_goes_to_the_model_untouched(self):
        pl = self.pl(self.save(dark_ui()))
        self.assertEqual(self.run_vetted(pl), "data:image/png;base64,OK")
        pl.capture_screen.assert_called_once_with()

    def test_a_black_frame_triggers_the_window_retry(self):
        pl = self.pl(self.save(black()), self.save(dark_ui(), "w.png"))
        self.assertEqual(self.run_vetted(pl), "data:image/png;base64,OK")
        self.assertEqual([c.kwargs for c in pl.capture_screen.call_args_list],
                         [{}, {"window": True}])

    def test_black_then_black_is_blind(self):
        pl = self.pl(self.save(black()), self.save(black(), "w.png"))
        got = self.run_vetted(pl)
        self.assertIsInstance(got, blank.Blind)

    def test_a_refused_capture_stays_none(self):
        self.assertIsNone(self.run_vetted(self.pl(None)))

    def test_a_blind_result_survives_the_speculative_slot(self):
        from wisp import context
        spec = context.Speculative({"screenshot": lambda: blank.Blind(
            "black")})
        spec.start()
        got = spec.take("screenshot", wait=2.0)
        self.assertIsInstance(got, blank.Blind)
        with mock.patch.object(stage_capture, "_vetted_b64") as again:
            self.assertIsInstance(stage_capture.turn_screenshot(
                {"agent": {"screenshots": "true"}}, _Held(got)),
                blank.Blind)
        again.assert_not_called()


class _Held:
    def __init__(self, v):
        self.v = v

    def take(self, *a, **k):
        return self.v


class InTheTurn(unittest.TestCase):
    def ctx(self):
        sp = mock.MagicMock()
        sp.timed.side_effect = lambda *_a, **_k: contextlib.nullcontext()
        c = stage_ctx.TurnCtx({"agent": {"screenshots": "true"},
                               "voice": {"enabled": "true"}},
                              mock.MagicMock(), None, None, None, sp,
                              "t1", None, None, 1.0, "m")
        c.text = "what does this say"
        return c

    def run_stage(self, c, shot, window_text):
        pl = mock.MagicMock()
        pl.active_window.return_value = {"class": "foot", "title": "t"}
        pl.turn_screenshot.side_effect = lambda cfg, spec: shot
        with mock.patch.object(stage_capture, "_pl", lambda: pl), \
                mock.patch.object(blank, "window_text",
                                  return_value=window_text), \
                mock.patch("wisp.speech.speak") as speak, \
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
            ok = stage_capture.context_stage(c)
        return ok, pl, speak

    def test_blind_with_window_text_says_why_and_reads_the_text(self):
        c = self.ctx()
        ok, pl, speak = self.run_stage(c, blank.Blind("black", True),
                                       "Invoice 1042\nTotal 99.00")
        self.assertTrue(ok)
        speak.assert_called_once()
        self.assertEqual(speak.call_args.args[0], blank.LINE_READING)
        self.assertIn("blocks screenshots", blank.LINE_READING)
        self.assertIsNone(c.shot_b64)
        self.assertIn("You cannot see it", c.context)
        self.assertIn("Invoice 1042", c.context)
        self.assertIn("came out black", c.context)

    def test_blind_with_nothing_to_read_ends_the_turn_honestly(self):
        c = self.ctx()
        ok, pl, speak = self.run_stage(c, blank.Blind("black", True), "")
        self.assertFalse(ok)
        self.assertEqual(speak.call_args.args[0], blank.LINE_BLIND)
        self.assertEqual(blank.LINE_BLIND, "I can't see that window.")
        states = [call.args[0] for call in c.state.transition.call_args_list]
        self.assertEqual(states[-1], "done")
        self.assertEqual(c.state.transition.call_args.kwargs["result"],
                         blank.LINE_BLIND)

    def test_a_normal_shot_is_untouched_and_nothing_is_said(self):
        c = self.ctx()
        ok, pl, speak = self.run_stage(c, "data:image/png;base64,AAAA", "x")
        self.assertTrue(ok)
        speak.assert_not_called()
        self.assertEqual(c.shot_b64, "data:image/png;base64,AAAA")
        self.assertNotIn("[screen]", c.context)

    def test_the_pipeline_makes_no_model_call_when_the_turn_ends_blind(self):
        route = mock.Mock()
        execute = mock.Mock()
        with mock.patch.object(pipeline, "capture_stage", lambda c: True), \
                mock.patch.object(pipeline, "context_stage",
                                  lambda c: False), \
                mock.patch.object(pipeline, "route_stage", route), \
                mock.patch.object(pipeline, "execute_stage", execute):
            token = mock.MagicMock()
            rc = pipeline._listen_turn({"audio": {}, "agent": {}},
                                       mock.MagicMock(), None, None, None,
                                       None, "t1", token)
        self.assertEqual(rc, 0)
        route.assert_not_called()
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
