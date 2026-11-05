"""B31 UI wiring contracts and executable service JS, without Quickshell."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"


def service_function(name):
    src = (PLUGIN / "WispService.qml").read_text()
    start = src.find("function " + name + "(")
    if start < 0:
        raise AssertionError(f"service function {name} is missing")
    opening = src.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (src[end] == "{") - (src[end] == "}")
        end += 1
    return src[start:end]


class GrowthUiTest(unittest.TestCase):
    def test_now_tab_mounts_a_window_free_token_styled_recap(self):
        card = PLUGIN / "components" / "WeeklyRecapCard.qml"
        self.assertTrue(card.exists(), "weekly recap card is missing")
        src = card.read_text()
        self.assertIn("textFormat: Text.PlainText", src)
        self.assertIn("wrapMode: Text.Wrap", src)
        self.assertIn("M.spacing", src)
        self.assertIn("root.tk.raised", src)
        self.assertIn("root.card.summary", src)
        self.assertIn("root.card.spend_note", src)
        self.assertIn("root.card.activity_note", src)
        self.assertNotRegex(src, r"\b(Process|Timer|FileView|Socket)\s*\{")
        self.assertNotIn("XMLHttpRequest", src)
        now = (PLUGIN / "components" / "NowTab.qml").read_text()
        self.assertIn("WeeklyRecapCard {", now)
        self.assertIn("service.weeklyRecap", now)
        self.assertIn("service.disableRecap()", now)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_service_gates_claim_and_discards_inflight_reply_after_off(self):
        functions = "\n".join(service_function(name) for name in (
            "loadConfig", "loadRecap", "finishRecap", "disableRecap"))
        harness = """
const assert = require('node:assert/strict');
const calls = [];
const root = {wispd:'/fake/wispd', recapEnabled:false,
  recapVisible:false,
  recapSuppressed:false, weeklyRecap:null, recapReadRequested:false,
  runAction:(cmd, verb)=>{ calls.push({cmd,verb}); return true; }};
const cfgProc = {running:false};
const recapProc = {running:false};
function runAction(cmd,verb) { return root.runAction(cmd,verb); }
"""
        assertions = """
loadConfig();
assert.equal(root.recapReadRequested, true);
assert.equal(cfgProc.running, true);
loadRecap();
assert.equal(recapProc.running, false);
root.recapEnabled = true;
loadRecap();
assert.equal(recapProc.running, false);
root.recapVisible = true;
loadRecap();
assert.equal(recapProc.running, true);
const reply = JSON.stringify({ok:true,data:{enabled:true,card:{turns:6}}});
finishRecap(0, reply);
assert.deepEqual(root.weeklyRecap, {turns:6});
recapProc.running = false;
loadRecap();
assert.equal(recapProc.running, false); // config/visibility callbacks cannot erase it
disableRecap();
assert.equal(root.weeklyRecap, null);
assert.equal(root.recapSuppressed, true);
assert.deepEqual(calls[0].cmd, ['/fake/wispd','recap','--off','--json']);
finishRecap(0, reply);
assert.equal(root.weeklyRecap, null);
root.recapSuppressed = false;
finishRecap(1, reply);
assert.equal(root.weeklyRecap, null);
finishRecap(0, 'bad json');
assert.equal(root.weeklyRecap, null);
"""
        result = subprocess.run(["node", "-e", harness + functions + assertions],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        svc = (PLUGIN / "WispService.qml").read_text()
        self.assertIn('[root.wispd, "recap", "--claim", "--json"]', svc)
        self.assertIn("root.loadRecap()", svc)
