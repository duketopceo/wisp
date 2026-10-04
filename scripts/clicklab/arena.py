#!/usr/bin/env python3
"""Training arena — standalone observability page for Wisp's
computer-use training loop.

Serves arena.html plus live JSON APIs over the run logs and skill
bank. Read-only — the page polls; nothing here mutates state.

    python3 scripts/clicklab/arena.py [--port 8798]
    python3 scripts/clicklab/arena.py --run --models "ollama:m,..." \
        [--via-orch] [run.py flags]
    python3 scripts/clicklab/arena.py --gen-css     # refresh page tokens
    python3 scripts/clicklab/arena.py --ground-offline [FIXTURE]

`--run` (W32) is the only way the arena starts an eval. The matrix must
pass arena_policy (local models plus at most one cheap hosted model).
A hosted model needs `--via-orch`, which re-execs under the `orch`
wrapper so spend bills the dedicated eval key; without it, hosted specs
are refused. Local-only matrices run without orch.

The page colors are generated from wisp.theme tokens: the block between
the wisp:tokens markers in arena.html is written by `--gen-css`, and
the server swaps in the active Omarchy theme when it serves the page.

`--ground-offline` (W13) replays RECORDED provider outputs from
tests/fixtures/ground/recorded.json through the grounding adapter's
parse + frame conversion and compares UI-TARS against the current
(Jev) provider by hit rate. No model, network, cua-driver or hyprctl
is touched; exit 1 when UI-TARS scores below the baseline.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import http.server

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arena_policy  # noqa: E402

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


BEGIN = "/* wisp:tokens:begin */"
END = "/* wisp:tokens:end */"


def token_css(light=None, dark=None) -> str:
    """Generated token block: dark by default, light under the OS
    preference, and both forceable with data-theme (used by renders)."""
    from wisp import theme
    d = dark or theme.derive(theme._fallback_colors("dark"),
                             source="fallback")
    lt = light or theme.derive(theme._fallback_colors("light"),
                               source="fallback")

    def props(res):
        return "\n".join(f"  {theme._css_name(k)}: {res['tokens'][k]};"
                          for k in theme.TOKENS)
    return (f"{BEGIN}\n"
            f":root {{\n  color-scheme: dark;\n{props(d)}\n}}\n"
            f"@media (prefers-color-scheme: light) {{\n"
            f"  :root:not([data-theme=\"dark\"]) {{\n"
            f"  color-scheme: light;\n{props(lt)}\n  }}\n}}\n"
            f":root[data-theme=\"light\"] {{\n  color-scheme: light;\n"
            f"{props(lt)}\n}}\n"
            f"{END}")


_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def swap_tokens(html: str, block: str) -> str:
    return _BLOCK.sub(lambda m: block, html, count=1)


def page_html() -> bytes:
    """arena.html with the active Omarchy theme as the token block.
    A light theme sets data-theme so the OS preference cannot fight it."""
    html = (HERE / "arena.html").read_text()
    try:
        from wisp import theme
        res = theme.load()
        if res.get("source") != "fallback":
            lt = res if res["mode"] == "light" else None
            dk = res if res["mode"] == "dark" else None
            html = swap_tokens(html, token_css(lt, dk))
            html = html.replace(
                '<html lang="en">',
                f'<html lang="en" data-theme="{res["mode"]}">', 1)
    except Exception:
        pass
    return html.encode()


def run_cli(argv) -> int:
    """`--run`: gate the matrix, then hand off to run.py."""
    specs = []
    if "--models" in argv:
        specs = [x.strip() for x in
                 argv[argv.index("--models") + 1].split(",") if x.strip()]
    try:
        hosted = arena_policy.validate_matrix(specs)
    except arena_policy.PolicyError as e:
        print(f"[arena] refused: {e}")
        return 2
    rest = [a for a in argv if a not in ("--run", "--via-orch")]
    if hosted and not arena_policy.via_orch():
        if "--via-orch" not in argv:
            print(f"[arena] refused: hosted model {hosted[0]} needs "
                  "the orch wrapper so spend bills the eval key; "
                  "rerun with --via-orch")
            return 2
        try:
            cmd = arena_policy.orch_argv(
                [sys.executable, str(pathlib.Path(__file__).resolve()),
                 "--run"] + rest)
        except arena_policy.PolicyError as e:
            print(f"[arena] refused: {e}")
            return 2
        os.environ[arena_policy.ORCH_MARKER] = "1"
        os.execv(cmd[0], cmd)
    return subprocess.call(
        [sys.executable, str(HERE / "run.py")] + rest)


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
            body = page_html()
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def main():
    if "--gen-css" in sys.argv:
        p = HERE / "arena.html"
        p.write_text(swap_tokens(p.read_text(), token_css()))
        print(f"[arena] tokens written to {p}")
        return
    if "--run" in sys.argv:
        sys.exit(run_cli(sys.argv[1:]))
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
