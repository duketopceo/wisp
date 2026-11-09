"""U4: the companion follows the monitor that holds the focused window.

The screenshot stays one whole-canvas image; the focused window's monitor
is only the default target for a point with no `:screenN` label."""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import platform, points  # noqa: E402

# screen1: logical 0,0 1728x1080 (scale 2); screen2: logical 1728,0 3440x1440
MONS = [
    {"id": 0, "x": 0, "y": 0, "width": 3456, "height": 2160, "scale": 2},
    {"id": 1, "x": 1728, "y": 0, "width": 3440, "height": 1440, "scale": 1},
]
ONE = MONS[:1]


def win(at, size, monitor=None):
    return {"class": "term", "title": "t", "at": list(at),
            "size": list(size), "monitor": monitor}


def query_for(window, mons):
    def q(name, timeout=None):
        return window if name == "activewindow" else mons
    return q


class FocusedMonitor(unittest.TestCase):
    def active(self, window, mons=MONS):
        with mock.patch.object(platform.hypr, "query",
                               side_effect=query_for(window, mons)):
            return platform.active_window(), platform.active_geometry()

    def test_window_on_the_second_monitor(self):
        aw, geo = self.active(win((2000, 100), (800, 600), 1))
        self.assertEqual(aw["monitor"], 2)
        self.assertEqual(geo, (2000, 100, 800, 600))
        self.assertEqual(geo.monitor, 2)

    def test_window_on_the_first_monitor(self):
        aw, geo = self.active(win((10, 10), (400, 300), 0))
        self.assertEqual(aw["monitor"], 1)
        self.assertEqual(geo.monitor, 1)

    def test_spanning_window_uses_the_monitor_holding_its_center(self):
        # x 1000..2400: center 1700 is on screen1 (ends at 1728)
        aw, geo = self.active(win((1000, 100), (1400, 300), 1))
        self.assertEqual(geo.monitor, 1)
        self.assertEqual(aw["monitor"], 1)
        # x 1500..2900: center 2200 is on screen2
        aw, geo = self.active(win((1500, 100), (1400, 300), 0))
        self.assertEqual(geo.monitor, 2)
        self.assertEqual(aw["monitor"], 2)

    def test_single_monitor_is_unchanged(self):
        aw, geo = self.active(win((5, 6), (700, 400), 0), ONE)
        self.assertEqual(geo, (5, 6, 700, 400))
        self.assertEqual(aw["class"], "term")
        self.assertEqual(aw["title"], "t")

    def test_no_layout_means_no_monitor_not_an_error(self):
        aw, geo = self.active(win((5, 6), (700, 400), 0), {})
        self.assertIsNone(aw["monitor"])
        self.assertEqual(geo, (5, 6, 700, 400))
        self.assertIsNone(geo.monitor)


class UnlabelledPoints(unittest.TestCase):
    def conv(self, raw, mons, focus, fn="to_logical"):
        with mock.patch.object(platform, "active_window",
                               return_value={"monitor": focus}):
            return getattr(points, fn)(raw, mons)

    def test_unlabelled_point_targets_the_focused_monitor(self):
        out = self.conv([{"x": 3656, "y": 100, "label": "a"}], MONS, 2)
        self.assertEqual(out[0]["screen"], 2)

    def test_explicit_label_wins(self):
        _, raw = points.extract("go [POINT:10,20:save:screen1]")
        self.assertEqual(raw[0]["screen"], 1)
        out = self.conv(raw, MONS, 2)
        self.assertEqual(out[0]["screen"], 1)
        out = self.conv(raw, MONS, 2, "canvas_to_logical")
        self.assertEqual(out[0]["screen"], 1)

    def test_coordinates_stay_on_the_shared_canvas(self):
        # canvas px 3656 with max scale 2 -> logical 1828 (inside screen2),
        # nothing re-based by the focused monitor
        out = self.conv([{"x": 3656, "y": 100, "label": ""}], MONS, 1)
        self.assertEqual((out[0]["x"], out[0]["y"]), (1828, 50))

    def test_scaled_monitors_convert_on_the_shared_canvas(self):
        out = self.conv([{"x": 100, "y": 100, "label": ""}], MONS, 1)
        self.assertEqual((out[0]["x"], out[0]["y"]), (50, 50))
        self.assertTrue(points.on_screen(out[0]["x"], out[0]["y"], MONS))

    def test_single_monitor_adds_nothing(self):
        out = self.conv([{"x": 100, "y": 100, "label": ""}], ONE, 1)
        self.assertNotIn("screen", out[0])

    def test_unknown_focus_adds_nothing(self):
        out = self.conv([{"x": 100, "y": 100, "label": ""}], MONS, None)
        self.assertNotIn("screen", out[0])

    def test_a_failing_lookup_adds_nothing(self):
        with mock.patch.object(platform, "active_window",
                               side_effect=RuntimeError("boom")):
            out = points.to_logical([{"x": 1, "y": 1, "label": ""}], MONS)
        self.assertNotIn("screen", out[0])

    def test_canvas_path_also_defaults_to_focus(self):
        out = self.conv([{"x": 10, "y": 10, "label": ""}], MONS, 2,
                        "canvas_to_logical")
        self.assertEqual(out[0]["screen"], 2)


if __name__ == "__main__":
    unittest.main()
