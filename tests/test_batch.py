#!/usr/bin/env python3
"""W15: OpenRouter Batch lane. Loopback fake only: no network, no paid call."""
import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import batch, config, ledger  # noqa: E402

KEY = "sk-or-test-SECRET-KEY"
NOW = dt.datetime.now()


class FakeBatchServer:
    """submit (JSONL) / status / results / cancel, Idempotency-Key aware."""

    def __init__(self):
        self.calls = []          # (method, path, headers, body)
        self.batches = {}        # id -> dict
        self.by_key = {}
        self.fail_ids = set()    # custom_ids that fail on this server
        self.final = "completed"
        self.polls_to_finish = 1
        self.submit_status = 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _go(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                outer.calls.append((method, self.path,
                                    dict(self.headers), body))
                outer.route(self, method, body)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/api/v1"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def submits(self):
        return [c for c in self.calls if c[0] == "POST"
                and c[1].endswith("/batches")]

    def route(self, h, method, body):
        p = h.path.split("?")[0]
        if method == "POST" and p.endswith("/batches"):
            if self.submit_status != 200:
                return h._send(self.submit_status,
                               {"error": {"message": "nope " + KEY}})
            key = h.headers.get("Idempotency-Key")
            if key and key in self.by_key:
                return h._send(200, self.view(self.by_key[key]))
            lines = [json.loads(x) for x in body.splitlines() if x.strip()]
            b = {"id": f"batch_{len(self.batches) + 1}", "lines": lines,
                 "status": "in_progress", "left": self.polls_to_finish}
            self.batches[b["id"]] = b
            if key:
                self.by_key[key] = b["id"]
            return h._send(200, self.view(b["id"]))
        parts = p.split("/")
        bid = parts[parts.index("batches") + 1]
        b = self.batches.get(bid)
        if b is None:
            return h._send(404, {"error": {"message": "no batch"}})
        if method == "POST" and p.endswith("/cancel"):
            b["status"] = "cancelled"
            return h._send(200, self.view(bid))
        if p.endswith("/results"):
            out = []
            for ln in b["lines"]:
                cid = ln["custom_id"]
                if cid in self.fail_ids:
                    out.append({"custom_id": cid,
                                "error": {"message": "item blew up"}})
                else:
                    out.append({"custom_id": cid, "response": {
                        "status_code": 200, "body": {
                            "choices": [{"message": {
                                "content": f"answer-{cid}"}}],
                            "usage": {"prompt_tokens": 100,
                                      "completion_tokens": 50,
                                      "cost": 0.001}}}})
            return h._send(200, raw=("\n".join(json.dumps(o) for o in out)
                                     + "\n").encode())
        if b["status"] == "in_progress":
            b["left"] -= 1
            if b["left"] <= 0:
                b["status"] = self.final
        h._send(200, self.view(bid))

    def view(self, bid):
        b = self.batches[bid]
        n = len(b["lines"])
        bad = len([1 for ln in b["lines"] if ln["custom_id"] in self.fail_ids])
        done = b["status"] in ("completed", "cancelled")
        return {"id": bid, "status": b["status"],
                "request_counts": {"total": n,
                                   "completed": n - bad if done else 0,
                                   "failed": bad if done else 0}}


def items(n=3):
    return [{"custom_id": f"i{k}",
             "messages": [{"role": "user", "content": f"q{k}"}]}
            for k in range(n)]


class Base(unittest.TestCase):
    MODEL = "meta-llama/llama-4-scout"

    def setUp(self):
        self.srv = FakeBatchServer()
        self.addCleanup(self.srv.stop)
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data = pathlib.Path(self._td.name)
        p = mock.patch.object(config, "DATA_DIR", self.data)
        p.start()
        self.addCleanup(p.stop)
        self.cfg = {"budget": {"daily_usd": "2.00", "monthly_usd": "20.00"}}

    def lane(self, cfg=None):
        return batch.Lane(cfg or self.cfg,
                          batch.Client(self.srv.url, key_fn=lambda: KEY))

    def ledger_text(self):
        try:
            return ledger.path().read_text()
        except FileNotFoundError:
            return ""

    def seed_spend(self, usd):
        ledger.record("openrouter", self.MODEL, 1, 1, usd=usd, paid=True)


class TestClient(Base):
    def test_submit_status_results_cancel_shape(self):
        c = batch.Client(self.srv.url, key_fn=lambda: KEY)
        b = c.submit(self.MODEL, items(2), "job-1", max_tokens=64)
        self.assertEqual(b["status"], "in_progress")
        m, path, hdr, body = self.srv.submits()[0]
        self.assertEqual(hdr["Idempotency-Key"], "job-1")
        self.assertEqual(hdr["Authorization"], "Bearer " + KEY)
        lines = [json.loads(x) for x in body.splitlines()]
        self.assertEqual([x["custom_id"] for x in lines], ["i0", "i1"])
        self.assertEqual(lines[0]["body"]["model"], self.MODEL)
        self.assertEqual(lines[0]["body"]["max_tokens"], 64)
        self.assertEqual(c.get(b["id"])["status"], "completed")
        res = c.results(b["id"])
        self.assertEqual(res[0]["content"], "answer-i0")
        self.assertEqual(res[0]["cost"], 0.001)
        b2 = c.submit(self.MODEL, items(1), "job-2")
        self.assertEqual(c.cancel(b2["id"])["status"], "cancelled")

    def test_error_never_leaks_key(self):
        self.srv.submit_status = 400
        c = batch.Client(self.srv.url, key_fn=lambda: KEY)
        with self.assertRaises(batch.ApiError) as cm:
            c.submit(self.MODEL, items(1), "j")
        self.assertNotIn(KEY, str(cm.exception))
        self.assertEqual(cm.exception.status, 400)

    def test_no_key_no_request(self):
        c = batch.Client(self.srv.url, key_fn=lambda: "")
        with self.assertRaises(batch.BatchRefused) as cm:
            c.submit(self.MODEL, items(1), "j")
        self.assertEqual(cm.exception.code, "no_key")
        self.assertEqual(self.srv.calls, [])


class TestAllowlist(Base):
    def test_cheap_models_allowed(self):
        for m in ("meta-llama/llama-4-scout", "google/gemini-2.5-flash",
                  "x-ai/grok-4.7"):
            self.assertTrue(batch.allowed(m), m)

    def test_premium_and_unknown_rejected(self):
        for m in ("anthropic/claude-opus-4", "anthropic/claude-sonnet-5.5",
                  "openai/gpt-5", "some/unknown-model", "",
                  "meta-llama/llama-4-scout:batch"):
            self.assertFalse(batch.allowed(m), m)

    def test_ceiling_holds_for_every_allowed_model(self):
        for m in batch.ALLOWED:
            pin, pout = ledger.PRICES[m]
            self.assertLessEqual(pin, 1.60)
            self.assertLessEqual(pout, 4.80)
            self.assertFalse(m.startswith("anthropic/"))

    def test_submit_refused_before_any_request(self):
        with self.assertRaises(batch.BatchRefused) as cm:
            self.lane().submit("j1", "learn", "anthropic/claude-opus-4",
                               items())
        self.assertEqual(cm.exception.code, "model_not_allowed")
        self.assertEqual(self.srv.calls, [])
        self.assertEqual(self.ledger_text(), "")
        self.assertEqual(batch.Lane(self.cfg, None).status(), [])


class TestCaps(Base):
    def test_cap_respected_refused_before_submit(self):
        self.seed_spend(1.999999)
        before = self.ledger_text()
        with self.assertRaises(batch.BatchRefused) as cm:
            self.lane().submit("j1", "learn", self.MODEL, items(50),
                               max_tokens=4000)
        self.assertEqual(cm.exception.code, "budget_exceeded")
        self.assertEqual(self.srv.calls, [])
        self.assertEqual(self.ledger_text(), before)
        self.assertEqual(self.lane().status(), [])

    def test_monthly_cap_and_blocked_ledger(self):
        self.seed_spend(19.9999)
        with self.assertRaises(batch.BatchRefused):
            self.lane().submit("j1", "learn", self.MODEL, items(50),
                               max_tokens=4000)
        self.assertEqual(self.srv.calls, [])

    def test_in_flight_reservation_counts(self):
        cfg = {"budget": {"daily_usd": "0.01"}}
        ln = self.lane(cfg)
        ln.submit("a", "learn", self.MODEL, items(3), max_tokens=200)
        est = ln.status("a")["est_usd"]
        self.assertGreater(est, 0.0)
        with self.assertRaises(batch.BatchRefused) as cm:
            ln.submit("b", "learn", self.MODEL, items(40), max_tokens=4000)
        self.assertEqual(cm.exception.code, "budget_exceeded")
        self.assertEqual(len(self.srv.submits()), 1)

    def test_unreadable_ledger_fails_closed(self):
        with mock.patch.object(ledger, "status", side_effect=OSError("x")):
            with self.assertRaises(batch.BatchRefused) as cm:
                self.lane().submit("j", "learn", self.MODEL, items())
        self.assertEqual(cm.exception.code, "ledger_unreadable")
        self.assertEqual(self.srv.calls, [])

    def test_estimate_scales_with_items_and_max_tokens(self):
        a = batch.estimate_usd(self.MODEL, items(2), 100)
        b = batch.estimate_usd(self.MODEL, items(4), 100)
        self.assertAlmostEqual(b, 2 * a, places=9)
        self.assertGreater(batch.estimate_usd(self.MODEL, items(2), 1000), a)


class TestLifecycle(Base):
    def test_resubmit_idempotent_no_duplicate_job(self):
        j1 = self.lane().submit("learn-2026-W40", "learn", self.MODEL,
                                items())
        j2 = self.lane().submit("learn-2026-W40", "learn", self.MODEL,
                                items())
        self.assertEqual(j1["remote_id"], j2["remote_id"])
        self.assertEqual(len(self.srv.submits()), 1)
        self.assertEqual(len(self.srv.batches), 1)

    def test_crash_before_persist_resubmits_same_key(self):
        ln = self.lane()
        real = ln._save
        n = {"c": 0}

        def boom(job):
            n["c"] += 1
            if n["c"] == 2:          # the save that records remote_id
                raise OSError("crash")
            real(job)
        ln._save = boom
        with self.assertRaises(OSError):
            ln.submit("j", "learn", self.MODEL, items())
        j = self.lane().submit("j", "learn", self.MODEL, items())
        keys = {c[2]["Idempotency-Key"] for c in self.srv.submits()}
        self.assertEqual(keys, {"j"})
        self.assertEqual(len(self.srv.batches), 1)
        self.assertTrue(j["remote_id"])

    def test_poll_success_applies_and_records_cost(self):
        self.lane().submit("j", "learn", self.MODEL, items(3))
        got = {}
        job = self.lane().poll("j", apply=lambda j, ok: got.update(ok))
        self.assertEqual(job["status"], "completed")
        self.assertTrue(job["settled"])
        self.assertEqual(got, {"i0": "answer-i0", "i1": "answer-i1",
                               "i2": "answer-i2"})
        rows = [json.loads(x) for x in self.ledger_text().splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["paid"] and r["usd"] == 0.001 for r in rows))
        self.assertEqual(rows[0]["model"], self.MODEL)

    def test_poll_twice_does_not_double_record_or_apply(self):
        self.lane().submit("j", "learn", self.MODEL, items(2))
        calls = []
        self.lane().poll("j", apply=lambda j, ok: calls.append(ok))
        self.lane().poll("j", apply=lambda j, ok: calls.append(ok))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.ledger_text().splitlines()), 2)

    def test_partial_failure(self):
        self.srv.fail_ids = {"i1"}
        self.lane().submit("j", "learn", self.MODEL, items(3))
        got = {}
        job = self.lane().poll("j", apply=lambda j, ok: got.update(ok))
        self.assertEqual(sorted(got), ["i0", "i2"])
        self.assertEqual(list(job["failed"]), ["i1"])
        self.assertIn("blew up", job["failed"]["i1"])
        self.assertEqual(len(self.ledger_text().splitlines()), 2)
        # no automatic realtime retry: only the one batch submit, no chat
        self.assertFalse([c for c in self.srv.calls
                          if "chat/completions" in c[1]])
        self.assertEqual(len(self.srv.submits()), 1)

    def test_restart_resumes_polling(self):
        self.srv.polls_to_finish = 3
        self.lane().submit("j", "learn", self.MODEL, items(2))
        job = self.lane().poll("j")
        self.assertEqual(job["status"], "in_progress")
        self.assertFalse(job["settled"])
        job = self.lane().poll("j")             # new Lane = restarted daemon
        self.assertFalse(job["settled"])
        got = {}
        job = self.lane().poll("j", apply=lambda j, ok: got.update(ok))
        self.assertTrue(job["settled"])
        self.assertEqual(len(got), 2)
        self.assertEqual(len(self.srv.submits()), 1)

    def test_cancel_settles_with_partials(self):
        self.srv.polls_to_finish = 9
        self.lane().submit("j", "learn", self.MODEL, items(2))
        job = self.lane().cancel("j")
        self.assertEqual(job["status"], "cancelled")
        self.assertTrue(job["settled"])

    def test_rejected_submit_frees_reservation(self):
        self.srv.submit_status = 400
        with self.assertRaises(batch.ApiError):
            self.lane().submit("j", "learn", self.MODEL, items())
        self.assertTrue(self.lane().status("j")["settled"])
        self.assertEqual(self.lane().reserved(), 0.0)

    def test_state_file_has_no_key(self):
        self.lane().submit("j", "learn", self.MODEL, items())
        for f in (self.data / "batch").iterdir():
            self.assertNotIn(KEY, f.read_text())


class TestLearnGlue(Base):
    def test_submit_learn_and_proposal_written(self):
        corr = self.data / "corrections.jsonl"
        corr.write_text(json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "heard": "open dicord", "picked": "app:discord",
            "jev_said": {"app": "browser", "route": "launch"}}) + "\n")
        out = self.data / "proposals"
        job = batch.submit_learn(self.lane(), self.MODEL,
                                 corrections_file=corr)
        self.assertEqual(job["kind"], "learn")
        self.assertTrue(job["job_id"].startswith("learn-"))
        again = batch.submit_learn(self.lane(), self.MODEL,
                                   corrections_file=corr)
        self.assertEqual(again["remote_id"], job["remote_id"])
        self.assertEqual(len(self.srv.submits()), 1)
        done = self.lane().poll(job["job_id"],
                                apply=batch.applier(out_dir=out))
        self.assertTrue(done["settled"])
        files = list(out.glob("*-batch.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("answer-", files[0].read_text())

    def test_nothing_to_learn(self):
        corr = self.data / "none.jsonl"
        self.assertIsNone(batch.submit_learn(self.lane(), self.MODEL,
                                             corrections_file=corr))
        self.assertEqual(self.srv.calls, [])


class TestLivePathGuard(unittest.TestCase):
    LIVE = ("pipeline", "brain", "evalroute", "act", "agents", "session",
            "context", "health", "ipc", "ledger", "learn", "judge")

    def test_live_modules_do_not_mention_batch(self):
        import re
        pat = re.compile(r"^\s*(from\s+(\.|wisp)\s*import\s+[^#\n]*\bbatch\b"
                         r"|from\s+(\.|wisp\.)batch\b|import\s+wisp\.batch)",
                         re.M)
        for name in self.LIVE:
            src = (ROOT / "wisp" / f"{name}.py").read_text()
            self.assertIsNone(pat.search(src), name)
        self.assertIsNone(pat.search((ROOT / "wispd").read_text()), "wispd")

    def test_importing_live_path_never_loads_batch(self):
        code = ("import sys; sys.path.insert(0, %r)\n"
                "import wisp.pipeline, wisp.brain, wisp.evalroute, "
                "wisp.ledger, wisp.learn, wisp.judge\n"
                "sys.exit(1 if 'wisp.batch' in sys.modules else 0)"
                % str(ROOT))
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestCli(unittest.TestCase):
    def test_commands_registered_with_help(self):
        from wisp.cli import registry
        cmds = registry.commands()
        for p in ("batch status", "batch submit-learn", "batch poll",
                  "batch cancel"):
            self.assertIn(p, cmds)


if __name__ == "__main__":
    unittest.main()
