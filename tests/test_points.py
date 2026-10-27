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


class ExtractMarked(unittest.TestCase):
    def test_inline_tag_offset(self):
        text = "Click Save [POINT:10,20:Save] to keep it."
        clean, marks = points.extract_marked(text)
        assert clean == "Click Save  to keep it."
        assert marks == [(11, {"x": 10, "y": 20, "label": "Save"})]
        assert clean[:marks[0][0]] == "Click Save "

    def test_two_sentences_two_spans(self):
        clean, marks = points.extract_marked(
            "Open Settings [POINT:1,2:a]. Then Display [POINT:3,4:b].")
        first_end = clean.index(".") + 1
        assert len(marks) == 2
        assert marks[0][0] <= first_end < marks[1][0] <= len(clean)
        assert [m[1]["label"] for m in marks] == ["a", "b"]

    def test_points_list_marks_at_end(self):
        clean, marks = points.extract_marked(
            'Steps. [POINTS:[{"x":1,"y":2,"label":"a"},'
            '{"x":3,"y":4,"label":"b"}]]')
        assert clean == "Steps."
        assert [m[0] for m in marks] == [len(clean)] * 2
        assert [m[1]["label"] for m in marks] == ["a", "b"]

    def test_leading_whitespace_offset(self):
        clean, marks = points.extract_marked("  [POINT:1,2:a]Hi.")
        assert clean == "Hi." and marks[0][0] == 0

    def test_extract_matches_marked(self):
        for text in ("a [POINT:1,2:x] b", "[POINT:5,6]", "plain",
                     'x [POINTS:[{"x":1,"y":2}]] y', "do [POINT:1,2"):
            clean, pts = points.extract(text)
            mclean, marks = points.extract_marked(text)
            assert (clean, pts) == (mclean, [p for _, p in marks])

    def test_prefix_agreement(self):
        full = ("Open it [POINT:1,2:a]. Then [POINTS:[{\"x\":3,\"y\":4}]]"
                " done [POINT:5,6:c].")
        full_clean, _ = points.extract_marked(full)
        for i in range(len(full) + 1):
            prefix = points.strip_partial(full[:i])
            clean, _ = points.extract_marked(prefix)
            assert full_clean.startswith(clean), (i, clean)


class StripPartial(unittest.TestCase):
    def test_partial_points_json_with_inner_bracket(self):
        out = points.strip_partial('Open it [POINTS:[{"x":1,"y":2}]')
        assert out == "Open it " and "{" not in out

    def test_partial_tag_start(self):
        assert points.strip_partial("Open it [POI") == "Open it "
        assert points.strip_partial("Open it [") == "Open it "

    def test_unclosed_point(self):
        assert points.strip_partial("Open [POINT:10,2") == "Open "

    def test_no_partial_unchanged(self):
        for text in ("plain text", "a [POINT:1,2:x] b", "press [POINTER] x",
                     'a [POINTS:[{"x":1,"y":2}]] b', "list [1] item"):
            assert points.strip_partial(text) == text


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
