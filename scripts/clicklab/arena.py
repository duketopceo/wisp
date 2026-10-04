#!/usr/bin/env python3
"""Training arena — standalone observability page for Wisp's
computer-use training loop.

Serves arena.html plus live JSON APIs over the run logs and skill
bank. Read-only — the page polls; nothing here mutates state.

    python3 scripts/clicklab/arena.py [--port 8798]
    python3 scripts/clicklab/arena.py --ground-offline [FIXTURE]

`--ground-offline` (W13) replays RECORDED provider outputs from
tests/fixtures/ground/recorded.json through the grounding adapter's
parse + frame conversion and compares UI-TARS against the current
(Jev) provider by hit rate. No model, network, cua-driver or hyprctl
is touched; exit 1 when UI-TARS scores below the baseline.
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


GROUND_FIXTURE = (HERE.parents[1] / "tests" / "fixtures" / "ground"
                  / "recorded.json")


def ground_offline(fixture=GROUND_FIXTURE) -> dict:
    """Offline grounding suite (W13): recorded outputs -> hit rates.
    Each case carries the monitor layout, the expected hit box in
    compositor-global px, and the recorded raw outputs of the UI-TARS
    provider and of the baseline (Jev) provider."""
    from wisp import grounding
    fx = json.loads(pathlib.Path(fixture).read_text())
    res = {"cases": 0, "uitars": {"hits": 0, "misses": []},
           "baseline": {"hits": 0, "misses": []}}

    def hit(box, xy):
        return (xy is not None and box[0] <= xy[0] <= box[2]
                and box[1] <= xy[1] <= box[3])

    for case in fx["cases"]:
        lay = fx["layouts"][case["layout"]]
        mons, (sw, sh) = lay["monitors"], lay["shot"]
        rec, box = case["recorded"], case["expect_box"]
        res["cases"] += 1
        u = rec["uitars"]
        sent = tuple(u["sent"])
        xy = grounding.parse_uitars_text(u["text"], sent)
        gxy = None
        if xy is not None:
            gxy = grounding.convert(xy[0] * sw / sent[0],
                                    xy[1] * sh / sent[1], "shot", mons)
        b = rec["baseline"]
        bxy = grounding.convert(b["xy"][0], b["xy"][1], "shot", mons) \
            if b["confidence"] >= 0.5 else None
        for key, p in (("uitars", gxy), ("baseline", bxy)):
            if hit(box, p):
                res[key]["hits"] += 1
            else:
                res[key]["misses"].append(case["target"])
    res["ok"] = res["uitars"]["hits"] >= res["baseline"]["hits"]
    return res


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
    if "--ground-offline" in sys.argv:
        i = sys.argv.index("--ground-offline")
        fx = sys.argv[i + 1] if len(sys.argv) > i + 1 \
            and not sys.argv[i + 1].startswith("-") else GROUND_FIXTURE
        r = ground_offline(fx)
        print(json.dumps(r, indent=1))
        sys.exit(0 if r["ok"] else 1)
    port = int(sys.argv[sys.argv.index("--port") + 1]) \
        if "--port" in sys.argv else PORT
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                            Handler)
    print(f"[arena] http://127.0.0.1:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
