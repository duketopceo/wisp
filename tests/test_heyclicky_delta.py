"""HeyClicky teardown delta tests: H1 walkthrough, H2 drawing tags,
H3 pointing resolution, H6 suggestion etiquette, H8 volatile memory.

Reference functions prefixed `clicky_` are literal Python translations of
farzaa/clicky (MIT) Swift source, used as the oracle for changed-input
comparisons:
  - ElementLocationDetector.swift: supportedComputerUseResolutions,
    bestComputerUseResolution, and the clamp/scale/flip block.
  - CompanionManager.swift: the [POINT:...] tag regex.
"""
import pathlib
import re
import tempfile
import unittest
from datetime import date
from unittest import mock

from wisp import grounding, memory, points, suggest_policy, walkthrough


# ------------------------------------------------------------ clicky oracle

CLICKY_RESOLUTIONS = (
    (1024, 768, 1024.0 / 768.0),
    (1280, 800, 1280.0 / 800.0),
    (1366, 768, 1366.0 / 768.0),
)


def clicky_best_resolution(display_w, display_h):
    ratio = float(display_w) / float(max(1, display_h))
    best_w, best_h = 1280, 800
    smallest = float("inf")
    for w, h, r in CLICKY_RESOLUTIONS:
        d = abs(ratio - r)
        if d < smallest:
            smallest = d
            best_w, best_h = w, h
    return best_w, best_h


def clicky_scale(px, py, res_w, res_h, disp_w, disp_h, flip_y):
    cx = max(0.0, min(float(px), float(res_w)))
    cy = max(0.0, min(float(py), float(res_h)))
    sx = (cx / res_w) * disp_w
    sy_top = (cy / res_h) * disp_h
    sy = disp_h - sy_top if flip_y else sy_top
    return sx, sy


CLICKY_POINT_RE = re.compile(
    r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?"
    r"(?::screen(\d+))?)\]\s*$")


def clicky_parse(text):
    m = CLICKY_POINT_RE.search(text)
    if not m:
        return text, None, None, None
    spoken = text[:m.start()].strip()
    if m.group(1) is None:
        return spoken, None, None, None
    return (spoken, (int(m.group(1)), int(m.group(2))),
            (m.group(3) or "").strip() or None,
            int(m.group(4)) if m.group(4) else None)


# ------------------------------------------------------------------ H3

class TestPointingResolution(unittest.TestCase):
    DISPLAYS = [
        (1024, 768), (800, 600), (1280, 800), (1440, 900), (1512, 982),
        (1728, 1117), (2560, 1600), (1920, 1080), (2560, 1440),
        (3840, 2160), (1366, 768), (3440, 1440), (5120, 1440),
        (1080, 1920), (1200, 1920), (1600, 1200), (1, 1), (1000, 1),
    ]

    def test_table_matches_clicky(self):
        self.assertEqual(grounding.POINTING_RESOLUTIONS,
                         tuple((w, h) for w, h, _ in CLICKY_RESOLUTIONS))

    def test_pick_matches_clicky_across_displays(self):
        for w, h in self.DISPLAYS:
            with self.subTest(display=(w, h)):
                self.assertEqual(grounding.pick_pointing_resolution(w, h),
                                 clicky_best_resolution(w, h))

    def test_known_picks(self):
        self.assertEqual(grounding.pick_pointing_resolution(1024, 768),
                         (1024, 768))
        self.assertEqual(grounding.pick_pointing_resolution(2560, 1600),
                         (1280, 800))
        self.assertEqual(grounding.pick_pointing_resolution(1920, 1080),
                         (1366, 768))
        # ultrawide falls back to the widest table entry
        self.assertEqual(grounding.pick_pointing_resolution(3440, 1440),
                         (1366, 768))

    def test_degenerate_dims_default(self):
        self.assertEqual(grounding.pick_pointing_resolution(0, 0),
                         (1280, 800))
        self.assertEqual(grounding.pick_pointing_resolution(-5, 100),
                         (1280, 800))
        self.assertEqual(grounding.pick_pointing_resolution("x", 1),
                         (1280, 800))

    def test_scale_matches_clicky_changed_inputs(self):
        cases = [
            (640, 400, 1280, 800, 2560, 1600),
            (0, 0, 1280, 800, 1440, 900),
            (1280, 800, 1280, 800, 1440, 900),
            (-50, 900, 1280, 800, 1440, 900),      # clamped both axes
            (2000, -1, 1366, 768, 1920, 1080),
            (683, 384, 1366, 768, 3840, 2160),
            (511, 383, 1024, 768, 1600, 1200),
            (17.6, 3.2, 1024, 768, 800, 600),
        ]
        for flip in (False, True):
            for c in cases:
                with self.subTest(case=c, flip=flip):
                    ex, ey = clicky_scale(*c, flip)
                    got = grounding.scale_point_from_resolution(
                        *c, flip_y=flip)
                    self.assertEqual(got, (round(ex), round(ey)))

    def test_scale_stays_in_display_bounds(self):
        for px, py in ((-1e6, -1e6), (1e6, 1e6), (5, 1e6)):
            x, y = grounding.scale_point_from_resolution(
                px, py, 1280, 800, 1440, 900)
            self.assertTrue(0 <= x <= 1440 and 0 <= y <= 900)

    def test_flip_y_center_is_symmetric(self):
        self.assertEqual(grounding.scale_point_from_resolution(
            640, 400, 1280, 800, 1440, 900, flip_y=True), (720, 450))
        self.assertEqual(grounding.scale_point_from_resolution(
            0, 0, 1280, 800, 1440, 900, flip_y=True), (0, 900))

    def test_zero_resolution_does_not_divide_by_zero(self):
        x, y = grounding.scale_point_from_resolution(5, 5, 0, 0, 100, 100)
        self.assertTrue(0 <= x <= 100 and 0 <= y <= 100)


# ------------------------------------------------------------------ H2

class TestDrawingTags(unittest.TestCase):
    CLICKY_EXAMPLES = [
        "you'll want to open the color inspector. it's right up in the "
        "top right area of the toolbar. [POINT:1100,42:color inspector]",
        "html stands for hypertext markup language, it's basically the "
        "skeleton of every web page. [POINT:none]",
        "that's over on your other monitor, see the terminal window? "
        "[POINT:400,300:terminal:screen2]",
        "see the source control icon in the sidebar? "
        "[POINT:24,180:source control]",
        "click here [POINT:10,20]",
    ]

    def test_extract_points_alias_is_extract(self):
        self.assertIs(points.extract_points, points.extract)
        self.assertEqual(points.extract_points("a [POINT:1,2:b] c"),
                         ("a  c", [{"x": 1, "y": 2, "label": "b"}]))

    def test_point_tags_match_clicky_parser(self):
        for text in self.CLICKY_EXAMPLES:
            with self.subTest(text=text):
                spoken, xy, label, screen = clicky_parse(text)
                clean, ds = points.extract_drawings(text)
                self.assertEqual(clean, spoken)
                if xy is None:
                    self.assertEqual(ds, [])
                    continue
                self.assertEqual(len(ds), 1)
                d = ds[0]
                self.assertEqual((d["kind"], d["x"], d["y"]),
                                 ("point", xy[0], xy[1]))
                self.assertEqual(d["label"] or None, label)
                self.assertEqual(d.get("screen"), screen)

    def test_all_shape_kinds(self):
        text = ("look [RING:100,200,30] then [ARROW:1,2,300,400] "
                "and [HL:10,20,200,50] at [POINT:5,6:save]")
        clean, ds = points.extract_drawings(text)
        self.assertNotIn("[", clean)
        kinds = {d["kind"]: d for d in ds}
        self.assertEqual(kinds["ring"],
                         {"kind": "ring", "type": "ring",
                          "x": 100, "y": 200, "r": 30})
        self.assertEqual(
            (kinds["arrow"]["x1"], kinds["arrow"]["y1"],
             kinds["arrow"]["x2"], kinds["arrow"]["y2"]), (1, 2, 300, 400))
        self.assertEqual(
            (kinds["hl"]["w"], kinds["hl"]["h"], kinds["hl"]["fade_ms"]),
            (200, 50, 2000))
        self.assertEqual(kinds["point"]["label"], "save")

    def test_malformed_shapes_stripped_not_drawn(self):
        clean, ds = points.extract_drawings(
            "a [RING:x,y,z] b [HL:1,2,0,5] c [ARROW:1,2] d")
        self.assertEqual(ds, [])
        self.assertEqual(clean, "a  b  c  d")

    def test_unclosed_tag_stays_visible(self):
        clean, ds = points.extract_drawings("see [RING:1,2,3")
        self.assertEqual(ds, [])
        self.assertIn("[RING:1,2,3", clean)

    def test_non_tags_pass_through(self):
        clean, ds = points.extract_drawings("[POINTER] [HLS] [RINGS]")
        self.assertEqual(ds, [])
        self.assertEqual(clean, "[POINTER] [HLS] [RINGS]")

    def test_points_json_form(self):
        _, ds = points.extract_drawings(
            'x [POINTS:[{"x":1,"y":2,"label":"a"},{"x":3,"y":4}]] y')
        self.assertEqual([(d["x"], d["y"]) for d in ds], [(1, 2), (3, 4)])

    def test_strip_drawing_tags(self):
        self.assertEqual(points.strip_drawing_tags(
            "hi [RING:1,2,3] there [POINT:none]"), "hi  there")

    def test_monitor_mapping_scale_2(self):
        mons = [{"x": 0, "y": 0, "width": 2880, "height": 1800,
                 "scale": 2.0},
                {"x": 1440, "y": 0, "width": 3840, "height": 2160,
                 "scale": 2.0}]
        _, ds = points.extract_drawings(
            "[RING:200,100,40] [HL:100,100,400,200] "
            "[ARROW:100,100,3080,100] [POINT:3120,20:x]", monitors=mons)
        by = {d["kind"]: d for d in ds}
        self.assertEqual((by["ring"]["x"], by["ring"]["y"], by["ring"]["r"]),
                         (100, 50, 20))
        self.assertEqual((by["hl"]["x"], by["hl"]["y"], by["hl"]["w"],
                          by["hl"]["h"]), (50, 50, 200, 100))
        # arrow crosses monitors: each endpoint maps independently
        self.assertEqual((by["arrow"]["x1"], by["arrow"]["y1"]), (50, 50))
        self.assertEqual((by["arrow"]["x2"], by["arrow"]["y2"]),
                         (1440 + 100, 50))
        self.assertEqual((by["point"]["x"], by["point"]["y"]),
                         (1440 + 120, 10))

    def test_point_mapping_agrees_with_to_logical(self):
        mons = [{"x": 0, "y": 0, "width": 3840, "height": 2160,
                 "scale": 1.5}]
        _, ds = points.extract_drawings("[POINT:1501,999:a]", monitors=mons)
        ref = points.to_logical([{"x": 1501, "y": 999, "label": "a"}], mons)
        self.assertEqual((ds[0]["x"], ds[0]["y"]),
                         (ref[0]["x"], ref[0]["y"]))

    def test_no_monitors_keeps_pixels(self):
        _, ds = points.extract_drawings("[RING:200,100,40]")
        self.assertEqual(ds[0]["r"], 40)

    def test_cap(self):
        text = " ".join(f"[RING:{i},{i},5]" for i in range(200))
        _, ds = points.extract_drawings(text)
        self.assertEqual(len(ds), points.MAX_DRAWINGS)


# ------------------------------------------------------------------ H1

def _win(title="Settings", cls="gnome-control-center", els=None):
    if els is None:
        els = [{"role": "button", "label": "Wi-Fi"}]
    return {"title": title, "class": cls, "elements": els}


class TestWalkthrough(unittest.TestCase):
    def test_three_step_script_driven_by_hypr_events(self):
        wt = walkthrough.Walkthrough(
            "turn on wifi", steps=["open settings", "click wifi",
                                   "flip the toggle"])
        first = wt.issue_step(now=0)
        self.assertEqual((first["action"], first["step_index"]),
                         ("step", 1))
        r = wt.observe(_win(), _win(), elapsed_s=1,
                       hypr_event=("activewindow", "x,y"))
        self.assertEqual(r["action"], "step")
        self.assertEqual(r["step_index"], 2)
        r = wt.observe(_win(), _win(), elapsed_s=1,
                       hypr_event="windowtitle>>abc")
        self.assertEqual(r["spoken"], "flip the toggle")
        r = wt.observe(_win(), _win(title="Wi-Fi"), elapsed_s=1)
        self.assertEqual(r["action"], "advanced")
        self.assertEqual(wt.done_log, ["open settings", "click wifi",
                                       "flip the toggle"])
        self.assertEqual(wt.issue_step()["action"], "complete")

    def test_done_log_refuses_reissue(self):
        wt = walkthrough.Walkthrough()
        wt.issue_step("open settings")
        wt.mark_step_done()
        r = wt.issue_step("Open  Settings")
        self.assertEqual(r["action"], "refused_already_done")

    def test_failed_step_not_repeated(self):
        wt = walkthrough.Walkthrough(steps=["a", "b"])
        wt.issue_step()
        r = wt.observe(_win(), _win(title="x"), verified=False)
        self.assertEqual(r["spoken"], "b")
        self.assertEqual(wt.issue_step("a")["action"], "refused_failed")

    def test_max_steps(self):
        wt = walkthrough.Walkthrough()
        for i in range(walkthrough.MAX_STEPS):
            self.assertEqual(wt.issue_step(f"s{i}")["action"], "step")
            wt.mark_step_done()
        r = wt.issue_step("s16")
        self.assertEqual(r["action"], "max_steps_refused")
        self.assertIn("15", r["spoken"])

    def test_load_wait_title_and_empty_tree(self):
        wt = walkthrough.Walkthrough()
        wt.issue_step("x")
        r = wt.observe(_win(), _win(title="Loading..."), elapsed_s=30)
        self.assertEqual(r["action"], "wait_load")
        r = wt.observe(_win(), _win(els=[]), elapsed_s=30)
        self.assertEqual(r["action"], "wait_load")
        self.assertTrue(walkthrough.is_loading_state(None, None))
        self.assertFalse(walkthrough.is_loading_state(_win(), _win()))

    def test_no_change_timeout_prompts(self):
        wt = walkthrough.Walkthrough()
        wt.issue_step("x")
        self.assertEqual(wt.observe(_win(), _win(), elapsed_s=19.9)["action"],
                         "wait")
        r = wt.observe(_win(), _win(), elapsed_s=20)
        self.assertEqual(r["action"], "prompt_stuck")
        self.assertEqual(r["spoken"], "done, or stuck?")
        # prompting does not advance or re-log the step
        self.assertEqual(wt.done_log, [])

    def test_esc_cancel_clears_state(self):
        st = mock.Mock()
        wt = walkthrough.Walkthrough(steps=["a", "b"])
        wt.issue_step()
        r = wt.cancel(st)
        self.assertTrue(r["overlay_cleared"])
        self.assertIsNone(wt.current_step)
        st.transition.assert_called_once_with("idle", points=[], choices=[])
        self.assertEqual(wt.issue_step()["action"], "cancelled")
        self.assertEqual(wt.observe(_win(), _win(title="z"))["action"],
                         "cancelled")

    def test_diff_helper(self):
        d = walkthrough.diff_window_state(_win(), _win())
        self.assertFalse(d["changed"])
        d = walkthrough.diff_window_state(
            _win(), _win(els=[{"role": "button", "label": "Wi-Fi"},
                              {"role": "switch", "label": "on"}]))
        self.assertTrue(d["changed"] and d["elements_changed"])
        self.assertEqual(d["added_count"], 1)
        d = walkthrough.diff_window_state(_win(), _win(cls="firefox"))
        self.assertTrue(d["focus_changed"])


# ------------------------------------------------------------------ H6

class TestSuggestEtiquette(unittest.TestCase):
    ev = staticmethod(suggest_policy.evaluate_suggestion_etiquette)

    def test_block_before_6am(self):
        for h in range(0, 6):
            self.assertEqual(self.ev(local_hour=h,
                                     current_day="2026-10-16")["reason"],
                             "before_6am")
        self.assertTrue(self.ev(local_hour=6,
                                current_day="2026-10-16")["allow"])

    def test_holds(self):
        for kw, reason in (("in_call", "in_call"),
                           ("screen_sharing", "screen_sharing"),
                           ("fullscreen", "fullscreen")):
            r = self.ev(local_hour=12, current_day="2026-10-16", **{kw: True})
            self.assertEqual((r["action"], r["reason"]), ("hold", reason))

    def test_streak_pauses_seven_days(self):
        r = self.ev(local_hour=12, dismissal_streak_days=3,
                    current_day="2026-10-16")
        self.assertEqual((r["action"], r["paused_until_day"]),
                         ("pause", "2026-10-23"))
        self.assertTrue(self.ev(local_hour=12, dismissal_streak_days=2,
                                current_day="2026-10-16")["allow"])

    def test_active_and_expired_pause(self):
        r = self.ev(local_hour=12, paused_until_day="2026-10-23",
                    current_day=date(2026, 10, 20))
        self.assertEqual(r["reason"], "paused_backoff")
        r = self.ev(local_hour=12, paused_until_day="2026-10-23",
                    dismissal_streak_days=3, current_day="2026-10-23")
        self.assertTrue(r["allow"])

    def test_declined_reasons_prompt(self):
        self.assertEqual(suggest_policy.format_declined_reasons_prompt([]),
                         "")
        p = suggest_policy.format_declined_reasons_prompt(
            ["too noisy", "too noisy", {"title": "auto-backup",
                                        "reason": "already have one"}])
        self.assertEqual(p.count("too noisy"), 1)
        self.assertIn("auto-backup: already have one", p)
        r = self.ev(local_hour=12, current_day="2026-10-16",
                    declined_reasons=["nope"])
        self.assertIn("nope", r["declined_prompt"])


# ------------------------------------------------------------------ H8

class TestVolatileMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.p = [mock.patch.object(memory, "MEMORY_FILE", d / "MEMORY.md"),
                  mock.patch.object(memory, "USER_FILE", d / "USER.md"),
                  mock.patch.object(memory, "VOLATILE_FILE",
                                    d / "VOLATILE.md")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    def test_parse_and_format_round_trip(self):
        for line in ("- doing taxes | until: 2026-10-23",
                     "- doing taxes (until: 2026-10-23)",
                     "doing taxes until: 2026-10-23"):
            e = memory.parse_volatile_line(line)
            self.assertEqual((e.text, e.until), ("doing taxes", "2026-10-23"))
        self.assertEqual(memory.format_volatile_line("doing taxes",
                                                     date(2026, 10, 23)),
                         "- doing taxes | until: 2026-10-23")
        self.assertIsNone(memory.parse_volatile_line("- no date here"))
        self.assertIsNone(memory.parse_volatile_line(
            "- bad | until: 2026-13-40"))

    def test_add_uses_ttl_and_expires(self):
        self.assertTrue(memory.add_volatile("debugging the router",
                                            today="2026-10-16")
                        .startswith("OK"))
        live = memory.load_volatile(today="2026-10-23")
        self.assertEqual([(e.text, e.until) for e in live],
                         [("debugging the router", "2026-10-23")])
        self.assertEqual(memory.load_volatile(today="2026-10-24"), [])
        # expired line was compacted out of the file on load
        self.assertNotIn("router", memory.VOLATILE_FILE.read_text())

    def test_dedupe_refreshes_expiry(self):
        memory.add_volatile("x", until="2026-10-20", today="2026-10-16")
        memory.add_volatile("X", until="2026-10-30", today="2026-10-16")
        live = memory.load_volatile(today="2026-10-16")
        self.assertEqual([(e.text, e.until) for e in live],
                         [("X", "2026-10-30")])

    def test_line_cap_evicts_soonest_expiring(self):
        for i in range(5):
            memory.add_volatile(f"f{i}", until=f"2026-11-0{i + 1}",
                                today="2026-10-16", max_lines=3)
        live = memory.load_volatile(today="2026-10-16", max_lines=3)
        self.assertEqual([e.text for e in live], ["f2", "f3", "f4"])

    def test_char_budget(self):
        self.assertIn("FAIL", memory.add_volatile(
            "y" * (memory.VOLATILE_BUDGET + 1), today="2026-10-16"))
        for i in range(10):
            memory.add_volatile(f"{i}" + "z" * 50, until=f"2026-11-1{i}",
                                today="2026-10-16", budget_chars=200)
        self.assertLessEqual(len(memory.VOLATILE_FILE.read_text()), 200)

    def test_promote_moves_to_memory(self):
        memory.add_volatile("prefers short replies this week",
                            today="2026-10-16")
        out = memory.promote_volatile_entry("short replies",
                                            today="2026-10-16")
        self.assertTrue(out.startswith("OK"), out)
        mem = memory.MEMORY_FILE.read_text()
        self.assertIn("- prefers short replies this week", mem)
        self.assertNotIn("until:", mem)
        self.assertEqual(memory.load_volatile(today="2026-10-16"), [])
        self.assertIn("FAIL", memory.promote_volatile_entry("nothing"))

    def test_tool_route_and_snapshots(self):
        self.assertTrue(memory.run("volatile|add||on call rotation")
                        .startswith("OK"))
        self.assertIn("on call rotation", memory.volatile_snapshot())
        # the frozen MEMORY/USER snapshot is unchanged by the volatile layer
        self.assertEqual(memory.snapshot(), "")
        self.assertTrue(memory.run("volatile|remove|on call|")
                        .startswith("OK"))
        self.assertEqual(memory.volatile_snapshot(), "")


if __name__ == "__main__":
    unittest.main()
