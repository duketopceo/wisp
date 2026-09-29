"""Tests for wisp/points.py — tag extraction + screenshot→logical mapping."""
import sys
import unittest

sys.path.insert(0, ".")
from wisp import points  # noqa: E402


class Extract(unittest.TestCase):
    def test_single_point(self):
        clean, pts = points.extract(
            "Click the button [POINT:100,200:OK button] now.")
        assert pts == [{"x": 100, "y": 200, "label": "OK button"}]
        assert "POINT" not in clean
        assert "Click the button" in clean

    def test_no_label(self):
        _, pts = points.extract("[POINT:5,6]")
        assert pts == [{"x": 5, "y": 6, "label": ""}]

    def test_points_list(self):
        _, pts = points.extract(
            'Steps: [POINTS:[{"x":1,"y":2,"label":"a"},'
            '{"x":3,"y":4,"label":"b"}]]')
        assert len(pts) == 2
        assert pts[1]["label"] == "b"

    def test_malformed_points_list_kept_visible(self):
        # no "]]" terminator → treated as unclosed, stays in the text
        clean, pts = points.extract("text [POINTS:not-json] more")
        assert pts == []
        assert "POINTS" in clean

    def test_string_coords_dont_crash(self):
        _, pts = points.extract('[POINTS:[{"x":"abc","y":1}]]')
        assert pts == []

    def test_whitespace_after_colon(self):
        _, pts = points.extract('[POINTS: [{"x":1,"y":2}]]')
        assert len(pts) == 1

    def test_unclosed_tag_kept_in_text(self):
        clean, pts = points.extract("do things [POINT:100,200")
        assert "POINT" in clean and pts == []

    def test_bracket_in_label(self):
        clean, pts = points.extract(
            'x [POINTS:[{"x":1,"y":2,"label":"a]b"}]] y')
        assert pts[0]["label"] == "a]b"
        assert clean == "x  y"

    def test_pointer_word_not_a_tag(self):
        clean, pts = points.extract("press [POINTER] here")
        assert "POINTER" in clean and pts == []

    def test_point_cap(self):
        tags = "".join(f"[POINT:{i},{i}:p{i}]" for i in range(50))
        _, pts = points.extract(tags)
        assert len(pts) == points.MAX_POINTS

    def test_no_tags_passthrough(self):
        clean, pts = points.extract("plain answer")
        assert clean == "plain answer" and pts == []


class ToLogical(unittest.TestCase):
    MONS = [
        # eDP-1: logical (0,0), scale 2, 3456x2160 physical
        {"x": 0, "y": 0, "width": 3456, "height": 2160, "scale": 2},
        # DP-3: logical (1728,0), scale 1, 3440x1440 physical
        {"x": 1728, "y": 0, "width": 3440, "height": 1440, "scale": 1},
    ]

    def test_scale_2_monitor(self):
        out = points.to_logical(
            [{"x": 1000, "y": 400, "label": "a"}], self.MONS)
        assert out[0]["x"] == 500 and out[0]["y"] == 200

    def test_scale_1_offset_monitor(self):
        # px on DP-3: image offset = 1728*1, 0
        out = points.to_logical(
            [{"x": 2000, "y": 50, "label": ""}], self.MONS)
        assert out[0]["x"] == 2000 and out[0]["y"] == 50

    def test_point_outside_monitors_passthrough(self):
        out = points.to_logical([{"x": 99999, "y": 0, "label": ""}],
                                self.MONS)
        assert out[0]["x"] == 99999

    def test_no_monitors_passthrough(self):
        out = points.to_logical([{"x": 10, "y": 20, "label": ""}], [])
        assert out[0]["x"] == 10


if __name__ == "__main__":
    unittest.main()
