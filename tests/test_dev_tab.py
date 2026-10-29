#!/usr/bin/env python3
"""U5: the Dev tab, local only. shell-plugin/lib/dev.js (pure, under node),
plus static wiring checks: the `[dev] panel` flag, the one-shot devlog
Process in WispService (open and refresh only, never a timer), the
flag-gated fifth tab in Panel, the component's rules, scenes and goldens.
qmltestrunner is not needed."""
import json
import pathlib
import re
import sys
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
HARNESS = ROOT / "tests" / "qml" / "harness"
sys.path.insert(0, str(ROOT))


def read(p):
    return pathlib.Path(p).read_text()


def js(expr):
    return jsnode.call(expr, D="dev")


def turn(**kw):
    t = {"id": "t1", "turn": "t1", "ts": "x", "transcript": "hi",
         "route": "act", "kind": "act", "result": "ACTED: 4 steps",
         "label": "none", "note": "", "total_ms": 1000,
         "stages": [{"name": "stt", "ms": 250}, {"name": "brain", "ms": 750}],
         "act_steps": 4}
    t.update(kw)
    return t


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestDevLib(unittest.TestCase):
    def test_pct(self):
        self.assertEqual(js("D.pct(0.274)"), "27%")
        self.assertEqual(js("D.pct(0)"), "0%")
        self.assertEqual(js("D.pct(null)"), "-")

    def test_gate_below_is_fail_at_or_above_is_ok(self):
        g = {"rate": 0.5, "gate_rate": 0.8, "labelled": 4, "min_turns": 20,
             "kinds": {}}
        v = js("D.gateView(%s)" % json.dumps(g))
        self.assertEqual((v["tone"], v["rateText"], v["gateText"]),
                         ("fail", "50%", "80%"))
        self.assertAlmostEqual(v["fill"], 0.5)
        self.assertAlmostEqual(v["tick"], 0.8)
        for r in (0.8, 0.95):
            g["rate"] = r
            self.assertEqual(
                js("D.gateView(%s)" % json.dumps(g))["tone"], "ok")

    def test_gate_unset_has_no_tick_and_is_muted(self):
        v = js("D.gateView(%s)" % json.dumps(
            {"rate": 0.5, "gate_rate": None, "labelled": 1, "min_turns": 5,
             "kinds": {}}))
        self.assertEqual(v["tone"], "muted")
        self.assertEqual(v["tick"], -1)
        v = js("D.gateView(%s)" % json.dumps(
            {"rate": None, "gate_rate": 0.8, "labelled": 0, "min_turns": 5,
             "kinds": {}}))
        self.assertEqual((v["tone"], v["rateText"], v["fill"]),
                         ("muted", "-", 0))

    def test_kind_line(self):
        k = {"act": {"rate": 0.27}, "launch": {"rate": 0.5},
             "answer": {"rate": 0}, "skip": {"rate": None}}
        self.assertEqual(js("D.kindLine(%s)" % json.dumps(k)),
                         "act 27% · launch 50% · answer 0%")
        self.assertEqual(js("D.kindLine({})"), "")

    def test_stage_shares_use_total_and_never_overflow(self):
        s = js("D.stageShares(%s, 1000)" % json.dumps(turn()["stages"]))
        self.assertEqual([x["name"] for x in s], ["stt", "brain"])
        self.assertAlmostEqual(s[0]["share"], 0.25)
        self.assertAlmostEqual(s[1]["share"], 0.75)
        # stages summing past the total: shares still add to at most 1
        s = js("D.stageShares(%s, 500)" % json.dumps(turn()["stages"]))
        self.assertLessEqual(sum(x["share"] for x in s), 1.0000001)
        self.assertEqual(js("D.stageShares([], 100)"), [])
        self.assertEqual(js("D.stageShares(null, null)"), [])
        # no total: shares are of the sum
        s = js("D.stageShares(%s, null)" % json.dumps(turn()["stages"]))
        self.assertAlmostEqual(s[0]["share"], 0.25)

    def test_bar_widths_fit_and_keep_tiny_stages_visible(self):
        sh = [{"name": "a", "ms": 1, "share": 0.001},
              {"name": "b", "ms": 999, "share": 0.999}]
        w = js("D.barWidths(%s, 150)" % json.dumps(sh))
        self.assertGreaterEqual(w[0], 1)
        self.assertLessEqual(sum(w), 150)

    def test_seconds_and_route_line(self):
        self.assertEqual(js("D.seconds(2400)"), "2.4 s")
        self.assertEqual(js("D.seconds(null)"), "-")
        words = {"step": "step", "steps": "steps"}
        line = lambda t: js("D.routeLine(%s, %s)" % (
            json.dumps(t), json.dumps(words)))
        self.assertEqual(line(turn(total_ms=2400)),
                         "act · 4 steps · 2.4 s")
        self.assertEqual(line(turn(act_steps=1, total_ms=None)),
                         "act · 1 step")
        self.assertEqual(line(turn(route="", act_steps=None, total_ms=900)),
                         "0.9 s")

    def test_label_icon(self):
        self.assertEqual(js("D.labelIcon('correct')"), "check")
        self.assertEqual(js("D.labelIcon('incorrect')"), "cross")
        self.assertEqual(js("D.labelIcon('none')"), "hollow")
        self.assertEqual(js("D.labelIcon('corrected-by-retry')"), "hollow")

    def test_selection_defaults_to_newest(self):
        ts = [turn(id="n"), turn(id="o")]
        self.assertEqual(js("D.selected(%s, '')" % json.dumps(ts))["id"], "n")
        self.assertEqual(js("D.selected(%s, 'o')" % json.dumps(ts))["id"], "o")
        self.assertEqual(js("D.selected(%s, 'gone')" % json.dumps(ts))["id"],
                         "n")
        self.assertIsNone(js("D.selected([], '')"))

    def test_stage_colors_are_stable_and_distinct(self):
        ts = [turn(stages=[{"name": "stt", "ms": 1}, {"name": "brain", "ms": 1}]),
              turn(stages=[{"name": "tts", "ms": 1}, {"name": "stt", "ms": 1}])]
        names = js("D.stageNames(%s)" % json.dumps(ts))
        self.assertEqual(names, ["stt", "brain", "tts"])
        toks = [js("D.stageToken(%s, %r)" % (json.dumps(names), n))
                for n in names]
        self.assertEqual(len(set(toks)), 3)
        self.assertEqual(js("D.stageToken([], 'zz')"), "inkMuted")

    def test_command_and_parse(self):
        self.assertEqual(js("D.command('/x/wispd')"),
                         ["/x/wispd", "dev", "turns", "--json"])
        body = {"turns": [], "gate": {}}
        r = js("D.parse(%r)" % json.dumps({"ok": True, "data": body}))
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["turns"], [])
        self.assertFalse(js("D.parse('')")["ok"])
        self.assertFalse(js("D.parse('not json')")["ok"])
        self.assertFalse(js("D.parse(%r)" % json.dumps(
            {"ok": False, "error": {"code": "E_X"}}))["ok"])

    def test_empty(self):
        self.assertTrue(js("D.isEmpty({turns: [], gate: {labelled: 0}})"))
        self.assertFalse(js("D.isEmpty({turns: [%s]})" % json.dumps(turn())))
        self.assertTrue(js("D.isEmpty(null)"))


class TestFlag(unittest.TestCase):
    def test_setting_exists_and_defaults_off(self):
        from wisp import config, settings_schema
        f = settings_schema.field("dev.panel")
        self.assertIsNotNone(f)
        self.assertEqual((f.kind, f.default), ("bool", "false"))
        self.assertFalse(f.panel)
        self.assertRegex(config.DEFAULT_CONFIG, r"(?m)^\[dev\]")
        self.assertRegex(config.DEFAULT_CONFIG, r"(?m)^panel\s*=\s*false")
        self.assertIn("dev.panel", read(PLUGIN / "lib" / "settings_schema.js"))

    def test_documented(self):
        self.assertIn("`[dev] panel`", read(ROOT / "docs" / "CONFIG.md"))


class TestWiring(unittest.TestCase):
    def setUp(self):
        self.svc = read(PLUGIN / "WispService.qml")
        self.panel = read(PLUGIN / "Panel.qml")
        self.fix = read(HARNESS / "FixtureService.qml")

    def test_flag_off_no_dev_call(self):
        # the only place the command is built is behind the flag
        m = re.search(r"function loadDev\(\)\s*\{(.*?)\n  \}", self.svc, re.S)
        self.assertIsNotNone(m, "loadDev() missing")
        self.assertIn("devPanel", m.group(1))
        self.assertIn("devProc", m.group(1))
        self.assertEqual(len(re.findall(r"devProc\.running\s*=\s*true",
                                        self.svc)), 1)

    def test_proc_is_one_shot_devlog_command(self):
        m = re.search(r"Process\s*\{\s*id:\s*devProc(.*?)\n  \}", self.svc, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("Dev.command", body + self.svc)
        self.assertIn("Dev.parse", body)
        self.assertNotRegex(body, r"Timer|FileView")

    def test_no_timer_drives_dev(self):
        self.assertNotRegex(self.svc, r"Timer\s*\{[^}]*loadDev")
        self.assertNotRegex(self.panel, r"Timer\s*\{")

    def test_service_members_mirrored_in_fixture(self):
        for name in ("devPanel", "devData", "devLoading", "devError",
                     "loadDev"):
            self.assertRegex(self.svc, name)
            self.assertRegex(self.fix, name)

    def test_panel_five_tabs_only_with_flag(self):
        self.assertIn('["now", "agents", "memory", "settings"]', self.panel)
        self.assertRegex(self.panel,
                         r"tabKeys:\s*service && service\.devPanel\s*\?"
                         r"\s*baseTabs\.concat\(\[\"devtab\"\]\)\s*:\s*baseTabs")
        # Settings stays index 3, Dev is index 4
        self.assertIn("tab === 3", self.panel)
        self.assertRegex(self.panel, r"DevTab\s*\{[^}]*?visible:\s*"
                                     r"wisp\.devPanelOn && wisp\.tab === 4",
                         )

    def test_loads_only_on_open_and_refresh(self):
        calls = [m.start() for m in re.finditer(r"loadDev\(\)", self.panel)]
        self.assertTrue(calls)
        # the panel wiring: tab change to 4, panel open on 4, refresh signal
        self.assertRegex(self.panel, r"onTabChanged:[^\n]*loadDev|"
                                     r"onTabChanged:\s*\{[^}]*loadDev")
        self.assertRegex(self.panel, r"onRefresh:\s*[^\n]*loadDev\(\)")
        self.assertRegex(self.panel, r"opened[^\n]*tab === 4[^\n]*loadDev|"
                                     r"tab === 4[^\n]*loadDev")

    def test_component_rules(self):
        src = read(PLUGIN / "components" / "DevTab.qml")
        self.assertNotRegex(src, r"\b(Timer|Process|FileView)\s*\{")
        self.assertIn("motionMode", src)
        self.assertNotRegex(src, r"#[0-9a-fA-F]{3,8}\b")
        self.assertNotIn("open trace", src.lower())  # no file open path exists

    def test_copy_keys(self):
        from wisp import copy
        for k in ("ui.tab.devtab", "ui.dev.local", "ui.dev.gate", "ui.dev.recent",
                  "ui.dev.misses", "ui.dev.empty", "ui.dev.loading",
                  "ui.dev.error", "ui.dev.refresh"):
            self.assertIn(k, copy.STRINGS)


class TestScenes(unittest.TestCase):
    def test_scene_and_goldens(self):
        scenes = json.loads(read(HARNESS / "scenes.json"))
        self.assertIn("DevTab", scenes)
        names = set(scenes["DevTab"]["variants"])
        self.assertTrue({"data", "empty", "loading", "error"} <= names)
        for theme in ("dark", "light"):
            for v in names:
                g = ROOT / "tests" / "qml" / "snapshots" / theme / "1x" / \
                    f"DevTab__{v}.png"
                self.assertTrue(g.exists(), g)

    def test_data_variant_selects_a_turn(self):
        scenes = json.loads(read(HARNESS / "scenes.json"))
        d = scenes["DevTab"]["variants"]["data"]
        self.assertTrue(d["reply"]["turns"])
        self.assertTrue(d.get("selectedId"))


if __name__ == "__main__":
    unittest.main()
