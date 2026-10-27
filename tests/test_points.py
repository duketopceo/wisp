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


ALL_KINDS = ("Circle [RING:100,200,30] and [ARROW:1,2,3,4] then "
             "[HL:5,6,70,80] ok [POINT:5,6:Tab] done "
             'and [POINTS:[{"x":3,"y":4}]] end.')


class Drawings(unittest.TestCase):
    def test_ring_mark_at_tag_offset(self):
        clean, marks = points.extract_marked(
            "Circle it [RING:100,200,30] now.")
        assert clean == "Circle it  now."
        assert marks == [(10, {"kind": "ring", "x": 100, "y": 200,
                               "r": 30})]

    def test_arrow_and_point_in_text_order(self):
        _, marks = points.extract_marked(
            "See [ARROW:1,2,3,4] and [POINT:5,6:Tab] here")
        assert [p.get("kind") for _, p in marks] == ["arrow", None]
        assert marks[0][1] == {"kind": "arrow", "x1": 1, "y1": 2,
                               "x2": 3, "y2": 4}
        assert marks[1][1] == {"x": 5, "y": 6, "label": "Tab"}
        assert "kind" not in marks[1][1]

    def test_spaces_allowed(self):
        _, marks = points.extract_marked("[RING:10, 20, 30]")
        assert marks[0][1] == {"kind": "ring", "x": 10, "y": 20, "r": 30}

    def test_bad_drawings_stripped_without_mark(self):
        for tag in ("[RING:10.5,20,30]", "[RING:1,2,0]", "[HL:1,2,-3,4]"):
            clean, marks = points.extract_marked(f"a {tag} b")
            assert (clean, marks) == ("a  b", []), tag

    def test_lookalikes_pass_through(self):
        for text in ("[POINTER]", "[HLS]", "[RINGS]", "[ARROWS]",
                     "[HL7 spec]"):
            assert points.extract_marked(text) == (text, [])
            assert points.strip_partial(text) == text

    def test_drawing_cap_keeps_later_points(self):
        text = " ".join(f"[RING:{i},{i},5]" for i in range(20))
        text += " [POINT:1,2:x]"
        _, marks = points.extract_marked(text)
        assert len([1 for _, p in marks if p.get("kind") == "ring"]) == 16
        assert marks[-1][1] == {"x": 1, "y": 2, "label": "x"}

    def test_extract_strips_all_returns_points_only(self):
        clean, pts = points.extract("Click [HL:1,2,3,4] here [POINT:5,6:x]")
        assert "[" not in clean
        assert pts == [{"x": 5, "y": 6, "label": "x"}]

    def test_unclosed_drawing_stays_visible(self):
        clean, marks = points.extract_marked("see [RING:1,2")
        assert clean == "see [RING:1,2" and marks == []

    def test_prefix_stability_all_kinds(self):
        full_clean, full_marks = points.extract_marked(ALL_KINDS)
        assert len(full_marks) == 5
        prev = ""
        for i in range(len(ALL_KINDS) + 1):
            out = points.strip_partial(ALL_KINDS[:i])
            assert out.startswith(prev), (i, out)
            prev = out
            clean, marks = points.extract_marked(out)
            assert full_clean.startswith(clean), (i, clean)
            # payloads form a prefix (offsets may clamp to the stripped
            # tail of a partial text)
            assert [p for _, p in marks] == \
                [p for _, p in full_marks[:len(marks)]], (i, marks)
            assert "[" not in clean, (i, clean)


class DrawingsToLogical(unittest.TestCase):
    MON2 = [{"x": 0, "y": 0, "width": 2880, "height": 1800, "scale": 2.0},
            {"x": 1440, "y": 0, "width": 3840, "height": 2160,
             "scale": 2.0}]
    RING = {"kind": "ring", "x": 200, "y": 100, "r": 40}
    HL = {"kind": "hl", "x": 100, "y": 100, "w": 400, "h": 200}
    ARROW = {"kind": "arrow", "x1": 100, "y1": 100, "x2": 3080, "y2": 100}

    def test_to_logical_path_divides_sizes_by_anchor_scale(self):
        out = points.drawings_to_logical([self.RING, self.HL, self.ARROW],
                                         self.MON2)
        assert out[0] == {"kind": "ring", "x": 100, "y": 50, "r": 20}
        assert out[1] == {"kind": "hl", "x": 50, "y": 50, "w": 200, "h": 100}
        assert (out[2]["x1"], out[2]["y1"]) == (50, 50)
        ref = points.to_logical([{"x": 3080, "y": 100}], self.MON2)[0]
        assert (out[2]["x2"], out[2]["y2"]) == (ref["x"], ref["y"])

    def test_sizes_at_least_one(self):
        out = points.drawings_to_logical(
            [{"kind": "ring", "x": 5, "y": 5, "r": 1}], self.MON2)
        assert out[0]["r"] == 1

    def test_canvas_path_keeps_sizes_and_shifts_origin(self):
        old = points.SHOT_ORIGIN
        points.SHOT_ORIGIN = (10, 20)
        try:
            out = points.drawings_to_logical([self.RING, self.HL],
                                             self.MON2, canvas=True)
        finally:
            points.SHOT_ORIGIN = old
        assert out[0] == {"kind": "ring", "x": 210, "y": 120, "r": 40}
        assert out[1] == {"kind": "hl", "x": 110, "y": 120, "w": 400,
                          "h": 200}

    def test_outside_every_monitor_passes_through(self):
        out = points.drawings_to_logical(
            [{"kind": "ring", "x": 99999, "y": 5, "r": 30}], self.MON2)
        assert out[0] == {"kind": "ring", "x": 99999, "y": 5, "r": 30}


class StripPartial(unittest.TestCase):
    def test_partial_points_json_with_inner_bracket(self):
        out = points.strip_partial('Open it [POINTS:[{"x":1,"y":2}]')
        assert out == "Open it " and "{" not in out

    def test_partial_tag_start(self):
        assert points.strip_partial("Open it [POI") == "Open it "
        assert points.strip_partial("Open it [") == "Open it "

    def test_unclosed_point(self):
        assert points.strip_partial("Open [POINT:10,2") == "Open "

    def test_partial_drawing_openers_and_open_tags(self):
        for tail in ("[R", "[RI", "[A", "[ARRO", "[H", "[HL", "[RING:1,2",
                     "[ARROW:1,2,3", "[HL:"):
            assert points.strip_partial("Look " + tail) == "Look ", tail

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
