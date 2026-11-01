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
        self.assertFalse(f.quick)
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
        # the only place the command is built is behind the flag or session
        m = re.search(r"function loadDev\(\)\s*\{(.*?)\n  \}", self.svc, re.S)
        self.assertIsNotNone(m, "loadDev() missing")
        self.assertIn("devTab", m.group(1))
        self.assertIn("devProc", m.group(1))
        self.assertEqual(len(re.findall(r"devProc\.running\s*=\s*true",
                                        self.svc)), 1)
        self.assertEqual(len(re.findall(r"devRunsProc\.running\s*=\s*true",
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
                     "loadDev", "devTab", "devOn", "devRunsLeft", "devRuns",
                     "devRunsLoading", "devRunsError"):
            self.assertRegex(self.svc, name)
            self.assertRegex(self.fix, name)

    def test_panel_five_tabs_only_with_flag(self):
        self.assertIn('["now", "agents", "memory", "settings"]', self.panel)
        self.assertRegex(self.panel,
                         r"tabKeys:\s*service && service\.devTab\s*\?"
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
        self.assertTrue({"data", "empty", "loading", "error", "runs",
                         "runs_empty", "runs_ab"} <= names)
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


def runsum(**kw):
    r = {"run_id": "20261030T081200Z", "tasks": 6, "ran": 6, "judged_n": 5,
         "unjudged": 1, "judge_capped": False,
         "mix": {"judged": {"success": 3, "stopped": 1, "incomplete": 1,
                            "wrong_tries": 0, "unjudged": 1},
                 "confirmed": {"correct": 2, "incorrect": 1,
                               "unreviewed": 3}},
         "accuracy": {"judged": 0.6, "confirmed": 2 / 3},
         "drift_count": 1,
         "cost": {"task_usd": 0.01, "judge_usd": 0.0112, "total_usd": 0.0212},
         "stage_ms": {"wall": 9000},
         "started": "2026-10-30T08:12:09+00:00",
         "ended": "2026-10-30T08:13:40+00:00", "rows": []}
    r.update(kw)
    return r


WORDS = {"success": "success", "stopped": "stopped",
         "incomplete": "incomplete", "wrong_tries": "wrong tries",
         "unjudged": "unjudged", "a": "A better", "b": "B better",
         "tie": "tie"}


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestRunsLib(unittest.TestCase):
    def test_command_and_parse(self):
        self.assertEqual(js("D.runsCommand('/x/wispd')"),
                         ["/x/wispd", "dev", "runs", "--json"])
        body = {"runs": [runsum()]}
        r = js("D.parseRuns(%r)" % json.dumps({"ok": True, "data": body}))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["data"]["runs"]), 1)
        self.assertTrue(js("D.parseRuns(%r)" % json.dumps(body))["ok"])
        self.assertFalse(js("D.parseRuns('')")["ok"])
        self.assertFalse(js("D.parseRuns(%r)" % json.dumps(
            {"turns": []}))["ok"])
        self.assertEqual(js("D.parseRuns(%r)" % json.dumps(
            {"ok": False, "error": {"code": "E_X"}}))["error"], "E_X")

    def test_empty_and_latest(self):
        self.assertTrue(js("D.isRunsEmpty(null)"))
        self.assertTrue(js("D.isRunsEmpty({runs: []})"))
        a, b = runsum(run_id="new"), runsum(run_id="old")
        d = json.dumps({"runs": [a, b]})
        self.assertFalse(js("D.isRunsEmpty(%s)" % d))
        self.assertEqual(js("D.latestRun(%s)" % d)["run_id"], "new")
        self.assertIsNone(js("D.latestRun({runs: []})"))

    def test_run_view_summary(self):
        v = js("D.runView(%s, %s)" % (json.dumps(runsum()),
                                      json.dumps(WORDS)))
        self.assertEqual(v["when"], "2026-10-30 08:12")
        self.assertEqual(v["judged"], "60%")
        self.assertEqual(v["confirmed"], "67%")
        self.assertEqual(v["tasks"], 6)
        self.assertEqual(v["drift"], 1)
        self.assertEqual(v["cost"], "$0.021")
        self.assertFalse(v["ab"])
        keys = [s["key"] for s in v["segments"]]
        self.assertEqual(keys, ["success", "incomplete", "stopped",
                                "unjudged"])
        self.assertAlmostEqual(sum(s["share"] for s in v["segments"]), 1.0)
        self.assertEqual(v["mixLine"],
                         "3 success \u00b7 1 incomplete \u00b7 1 stopped"
                         " \u00b7 1 unjudged")

    def test_run_view_unknowns_are_dashes(self):
        r = runsum(accuracy={"judged": None, "confirmed": None},
                   cost={}, started=None, ended=None, mix={}, tasks=0)
        v = js("D.runView(%s, %s)" % (json.dumps(r), json.dumps(WORDS)))
        self.assertEqual((v["judged"], v["confirmed"], v["cost"]),
                         ("-", "-", "-"))
        self.assertEqual(v["when"], "20261030T081200Z")
        self.assertEqual(v["segments"], [])

    def test_run_view_ab_pair_line(self):
        pairs = [{"index": i, "goal": "g", "a": "success", "b": "stopped",
                  "better": b} for i, b in enumerate(
                      ["a", "a", "b", "tie"])]
        r = runsum(vs="brain.default=acme/model", pairs=pairs,
                   arms={"a": runsum(), "b": runsum()})
        v = js("D.runView(%s, %s)" % (json.dumps(r), json.dumps(WORDS)))
        self.assertTrue(v["ab"])
        self.assertEqual(v["vs"], "brain.default=acme/model")
        self.assertEqual(v["pairLine"],
                         "2 A better \u00b7 1 B better \u00b7 1 tie")

    def test_badge_text(self):
        w = {"dev": "dev", "local": "local", "one": "run left",
             "many": "runs left"}
        self.assertEqual(js("D.badgeText(true, 3, %s)" % json.dumps(w)),
                         "dev \u00b7 3 runs left")
        self.assertEqual(js("D.badgeText(true, 1, %s)" % json.dumps(w)),
                         "dev \u00b7 1 run left")
        self.assertEqual(js("D.badgeText(false, 0, %s)" % json.dumps(w)),
                         "local")

    def test_session_helpers(self):
        self.assertTrue(js("D.sessionOn({dev: {on: true, runs_left: 4}})"))
        self.assertFalse(js("D.sessionOn({dev: {on: 'yes'}})"))
        self.assertFalse(js("D.sessionOn({})"))
        self.assertFalse(js("D.sessionOn(null)"))
        self.assertEqual(js("D.runsLeft({dev: {on: true, runs_left: 4}})"), 4)
        self.assertEqual(js("D.runsLeft({dev: {on: true, runs_left: -2}})"), 0)
        self.assertEqual(js("D.runsLeft({})"), 0)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestBarDevBadge(unittest.TestCase):
    BASE = {"status": "idle", "result": "", "errorCode": "",
            "offline": False, "confirm": False, "windowOpen": False,
            "rateable": False, "run": None}

    def pill(self, **kw):
        o = dict(self.BASE, **kw)
        return jsnode.call("B.pillState(%s)" % json.dumps(o), B="bar")

    def test_idle_without_dev_is_still_hidden(self):
        v = self.pill()
        self.assertFalse(v["visible"])
        self.assertFalse(v.get("dev", False))

    def test_idle_with_dev_shows_only_the_badge(self):
        v = self.pill(dev=True)
        self.assertTrue(v["visible"])
        self.assertTrue(v["dev"])
        self.assertEqual((v["kind"], v["glyph"], v["wordKey"]),
                         ("idle", "", ""))

    def test_live_state_keeps_its_pill_and_gains_the_badge(self):
        v = self.pill(status="acting", dev=True)
        self.assertEqual((v["kind"], v["glyph"]), ("acting", "act"))
        self.assertTrue(v["dev"])
        self.assertFalse(self.pill(status="acting")["dev"])

    def test_error_keeps_its_red_border_with_dev(self):
        v = self.pill(status="error", errorCode="timeout", dev=True)
        self.assertEqual((v["kind"], v["border"]), ("error", "fail"))
        self.assertTrue(v["dev"])

    def test_offline_never_shows_the_badge(self):
        v = self.pill(offline=True, dev=True)
        self.assertFalse(v["visible"])

    def test_badge_uses_the_yellow_token(self):
        src = read(PLUGIN / "components" / "BarPill.qml")
        self.assertRegex(src, r"info\.dev")
        self.assertIn("root.tk.needsYou", src.split("info.dev", 1)[1])
        self.assertIn("ui.bar.badge", src)
        self.assertNotRegex(src, r"\bTimer\s*\{")


class TestRunsWiring(unittest.TestCase):
    def setUp(self):
        self.svc = read(PLUGIN / "WispService.qml")
        self.panel = read(PLUGIN / "Panel.qml")
        self.tab = read(PLUGIN / "components" / "DevTab.qml")

    def test_runs_proc_is_one_shot_and_loaded_with_the_turns(self):
        m = re.search(r"Process\s*\{\s*id:\s*devRunsProc(.*?)\n  \}",
                      self.svc, re.S)
        self.assertIsNotNone(m)
        self.assertIn("Dev.parseRuns", m.group(1))
        self.assertNotRegex(m.group(1), r"Timer|FileView")
        self.assertIn("Dev.runsCommand", self.svc)
        loader = re.search(r"function loadDev\(\)\s*\{(.*?)\n  \}",
                           self.svc, re.S).group(1)
        self.assertIn("devRunsProc", loader)

    def test_session_flag_reads_state_dev_field(self):
        self.assertRegex(self.svc, r"devOn:\s*Dev\.sessionOn")
        self.assertRegex(self.svc, r"devTab:\s*devPanel \|\| devOn")

    def test_panel_badge_and_runs_wiring(self):
        self.assertIn("Dev.badgeText", self.panel)
        self.assertIn("service.devTab", self.panel)
        self.assertRegex(self.panel, r"runsReply:\s*col\.svc\.devRuns")
        self.assertIn("devOn", self.panel)

    def test_dev_tab_runs_section_rules(self):
        self.assertIn("D.runView", self.tab)
        self.assertIn("ui.dev.runs.empty", self.tab)
        self.assertNotRegex(self.tab, r"\b(Timer|Process|FileView)\s*\{")

    def test_new_copy_keys(self):
        from wisp import copy
        for k in ("ui.bar.badge", "ui.dev.badge.one", "ui.dev.badge.many",
                  "ui.dev.runs", "ui.dev.runs.empty", "ui.dev.runs.error",
                  "ui.dev.out.success", "ui.dev.out.stopped",
                  "ui.dev.out.incomplete", "ui.dev.out.wrong_tries",
                  "ui.dev.out.unjudged", "ui.dev.pair.a", "ui.dev.pair.b",
                  "ui.dev.pair.tie"):
            self.assertIn(k, copy.STRINGS)

    def test_goldens_exist(self):
        for theme in ("dark", "light"):
            base = ROOT / "tests" / "qml" / "snapshots" / theme / "1x"
            for name in ("DevTab__runs", "DevTab__runs_empty",
                         "DevTab__runs_ab", "BarPillWindow__dev_idle",
                         "BarPillWindow__dev_acting"):
                self.assertTrue((base / f"{name}.png").exists(), name)


if __name__ == "__main__":
    unittest.main()
