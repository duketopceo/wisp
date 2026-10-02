#!/usr/bin/env python3
"""Clicklab — a self-grading pointer-accuracy lab for the act loop.

Serves index.html locally, opens it in a fresh BrowserOS tab, then
drives wisp.act.run_act_loop against a task list. After every task it
evaluates a JS check on window.__score in that page via the BrowserOS
MCP `evaluate` tool — auto-labeled runs, no human ✓/✗.

Usage:
    python3 scripts/clicklab/run.py [--tasks N] [--repeat R]
"""
import json
import sys
import threading
import time
import re
import http.server
import functools
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

PORT = 8797
URL = f"http://127.0.0.1:{PORT}/index.html"
OUT = (pathlib.Path.home() / ".local" / "share" / "wisp"
       / "clicklab.jsonl")

# (instruction, JS check — body of a function where `s` is
# window.__score; must `return` a bool)
TASKS = [
    ("click the button labeled ALPHA",
     "return s.counts['btn-alpha'] >= 1"),
    ("click dot 3",
     "return s.counts['dot-3'] >= 1"),
    ("click the green triangle",
     "return s.counts['shape-green-triangle'] >= 1"),
    ("click the button labeled DELTA",
     "return s.counts['btn-delta'] >= 1"),
    ("click dot 7",
     "return s.counts['dot-7'] >= 1"),
    ("click the red circle",
     "return s.counts['shape-red-circle'] >= 1"),
    ("click the second checkbox",
     "return s.counts['chk-2'] >= 1"),
    ("click the button labeled FOXTROT",
     "return s.counts['btn-foxtrot'] >= 1"),
    ("type 'hello wisp' into the text field",
     "return (s.typed['textin']||'').includes('hello wisp')"),
    ("scroll the list to the bottom",
     "return s.scroll_top > 400"),
    ("click the blue square",
     "return s.counts['shape-blue-square'] >= 1"),
    ("click dot 5",
     "return s.counts['dot-5'] >= 1"),
    ("select 'gamma' in the dropdown",
     "return s.events.some(e => e.id==='sel' && e.value==='gamma')"),
    ("type 'testing typing' into the big text area",
     "return (s.typed['textbox']||'').includes('testing typing')"),
]


def serve():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(pathlib.Path(__file__).parent))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT),
                                            handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def bos(tool: str, args: dict) -> str:
    from wisp.tools import mcpclient
    return mcpclient.call(f"browseros {tool} {json.dumps(args)}", {})


def open_lab() -> int:
    """Open clicklab in a new BrowserOS tab; return its page id."""
    out = bos("tabs", {"action": "new", "url": URL})
    m = re.search(r"page (\d+)", out)
    if m:
        time.sleep(2)
        return int(m.group(1))
    # fall back: find it in the tab list
    time.sleep(2)
    out = bos("tabs", {"action": "list"})
    ids = re.findall(r"\[(\d+)\][^\n]*" + str(PORT), out)
    if not ids:
        raise RuntimeError("clicklab tab not found:\n" + out)
    return int(ids[-1])


def check(page: int, expr: str) -> bool:
    code = (f"var s = window.__score || {{}}; {expr}")
    out = bos("evaluate", {"page": page, "code": code})
    return "true" in out.lower()


LAB_WS = 97


def _dsp(expr: str):
    import subprocess
    subprocess.run(["hyprctl", "dispatch", expr], capture_output=True)


def focus_browseros():
    """Raise the clicklab window on its own workspace."""
    import subprocess, json as _j
    r = subprocess.run(["hyprctl", "clients", "-j"],
                       capture_output=True, text=True)
    try:
        addr = next(c["address"] for c in _j.loads(r.stdout)
                    if "clicklab" in c.get("title", "").lower())
        _dsp(f'hl.dsp.focus({{monitor="eDP-1"}})')
        _dsp(f'hl.dsp.focus({{workspace={LAB_WS}}})')
        _dsp(f'hl.dsp.window.move({{window="address:{addr}",'
             f' workspace={LAB_WS}, follow=true}})')
        return addr
    except (StopIteration, _j.JSONDecodeError):
        return None


def calibrate_dom_origin(page: int, cfg: dict):
    """Inject one probe click inside the lab window; the page echoes
    clientX/Y → viewport origin in logical coords. Stored as
    cfg.screen.dom_origin for _dom_shot/_parse_xy."""
    import subprocess, json as _j
    r = subprocess.run(["hyprctl", "clients", "-j"],
                       capture_output=True, text=True)
    win = next((c for c in _j.loads(r.stdout)
                if "clicklab" in c.get("title", "").lower()), None)
    if not win:
        print("[clicklab] WARN: lab window not found, origin=0,0")
        cfg["screen"]["dom_origin"] = [0, 0]
        return
    wx, wy = win["at"]
    # probe near mid-window — safely inside the viewport
    px, py = wx + 900, wy + 500
    from wisp import tools
    tools.run("click", f"{px},{py}@logical", cfg)
    time.sleep(0.4)
    out = bos("evaluate", {"page": page, "code":
                           "var c=window.__score.lastClick;"
                           "return c?JSON.stringify(c):'null'"})
    m = re.search(r"\{[^}]*\}", out)
    if not m:
        print("[clicklab] WARN: no click echo, origin=0,0")
        cfg["screen"]["dom_origin"] = [0, 0]
        return
    c = json.loads(m.group(0))
    ox, oy = px - c["x"], py - c["y"]
    cfg["screen"]["dom_origin"] = [ox, oy]
    print(f"[clicklab] dom origin: ({ox},{oy})")


def main():
    from wisp import act, config
    serve()
    print(f"[clicklab] serving on {URL}")
    try:
        page = open_lab()
    except RuntimeError as e:
        print(f"[clicklab] {e}")
        sys.exit(2)
    print(f"[clicklab] page id {page}")
    focus_browseros()
    time.sleep(1)

    cfg = config.load_config()
    cfg.setdefault("screen", {})
    if "--dom" in sys.argv:
        # DOM-schematic mode: screenshots are synthesized from element
        # rects — works with the panel powered off (lid closed)
        cfg["screen"]["dom_page"] = page
        cfg["screen"]["output"] = ""
        # clicks in dom mode are pure viewport CSS px — no compositor
        # origin involved; keep SHOT_ORIGIN bookkeeping consistent
        cfg["screen"]["dom_origin"] = [0, 0]
        # liveness probe: a DOM click at a known element's rect
        out = bos("evaluate", {"page": page, "code":
                               "var b=document.getElementById('btn-alpha');"
                               "if(!b)return 'miss';"
                               "var r=b.getBoundingClientRect();"
                               "return ''+Math.round(r.x+r.width/2)+','+"
                               "Math.round(r.y+r.height/2)"})
        m = re.search(r"(\d+),(\d+)", out)
        if m:
            from wisp import tools
            print(f"[clicklab] probe click at {m.group(0)}")
            print(f"[clicklab] probe → "
                  f"{tools.run('click', m.group(0), cfg)}")
            bos("evaluate", {"page": page, "code":
                             "window.__score={events:[],counts:{},"
                             "scroll_top:0,typed:{},lastClick:null};"
                             "return 'reset'"})
        else:
            print("[clicklab] WARN: probe failed — page reachable?")
    else:
        cfg["screen"]["output"] = \
            sys.argv[sys.argv.index("--output") + 1] \
            if "--output" in sys.argv else ""
    repeat = int(sys.argv[sys.argv.index("--repeat") + 1]) \
        if "--repeat" in sys.argv else 1
    n = int(sys.argv[sys.argv.index("--tasks") + 1]) \
        if "--tasks" in sys.argv else len(TASKS)
    tasks = (TASKS * repeat)[:n * repeat]
    brain = cfg.get("brain", {}).get("default", "openrouter")
    print(f"[clicklab] {len(tasks)} tasks, brain={brain}")

    results = []
    for i, (task, expr) in enumerate(tasks, 1):
        # reset the scoreboard per task — cumulative state would let a
        # repeat pass on a previous task's leftovers
        bos("evaluate", {"page": page, "code":
                         "window.__score={events:[],counts:{},"
                         "scroll_top:0,typed:{},lastClick:null};"
                         "document.querySelectorAll('input,textarea')"
                         ".forEach(e=>e.value='');"
                         "document.getElementById('scroller')"
                         ".scrollTop=0;"
                         "document.activeElement.blur();return 'r'"})
        focus_browseros()
        t0 = time.time()
        verdict = act.run_act_loop(task, cfg,
                                   confirm=lambda p: True)
        ms = int((time.time() - t0) * 1000)
        ok = check(page, expr)
        rec = {"i": i, "task": task, "verdict": verdict,
               "verified": ok, "ms": ms, "ts": time.time()}
        results.append(rec)
        print(f"[{i}/{len(tasks)}] {'PASS' if ok else 'FAIL'} "
              f"({ms}ms) {task}\n    {verdict[:140]}",
              flush=True)
        time.sleep(0.5)

    hits = sum(1 for r in results if r["verified"])
    print(f"\n[clicklab] {hits}/{len(results)} verified "
          f"({100 * hits // max(len(results), 1)}%)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"[clicklab] results appended to {OUT}")


if __name__ == "__main__":
    main()
