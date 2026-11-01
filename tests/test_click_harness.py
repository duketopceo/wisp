"""Deterministic click harness: the real capture path (stage_capture ->
`_normalize_shot` -> grounding) on the real two-monitor layout, with a
fake model that answers exactly right for whatever image it is handed.
Zero math error expected: every miss here is a mapping bug, never model
error. Offline: no grim, no compositor, no network.

Layout (Luke's desk): eDP-1 3456x2160 @ scale 2 at logical (0,0), DP-3
3440x1440 @ scale 1 at logical (1728,0). grim composites every output at
the highest scale (2), so the raw canvas is 10336x2880.
"""
import io
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import config, grounding as g, points, stage_capture  # noqa: E402
from wisp import verify  # noqa: E402

try:
    from PIL import Image  # noqa: E402
except ImportError:
    Image = None

_need_pil = unittest.skipUnless(Image, "PIL not installed")
_need_magick = unittest.skipUnless(shutil.which("magick"),
                                   "magick not installed")

EDP = {"name": "eDP-1", "x": 0, "y": 0, "width": 3456, "height": 2160,
       "scale": 2.0}
DP3 = {"name": "DP-3", "x": 1728, "y": 0, "width": 3440, "height": 1440,
       "scale": 1.0}
LAYOUT = [EDP, DP3]


def _png_file(path, w, h):
    """A flat PNG of the given size (cheap to write, cheap to resize)."""
    Image.new("RGB", (w, h), (30, 30, 30)).save(path, format="PNG")


def png_size(path) -> tuple:
    head = pathlib.Path(path).read_bytes()[:24]
    return struct.unpack(">II", head[16:24])


def raw_canvas_size(mons) -> tuple:
    """What grim writes for the whole layout: the logical bbox at the
    highest output scale."""
    smax = max(float(m.get("scale", 1) or 1) for m in mons)
    _, _, w, h = points.logical_bbox(mons)
    return round(w * smax), round(h * smax)


class Oracle:
    """A model that is exactly right for the image it sees. `region` is
    the logical rect (x, y, w, h) that image shows, uniformly scaled to
    the image size, so the answer is the target's pixel in that image."""

    def __init__(self, target_logical, region, source="vlm"):
        self.target = target_logical
        self.region = region
        self.source = source
        self.seen = []

    def __call__(self, ctx):
        rx, ry, rw, rh = self.region
        w, h = ctx.shot.width, ctx.shot.height
        self.seen.append((w, h))
        px = (self.target[0] - rx) * w / rw
        py = (self.target[1] - ry) * h / rh
        return g.Candidate(px, py, 0.9, self.source, size=(w, h))


class Harness(unittest.TestCase):
    """Run the REAL capture_screen (grim command swapped for a copy of a
    synthetic raw canvas) so `_normalize_shot` rewrites the image
    exactly as in production, then ground through the real chain."""

    mons = LAYOUT

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._saved_origin = points.SHOT_ORIGIN
        self.addCleanup(setattr, points, "SHOT_ORIGIN", self._saved_origin)

    def patched(self, mons=None):
        mons = self.mons if mons is None else mons
        w, h = raw_canvas_size(mons)
        src = self.tmp / "grim-raw.png"
        _png_file(src, w, h)

        def cmd(out, output=None):
            return ["cp", str(src), str(out)]

        stack = [
            mock.patch("wisp.cua_safety.capture_blocked", return_value=""),
            mock.patch("wisp.platform.screenshot_cmd", side_effect=cmd),
            mock.patch("wisp.platform.monitors", return_value=mons),
            mock.patch("wisp.redact.apply", return_value=None),
            mock.patch("wisp.config.load_config", return_value={}),
            mock.patch.object(config, "RUN_DIR", self.tmp / "run"),
        ]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def ground(self, target_logical, mons=None, providers=None,
               region=None, capture=None):
        mons = self.mons if mons is None else mons
        region = region or points.logical_bbox(mons)
        oracle = Oracle(target_logical, region)
        t = g.ground_target(
            "the thing", {"ground": {"providers": "vlm"}},
            capture=capture or g._default_capture, monitors=mons,
            providers=providers or {"vlm": {"fn": oracle, "fast": True}},
            cua=object())
        return t, oracle

    def assertLands(self, target, got, tol=1):
        self.assertLessEqual(abs(got.x - target[0]), tol, (target, got))
        self.assertLessEqual(abs(got.y - target[1]), tol, (target, got))


@_need_pil
@_need_magick
class NormalizedShot(Harness):
    """stage_capture normalized the shot to logical size: image pixels ==
    logical coords minus the shot origin."""

    def test_shot_really_is_normalized(self):
        self.patched()
        out = stage_capture.capture_screen()
        self.assertEqual(png_size(out), (5168, 1440))

    def test_edp_centre_maps_to_edp_logical_centre(self):
        self.patched()
        t, _ = self.ground((864, 540))
        self.assertLands((864, 540), t)

    def test_dp3_point_maps_to_logical_x_1828(self):
        self.patched()
        t, _ = self.ground((1728 + 100, 50))
        self.assertLands((1828, 50), t)

    def test_candidate_size_smaller_than_shot_rescales_first(self):
        self.patched()
        seen = {}

        def half_res(ctx):
            w, h = ctx.shot.width, ctx.shot.height
            tw, th = w // 2, h // 2           # the model saw a half image
            seen["size"] = (tw, th)
            return g.Candidate((1828 - 0) * tw / 5168, 50 * th / 1440,
                               0.9, "vlm", size=(tw, th))

        t, _ = self.ground(None, providers={"vlm": {"fn": half_res,
                                                     "fast": True}})
        self.assertLands((1828, 50), t, tol=2)

    def test_negative_origin_layout_keeps_origin_offset(self):
        left = {"name": "L", "x": -1920, "y": 0, "width": 1920,
                "height": 1080, "scale": 1.0}
        main = {"name": "M", "x": 0, "y": 0, "width": 1920,
                "height": 1080, "scale": 1.0}
        mons = [left, main]
        self.patched(mons)
        t, _ = self.ground((-1910, 10), mons=mons)
        self.assertLands((-1910, 10), t)


@_need_pil
class RawShot(Harness):
    """No magick: the shot is the raw grim canvas (max-scale, whole
    layout) and keeps the uniform scale path."""

    def _raw(self, mons=None):
        mons = self.mons if mons is None else mons
        w, h = raw_canvas_size(mons)
        buf = io.BytesIO()
        Image.new("RGB", (w // 8, h // 8)).save(buf, format="PNG")
        s = g.Shot(g.base64.b64encode(buf.getvalue()).decode(), w, h)
        return lambda: s

    def test_raw_max_scale_canvas_uses_uniform_scale(self):
        t, _ = self.ground((1828, 50), region=points.logical_bbox(LAYOUT),
                           capture=self._raw())
        self.assertLands((1828, 50), t)
        t, _ = self.ground((864, 540), capture=self._raw())
        self.assertLands((864, 540), t)


class OneCanvasModel(unittest.TestCase):
    """U2: grounding.convert, points.to_logical and verify._frame_rect
    all read grim's raw canvas the same way."""

    # (name, logical point, raw canvas pixel under the uniform model)
    CASES = [("eDP-1", (864, 540), (1728, 1080)),
             ("DP-3", (1828, 50), (3656, 100)),
             ("DP-3 far edge", (5000, 1400), (10000, 2800))]

    def test_three_callers_agree_on_both_monitors(self):
        for name, logical, px in self.CASES:
            with self.subTest(name):
                c = g.convert(*px, "shot", LAYOUT)
                t = points.to_logical([{"x": px[0], "y": px[1]}], LAYOUT)[0]
                self.assertEqual(c, logical)
                self.assertEqual((t["x"], t["y"]), logical)
                # a 10x10 logical rect centred there lands on the same px
                box = verify._frame_rect(
                    (logical[0] - 5, logical[1] - 5, 10, 10), LAYOUT)
                self.assertEqual((box[0] + box[2] // 2,
                                  box[1] + box[3] // 2), px)
                self.assertEqual(box[2:], [20, 20])

    def test_dead_space_maps_off_screen_and_is_rejected(self):
        # below eDP-1 (1080 logical tall), left of DP-3 (x < 1728)
        px = (200, 2700)
        lx, ly = g.convert(*px, "shot", LAYOUT)
        self.assertEqual((lx, ly), (100, 1350))
        self.assertFalse(points.on_screen(lx, ly, LAYOUT))
        self.assertTrue(points.on_screen(1828, 50, LAYOUT))

    def test_single_monitor_scale_1_is_unchanged(self):
        mons = [{"name": "H", "x": 0, "y": 0, "width": 1920,
                 "height": 1080, "scale": 1.0}]
        self.assertEqual(g.convert(700, 300, "shot", mons), (700, 300))
        t = points.to_logical([{"x": 700, "y": 300}], mons)[0]
        self.assertEqual((t["x"], t["y"]), (700, 300))
        self.assertEqual(verify._frame_rect((10, 20, 30, 40), mons),
                         [10, 20, 30, 40])

    def test_round_trip(self):
        for lx, ly in ((0, 0), (1728, 0), (4000, 1000), (-3, 7)):
            px = points.logical_to_raw_canvas(lx, ly, LAYOUT)
            back = points.raw_canvas_to_logical(*px, LAYOUT)
            self.assertAlmostEqual(back[0], lx)
            self.assertAlmostEqual(back[1], ly)

    @unittest.skipUnless(shutil.which("grim")
                         and __import__("os").environ.get("WISP_LIVE_GRIM"),
                         "needs grim, a compositor and WISP_LIVE_GRIM=1")
    def test_real_grim_capture_size_matches_the_model(self):
        import subprocess
        mons = points.monitors()
        out = pathlib.Path(tempfile.mkdtemp()) / "g.png"
        subprocess.run(["grim", str(out)], check=True, timeout=20)
        self.assertEqual(png_size(out), raw_canvas_size(mons))


if __name__ == "__main__":
    unittest.main()
