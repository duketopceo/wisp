#!/usr/bin/env python3
"""Ember snapshot harness (W20, Ember U5): scripts/ui/snap.py.

Pure parts (tolerance compare, case matrix, tolerance table, fixtures)
always run. The render tests need qmltestrunner and PIL and are skipped
without them. The harness never opens a Wayland or X window: the render
environment forces Qt's offscreen platform whatever the parent has set.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "ui"))

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

import snap  # noqa: E402

needs_render = unittest.skipUnless(
    snap.find_runner() and Image, "qmltestrunner or PIL missing")


def solid(size, rgb):
    return Image.new("RGB", size, rgb)


@unittest.skipUnless(Image, "PIL missing")
class TestCompare(unittest.TestCase):
    TOL = snap.Tolerance(channel=6, fraction=0.01)

    def test_identical(self):
        r = snap.compare_images(solid((20, 20), (9, 9, 9)),
                                solid((20, 20), (9, 9, 9)), self.TOL)
        self.assertTrue(r.ok)
        self.assertEqual(r.bad_pixels, 0)

    def test_small_channel_drift_is_ignored(self):
        r = snap.compare_images(solid((20, 20), (9, 9, 9)),
                                solid((20, 20), (14, 9, 9)), self.TOL)
        self.assertTrue(r.ok)

    def test_few_bad_pixels_within_fraction(self):
        a, b = solid((20, 20), (0, 0, 0)), solid((20, 20), (0, 0, 0))
        for x in range(3):  # 3 / 400 = 0.75 %
            b.putpixel((x, 0), (255, 255, 255))
        r = snap.compare_images(a, b, self.TOL)
        self.assertTrue(r.ok)
        self.assertEqual(r.bad_pixels, 3)

    def test_too_many_bad_pixels_fail(self):
        a, b = solid((20, 20), (0, 0, 0)), solid((20, 20), (0, 0, 0))
        for x in range(10):
            b.putpixel((x, 0), (255, 255, 255))
        r = snap.compare_images(a, b, self.TOL)
        self.assertFalse(r.ok)
        self.assertIn("pixels", r.reason)

    def test_size_mismatch_fails(self):
        r = snap.compare_images(solid((20, 20), (0, 0, 0)),
                                solid((20, 21), (0, 0, 0)), self.TOL)
        self.assertFalse(r.ok)
        self.assertIn("size", r.reason)

    def test_alpha_is_compared(self):
        a = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        b = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        self.assertFalse(snap.compare_images(a, b, self.TOL).ok)


class TestToleranceTable(unittest.TestCase):
    def test_every_scene_component_resolves(self):
        for comp in snap.scenes():
            t = snap.tolerance_for(comp)
            self.assertGreaterEqual(t.channel, 0)
            self.assertGreater(t.fraction, 0)

    def test_tolerances_stay_tight(self):
        for name, t in snap.TOLERANCE.items():
            self.assertLessEqual(t.channel, 24, name)
            self.assertLessEqual(t.fraction, 0.03, name)
        self.assertLessEqual(snap.DEFAULT_TOLERANCE.fraction, 0.01)

    def test_table_names_are_real_components(self):
        for name in snap.TOLERANCE:
            self.assertIn(name, snap.scenes(), name)


class TestMatrix(unittest.TestCase):
    def test_state_fixtures_cover_every_status(self):
        have = {json.loads(p.read_text()).get("status", "offline")
                for p in snap.FIXTURES.glob("*.json")}
        want = {"idle", "listening", "transcribing", "deciding",
                "awaiting_choice", "acting", "speaking", "suggestion",
                "done", "error", "offline"}
        self.assertEqual(want - have, set())

    def test_edge_fixtures_exist(self):
        names = {p.stem for p in snap.FIXTURES.glob("*.json")}
        for n in ("offline", "stale", "long_answer", "blocked"):
            self.assertIn(n, names)

    def test_cases_cover_each_component_in_each_fixture(self):
        cases = snap.cases()
        ids = {c["id"] for c in cases}
        self.assertEqual(len(ids), len(cases), "case ids are unique")
        fixtures = {p.stem for p in snap.FIXTURES.glob("*.json")}
        for comp, scene in snap.scenes().items():
            for theme in snap.THEMES:
                if scene["mode"] == "state":
                    for fx in fixtures:
                        self.assertIn(
                            f"{theme}/1x/{comp}__{fx}", ids)
                else:
                    for var in scene["variants"]:
                        self.assertIn(
                            f"{theme}/1x/{comp}__{var}", ids)

    def test_scale_two_and_light_theme_present(self):
        ids = {c["id"] for c in snap.cases()}
        self.assertTrue(any("/2x/" in i for i in ids))
        self.assertEqual(set(snap.THEMES), {"dark", "light"})

    def test_goldens_match_cases_exactly(self):
        gold = {str(p.relative_to(snap.GOLDEN))[:-4]
                for p in snap.GOLDEN.rglob("*.png")}
        ids = {c["id"] for c in snap.cases()}
        self.assertEqual(ids - gold, set(), "missing golden (snap.py update)")
        self.assertEqual(gold - ids, set(), "orphan golden")


class TestEnvironment(unittest.TestCase):
    def test_render_env_is_offscreen_and_headless(self):
        env = snap.render_env(base={"WAYLAND_DISPLAY": "wayland-1",
                                    "DISPLAY": ":0",
                                    "QT_QPA_PLATFORM": "wayland",
                                    "XDG_SESSION_TYPE": "wayland"},
                              scale=2, fonts_conf="/x/fonts.conf")
        self.assertEqual(env["QT_QPA_PLATFORM"], "offscreen")
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertNotIn("DISPLAY", env)
        self.assertEqual(env["QT_QUICK_BACKEND"], "software")
        self.assertEqual(env["QT_SCALE_FACTOR"], "2")
        self.assertEqual(env["FONTCONFIG_FILE"], "/x/fonts.conf")
        self.assertEqual(env["TZ"], "UTC")

    def test_missing_runner_is_a_skip_not_a_failure(self):
        code = snap.main(["check"], runner=None)
        self.assertEqual(code, snap.EXIT_SKIPPED)

    def test_fonts_are_bundled(self):
        for f in ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf"):
            self.assertTrue((snap.FONTS / f).exists(), f)


@needs_render
class TestRender(unittest.TestCase):
    def test_render_never_uses_a_window_platform(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, WAYLAND_DISPLAY="wayland-9",
                       DISPLAY=":9", QT_QPA_PLATFORM="wayland")
            old = os.environ.copy()
            os.environ.update(env)
            try:
                out = snap.render(pathlib.Path(d), only="Mark__idle")
            finally:
                os.environ.clear()
                os.environ.update(old)
            self.assertTrue(out)

    def test_render_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, \
                tempfile.TemporaryDirectory() as b:
            ra = snap.render(pathlib.Path(a), only="Pill__")
            rb = snap.render(pathlib.Path(b), only="Pill__")
            self.assertTrue(ra)
            self.assertEqual(sorted(p.name for p in ra),
                             sorted(p.name for p in rb))
            for pa in ra:
                pb = pathlib.Path(b) / pa.relative_to(a)
                self.assertEqual(pa.read_bytes(), pb.read_bytes(),
                                 pa.name)

    def test_outputs_are_non_empty_pngs(self):
        with tempfile.TemporaryDirectory() as d:
            for p in snap.render(pathlib.Path(d), only="Mark__"):
                im = Image.open(p)
                self.assertGreater(im.width, 4)
                self.assertGreater(im.height, 4)
                self.assertGreater(len(im.convert("RGB").getcolors(1 << 20)), 1,
                                   f"{p.name} is blank")

    def test_all_fixtures_match_goldens_within_tolerance(self):
        with tempfile.TemporaryDirectory() as d:
            report = snap.check(pathlib.Path(d))
        self.assertEqual(report.failures, [], "\n".join(
            f"{f.id}: {f.reason}" for f in report.failures))
        self.assertEqual(report.missing, [])
        self.assertGreater(report.total, 300)

    def test_a_changed_render_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            made = snap.render(out, only="Chip__normal")
            self.assertTrue(made)
            im = Image.open(made[0]).convert("RGB")
            for x in range(im.width):
                for y in range(im.height):
                    im.putpixel((x, y), (255, 0, 255))
            im.save(made[0])
            report = snap.compare_dir(out, only="Chip__normal")
            self.assertTrue(report.failures)


class TestCheckCleanup(unittest.TestCase):
    """check() with no out_dir must not leave /tmp/wisp-snap-* behind when
    everything matched."""

    def test_temp_dir_removed_on_success_and_error(self):
        from unittest import mock
        seen = []

        def fake_render(d, only=None, runner=None):
            seen.append(pathlib.Path(d))
            return []

        ok = snap.Report()
        with mock.patch.object(snap, "render", fake_render), \
                mock.patch.object(snap, "compare_dir", lambda *a, **k: ok):
            rep = snap.check()
        self.assertTrue(rep.ok)
        self.assertFalse(seen[0].exists())
        with mock.patch.object(snap, "render",
                               side_effect=RuntimeError("x")) as r:
            r.side_effect = lambda d, **k: (seen.append(pathlib.Path(d)),
                                            (_ for _ in ()).throw(
                                                RuntimeError("x")))
            with self.assertRaises(RuntimeError):
                snap.check()
        self.assertFalse(seen[-1].exists())

    def test_failing_run_keeps_its_renders(self):
        from unittest import mock
        bad = snap.Report(failures=[snap.Failure("a", "b")])
        with mock.patch.object(snap, "render", lambda d, **k: []), \
                mock.patch.object(snap, "compare_dir", lambda *a, **k: bad):
            rep = snap.check()
        try:
            self.assertTrue(rep.kept and rep.kept.exists())
        finally:
            shutil.rmtree(rep.kept, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
