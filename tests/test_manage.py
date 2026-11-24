#!/usr/bin/env python3
"""Status and management pages and the TUI (W26): one data path, two
renderers.

  - TUI text for each view is golden (tests/golden/tui/*.txt) over fixture
    JSON in tests/fixtures/manage/. Regenerate with UPDATE_GOLDEN=1.
  - Parity: the Python model builders in wisp/tui.py return exactly what
    shell-plugin/lib/health.js and lib/manage.js return for the same JSON,
    and the QML views read every field of those models.
  - The pages live in the settings window (shells/settings/shell.qml,
    one-surface U3 retired the console app). It uses the W17 service, opens
    no state.json, and has no timer: nothing polls.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import copylint  # noqa: E402
import jsnode  # noqa: E402
from wisp import cua_safety, tui  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "manage"
GOLD = ROOT / "tests" / "golden" / "tui"
APP = ROOT / "shells" / "settings"
SHELL = (APP / "shell.qml").read_text()
CODE = re.sub(r"(?m)^\s*//.*$", "", SHELL)  # comments may name state.json
COMP = ROOT / "shell-plugin" / "components"
PAGE = (COMP / "ManagePage.qml").read_text()
_TZ = None


def setUpModule():
    global _TZ
    _TZ = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()


def tearDownModule():
    if _TZ is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _TZ
    time.tzset()


def load(name):
    return json.loads((FIX / name).read_text())


STATE = load("state.json")
CUA = load("cua_status.json")
SPEND = load("spend_cli.json")
HEALTH_CLI = load("health_cli.json")
BINDS = load("binds_cli.json")
AUDIT = (FIX / "cua.jsonl").read_text()


def text(lines):
    return "\n".join(t for t, _ in lines) + "\n"


def golden(name, lines):
    path = GOLD / f"{name}.txt"
    got = text(lines)
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(got)
    return path.read_text(), got


class TestTuiGolden(unittest.TestCase):
    def check(self, name, lines):
        want, got = golden(name, lines)
        self.assertEqual(got, want, name)

    def test_health_from_state_rows(self):
        self.check("health", tui.view_lines("health", {
            "health": STATE["health"], "spend": STATE["spend"],
            "cua": CUA, "models": SPEND["models"]}))

    def test_health_offline_from_cli_json(self):
        self.check("health_offline", tui.view_lines("health", {
            "endpoints": HEALTH_CLI, "notice": "wisp is not running"}))

    def test_spend(self):
        self.check("spend", tui.view_lines("spend", {
            "spend": STATE["spend"], "models": SPEND["models"]}))

    def test_spend_empty(self):
        self.check("spend_empty", tui.view_lines("spend", {}))

    def test_audit(self):
        self.check("audit", tui.view_lines("audit", {"audit": AUDIT}))

    def test_audit_empty(self):
        self.check("audit_empty", tui.view_lines("audit", {"audit": ""}))

    def test_binds_with_submap(self):
        self.check("binds", tui.view_lines("binds", {"binds": BINDS}))

    def test_binds_without_submap_or_hyprland(self):
        data = {"hotkey": BINDS["hotkey"], "hyprland": False, "binds": []}
        self.check("binds_none", tui.view_lines("binds", {"binds": data}))

    def test_roles_follow_state(self):
        roles = {t.strip().split(" ")[0]: r for t, r in
                 tui.view_lines("health", {"health": STATE["health"]})}
        self.assertEqual(roles["ok"], "ok")
        self.assertEqual(roles["DOWN"], "fail")

    def test_every_line_is_plain_copy(self):
        for name, lines in (
                ("health", tui.view_lines("health", {
                    "health": STATE["health"], "spend": STATE["spend"],
                    "cua": CUA, "models": SPEND["models"]})),
                ("audit", tui.view_lines("audit", {"audit": AUDIT})),
                ("binds", tui.view_lines("binds", {"binds": BINDS}))):
            for line, _ in lines:
                self.assertEqual(copylint.check_string(line), [], line)
                self.assertTrue(line.isascii(), (name, line))

    def test_no_typed_text_anywhere_in_audit_view(self):
        out = text(tui.view_lines("audit", {"audit": AUDIT}))
        for secret in ("3fa9c01be2d4", "ctrl+l", "640", "380"):
            self.assertNotIn(secret, out)


class TestAuditSource(unittest.TestCase):
    def test_reads_the_cua_safety_audit_path_read_only(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "cua.jsonl"
            p.write_text(AUDIT)
            before = p.read_bytes()
            with mock.patch.object(cua_safety, "audit_default_path",
                                   return_value=p):
                self.assertEqual(tui.audit_text(), AUDIT)
            self.assertEqual(p.read_bytes(), before)

    def test_missing_log_is_empty(self):
        with mock.patch.object(cua_safety, "audit_default_path",
                               return_value=pathlib.Path("/nonexistent/x")):
            self.assertEqual(tui.audit_text(), "")

    def test_app_reads_the_same_path(self):
        self.assertIn('"/wisp/cua.jsonl"', SHELL)
        self.assertEqual(
            cua_safety.audit_default_path().parts[-2:], ("wisp", "cua.jsonl"))

    def test_rows_hold_only_display_fields(self):
        for r in tui.audit_rows(AUDIT):
            self.assertEqual(set(r), {"time", "tool", "app", "decision",
                                      "result", "ms", "dryRun"})


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestParity(unittest.TestCase):
    def js(self, expr, **libs):
        return jsnode.call(expr, **libs)

    def same(self, js_expr, py, **libs):
        self.assertEqual(self.js(js_expr, **libs), json.loads(json.dumps(py)))

    def test_sections(self):
        for health in (STATE["health"], {}, None,
                       {"x": {"ok": True, "latency_ms": "7"}, "y": 3}):
            self.same(f"H.sections({json.dumps(health)})",
                      tui.sections(health), H="health")

    def test_spend_view(self):
        for sp in (STATE["spend"], {}, None,
                   {"today_usd": 0.5, "cap_usd": None, "month_usd": 1},
                   {"today_usd": 1, "cap_usd": 4, "monthly_cap_usd": 9.999}):
            self.same(f"H.spendView({json.dumps(sp)})",
                      tui.spend_view(sp), H="health")

    def test_cua_view(self):
        for c in (CUA, None, {}, {"state": "running", "live": True}):
            self.same(f"H.cuaView({json.dumps(c)})", tui.cua_view(c),
                      H="health")

    def test_model_rows(self):
        for m in (SPEND["models"], [], None, [{"model": "a"}, 5]):
            self.same(f"H.modelRows({json.dumps(m)})", tui.model_rows(m),
                      H="health")

    def test_spend_models(self):
        for m in (SPEND["models"], [], None, [{"model": "a", "in": 3}]):
            self.same(f"M.spendModels({json.dumps(m)})",
                      tui.spend_models(m), M="manage")

    def test_audit_rows(self):
        for limit in (50, 2):
            self.same(f"M.auditRows({json.dumps(AUDIT)}, {limit})",
                      tui.audit_rows(AUDIT, limit), M="manage")
        self.same("M.auditRows('', 5)", tui.audit_rows("", 5), M="manage")

    def test_chord_and_binds(self):
        for mask in (0, 1, 4, 8, 64, 65, 77):
            self.same(f"M.chord({mask}, 'D')", tui.chord(mask, "D"),
                      M="manage")
        for b in (BINDS, None, {"hyprland": True, "binds": []}):
            self.same(f"M.bindsView({json.dumps(b)})", tui.binds_view(b),
                      M="manage")

    def test_decision_tone(self):
        for d in ("allow", "deny", "dry_run", "cancelled", "", "x"):
            self.same(f"M.decisionTone({json.dumps(d)})",
                      tui.decision_tone(d), M="manage")

    def test_health_json_and_state_rows_give_one_model(self):
        # `wispd health --json` through the converter reads like state rows
        want = [e for e in HEALTH_CLI["endpoints"]]
        sec = tui.sections(tui.health_from_endpoints(HEALTH_CLI))
        self.assertEqual(sorted((e["name"], e["ok"], e["code"], e["latencyMs"])
                                for e in sec["endpoints"]),
                         sorted((e["name"], e["ok"], e["code"], e["latency_ms"])
                                for e in want))
        self.same(f"H.sections({json.dumps(tui.health_from_endpoints(HEALTH_CLI))})",
                  sec, H="health")


class TestViewsReadEveryField(unittest.TestCase):
    """The QML views and the TUI builders share one model: every field a
    builder produces is read by a view (a few are TUI or fixture only)."""

    def src(self, *names):
        return "".join((COMP / f"{n}.qml").read_text() for n in names)

    def assertReads(self, model, src, skip=()):
        for key in model:
            if key in skip:
                continue
            self.assertRegex(src, rf"\.{key}\b", key)

    def test_health_and_spend_fields(self):
        health = self.src("HealthSection")
        self.assertReads(tui.sections(STATE["health"]), health)
        self.assertReads(tui.spend_view(STATE["spend"]), health)
        self.assertReads(tui.cua_view(CUA), health, skip=("mode",))
        self.assertReads(tui.spend_view(STATE["spend"]), self.src("SpendView"))
        self.assertReads(tui.model_rows(SPEND["models"])[0], health)

    def test_spend_view_reads_the_model_table_fields(self):
        self.assertReads(tui.spend_models(SPEND["models"])[0],
                         self.src("SpendView"))

    def test_audit_and_binds_fields(self):
        self.assertReads(tui.audit_rows(AUDIT)[0], self.src("AuditView"),
                         skip=("result", "dryRun"))
        b = tui.binds_view(BINDS)
        self.assertReads(b, self.src("BindsView"))
        self.assertReads(b["global"][0], self.src("BindsView"),
                         skip=("submap",))

    def test_views_use_the_shared_builders(self):
        self.assertIn("H.sections", self.src("HealthSection"))
        self.assertIn("H.spendView", self.src("SpendView"))
        self.assertIn("Manage.auditRows", self.src("AuditView"))
        self.assertIn("Manage.bindsView", self.src("BindsView"))
        self.assertIn("HealthSection", self.src("HealthView"))

    def test_app_hands_each_view_its_wispd_json(self):
        # the window feeds the host, the page hands each view its part
        for frag in ("cua: svc.cuaStatus", "spendModels: svc.spendModels",
                     "auditText: win.auditText", "binds: win.bindsData",
                     '"binds", "--json"'):
            self.assertIn(frag, SHELL, frag)
        for frag in ("cua: root.cua", "spendModels: root.spendModels",
                     "models: root.spendModels", "log: root.auditText",
                     "binds: root.binds"):
            self.assertIn(frag, PAGE, frag)

    def test_tui_runs_the_same_wispd_commands(self):
        src = (ROOT / "wisp" / "tui.py").read_text()
        for argv in ('["cua", "status"]', '["spend"]', '["binds"]',
                     '["health"]'):
            self.assertIn(f"fetch_json({argv})", src)
        self.assertIn("audit_default_path", src)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestPageHelpers(unittest.TestCase):
    """lib/manage.js helpers behind the settings window's pages."""

    def js(self, expr):
        return jsnode.call(expr, Manage="manage")

    def test_page_state_priority(self):
        cases = [((False, True, True, "exit"), "loading"),
                 ((True, True, True, "exit"), "error"),
                 ((True, True, True, ""), "offline"),
                 ((True, False, True, ""), "stale"),
                 ((True, False, False, ""), "ready")]
        for args, want in cases:
            heard, offline, stale, err = args
            got = self.js(f"Manage.pageState({json.dumps(heard)}, "
                          f"{json.dumps(offline)}, {json.dumps(stale)}, "
                          f"{json.dumps(err)})")
            self.assertEqual(got, want, args)
        # loading and error replace the page; offline and stale keep it
        self.assertEqual(self.js(
            '["loading","error","offline","stale","ready"]'
            ".map(Manage.showsContent)"),
            [False, False, True, True, True])

    def test_turn_rows_keep_the_newest_and_skip_bad_lines(self):
        lines = [json.dumps({"ts": f"2026-11-24T10:00:{i:02d}",
                             "answers": {"route": {"choice": "act"}},
                             "timing_ms": {"act_ms": i},
                             "transcript": f"t{i}", "result": f"r{i}"})
                 for i in range(35)]
        text = "\n".join(lines[:10] + ["{bad"] + lines[10:])
        rows = self.js(f"Manage.turnRows({json.dumps(text)}, 30)")
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0], {"time": "10:00:34", "route": "act",
                                   "ms": 34, "you": "t34", "wisp": "r34"})
        self.assertEqual(rows[-1]["you"], "t5")
        self.assertEqual(self.js('Manage.turnRows("", 30)'), [])

    def test_open_suggestions_take_the_latest_record_per_key(self):
        text = "\n".join(json.dumps(r) for r in (
            {"key": "a", "status": "new", "title": "A"},
            {"key": "b", "status": "new", "title": "B"},
            {"key": "a", "status": "accepted"},
            {"key": "c", "status": "new", "title": "C"}))
        got = self.js(f"Manage.openSuggestions({json.dumps(text)})")
        self.assertEqual([r["key"] for r in got], ["c", "b"])

    def test_corrections_newest_first(self):
        text = "\n".join(f"c{i}" for i in range(10)) + "\n\n"
        self.assertEqual(
            self.js(f"Manage.correctionLines({json.dumps(text)}, 6)"),
            ["c9", "c8", "c7", "c6", "c5", "c4"])

    def test_binds_read(self):
        ok = json.dumps({"ok": True, "data": BINDS})
        self.assertEqual(self.js(f"Manage.bindsRead(0, {json.dumps(ok)})"),
                         {"data": BINDS, "error": ""})
        self.assertEqual(self.js('Manage.bindsRead(1, "")'),
                         {"data": None, "error": "exit"})
        self.assertEqual(self.js('Manage.bindsRead(0, "{bad")'),
                         {"data": None, "error": "parse"})

    def test_utf8_base64_matches_python(self):
        import base64
        for text in ("", "plain", "dash \u2014 and \u00e9", "emoji \U0001F600 end",
                     "# Memory\n\n- line\n"):
            # with an identity encoder the helper returns the UTF-8 bytes as a
            # Latin-1 string, which is exactly what Qt.btoa encodes
            raw = self.js(f"Manage.utf8Base64({json.dumps(text)}, "
                          "function (s) { return s })")
            self.assertEqual(base64.b64encode(raw.encode("latin1")).decode(),
                             base64.b64encode(text.encode()).decode(), repr(text))

    def test_task_hint_key(self):
        self.assertEqual(self.js('Manage.taskHintKey({status: "interrupted"})'),
                         "ui.tasks.interrupted")
        self.assertEqual(self.js('Manage.taskHintKey({status: "running", waiting: true})'),
                         "ui.tasks.waiting")
        self.assertEqual(self.js('Manage.taskHintKey({status: "running"})'), "")
        from wisp import copy as wcopy
        for k in ("ui.tasks.interrupted", "ui.tasks.waiting"):
            self.assertIn(k, wcopy.STRINGS)

    def test_task_of_reads_old_and_new_shapes(self):
        self.assertEqual(self.js('Manage.taskOf("running")'),
                         {"status": "running", "task": ""})
        self.assertEqual(self.js('Manage.taskOf(undefined)'),
                         {"status": "", "task": ""})


class TestConsoleRetired(unittest.TestCase):
    def test_no_reference_to_the_console_outside_history(self):
        # the changelog and the historical plans keep the record
        # walk the tree rather than ask git: CI's container checkout is
        # owned by another user, so `git ls-files` refuses to run there
        skip_dirs = {".git", "node_modules", "target", "__pycache__",
                     ".venv", "dist", "build", ".codebase-memory"}
        files = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for name in filenames:
                files.append(os.path.relpath(os.path.join(dirpath, name), ROOT))
        allowed = ("CHANGELOG.md", "docs/plans/")
        me = "tests/test_manage.py"
        hits = []
        for rel in files:
            if rel.startswith(allowed) or rel == me:
                continue
            f = ROOT / rel
            if not f.is_file() or f.is_symlink():
                continue
            try:
                if "shells/debug" in f.read_text(errors="strict"):
                    hits.append(rel)
            except (UnicodeDecodeError, OSError):
                continue
        self.assertEqual(hits, [])


class TestFeed(unittest.TestCase):
    def test_snapshot_diff_and_health_event(self):
        s = tui.apply_message({}, {"type": "snapshot", "seq": 1,
                                   "state": {"status": "idle",
                                             "health": {"jev": {"ok": True}}}})
        self.assertEqual(s["status"], "idle")
        s = tui.apply_message(s, {"type": "state", "seq": 2,
                                  "diff": {"status": "acting", "seq": 2}})
        self.assertEqual((s["status"], s["health"]["jev"]["ok"]),
                         ("acting", True))
        s = tui.apply_message(s, {"type": "event", "name": "health_changed",
                                  "data": {"name": "jev", "ok": False,
                                           "code": "jev_down"}})
        self.assertEqual(s["health"]["jev"], {"ok": False,
                                              "code": "jev_down"})
        self.assertIs(tui.apply_message(s, {"type": "ping"}), s)

    def test_loop_blocks_in_select_not_on_a_timer(self):
        src = (ROOT / "wisp" / "tui.py").read_text()
        self.assertIn("select.select([sys.stdin, feed.rfd]", src)
        self.assertNotIn("win.timeout(", src)
        self.assertNotIn('"cmd": "status"', src)


class TestAppNeverPolls(unittest.TestCase):
    def test_uses_the_service_not_its_own_reader(self):
        self.assertRegex(SHELL, r"WispService\s*\{\s*id:\s*svc")
        self.assertIsNone(re.search(r"state\.json|stateFile", CODE))
        self.assertNotIn("socket", CODE.lower())

    def test_no_timer_anywhere(self):
        self.assertIsNone(re.search(r"\bTimer\s*\{", SHELL))
        self.assertIsNone(re.search(r"\brepeat:\s*true", SHELL))
        self.assertIsNone(re.search(r"\bpollMs|setInterval", SHELL))

    def test_every_filewatch_is_event_driven(self):
        # each FileView that is not a one-shot note read reloads on change,
        # watched only while its page is open and read when it opens
        for fid, page in (("decisionsView", "activity"), ("corrView", "activity"),
                          ("suggView", "activity"), ("auditView", "audit")):
            m = re.search(rf"id:\s*{fid}\b(.*?)\n  \}}", SHELL, re.S)
            self.assertIn(f'watchChanges: host.category === "{page}"', m.group(1), fid)
            self.assertIn("preload: false", m.group(1), fid)
            self.assertIn("onFileChanged: reload()", m.group(1), fid)
            self.assertIn(f"{fid}.reload()", SHELL, fid)

    def test_wispd_results_are_read_when_a_view_opens(self):
        self.assertIn("win.enter(host.category)", SHELL)
        m = re.search(r"function enter\(page\) \{(.*?)\n  \}", SHELL, re.S)
        self.assertIn('page === "health" || page === "spend"', m.group(1))
        self.assertIn("svc.loadSettings()", m.group(1))
        self.assertIn("bindsProc.running = true", m.group(1))

    def test_no_hex_literal_and_no_legacy_theme_reader(self):
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", CODE), [])
        self.assertNotIn("colors.toml", CODE)
        self.assertNotIn("Tokens.load", SHELL)

    def test_views_are_present_in_order(self):
        from wisp import settings_schema as S
        self.assertEqual(S.SIDEBAR,
                         ("home", "activity", "memory", "tasks")
                         + S.CATEGORIES
                         + ("health", "spend", "audit", "binds"))
        # every page has a view in the page's component map
        m = re.search(r"sourceComponent: \(\{(.*?)\}\)", PAGE, re.S)
        self.assertEqual(re.findall(r"(\w+): \w+Page", m.group(1)),
                         list(S.PAGES))

    def test_copy_lint_is_clean(self):
        self.assertEqual(
            copylint.violations(copylint.qml_strings(SHELL)), [])

    def test_page_titles_come_from_the_copy_table(self):
        from wisp import copy as wcopy
        from wisp import settings_schema as S
        for k in S.SIDEBAR:
            self.assertIn(f"set.cat.{k}", wcopy.STRINGS)
        for k in ("settings", "status"):
            self.assertIn(f"set.group.{k}", wcopy.STRINGS)
        for st in ("loading", "offline", "stale", "error"):
            self.assertIn(f"ui.page.{st}", wcopy.STRINGS)
            self.assertIn(f"ui.page.{st}.hint", wcopy.STRINGS)

    def test_actions_run_through_run_action(self):
        # the console called svc.run(...), which is a view model, not a
        # function; every page action goes through runAction or the
        # service's own entry points
        code = re.sub(r"(?m)^\s*//.*$", "", SHELL)
        self.assertNotRegex(code, r"\bsvc\.run\s*\(")
        self.assertIn('svc.runAction(["systemctl", "--user", verb, "wispd"], "daemon")', code)
        self.assertIn('onRestart: win.daemon("restart")', code)
        self.assertIn('onStop: win.daemon("stop")', code)
        self.assertIn('svc.runAction([svc.wispd].concat(args).concat(["--json"]), verb)', code)
        # notes go on stdin as base64 of UTF-8; task text follows `--`
        self.assertIn('svc.runAction([svc.wispd, "memory", "write", which, "--stdin", "--json"],', code)
        self.assertIn('"memory", null, Manage.utf8Base64(text, Qt.btoa))', code)
        self.assertIn('svc.runAction([svc.wispd, "task", "run", "--json", "--", text], "task")', code)
        self.assertIn('win.wispd(["task", "cancel", name], "task")', code)
        self.assertIn("onAnswer: (pick) => svc.sendChoice(pick)", code)
        self.assertIn("onTalk: svc.trigger()", code)


class TestAppFiles(unittest.TestCase):
    def test_shim_and_links(self):
        for name, target in (("WispService.qml", "../../shell-plugin/WispService.qml"),
                             ("lib", "../../shell-plugin/lib"),
                             ("components", "../../shell-plugin/components")):
            self.assertEqual(os.readlink(APP / name), target, name)
            self.assertTrue((APP / name).exists(), name)
        # the shim is the window's own directory, not a link into the
        # retired console
        self.assertTrue((APP / "Commons").is_dir())
        self.assertFalse((APP / "Commons").is_symlink())
        self.assertFalse((ROOT / "shells" / "debug").exists())
        qmldir = (APP / "Commons" / "qmldir").read_text()
        self.assertIn("module qs.Commons", qmldir)
        for name in ("Color", "Style"):
            self.assertIn(f"singleton {name} ", qmldir)
            self.assertIn("pragma Singleton",
                          (APP / "Commons" / f"{name}.qml").read_text())

    def test_shim_covers_what_the_service_reads(self):
        svc = (ROOT / "shell-plugin" / "WispService.qml").read_text()
        color = (APP / "Commons" / "Color.qml").read_text()
        style = (APP / "Commons" / "Style.qml").read_text()
        for m in set(re.findall(r"\bColor\.(\w+)", svc)):
            self.assertRegex(color, rf"\b{m}\b", f"Color.{m}")
        for m in set(re.findall(r"\bStyle\.(\w+)", svc)):
            self.assertRegex(style, rf"\b{m}\b", f"Style.{m}")
        for sig in re.findall(r"function on(\w+)Changed", svc):
            self.assertRegex(color, rf"property \w+ {sig.lower()}\b", sig)
        self.assertNotRegex(color, r"\bTimer\b")


QMLLINT = shutil.which("qmllint") or (
    "/usr/lib/qt6/bin/qmllint"
    if os.path.exists("/usr/lib/qt6/bin/qmllint") else None)


@unittest.skipUnless(QMLLINT, "qmllint not installed")
class TestQmllint(unittest.TestCase):
    def test_app_and_shim_lint_without_errors(self):
        # the window resolves qs.Commons to its own Commons/ shim
        files = [APP / "shell.qml", APP / "Commons" / "Color.qml",
                 APP / "Commons" / "Style.qml"]
        files += [COMP / f"{n}.qml" for n in (
            "HealthView", "SpendView", "AuditView", "BindsView", "ManagePage",
            "HomeView", "ActivityView", "MemoryView", "AgentsView")]
        for f in files:
            p = subprocess.run([QMLLINT, "-I", str(APP.parent), str(f)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{f}\n{p.stdout}{p.stderr}")
            self.assertNotRegex(p.stdout + p.stderr, r"(?m)^Error", str(f))

    def test_manage_lib_lints(self):
        p = subprocess.run([QMLLINT, str(ROOT / "shell-plugin/lib/manage.js")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_wisp_service_has_no_name_collisions(self):
        # qs.Commons stays unresolved standalone — only the duplicated-name
        # class is gated here (a `run` property once shadowed the run()
        # action method, making every click throw).
        p = subprocess.run([QMLLINT, str(ROOT / "shell-plugin" / "WispService.qml")],
                           capture_output=True, text=True)
        self.assertNotIn("duplicated-name", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
