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
         "choices", "promptId", "points", "steps", "suggestion", "guide",
         "windowFocus", "goal", "goalStatus", "level", "tasks", "error",
         "errorCode", "health", "turnId", "seq", "contractVersion",
         "connection", "offline", "stale", "contractNewer",
         "statusWord", "statusTone", "resultView", "errorMessage",
         "errorHint", "notice", "tokens", "tokenSource", "themeMode",
         "motionMode", "staleAfterMs", "streamEnabled", "motionConfig",
         "animationsEnabled", "shell", "manifest"]
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

    def test_no_hex_colors(self):
        code = re.sub(r"//.*", "", SRC)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", code), [])


class TestSingleReader(unittest.TestCase):
    """Only the service may own a FileView on state.json. The surfaces
    still carrying their own reader are counted so the number can only go
    down; W21 to W23 delete them."""

    RATCHET = {"BarWidget.qml": 0, "Companion.qml": 1}

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
        # W26: the management app reads state only through the service
        app = (ROOT / "shells" / "debug" / "shell.qml").read_text()
        code = re.sub(r"(?m)^\s*//.*$", "", app)
        self.assertEqual(len(re.findall(r"state\.json|stateFile", code)), 0)
        self.assertIn("WispService", code)


class TestManifest(unittest.TestCase):
    def test_service_entry_point_is_this_file(self):
        import json
        m = json.loads((PLUGIN / "manifest.json").read_text())
        self.assertEqual(m["entryPoints"]["service"], "WispService.qml")
        self.assertIn("service", m["kinds"])


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
