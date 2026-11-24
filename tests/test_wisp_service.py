#!/usr/bin/env python3
"""WispService.qml static checks (W17).

The service is Quickshell glue over shell-plugin/lib/state.js (whose
behavior is tested in test_state_reader.py and tests/qml/lib/tst_state.qml).
quickshell cannot run headless here, so these tests pin the shape: the
public properties, signals and functions every surface binds to, the
library imports, the transport wiring and the single-reader rule. When
qmllint is installed the file must also lint clean of errors.
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
SRC = (PLUGIN / "WispService.qml").read_text()

PROPS = ["view", "status", "rawStatus", "transcript", "answer", "result",
         "choices", "promptId", "points", "steps", "actions",
         "suggestion", "guide", "chips",
         "windowFocus", "goal", "goalStatus", "level", "tasks", "error",
         "errorCode", "health", "turnId", "seq", "contractVersion",
         "connection", "offline", "stale", "contractNewer",
         "statusWord", "statusTone", "resultView", "errorMessage",
         "errorHint", "notice", "tokens", "tokenSource", "themeMode",
         "motionMode", "staleAfterMs", "streamEnabled", "motionConfig",
         "animationsEnabled", "shell", "manifest", "lastAction"]
SIGNALS = ["stateApplied", "turnChanged"]
FUNCTIONS = ["ui", "pickLabel", "sendChoice", "interrupt", "trigger",
             "label", "refresh", "reconnect"]


class TestShape(unittest.TestCase):
    def test_properties(self):
        have = set(re.findall(r"property\s+\w+\s+(\w+)", SRC))
        for p in PROPS:
            self.assertIn(p, have, p)

    def test_signals(self):
        have = set(re.findall(r"^\s*signal\s+(\w+)", SRC, re.M))
        for s in SIGNALS:
            self.assertIn(s, have, s)

    def test_functions(self):
        have = set(re.findall(r"^\s*function\s+(\w+)", SRC, re.M))
        for f in FUNCTIONS:
            self.assertIn(f, have, f)

    def test_imports_shared_libs(self):
        for lib in ("state.js", "copy.js", "tokens.js", "motion.js"):
            self.assertRegex(SRC, rf'\.import\s+"lib/{re.escape(lib)}"|'
                                  rf'import\s+"lib/{re.escape(lib)}"',
                             lib)

    def test_reads_contract_through_the_reducer(self):
        for call in ("applySnapshot", "applyMessage", "markOffline",
                     "isStale", "backoffMs", "subscribeRequest"):
            self.assertIn(call, SRC, call)

    def test_stream_transport_with_file_fallback(self):
        self.assertIn("Socket", SRC)
        self.assertIn("wispd.sock", SRC)
        self.assertIn("FileView", SRC)
        self.assertIn("state.json", SRC)
        self.assertIn("colors.toml", SRC)

    def test_does_not_shadow_item_properties(self):
        have = set(re.findall(r"property\s+\w+\s+(\w+)", SRC))
        self.assertFalse(have & {"focus", "visible", "enabled", "state",
                                 "data", "children", "parent"}, have)

    def test_stale_default_is_above_heartbeat(self):
        self.assertRegex(SRC, r"staleAfterMs:\s*20000|Reader\.STALE_AFTER_MS")

    def test_no_sub_two_second_timer_while_idle(self):
        for m in re.finditer(r"Timer\s*\{(.*?)\n\s*\}", SRC, re.S):
            body = m.group(1)
            iv = re.search(r"interval:\s*(\d+)", body)
            if iv and int(iv.group(1)) < 2000:
                self.assertRegex(body, r"running:[^\n]*(busy|stale|Busy)",
                                 "fast timer must run only while busy")

    def test_every_repeating_timer_is_gated_on_a_condition(self):
        # nothing repeats unconditionally: each repeat:true Timer's running
        # binding names the state that justifies it
        for m in re.finditer(r"Timer\s*\{(.*?)\n\s*\}", SRC, re.S):
            body = m.group(1)
            if re.search(r"repeat:\s*true", body):
                self.assertRegex(body, r"running:[^\n]*(busy|stale|refused|connection)",
                                 "a repeating timer must be gated")

    def test_rating_window_is_one_single_shot_timer(self):
        # U3: the bar pill's 8 s done window. Single-shot, runs only while
        # the window is open and the pill is not hovered; never at idle.
        timers = [m.group(1) for m in re.finditer(r"Timer\s*\{(.*?)\n\s*\}", SRC, re.S)
                  if "ratingTimer" in m.group(1)]
        self.assertEqual(len(timers), 1)
        body = timers[0]
        self.assertRegex(body, r"interval:\s*B\.WINDOW_MS|interval:\s*8000")
        self.assertRegex(body, r"repeat:\s*false")
        self.assertRegex(body, r"running:[^\n]*ratingWindowOpen[^\n]*!\s*root\.pillHover"
                               r"|running:[^\n]*!\s*root\.pillHover[^\n]*ratingWindowOpen")
        self.assertRegex(body, r"ratingWindowOpen\s*=\s*false")
        for prop in ("ratingWindowOpen", "pillHover"):
            self.assertRegex(SRC, r"property\s+bool\s+" + prop)
        self.assertIn("B.windowAction", SRC)

    def test_no_hex_colors(self):
        code = re.sub(r"//.*", "", SRC)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", code), [])


class TestSingleReader(unittest.TestCase):
    """Only the service may own a FileView on state.json. The surfaces
    still carrying their own reader are counted so the number can only go
    down; W21 to W23 delete them."""

    RATCHET = {"BarWidget.qml": 0}

    def test_service_is_a_reader(self):
        self.assertRegex(SRC, r"FileView\s*\{[^}]*state\.json|stateFile")

    def test_other_surfaces_do_not_add_readers(self):
        for p in PLUGIN.rglob("*.qml"):
            if p.name == "WispService.qml":
                continue
            n = len(re.findall(r"path:\s*root\.stateFile", p.read_text()))
            ceiling = self.RATCHET.get(p.name, 0)
            self.assertLessEqual(n, ceiling, p.name)
            if n < ceiling:
                self.fail(f"{p.name} dropped to {n}: lower RATCHET")


    def test_management_app_ratchet_is_zero(self):
        # the settings window (management pages) reads state only through
        # the service
        app = (ROOT / "shells" / "settings" / "shell.qml").read_text()
        code = re.sub(r"(?m)^\s*//.*$", "", app)
        self.assertEqual(len(re.findall(r"state\.json|stateFile", code)), 0)
        self.assertIn("WispService", code)


class TestManifest(unittest.TestCase):
    def test_service_entry_point_is_this_file(self):
        import json
        m = json.loads((PLUGIN / "manifest.json").read_text())
        self.assertEqual(m["entryPoints"]["service"], "WispService.qml")
        self.assertIn("service", m["kinds"])


class TestActionLifecycle(unittest.TestCase):
    """U1: every surface action produces ack + terminal state. The action
    subprocess collects both streams, exit code lands in lastAction via
    Reader.actionResult, concurrent clicks queue (bounded, a full queue
    refuses loudly), and no path is a silent drop."""

    def test_action_process_collects_output_and_reports_exit(self):
        m = re.search(r"Process\s*\{\s*id:\s*actionProc(.*?)\n\s*\}",
                      SRC, re.S)
        self.assertIsNotNone(m, "actionProc not found")
        body = m.group(1)
        self.assertIn("stdout: StdioCollector", body)
        self.assertIn("stderr: StdioCollector", body)
        self.assertIn("onExited", body)
        self.assertIn("finishAction", body)

    def test_typed_text_goes_to_stdin_not_argv(self):
        # other local accounts can read argv while a process runs
        m = re.search(r"function sendChoice.*?\n  \}", SRC, re.S)
        self.assertIn('"choice", "--stdin"', m.group(0))
        self.assertNotRegex(m.group(0), r'\[wispd, "choice", pick')
        self.assertIn('[wispd, "ask", "--stdin", "--json"]', SRC)
        self.assertRegex(SRC, r"stdinEnabled:\s*true")
        self.assertIn("actionProc.write(", SRC)
        self.assertRegex(SRC, r"onStarted:\s*root\.writeActionStdin\(\)")

    def test_actions_are_serial_with_a_visible_busy_cap(self):
        self.assertIn("actionQueue", SRC)
        self.assertIn("actionProc.running", SRC)
        # a full queue refuses through lastAction, not a silent drop
        self.assertRegex(SRC, r'Copy\.errorMessage\("busy"\)')

    def test_exit_result_normalizes_through_the_reducer(self):
        self.assertIn("Reader.actionResult", SRC)
        self.assertIn("Copy.errorMessage", SRC)
        # empty success still acks ("noted"), never an empty string
        self.assertIn('Copy.string("ui.noted")', SRC)

    def test_local_choice_refusal_reaches_last_action(self):
        self.assertIn("Reader.acceptChoice", SRC)
        self.assertIn('Copy.errorMessage("stale_prompt")', SRC)
        # --prompt-id is conditional (suggestion picks carry none)
        self.assertRegex(SRC, r"if\s*\(pid\)\s*cmd\s*=\s*cmd\.concat")

    def test_confirm_card_uses_snapshotted_picks(self):
        bubble = (PLUGIN / "components" / "Bubble.qml").read_text()
        self.assertIn("root.card.allow", bubble)
        self.assertIn("root.card.deny", bubble)
        # no live choice-array reads inside click handlers
        self.assertNotRegex(bubble, r"onClicked[^\n]*service\.choices\[")

    def test_label_click_renders_an_ack(self):
        now = (PLUGIN / "components" / "NowTab.qml").read_text()
        # the answer card's ack moved into RateRow (U2)
        row = (PLUGIN / "components" / "RateRow.qml").read_text()
        self.assertIn("lastAction", now)
        self.assertIn("ui.noted", now)
        self.assertIn("lastAction", row)

    def test_settings_window_calls_existing_service_entrypoints(self):
        app = (ROOT / "shells" / "settings" / "shell.qml").read_text()
        code = re.sub(r"(?m)^\s*//.*$", "", app)
        # every action goes through runAction or a service entry point;
        # the console's svc.run(...) called a view model, not a function
        self.assertNotRegex(code, r"\bsvc\.run\s*\(")
        self.assertNotRegex(code, r"\bwin\.svc\s*\(")
        for fn in re.findall(r"\bsvc\.(\w+)\s*\(", code):
            self.assertRegex(SRC, rf"function {fn}\s*\(", fn)
        # suggestion buttons take the same ack path as every other action
        self.assertIn("svc.sendChoice(pick)", code)

class TestSettingsWindowReads(unittest.TestCase):
    """U5: the settings window's service surface. The write queue rules are
    pure functions in lib/settings.js (tested in tst_settings_search.qml);
    these pin that the service routes every write through them and wires
    the status and connector reads."""

    def test_writes_go_through_the_queue_rules(self):
        m = re.search(r"function configSet.*?\n  \}", SRC, re.S)
        self.assertIsNotNone(m)
        self.assertIn("Settings.formatValue", m.group(0))
        self.assertIn("Settings.enqueueWrite", m.group(0))
        self.assertIn("pumpConfig()", m.group(0))
        pump = re.search(r"function pumpConfig.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("if (setProc.running || setActive) return", pump)
        self.assertIn("Settings.nextWrite", pump)
        # one config read after a burst of writes, when the queue drains
        self.assertIn("if (configDirty) { configDirty = false; readConfig(); }",
                      pump)
        # the in-flight flag is set before the process starts
        self.assertLess(pump.index("setActive = true"),
                        pump.index("setProc.running = true"))
        done = re.search(r"function finishSet.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("Settings.finishWrite", done)
        self.assertIn("if (!setActive) return;", done)
        # the next write never starts inside the exit handler: a late
        # running=false would otherwise be taken for its spawn failure
        self.assertNotIn("pumpConfig()", done)
        proc = re.search(r"id: setProc.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("Qt.callLater(root.settleSet)", proc)
        settle = re.search(r"function settleSet.*?\n  \}", SRC, re.S).group(0)
        # a write still in flight a tick after the process stopped had no
        # exited: a spawn failure; either way the next write starts
        self.assertIn("if (setActive) finishSet(127", settle)
        self.assertIn("pumpConfig()", settle)
        # exactly one config-set process: writes never overlap
        self.assertEqual(len(re.findall(r'"config",\s*"set"', SRC)), 0)
        self.assertEqual(SRC.count("setProc.running = true"), 1)

    def test_config_read_marks_loaded_whatever_the_exit(self):
        m = re.search(r"Process\s*\{\s*id:\s*cfgProc(.*?)\n  \}\n", SRC, re.S)
        body = m.group(1)
        self.assertIn("stderr: StdioCollector", body)
        loaded = body.index("configLoaded = true")
        failed = body.index("code !== 0")
        self.assertLess(loaded, failed)
        self.assertIn("configReadError", body)

    def test_status_probe_is_one_shot_and_exit_three_is_offline(self):
        self.assertRegex(SRC, r'\[root\.wispd,\s*"status",\s*"--json"\]')
        self.assertRegex(SRC, r"settingsOffline:\s*statusCode === 3")
        retry = re.search(r"function retrySettings.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("readConfig()", retry)
        self.assertIn("statusProc.running = true", retry)

    def test_connectors_read_the_envelope_and_add_runs_per_alias(self):
        self.assertRegex(
            SRC, r'\[root\.wispd,\s*"connect",\s*"list",\s*"--json"\]')
        self.assertIn("doc.data.connectors", SRC)
        self.assertRegex(
            SRC, r'\[wispd,\s*"connect",\s*"add",\s*alias\]')
        add = re.search(r"function connectAdd.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("connAddProc.running", add)
        fin = re.search(r"function finishConnect.*?\n  \}", SRC, re.S).group(0)
        self.assertIn("loadConnectors()", fin)
        self.assertIn("connectorErrors", fin)

    def test_panel_no_longer_reads_connectors(self):
        # the Panel's Quick tab has no connector list (one-surface U2);
        # the settings window's Connectors page is the one path
        panel = (PLUGIN / "Panel.qml").read_text()
        self.assertNotIn('"connect", "--list"', panel)
        self.assertIn('"connect", "list", "--json"', SRC)


QMLLINT = shutil.which("qmllint") or (
    "/usr/lib/qt6/bin/qmllint"
    if os.path.exists("/usr/lib/qt6/bin/qmllint") else None)


@unittest.skipUnless(QMLLINT, "qmllint not installed")
class TestQmllint(unittest.TestCase):
    def test_service_lints_without_errors(self):
        with tempfile.TemporaryDirectory() as d:
            qs = pathlib.Path(d) / "qs"
            qs.mkdir()
            shell = pathlib.Path("/usr/share/omarchy/shell")
            for mod in ("Commons", "Ui"):
                if (shell / mod).exists():
                    (qs / mod).symlink_to(shell / mod)
            p = subprocess.run(
                [QMLLINT, "-I", d, str(PLUGIN / "WispService.qml")],
                capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotRegex(p.stdout + p.stderr, r"(?m)^Error")

    def test_libs_lint(self):
        for js in sorted((PLUGIN / "lib").glob("*.js")):
            p = subprocess.run([QMLLINT, str(js)], capture_output=True,
                               text=True)
            self.assertEqual(p.returncode, 0, f"{js.name}: {p.stdout}")


if __name__ == "__main__":
    unittest.main()
