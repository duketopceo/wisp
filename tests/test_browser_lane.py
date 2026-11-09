"""B14 watchable browser lane: the loopback protocol, pairing, the
refusals (stale refs, password fields, too many steps), Stop within a
second, the proof screenshot and the extension manifest. A fake extension
speaks the real HTTP protocol, so no browser is needed."""
import base64
import http.client
import json
import pathlib
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from wisp import cua_safety, tools, trace
from wisp.tools import browser

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
CFG = {"browser": {"lane": "extension"}, "cua": {"audit": "false"}}

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def request(lane, method, path, body=None, token="", origin=ORIGIN,
            host=None):
    c = http.client.HTTPConnection("127.0.0.1", lane.port, timeout=30)
    h = {"Host": host or f"127.0.0.1:{lane.port}"}
    if origin is not None:
        h["Origin"] = origin
    if token:
        h["X-Wisp-Token"] = token
    if body is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, json.dumps(body) if body is not None else None,
              h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, (json.loads(raw) if raw else {})


class FakeExtension(threading.Thread):
    """Polls like the real extension and answers from a tiny page model:
    a login form (email + password) and a button. Records every command."""

    def __init__(self, lane, hang_on=""):
        super().__init__(daemon=True)
        self.lane, self.token = lane, ""
        self.hang_on = hang_on
        self.cmds = []
        self.epoch = 0
        self.live = True

    def pair(self):
        code = self.lane.new_code()
        st, body = request(self.lane, "POST", "/pair", {"code": code})
        assert st == 200, (st, body)
        self.token = body["token"]
        self.start()

    def run(self):
        while self.live:
            try:
                st, body = request(self.lane, "POST", "/poll", {"wait": 1},
                                   token=self.token)
            except OSError:
                return
            cmd = body.get("cmd") if st == 200 else None
            if not cmd:
                continue
            self.cmds.append(cmd)
            res = self.answer(cmd)
            if res is not None:
                request(self.lane, "POST", "/result",
                        dict(res, id=cmd["id"]), token=self.token)

    def answer(self, cmd):
        if cmd.get("op") != "batch":
            return {"ok": True, "results": []}
        results = []
        for s in cmd["steps"]:
            op = s["do"]
            if op == self.hang_on:
                return None            # never answers: a stuck page
            if op == "open":
                results.append({"ok": True, "tab": 7})
            elif op == "snapshot":
                self.epoch += 1
                e = self.epoch
                results.append({"ok": True, "epoch": e, "tab": 7,
                                "url": "https://x.test/login",
                                "title": "Sign in", "text": "Sign in",
                                "elements": [
                                    {"ref": f"{e}:0", "tag": "input",
                                     "type": "text", "name": "Email",
                                     "sensitive": False, "value": ""},
                                    {"ref": f"{e}:1", "tag": "input",
                                     "type": "password", "name": "Password",
                                     "sensitive": True, "value": ""},
                                    {"ref": f"{e}:2", "tag": "button",
                                     "type": "", "name": "Continue",
                                     "sensitive": False, "value": ""}]})
            elif op == "screenshot":
                results.append({"ok": True, "png": PNG})
            else:
                results.append({"ok": True})
        return {"ok": True, "results": results}

    def stop(self):
        self.live = False


class LaneCase(unittest.TestCase):
    def setUp(self):
        self.lane = browser.Lane(0)
        self.lane.start()
        self.addCleanup(self.lane.close)
        self.out = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out, True)
        self.turn = "t1"
        p = mock.patch.object(trace, "current", lambda: self.turn)
        p.start()
        self.addCleanup(p.stop)

    def paired(self, **kw):
        ext = FakeExtension(self.lane, **kw)
        ext.pair()
        self.addCleanup(ext.stop)
        return ext

    def run_tool(self, arg, cfg=CFG):
        return browser.run(arg, cfg, lane=self.lane, out_dir=self.out)

    def batch_cmds(self, ext):
        return [c for c in ext.cmds if c.get("op") == "batch"]


class Gating(LaneCase):
    def test_off_by_default(self):
        self.assertEqual(browser.run("snapshot", {}, lane=self.lane),
                         browser.MSG_OFF)
        self.assertEqual(browser.run("snapshot", {"browser": {"lane": "off"}},
                                     lane=self.lane), browser.MSG_OFF)
        self.assertTrue(browser.enabled(CFG))

    def test_unpaired_calls_fail_with_setup_and_do_nothing(self):
        out = self.run_tool("open https://example.com")
        self.assertTrue(out.startswith("SKIP (the browser lane is not paired"))
        self.assertRegex(out, r"\d{6}")
        self.assertIn("Nothing was done", out)
        self.assertTrue(self.lane._cmds.empty())

    def test_the_tool_is_offered_only_when_the_lane_is_on(self):
        off = {t["function"]["name"] for t in tools.tool_schemas({})}
        on = {t["function"]["name"] for t in tools.tool_schemas(CFG)}
        self.assertNotIn("browser", off)
        self.assertIn("browser", on)
        self.assertEqual(tools.meta_of("browser")["tier"], "T2")

    def test_port_setting(self):
        self.assertEqual(browser.port_of({}), 47315)
        self.assertEqual(browser.port_of({"browser": {"port": "50000"}}),
                         50000)
        self.assertEqual(browser.port_of({"browser": {"port": "80"}}), 47315)


class Pairing(LaneCase):
    def test_wrong_origin_or_host_is_refused(self):
        code = self.lane.new_code()
        for kw in ({"origin": None}, {"origin": "https://evil.example"},
                   {"host": "evil.example"}):
            st, _ = request(self.lane, "POST", "/pair", {"code": code}, **kw)
            self.assertEqual(st, 403, kw)
        self.assertFalse(self.lane.authorized("x"))

    def test_a_code_works_once(self):
        code = self.lane.new_code()
        st, body = request(self.lane, "POST", "/pair", {"code": code})
        self.assertEqual(st, 200)
        self.assertTrue(self.lane.authorized(body["token"]))
        st, _ = request(self.lane, "POST", "/pair", {"code": code})
        self.assertEqual(st, 403)

    def test_five_wrong_guesses_burn_the_code(self):
        code = self.lane.new_code()
        for _ in range(browser.MAX_BAD_CODES):
            self.assertEqual(request(self.lane, "POST", "/pair",
                                     {"code": "nope"})[0], 403)
        self.assertEqual(request(self.lane, "POST", "/pair",
                                 {"code": code})[0], 403)
        self.assertNotEqual(self.lane.live_code(), code)

    def test_a_code_expires(self):
        t = [0.0]
        lane = browser.Lane(0, clock=lambda: t[0])
        code = lane.new_code()
        t[0] = browser.CODE_TTL_S + 1
        self.assertEqual(lane.pair(code), "")

    def test_poll_needs_the_token(self):
        self.assertEqual(request(self.lane, "POST", "/poll", {"wait": 0})[0],
                         401)
        self.assertEqual(request(self.lane, "POST", "/poll", {"wait": 0},
                                 token="bad")[0], 401)

    def test_paired_means_the_extension_polled_recently(self):
        t = [0.0]
        lane = browser.Lane(0, clock=lambda: t[0])
        tok = lane.pair(lane.new_code())
        self.assertTrue(tok and lane.paired)
        t[0] = browser.ALIVE_S + 1
        self.assertFalse(lane.paired)


class Steps(LaneCase):
    def test_batch_runs_and_snapshot_is_listed(self):
        ext = self.paired()
        out = self.run_tool(json.dumps({"steps": [
            {"do": "open", "url": "https://x.test/login"},
            {"do": "snapshot"}]}))
        self.assertTrue(out.startswith("OK (browser, 2 steps)"), out)
        self.assertIn("1:1 input/password 'Password' [never filled]", out)
        self.assertEqual(self.batch_cmds(ext)[0]["task"], "t1")

    def test_password_field_is_read_but_never_filled(self):
        ext = self.paired()
        self.run_tool("snapshot")
        # the open step is missing, but the fake page model does not care
        sent = len(self.batch_cmds(ext))
        out = self.run_tool("fill 1:1 hunter2")
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertIn("never filled", out)
        self.assertEqual(len(self.batch_cmds(ext)), sent)   # nothing sent
        ok = self.run_tool("fill 1:0 me@example.com")
        self.assertTrue(ok.startswith("OK"), ok)

    def test_an_old_epoch_ref_is_rejected_before_anything_is_sent(self):
        ext = self.paired()
        self.run_tool("snapshot")
        self.run_tool("snapshot")
        sent = len(self.batch_cmds(ext))
        out = self.run_tool("click 1:2")
        self.assertTrue(out.startswith("REFUSED (step 1: stale ref 1:2"), out)
        self.assertEqual(len(self.batch_cmds(ext)), sent)
        self.assertTrue(self.run_tool("click 2:2").startswith("OK"))

    def test_a_ref_before_any_snapshot_is_refused(self):
        self.paired()
        self.assertIn("stale ref", self.run_tool("click 1:0"))

    def test_at_most_twenty_steps(self):
        ext = self.paired()
        many = [{"do": "scroll"}] * (browser.MAX_STEPS + 1)
        out = self.run_tool(json.dumps({"steps": many}))
        self.assertTrue(out.startswith("REFUSED (too many steps"), out)
        self.assertEqual(self.batch_cmds(ext), [])
        fine = self.run_tool(json.dumps({"steps": many[:browser.MAX_STEPS]}))
        self.assertTrue(fine.startswith("OK"), fine)

    def test_only_web_pages_open(self):
        ext = self.paired()
        for url in ("file:///etc/passwd", "javascript:alert(1)",
                    "chrome://settings", "data:text/html,hi", "example.com"):
            out = self.run_tool(f"open {url}")
            self.assertTrue(out.startswith("REFUSED"), (url, out))
        self.assertEqual(self.batch_cmds(ext), [])

    def test_bad_input_is_a_skip(self):
        self.paired()
        self.assertEqual(self.run_tool("{nope").split(" (")[0], "SKIP")
        self.assertEqual(self.run_tool("").split(" (")[0], "SKIP")
        self.assertIn("unknown step", self.run_tool("dance"))

    def test_proof_screenshot_lands_in_the_output_folder(self):
        self.paired()
        out = self.run_tool("screenshot")
        files = list(self.out.glob("proof-t1-1.png"))
        self.assertEqual(len(files), 1, out)
        self.assertTrue(files[0].read_bytes().startswith(b"\x89PNG"))
        self.assertIn(str(files[0]), out)

    def test_kill_switch_refuses(self):
        ext = self.paired()
        cfg = {"browser": {"lane": "extension"},
               "cua": {"kill_switch": "true", "audit": "false"}}
        self.assertEqual(self.run_tool("snapshot", cfg),
                         "REFUSED (cua kill switch is on)")
        self.assertEqual(self.batch_cmds(ext), [])

    def test_audit_records_steps_but_never_typed_text(self):
        self.paired()
        audit = self.out / "cua.jsonl"
        real = cua_safety.audit_event

        def to_file(*a, **k):
            return real(*a, path=audit, **k)
        cfg = {"browser": {"lane": "extension"}}
        with mock.patch.object(cua_safety, "audit_event", to_file):
            self.run_tool("snapshot", cfg)
            self.run_tool("fill 1:0 secret-text-here", cfg)
        text = audit.read_text()
        self.assertIn('"tool":"browser"', text)
        self.assertNotIn("secret-text-here", text)
        self.assertIn('"chars":16', text)


class Turns(LaneCase):
    def test_a_new_turn_closes_the_last_tab_group(self):
        ext = self.paired()
        self.run_tool("open https://x.test/")
        self.turn = "t2"
        self.run_tool("snapshot")
        ends = [c for c in ext.cmds if c.get("op") == "end_task"]
        self.assertEqual([c["task"] for c in ends], ["t1"])

    def test_stop_ends_the_call_within_a_second_and_the_turn(self):
        ext = self.paired(hang_on="wait_for")
        got = {}

        def go():
            t0 = time.monotonic()
            got["out"] = self.run_tool(json.dumps({"steps": [
                {"do": "open", "url": "https://x.test/"},
                {"do": "wait_for", "text": "never"}]}))
            got["secs"] = time.monotonic() - t0
        th = threading.Thread(target=go)
        th.start()
        for _ in range(100):
            if self.batch_cmds(ext):
                break
            time.sleep(0.02)
        t_stop = time.monotonic()
        st, _ = request(self.lane, "POST", "/stop", {}, token=ext.token)
        self.assertEqual(st, 200)
        th.join(5)
        self.assertEqual(got["out"], browser.MSG_STOPPED)
        self.assertLess(time.monotonic() - t_stop, 1.0)
        # the rest of the turn is refused, nothing more is sent
        sent = len(ext.cmds)
        self.assertEqual(self.run_tool("snapshot"), browser.MSG_STOPPED)
        self.assertEqual(len(ext.cmds), sent)
        # the next turn starts clean and tells the extension to resume
        self.turn = "t2"
        ext.hang_on = ""
        self.assertTrue(self.run_tool("snapshot").startswith("OK"))
        self.assertTrue(self.batch_cmds(ext)[-1]["resume"])


class FieldRule(unittest.TestCase):
    """The field rule has one fixture. The extension's unit test
    (browser-extension/tests/fieldrule.test.ts) reads the same file, so
    the Python and TypeScript rules cannot drift apart."""

    CASES = json.loads((ROOT / "tests" / "fixtures"
                        / "sensitive_fields.json").read_text())["cases"]

    def test_the_field_rule_matches_the_shared_fixture(self):
        for c in self.CASES:
            self.assertEqual(bool(cua_safety.sensitive_field(c["field"])),
                             c["sensitive"], c["field"])

    def test_the_fixture_has_both_kinds_of_field(self):
        flags = [c["sensitive"] for c in self.CASES]
        self.assertGreaterEqual(sum(flags), 10)
        self.assertGreaterEqual(len(flags) - sum(flags), 8)


if __name__ == "__main__":
    unittest.main()
