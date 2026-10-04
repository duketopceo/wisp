#!/usr/bin/env python3
"""Window-free QML components (W20, Ember U4): static rules.

Every file under shell-plugin/components/ is a visual part that W21 to W23
mount inside their own windows. The rules keep it that way: no window or
process or file access, no hex literals or named colors (tokens come from
service.tokens), copy only through service.ui() / Copy, and every
`service.X` a component reads must exist on WispService and on the
harness FixtureService, so a fixture render can never drift from the real
service.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
COMP = PLUGIN / "components"
FIXTURE_SERVICE = ROOT / "tests" / "qml" / "harness" / "FixtureService.qml"

EXPECTED = ["Answer", "AgentRow", "AgentsTab", "BarActions", "BarMark", "Beacon", "Bubble", "Chip", "Console",
            "Corner", "Creature", "EmptyState", "GhostCursor",
            "HealthSection", "Icon", "Mark", "MemoryTab", "NowTab",
            "PanelTab", "Pill", "SettingsTab", "StatusLine", "StepRow",
            "StopControl", "Transcript"]

FORBIDDEN = [
    (r"\bimport\s+Quickshell", "Quickshell import"),
    (r"\bimport\s+qs\.", "qs import"),
    (r"\b(PanelWindow|FloatingWindow|PopupWindow|Window|LazyLoader|"
     r"Variants|WlrLayershell)\s*\{", "window item"),
    (r"\b(Process|FileView|Socket|SplitParser|DataStream)\s*\{",
     "process or io item"),
    (r"state\.json|wispd\.sock|colors\.toml|shell\.toml", "direct file read"),
    (r"\bStyle\.|\bColor\.", "Omarchy Style/Color singleton"),
    (r"XMLHttpRequest", "xhr"),
]

_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"(?m)(^|[^:\"'\\])//.*$")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
NAMED = re.compile(
    r"\"(red|green|blue|white|black|gray|grey|yellow|orange|purple|pink|"
    r"cyan|magenta|brown|silver|gold)\"", re.I)


def code(path):
    src = _BLOCK.sub("", path.read_text())
    return _LINE.sub(lambda m: m.group(1), src)


def service_members(text):
    names = set()
    for m in re.finditer(
            r"(?:property\s+(?:readonly\s+)?\w+(?:<[^>]*>)?\s+|"
            r"function\s+|signal\s+)(\w+)", text):
        names.add(m.group(1))
    return names


def used_service_members(src):
    return set(re.findall(r"\bservice\.(\w+)", src))


class TestComponentSet(unittest.TestCase):
    def test_expected_components_exist(self):
        have = {p.stem for p in COMP.glob("*.qml")}
        self.assertEqual(set(EXPECTED) - have, set())
        self.assertEqual(have - set(EXPECTED), set(),
                         "new component: add it to EXPECTED and scenes.json")

    def test_every_component_has_a_scene(self):
        import json
        scenes = json.loads(
            (ROOT / "tests/qml/harness/scenes.json").read_text())
        self.assertEqual(set(EXPECTED) - {"Icon", "BarActions"} - set(scenes), set())

    def test_metrics_lib_has_no_colors(self):
        src = code(PLUGIN / "lib" / "metrics.js")
        self.assertIsNone(HEX.search(src))
        self.assertIn(".pragma library", src)


class TestComponentRules(unittest.TestCase):
    def test_forbidden_constructs(self):
        for p in sorted(COMP.glob("*.qml")):
            src = code(p)
            for rx, what in FORBIDDEN:
                self.assertIsNone(re.search(rx, src), f"{p.name}: {what}")

    def test_tokens_only(self):
        for p in sorted(COMP.glob("*.qml")):
            src = code(p)
            self.assertIsNone(HEX.search(src), f"{p.name}: hex literal")
            self.assertIsNone(NAMED.search(src), f"{p.name}: named color")
            self.assertNotRegex(src, r"Qt\.(rgba|hsla|hsva)\(\s*[\d.]+\s*,",
                                p.name)

    def test_every_component_has_a_header_comment(self):
        for p in sorted(COMP.glob("*.qml")):
            lines = [ln for ln in p.read_text().splitlines()
                     if ln.strip()]
            body = [ln for ln in lines if not ln.startswith("import")]
            self.assertTrue(body[0].startswith("//"), p.name)

    def test_looping_animation_only_in_creature_and_gated(self):
        for p in sorted(COMP.glob("*.qml")):
            src = code(p)
            if re.search(r"Animation\.Infinite|loops:\s*Animation", src):
                self.assertEqual(p.stem, "Creature")
                self.assertIn("motionMode", src)
                self.assertIn("Motion.loops", src)

    def test_motion_respects_service_mode(self):
        for p in sorted(COMP.glob("*.qml")):
            src = code(p)
            if re.search(r"\b(Behavior|NumberAnimation|ColorAnimation|"
                         r"SpringAnimation|SequentialAnimation)\b", src):
                self.assertIn("motionMode", src, p.name)


class TestCompanionRules(unittest.TestCase):
    """W21: no timers, no polling and no process spawns in components; the
    creature ships its baked shader and a plain-item fallback."""

    def test_no_timers_in_components(self):
        for p in sorted(COMP.glob("*.qml")):
            self.assertNotRegex(code(p), r"\bTimer\s*\{", p.name)

    def test_no_hyprctl_or_polling(self):
        for p in sorted(COMP.glob("*.qml")):
            self.assertNotRegex(code(p), r"hyprctl|cursorpos|setInterval",
                                p.name)

    def test_creature_ships_shader_and_fallback(self):
        src = code(COMP / "Creature.qml")
        m = re.search(r'resolvedUrl\("\.\./shaders/([\w.]+)"\)', src)
        self.assertIsNotNone(m)
        self.assertTrue((PLUGIN / "shaders" / m.group(1)).is_file())
        self.assertIn("GraphicsInfo.Software", src)
        self.assertIn("visible: !root.shaderOk", src)

    def test_ghost_cursor_reads_the_target_from_the_service(self):
        src = code(COMP / "GhostCursor.qml")
        self.assertIn("service.cuaTarget", src)

    def test_window_free_libs_have_no_colors(self):
        for name in ("creature", "cursor", "companion"):
            src = code(PLUGIN / "lib" / f"{name}.js")
            self.assertIsNone(HEX.search(src), name)
            self.assertIn(".pragma library", src)


class TestServiceSurface(unittest.TestCase):
    def test_service_members_exist_on_real_and_fixture_service(self):
        real = service_members((PLUGIN / "WispService.qml").read_text())
        fix = service_members(FIXTURE_SERVICE.read_text())
        used = set()
        for p in sorted(COMP.glob("*.qml")):
            used |= used_service_members(code(p))
        self.assertTrue(used, "components read nothing from service")
        self.assertEqual(used - real, set(), "missing on WispService")
        self.assertEqual(used - fix, set(), "missing on FixtureService")

    def test_fixture_service_mirrors_view_fields(self):
        real = service_members((PLUGIN / "WispService.qml").read_text())
        fix = service_members(FIXTURE_SERVICE.read_text())
        mirrored = {"status", "transcript", "answer", "result", "choices",
                    "promptId", "points", "steps", "suggestion", "goal",
                    "level", "tasks", "error", "errorCode", "health",
                    "offline", "stale", "tokens", "motionMode", "fontFamily",
                    "statusWord", "statusTone", "resultView", "notice",
                    "busy", "ui", "pickLabel", "errorMessage", "errorHint", "spend"}
        self.assertEqual(mirrored - real, set())
        self.assertEqual(mirrored - fix, set())


class TestPanelW22(unittest.TestCase):
    """W22: Panel is four tabs, no timers, no literal copy; Settings writes
    only through the service (wispd config set)."""

    PANEL = PLUGIN / "Panel.qml"

    def test_four_tabs(self):
        src = code(self.PANEL)
        self.assertIn('["now", "agents", "memory", "settings"]', src)

    def test_no_timer_or_polling(self):
        src = code(self.PANEL)
        self.assertNotRegex(src, r"\bTimer\s*\{")
        self.assertNotRegex(src, r"setInterval|repeat:\s*true")

    def test_panel_reads_state_only_through_the_service(self):
        src = code(self.PANEL)
        self.assertNotIn("state.json", src)
        self.assertNotIn("hostWidget.status", src)
        self.assertIn("hostWidget.service", src)

    def test_settings_write_through_service_config_set(self):
        self.assertIn("configSet", code(self.PANEL))
        svc = code(PLUGIN / "WispService.qml")
        self.assertIn("Settings.setCommand", svc)
        self.assertNotRegex(code(COMP / "SettingsTab.qml"),
                            r"config\.toml|\"config\", \"set\"")

    def test_settings_keys_exist_in_default_config(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from wisp import config
        import re as _re
        js = (PLUGIN / "lib" / "settings.js").read_text()
        keys = _re.findall(r'key: "([a-z_]+\.[a-z_]+)"', js)
        self.assertGreaterEqual(len(keys), 8)
        for k in keys:
            sec, _, name = k.partition(".")
            self.assertRegex(config.DEFAULT_CONFIG,
                             r"(?m)^%s\s*=" % _re.escape(name), k)


class TestPureLibs(unittest.TestCase):
    """metrics.js and steps.js run under node (skipped without it)."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT / "tests"))
        import jsnode
        if not jsnode.NODE:
            self.skipTest("node not installed")
        self.call = jsnode.call

    def test_step_rows(self):
        rows = self.call(
            "Steps.rows(['focus Settings -> ok', 'click rename -> ERROR x',"
            " 'run_shell rm -> BLOCKED (risk=0.9)', 'verify toggle'], true)",
            Steps="steps")
        self.assertEqual([r["state"] for r in rows],
                         ["done", "failed", "confirm", "running"])
        self.assertEqual(rows[0]["text"], "focus Settings")
        self.assertEqual(rows[0]["raw"], "focus Settings -> ok")

    def test_step_rows_idle_last_step_is_done(self):
        rows = self.call("Steps.rows(['verify toggle'], false)",
                         Steps="steps")
        self.assertEqual(rows[0]["state"], "done")

    def test_step_arrow_glyph_is_split(self):
        rows = self.call("Steps.rows(['click ok \\u2192 ERROR x'], false)",
                         Steps="steps")
        self.assertEqual(rows[0]["text"], "click ok")
        self.assertEqual(rows[0]["state"], "failed")

    def test_step_rows_tolerate_junk(self):
        self.assertEqual(self.call("Steps.rows(null, true)", Steps="steps"),
                         [])
        r = self.call("Steps.rows([null, 5], false)", Steps="steps")
        self.assertEqual(len(r), 2)

    def test_every_status_has_a_mark_and_token(self):
        statuses = ["idle", "listening", "transcribing", "deciding",
                    "awaiting_choice", "acting", "speaking", "suggestion",
                    "done", "error", "offline"]
        icons = self.call(f"{statuses}.map(M.markIcon)", M="metrics")
        self.assertTrue(all(i.startswith("bar-") for i in icons))
        for i in icons:
            self.assertIn(f"{i}", (ROOT / "shell-plugin/lib/icons.js")
                          .read_text())
        toks = self.call(f"{statuses}.map(M.markToken)", M="metrics")
        self.assertTrue(all(t for t in toks))
        self.assertEqual(self.call("M.markIcon('nope')", M="metrics"),
                         "bar-offline")

    def test_elapsed(self):
        self.assertEqual(self.call("[0, 47, 83, 301, -4, 'x'].map(M.elapsed)",
                                   M="metrics"),
                         ["0s", "47s", "1m 23s", "5m 01s", "0s", "0s"])

    def test_energy_is_bounded(self):
        self.assertAlmostEqual(
            self.call("M.energy('listening', 9)", M="metrics"), 0.9)
        self.assertEqual(self.call("M.energy('nope', 0)", M="metrics"),
                         0.25)

    def test_pill_radius_square_theme(self):
        self.assertEqual(self.call("M.pillRadius(30, 0)", M="metrics"), 0)
        self.assertEqual(self.call("M.pillRadius(30, 8)", M="metrics"), 15)


QMLLINT = shutil.which("qmllint") or (
    "/usr/lib/qt6/bin/qmllint"
    if os.path.exists("/usr/lib/qt6/bin/qmllint") else None)


@unittest.skipUnless(QMLLINT, "qmllint not installed")
class TestQmllint(unittest.TestCase):
    def test_components_lint_without_errors(self):
        # Components import only QtQuick and sibling files, so no qs shims
        # are needed. (WispService.qml, which does, is linted with the
        # Commons shim in test_wisp_service.py.)
        files = sorted(str(p) for p in COMP.glob("*.qml"))
        self.assertTrue(files)
        for f in files:
            p = subprocess.run([QMLLINT, f], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{f}\n{p.stdout}{p.stderr}")
            self.assertNotRegex(p.stdout + p.stderr, r"(?m)^Error", f)


if __name__ == "__main__":
    unittest.main()
