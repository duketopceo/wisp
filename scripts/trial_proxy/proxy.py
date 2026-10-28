#!/usr/bin/env python3
"""Reference proxy for Wisp's capped trial (B34 option A). NOT RUNNING.

Run by the owner, on a host the owner pays for, only after the cost cap in
docs/COSTS.md is signed off. Standard library only.

    TRIAL_UPSTREAM_KEY=sk-or-... python3 proxy.py --port 8787

The proxy holds the only real key. A client sends `Authorization: Bearer
wt_<32 hex>`, a random per-install token. Every request is checked, in this
order, before anything is forwarded:

  1. the kill switch (`TRIAL_OFF=1` or a file named `OFF` beside the db)
  2. the token shape
  3. the model is on the allowlist, and `max_tokens` is clamped
  4. per-address calls per day
  5. per-token calls per day and in total
  6. the global dollar ceiling for the day (calls x a deliberately high
     per-call estimate), the hard stop on spend

A refused call is HTTP 429 with {"error": {"code": "trial_cap", ...}} and
is never forwarded. Streaming is not offered; the client falls back to a
normal reply.
"""
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://openrouter.ai/api/v1/chat/completions"
TOKEN_RE = re.compile(r"\Awt_[0-9a-f]{32}\Z")
MODELS = ("meta-llama/llama-4-maverick",)
MAX_TOKENS = 600
LIMITS = {"token_day": 30, "token_total": 100, "ip_day": 60,
          "global_day_usd": 5.0, "call_usd": 0.002}
MAX_BODY = 256 * 1024


def day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("create table if not exists calls "
                        "(day text, token text, ip text)")
        self.db.execute("create index if not exists c_day on calls(day)")

    def count(self, where: str, *args) -> int:
        return self.db.execute(
            f"select count(*) from calls where {where}", args).fetchone()[0]

    def add(self, d, token, ip):
        self.db.execute("insert into calls values (?,?,?)", (d, token, ip))
        self.db.commit()


def text_only(messages: list) -> list:
    """Drop every image part: the trial never receives a screenshot, which
    keeps the screen off the owner's server and the per-call cost low."""
    out = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list):
            c = "\n".join(str(p.get("text", "")) for p in c
                          if isinstance(p, dict) and p.get("type") == "text")
        out.append({"role": str((m or {}).get("role", "user")),
                    "content": str(c or "")[:20000]})
    return out


def refuse(status, code, message):
    return status, {"error": {"code": code, "message": message}}


def handle(headers: dict, body: dict, ip: str, store: Store, forward,
           now: float | None = None, limits: dict | None = None,
           off: bool = False):
    """-> (status, json). `forward(body)` makes the upstream call and is the
    only place the real key exists."""
    lim = {**LIMITS, **(limits or {})}
    now = time.time() if now is None else now
    if off:
        return refuse(503, "trial_off", "The trial is switched off.")
    m = re.match(r"Bearer (\S+)\Z", str(headers.get("Authorization", "")))
    token = m.group(1) if m else ""
    if not TOKEN_RE.match(token):
        return refuse(401, "bad_token", "Missing or malformed trial token.")
    if body.get("model") not in MODELS or not isinstance(
            body.get("messages"), list):
        return refuse(400, "bad_request", "Model or messages not allowed.")
    d = day(now)
    if store.count("day=? and ip=?", d, ip) >= lim["ip_day"]:
        return refuse(429, "trial_cap", "Too many trial calls from here today.")
    if store.count("token=?", token) >= lim["token_total"]:
        return refuse(429, "trial_cap", "Trial finished. Add your own keys.")
    if store.count("day=? and token=?", d, token) >= lim["token_day"]:
        return refuse(429, "trial_cap", "Trial limit for today. Try tomorrow "
                      "or add your own keys.")
    if store.count("day=?", d) * lim["call_usd"] >= lim["global_day_usd"]:
        return refuse(429, "trial_cap", "The trial is full for today.")
    store.add(d, token, ip)       # counted before the call: a failure costs a call
    safe = {"model": body["model"], "messages": text_only(body["messages"]),
            "max_tokens": min(int(body.get("max_tokens") or MAX_TOKENS),
                              MAX_TOKENS)}
    return 200, forward(safe)


def upstream(key: str):
    def forward(body):
        req = urllib.request.Request(
            UPSTREAM, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    return forward


def make_handler(store, forward, off_file):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if self.path != "/v1/chat/completions" or n > MAX_BODY:
                return self._send(*refuse(404, "not_found", "No such path."))
            try:
                body = json.loads(self.rfile.read(n))
            except ValueError:
                return self._send(*refuse(400, "bad_request", "Not JSON."))
            off = os.environ.get("TRIAL_OFF") == "1" or os.path.exists(off_file)
            ip = self.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
                or self.client_address[0]
            try:
                self._send(*handle(dict(self.headers), body, ip, store,
                                   forward, off=off))
            except Exception:
                self._send(*refuse(502, "upstream", "Upstream failed."))

        def _send(self, status, obj):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass            # no request logs: nothing of the user's is kept
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--db", default="trial.sqlite")
    a = ap.parse_args(argv)
    key = os.environ.get("TRIAL_UPSTREAM_KEY", "")
    if not key:
        raise SystemExit("TRIAL_UPSTREAM_KEY is not set")
    h = make_handler(Store(a.db), upstream(key),
                     os.path.join(os.path.dirname(os.path.abspath(a.db)), "OFF"))
    ThreadingHTTPServer(("127.0.0.1", a.port), h).serve_forever()


if __name__ == "__main__":
    main()
