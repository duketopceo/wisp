"""HeyClicky teardown delta tests: H1 walkthrough, H2 drawing tags,
H3 pointing resolution, H4 app skills, H5 routines, H6 suggestion etiquette,
H7 conversation grants, H8 volatile memory, H9 talk/deep lanes.

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

from wisp import (
    cancel,
    conversation_grants,
    grounding,
    lanes,
    memory,
    points,
    routines,
    skills,
    suggest_policy,
    walkthrough,
)


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


# ------------------------------------------------------------------ H4

class TestAppSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skills_dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_skill(self, slug: str, app_classes: str = "",
                     url_hosts: str = "", body: str = "skill body"):
        d = self.skills_dir / "apps" / slug
        d.mkdir(parents=True, exist_ok=True)
        lines = ["---", f"name: {slug}", f"description: {slug} notes"]
        if app_classes:
            lines.append(f"app_classes: {app_classes}")
        if url_hosts:
            lines.append(f"url_hosts: {url_hosts}")
        lines.extend(["---", f"# {slug}", "", body])
        (d / "SKILL.md").write_text("\n".join(lines) + "\n")

    def test_window_class_match_and_unknown_app_returns_empty(self):
        self._write_skill("chromium", app_classes="chromium, google-chrome",
                          body="Ctrl+L focuses omnibox")
        self._write_skill("gimp", app_classes="gimp, org.gimp.gimp",
                          body="Ctrl+Shift+E exports")
        matched = skills.match_app_skill("chromium", skills_dir=self.skills_dir)
        self.assertIn("# chromium", matched)
        self.assertIn("Ctrl+L focuses omnibox", matched)
        self.assertEqual(
            skills.match_app_skill("unknown-app-xyz", skills_dir=self.skills_dir),
            "",
        )

    def test_url_host_takes_precedence_over_window_class(self):
        self._write_skill("chromium", app_classes="chromium",
                          body="generic browser notes")
        self._write_skill("github", url_hosts="github.com, gist.github.com",
                          body="press T to find file")
        # Browser on github.com -> github skill wins over chromium class
        matched = skills.match_app_skill(
            "chromium",
            url_host="https://www.github.com/duketopceo/wisp/pulls",
            skills_dir=self.skills_dir,
        )
        self.assertIn("# github", matched)
        self.assertNotIn("generic browser notes", matched)
        # Browser on unindexed site -> falls back to chromium class skill
        fallback = skills.match_app_skill(
            "chromium",
            url_host="https://example.org/docs",
            skills_dir=self.skills_dir,
        )
        self.assertIn("# chromium", fallback)

    def test_token_and_char_budget_respected(self):
        long_body = "A" * 2000
        self._write_skill("nvim", app_classes="nvim", body=long_body)
        capped = skills.match_app_skill(
            "nvim", skills_dir=self.skills_dir, budget_chars=120
        )
        self.assertLessEqual(len(capped), 120)
        tok_capped = skills.match_app_skill(
            "nvim", skills_dir=self.skills_dir, token_budget=25
        )
        self.assertLessEqual(len(tok_capped), 100)

    def test_seed_app_skills_present_and_matchable(self):
        expected = (
            "hyprland", "chromium", "firefox", "nvim", "vscode", "gimp",
            "libreoffice", "obsidian", "kitty", "spotify", "thunderbird",
            "steam", "nautilus", "1password",
        )
        seed_apps = skills._seed_dir() / "apps"
        for name in expected:
            with self.subTest(seed=name):
                self.assertTrue((seed_apps / name / "SKILL.md").is_file())
        body = skills.match_app_skill("firefox")
        self.assertIn("# firefox", body)


# ------------------------------------------------------------------ H5

class TestRoutines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_path = pathlib.Path(self.tmp.name) / "routines.json"
        self.store = routines.RoutineStore(self.store_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_systemd_units_includes_persistent_and_exec(self):
        r = routines.Routine(
            id="inbox-digest",
            name="Inbox Digest",
            task="summarize unread messages",
            schedule="*-*-* 08:00:00",
        )
        units = routines.generate_systemd_units(r)
        svc, tmr = units
        self.assertEqual(svc, units["service"])
        self.assertEqual(tmr, units["timer"])
        self.assertIn("[Unit]", svc)
        self.assertIn("[Service]", svc)
        self.assertIn("Type=oneshot", svc)
        self.assertIn("wispd agents run inbox-digest", svc)
        self.assertIn("[Timer]", tmr)
        self.assertIn("OnCalendar=*-*-* 08:00:00", tmr)
        self.assertIn("Persistent=true", tmr)
        self.assertIn("[Install]", tmr)
        self.assertIn("WantedBy=timers.target", tmr)

    def test_first_opt_in_gate_refusal_creates_nothing(self):
        prompts = []
        created = self.store.create(
            "Morning check",
            task="check PRs",
            schedule="daily",
            confirm_fn=lambda p: (prompts.append(p), False)[1],
        )
        self.assertIsNone(created)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.has_opted_in())

    def test_first_opt_in_gate_approves_then_subsequent_skips_prompt(self):
        prompts = []
        r1 = self.store.create(
            "Morning check",
            task="check PRs",
            schedule="daily",
            confirm_fn=lambda p: (prompts.append(p), True)[1],
        )
        self.assertIsNotNone(r1)
        self.assertEqual(len(prompts), 1)
        self.assertTrue(self.store.has_opted_in())
        # Second routine does not need to prompt again
        r2 = self.store.create("Evening check", task="check CI", schedule="daily")
        self.assertIsNotNone(r2)
        self.assertEqual(len(self.store.list()), 2)

    def test_quiet_completion_sets_unread_and_never_speaks(self):
        self.store.create("Digest", task="run digest", opt_in=True)
        out = routines.record_routine_outcome("digest", ok=True, store=self.store)
        self.assertTrue(out["ok"])
        self.assertTrue(out["unread"])
        self.assertFalse(out["speak"])
        self.assertFalse(out["paused"])
        loaded = self.store.get("digest")
        self.assertTrue(loaded.unread)
        self.store.mark_read("digest")
        self.assertFalse(self.store.get("digest").unread)

    def test_auto_pauses_after_three_consecutive_failures(self):
        self.store.create("Flaky check", task="check feed", opt_in=True)
        r1 = routines.record_routine_outcome("flaky-check", ok=False, store=self.store)
        self.assertFalse(r1["paused"])
        self.assertEqual(r1["consecutive_failures"], 1)
        r2 = routines.record_routine_outcome("flaky-check", ok=False, store=self.store)
        self.assertFalse(r2["paused"])
        self.assertEqual(r2["consecutive_failures"], 2)
        r3 = routines.record_routine_outcome("flaky-check", ok=False, store=self.store)
        self.assertTrue(r3["paused"])
        self.assertTrue(r3["auto_paused"])
        self.assertTrue(r3["notify_user_once"])
        self.assertEqual(r3["consecutive_failures"], 3)
        # Subsequent failure while already paused does not notify a second time
        r4 = routines.record_routine_outcome("flaky-check", ok=False, store=self.store)
        self.assertTrue(r4["paused"])
        self.assertFalse(r4["notify_user_once"])


# ------------------------------------------------------------------ H7

class TestConversationGrants(unittest.TestCase):
    def test_hard_stop_kinds_constant(self):
        self.assertEqual(
            conversation_grants.HARD_STOP_KINDS,
            frozenset({"purchase", "send", "delete", "payment"}),
        )

    def test_parse_voice_grant_reply(self):
        parse = conversation_grants.parse_voice_grant_reply
        for phrase in ("allow once", "just once", "once", "yes", "go ahead", "sure"):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse(phrase), "allow_once")
        for phrase in ("always", "always allow", "every time", "for this app"):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse(phrase), "always")
        for phrase in ("not now", "no", "nope", "cancel", "deny", "never", "don't allow"):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse(phrase), "not_now")
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("what time is it"))

    def test_parse_curly_apostrophe_denial_and_negated_always(self):
        parse = conversation_grants.parse_voice_grant_reply
        self.assertEqual(parse("don\u2019t allow"), "not_now")
        self.assertEqual(parse("not always, just this once"), "allow_once")
        self.assertEqual(parse("not always"), "not_now")
        self.assertEqual(parse("always, just this once"), "allow_once")
        self.assertEqual(parse("always"), "always")

    def test_grant_scoping_by_conversation_and_app_class(self):
        mgr = conversation_grants.ConversationGrantManager()
        s_chr = conversation_grants.GrantScope("conv-1", "chromium")
        s_gimp = conversation_grants.GrantScope("conv-1", "gimp")
        s_conv2_chr = conversation_grants.GrantScope("conv-2", "chromium")
        s_conv2_kitty = conversation_grants.GrantScope("conv-2", "kitty")

        # allow_once permits exactly one action in (conv-1, gimp)
        mgr.record_decision(s_gimp, "allow_once")
        self.assertFalse(mgr.is_granted(s_chr))
        self.assertTrue(mgr.authorize(s_gimp, "click"))
        self.assertFalse(mgr.is_granted(s_gimp))

        # always persists across turns for this conversation + app_class,
        # not other apps and not other conversations
        mgr.record_decision(s_chr, "always")
        self.assertTrue(mgr.is_granted(s_chr))
        self.assertFalse(mgr.is_granted(s_conv2_chr))
        self.assertFalse(mgr.is_granted(s_conv2_kitty))

    def test_hard_stop_cannot_be_bypassed_by_always(self):
        mgr = conversation_grants.ConversationGrantManager()
        scope = conversation_grants.GrantScope("conv-1", "chromium")
        mgr.record_decision(scope, "always")
        self.assertTrue(mgr.is_granted(scope, action_kind="click"))

        for kind in conversation_grants.HARD_STOP_KINDS:
            with self.subTest(kind=kind):
                self.assertFalse(mgr.is_granted(scope, action_kind=kind))
                prompts = []
                allowed = mgr.authorize(
                    scope,
                    action_kind=kind,
                    prompt_fn=lambda sc, k: (prompts.append((sc, k)), "allow once")[1],
                )
                self.assertTrue(allowed)
                self.assertEqual(len(prompts), 1)
                # Still not granted for the next hard-stop action
                self.assertFalse(mgr.is_granted(scope, action_kind=kind))

    def test_five_step_conversation_prompts_once_with_always(self):
        mgr = conversation_grants.ConversationGrantManager()
        scope = conversation_grants.GrantScope("conv-42", "libreoffice")
        prompts = 0

        def prompt_fn(_sc, _kind):
            nonlocal prompts
            prompts += 1
            return "always"

        for step in ("click", "type_text", "click", "scroll", "key"):
            self.assertTrue(mgr.authorize(scope, action_kind=step, prompt_fn=prompt_fn))
        self.assertEqual(prompts, 1)
        self.assertEqual(sum(1 for e in mgr.audit_log if e["prompted"]), 1)


# ------------------------------------------------------------------ H9

class TestLanes(unittest.TestCase):
    def test_talk_lane_budget_and_selection_table(self):
        talk = lanes.select_lane(mode="talk", needs_tools=False, is_walkthrough_verify=False)
        self.assertEqual(talk, "talk")
        self.assertEqual(talk.name, "talk")
        self.assertEqual(talk.first_token_budget_ms, 1500)
        self.assertAlmostEqual(talk.first_token_s, 1.5)
        self.assertTrue(talk.streaming)
        self.assertTrue(talk.vision)

        # Walkthrough verification always selects talk lane when tools not needed
        wt_verify = lanes.select_lane(
            mode="act", needs_tools=False, is_walkthrough_verify=True
        )
        self.assertEqual(wt_verify.name, "talk")
        self.assertEqual(wt_verify.first_token_budget_ms, 1500)

        # Needs tools or agent/act mode -> deep lane
        deep_tools = lanes.select_lane(
            mode="talk", needs_tools=True, is_walkthrough_verify=False
        )
        self.assertEqual(deep_tools, "deep")
        self.assertEqual(deep_tools.name, "deep")
        self.assertTrue(deep_tools.supports_tools)

        deep_act = lanes.select_lane(
            mode="act", needs_tools=False, is_walkthrough_verify=False
        )
        self.assertEqual(deep_act.name, "deep")

    def test_lane_ledger_records_per_lane_spend_and_latency(self):
        led = lanes.LaneLedger()
        led.record("talk", usd=0.0012, latency_ms=820, tokens_in=300, tokens_out=40)
        led.record("talk", usd=0.0008, latency_ms=1180, tokens_in=250, tokens_out=30)
        led.record("deep", usd=0.0250, latency_ms=2600, tokens_in=2000, tokens_out=400)

        summary = led.summary()
        self.assertEqual(summary["talk"]["calls"], 2)
        self.assertAlmostEqual(summary["talk"]["usd"], 0.0020)
        self.assertEqual(summary["talk"]["within_budget_count"], 2)
        self.assertLessEqual(summary["talk"]["p50_ms"], 1500)

        self.assertEqual(summary["deep"]["calls"], 1)
        self.assertAlmostEqual(summary["deep"]["usd"], 0.0250)
        self.assertEqual(summary["deep"]["p50_ms"], 2600.0)
        self.assertAlmostEqual(summary["total_usd"], 0.0270)

    def test_barge_in_controller_cancels_tts_and_stream(self):
        tok = cancel.CancelToken()
        tts_stopped = []
        stream_closed = []
        speaker = mock.Mock()

        ctrl = lanes.BargeInController(
            stream_token=tok,
            tts_stop=lambda: tts_stopped.append(True),
            speaker=speaker,
            stream_close=lambda: stream_closed.append(True),
        )
        self.assertFalse(ctrl.is_cancelled)
        res = ctrl.barge_in("user_spoke")
        self.assertTrue(res["cancelled"])
        self.assertTrue(res["tts_cancelled"])
        self.assertTrue(res["stream_cancelled"])
        self.assertTrue(tok.cancelled)
        self.assertTrue(ctrl.tts_token.cancelled)
        self.assertEqual(tts_stopped, [True])
        self.assertEqual(stream_closed, [True])
        speaker.stop.assert_called_once()
        self.assertTrue(ctrl.is_cancelled)


class TestReviewRegressions(unittest.TestCase):
    """Regressions for PR #124 review findings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)
        self.p = [mock.patch.object(memory, "MEMORY_FILE", self.d / "MEMORY.md"),
                  mock.patch.object(memory, "USER_FILE", self.d / "USER.md"),
                  mock.patch.object(memory, "VOLATILE_FILE",
                                    self.d / "VOLATILE.md")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    # memory
    def test_volatile_write_enforces_line_cap(self):
        body = "\n".join(f"- f{i} | until: 2099-01-01" for i in range(41))
        self.assertTrue(memory.edit("volatile", "write", new=body).startswith("FAIL"))

    def test_context_read_persists_expiry_compaction(self):
        (self.d / "VOLATILE.md").write_text(
            "# Volatile\n- old | until: 2000-01-01\n- new | until: 2099-01-01\n")
        memory.volatile_snapshot()
        self.assertNotIn("old", (self.d / "VOLATILE.md").read_text())

    def test_multiline_fact_is_folded_to_one_line(self):
        self.assertTrue(memory.add_volatile("one\ntwo", today="2026-10-16")
                        .startswith("OK"))
        got = memory.load_volatile(today="2026-10-16")
        self.assertEqual([e.text for e in got], ["one two"])

    def test_past_expiry_does_not_delete_live_entry(self):
        memory.add_volatile("keep me", today="2026-10-16")
        r = memory.add_volatile("keep me", until="2026-10-01", today="2026-10-16")
        self.assertTrue(r.startswith("FAIL"))
        self.assertEqual(len(memory.load_volatile(today="2026-10-16")), 1)

    def test_cap_eviction_of_new_fact_reports_failure(self):
        for i in range(3):
            memory.add_volatile(f"f{i}", until="2026-12-31", today="2026-10-16",
                                max_lines=3)
        r = memory.add_volatile("soon", until="2026-10-20", today="2026-10-16",
                                max_lines=3)
        self.assertTrue(r.startswith("FAIL"))
        self.assertEqual(len(memory.load_volatile(today="2026-10-16",
                                                  max_lines=3)), 3)

    def test_promote_not_fooled_by_substring_memory_match(self):
        memory.edit("memory", "add", new="not on call this week")
        memory.add_volatile("on call this week", today="2026-10-16")
        r = memory.promote_volatile_entry("on call this week", today="2026-10-16")
        self.assertTrue(r.startswith("OK"))
        mem = (self.d / "MEMORY.md").read_text().splitlines()
        self.assertIn("- on call this week", mem)

    # points
    def test_bad_monitor_scale_falls_back_to_one(self):
        for bad in (-2, "auto", float("nan"), 0, None):
            self.assertEqual(points._scale_of({"scale": bad}), 1.0)
        self.assertEqual(points._scale_of({"scale": 2}), 2.0)

    def test_points_json_label_screen_suffix_matches_point_tag(self):
        _, d = points.extract_drawings(
            '[POINTS:[{"x":1,"y":2,"label":"terminal:screen2"}]]')
        self.assertEqual(d[0]["label"], "terminal")
        self.assertEqual(d[0]["screen"], 2)

    # suggest policy
    def test_expired_pause_does_not_disable_later_backoff(self):
        r = suggest_policy.evaluate_suggestion_etiquette(
            local_hour=12, paused_until_day="2026-10-23",
            dismissal_streak_days=3, current_day="2026-10-26")
        self.assertEqual(r["reason"], "dismissal_streak")

    def test_default_hour_and_day_share_one_clock(self):
        with mock.patch.object(suggest_policy, "datetime") as dt:
            dt.now.return_value = __import__("datetime").datetime(
                2026, 10, 16, 3, 0)
            r = suggest_policy.evaluate_suggestion_etiquette()
        self.assertEqual(r["reason"], "before_6am")

    # walkthrough
    def test_loading_markers_need_word_boundaries(self):
        for t in ("Downloading", "Uploading", "Opening Hours.pdf",
                  "Connecting Devices"):
            self.assertFalse(walkthrough.is_loading_state(_win(title=t), _win(title=t)), t)
        self.assertTrue(walkthrough.is_loading_state(_win(title="Loading"), _win(title="Loading")))

    def test_window_only_snapshot_can_reach_prompt_stuck(self):
        wt = walkthrough.Walkthrough("t", steps=["a"])
        wt.issue_step(now=0)
        w = {"title": "Settings", "class": "gnome-control-center"}
        self.assertEqual(wt.observe(w, dict(w), elapsed_s=30)["action"],
                         "prompt_stuck")

    def test_same_text_different_label_steps_are_distinct(self):
        wt = walkthrough.Walkthrough("t", steps=[])
        a = walkthrough.Step("click here", label="Save")
        b = walkthrough.Step("click here", label="Cancel")
        wt.mark_done(a) if hasattr(wt, "mark_done") else None
        self.assertFalse(wt.has_completed(b))

    # grants
    def test_always_does_not_cross_conversations(self):
        m = conversation_grants.ConversationGrantManager()
        m.record_decision(conversation_grants.GrantScope("c1", "chromium"), "always")
        self.assertFalse(m.is_granted(conversation_grants.GrantScope("c2", "chromium")))

    # lanes
    def test_barge_in_reports_failed_close_and_reset_clears_closer(self):
        def boom():
            raise RuntimeError("x")
        c = lanes.BargeInController(stream_close=boom)
        with self.assertLogs("wisp.lanes", level="WARNING"):
            r = c.barge_in()
        self.assertFalse(r["stream_cancelled"])
        c.reset()
        self.assertIsNone(c._stream_close)

    # routines
    def test_unit_text_rejects_injection(self):
        r = routines.Routine(id="r", name="a\rb%h", task="t", schedule="daily")
        u = routines.generate_systemd_units(r)
        self.assertNotIn("\r", u.service)
        self.assertIn("%%h", u.service)
        bad = routines.Routine(id="r", name="n", task="t", schedule="daily\\")
        with self.assertRaises(ValueError):
            routines.generate_systemd_units(bad)
        with self.assertRaises(ValueError):
            routines.generate_systemd_units(r, wispd_bin="x\nExecStart=evil")

    def test_corrupt_store_is_moved_aside_not_overwritten(self):
        path = self.d / "routines.json"
        path.write_text("{not json")
        st = routines.RoutineStore(path)
        self.assertEqual(st.list(), [])
        self.assertTrue(list(self.d.glob("routines.json.corrupt-*")))

    def test_confirm_fn_does_not_reprompt_after_opt_in(self):
        st = routines.RoutineStore(self.d / "r.json")
        st.set_opted_in(True)
        calls = []
        ok = routines.require_first_opt_ingate(
            confirm_fn=lambda p: calls.append(p) or True, store=st)
        self.assertTrue(ok)
        self.assertEqual(calls, [])

    def test_outcome_for_unknown_routine_writes_nothing(self):
        st = routines.RoutineStore(self.d / "r.json")
        out = routines.record_routine_outcome("ghost", ok=True, store=st)
        self.assertEqual(out["error"], "unknown_routine")
        self.assertFalse(st.has_opted_in())
        self.assertFalse((self.d / "r.json").exists())

    # skills
    def test_non_positive_app_skill_budget_rejected(self):
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                skills.match_app_skill_info("chromium", budget_chars=bad)


if __name__ == "__main__":
    unittest.main()
