#!/usr/bin/env python3
"""Training arena — standalone observability page for Wisp's
computer-use training loop.

Serves arena.html plus live JSON APIs over the run logs and skill
bank. Read-only — the page polls; nothing here mutates state.

    python3 scripts/clicklab/arena.py [--port 8798]
"""
import json
import pathlib
import sys
import http.server

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

PORT = 8798
HERE = pathlib.Path(__file__).parent


def _api(path: str) -> tuple[int, bytes]:
    from wisp import train
    if path == "/api/stats":
        return 200, json.dumps(train.stats()).encode()
    if path == "/api/bank":
        return 200, json.dumps(list(train.load_bank().values())).encode()
    if path.startswith("/api/feed"):
        limit = 200
        recs = train._load_jsonl(train.RESULTS)[-limit:]
        return 200, json.dumps(recs).encode()
    if path == "/api/trajs":
        recs = train._load_jsonl(train.TRAJECTORIES)[-100:]
        return 200, json.dumps(recs).encode()
    return 404, b"not found"


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            code, body = _api(self.path)
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        p = self.path.split("?")[0]
        if p in ("/", "/arena.html"):
            body = (HERE / "arena.html").read_bytes()
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) \
        if "--port" in sys.argv else PORT
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                            Handler)
    print(f"[arena] http://127.0.0.1:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
