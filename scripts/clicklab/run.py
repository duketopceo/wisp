#!/usr/bin/env python3
"""Clicklab — a self-grading pointer-accuracy lab for the act loop.

Serves index.html locally, opens it in a fresh BrowserOS tab, then
drives wisp.act.run_act_loop against a task list. After every task it
evaluates a JS check on window.__score in that page via the BrowserOS
MCP `evaluate` tool — auto-labeled runs, no human ✓/✗.

Usage:
    python3 scripts/clicklab/run.py [--tasks N] [--repeat R]
        [--suite NAME] [--seed S] [--dom] [--only SUBSTR]
        [--page index.html|apps.html] [--teach]
        [--models "provider:model,provider:model"]
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

SUITES_FILE = pathlib.Path(__file__).parent / "suites.json"


def load_suite(name: str) -> list:
    """(instruction, JS check, oracle_len) triples — check body runs
    with `s` bound to window.__score and must return a bool; oracle_len
    is the authored minimal tool-call count (0 = unknown)."""
    suites = json.loads(SUITES_FILE.read_text())
    if name not in suites:
        raise SystemExit(f"unknown suite '{name}' "
                         f"(have: {', '.join(suites)})")
    return [(t[0], t[1], t[2] if len(t) > 2 else 0)
            for t in suites[name]]


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


def open_lab(seed: int = 0, url: str | None = None) -> int:
    """Open clicklab in a new BrowserOS tab; return its page id.
    `seed` reshuffles the page layout (dots/buttons/shapes) so the
    agent can't memorize positions across runs."""
    url = (url or URL) + (f"?seed={seed}" if seed else "")
    out = bos("tabs", {"action": "new", "url": url})
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


def _flag(name: str, default: str = "") -> str:
    """--name value CLI flag."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv \
        else default


def replay(match: str):
    """Re-run a banked step sequence deterministically — no model —
    and re-check the ground truth. Proves a graduated recipe still
    works on a fresh layout seed."""
    from wisp import config, tools, train
    seed = int(_flag("--seed", "0"))
    bank = train.load_bank()
    hits = [e for e in bank.values()
            if match.lower() in (e.get("task") or "").lower()]
    if not hits:
        raise SystemExit(f"no bank entry matching '{match}'")
    serve()
    page = open_lab(seed)
    print(f"[clicklab] replay page {page} seed={seed}")
    cfg = config.load_config()
    cfg.setdefault("screen", {})["dom_page"] = page
    cfg["screen"]["dom_origin"] = [0, 0]
    for e in hits:
        bos("evaluate", {"page": page, "code":
                         "window.__score={events:[],counts:{},"
                         "scroll_top:0,typed:{},lastClick:null};"
                         "return 'r'"})
        print(f"\n== {e['task']}  (status={e['status']})")
        for s in e.get("steps") or []:
            r = tools.run(s["tool"], s.get("arg", ""), cfg)
            print(f"   {s['tool']} {s.get('arg','')[:40]} → {r[:60]}")
        if e.get("check"):
            ok = check(page, e["check"])
            print(f"   → {'PASS' if ok else 'FAIL'} "
                  f"(re-verified on seed={seed})")


def main():
    from wisp import act, config, judge, train
    if "--replay" in sys.argv:
        replay(_flag("--replay"))
        return
    suite_name = _flag("--suite", "core")
    seed = int(_flag("--seed", "0"))
    teach = "--teach" in sys.argv
    page_name = _flag("--page", "index.html")
    url = f"http://127.0.0.1:{PORT}/{page_name}"
    serve()
    print(f"[clicklab] serving on {url} suite={suite_name}"
          + (f" seed={seed}" if seed else "")
          + (" teach" if teach else ""))
    try:
        page = open_lab(seed, url)
    except RuntimeError as e:
        print(f"[clicklab] {e}")
        sys.exit(2)
    print(f"[clicklab] page id {page}")
    dom = "--dom" in sys.argv
    if not dom:
        focus_browseros()
        time.sleep(1)

    cfg = config.load_config()
    cfg.setdefault("screen", {})
    if dom:
        # DOM-schematic mode: screenshots are synthesized from element
        # rects — works with the panel powered off (lid closed)
        cfg["screen"]["dom_page"] = page
        cfg["screen"]["output"] = ""
        # clicks in dom mode are pure viewport CSS px — no compositor
        # origin involved; keep SHOT_ORIGIN bookkeeping consistent
        cfg["screen"]["dom_origin"] = [0, 0]
        # liveness probe: a DOM click at a known element's rect
        probe_id = "tab-chess" if page_name == "apps.html" \
            else "btn-alpha"
        out = bos("evaluate", {"page": page, "code":
                               f"var b=document.getElementById('{probe_id}');"
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
        cfg["screen"]["output"] = _flag("--output")
    repeat = int(_flag("--repeat", "1"))
    suite = load_suite(suite_name)
    only = _flag("--only")
    if only:
        suite = [t for t in suite
                 if only.lower() in t[0].lower()]
        if not suite:
            raise SystemExit(f"no task in '{suite_name}' "
                             f"matching '{only}'")
    n = int(_flag("--tasks", str(len(suite))))
    tasks = (suite * repeat)[:n * repeat]

    # --models "provider:model,provider:model" — same suite, same seed,
    # each run tagged with the actor so the bank and arena compare
    # models on equal footing. Local endpoints get a health check and
    # are skipped (not failed) when their server is down.
    specs = [s.strip() for s in _flag("--models").split(",")
             if s.strip()]
    if not specs:
        specs = [cfg.get("brain", {}).get("default", "openrouter")]
    results = []
    for spec in specs:
        if ":" not in spec:
            print(f"[clicklab] bad --models spec '{spec}' — want "
                  "provider:model; skipping")
            continue
        import copy as _copy
        mcfg = _copy.deepcopy(cfg)
        mcfg.setdefault("brain", {})["default"] = spec
        model = spec.split(":", 1)[1]
        if not _provider_up(mcfg):
            print(f"[clicklab] SKIP {spec} — provider unreachable")
            continue
        results.extend(
            _run_suite(mcfg, tasks, page, dom, suite_name, spec,
                       model, len(tasks), teach=teach,
                       apps_page=page_name == "apps.html"))

    hits = sum(1 for r in results if r["verified"])
    print(f"\n[clicklab] {hits}/{len(results)} verified "
          f"({100 * hits // max(len(results), 1)}%)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"[clicklab] results appended to {OUT}")


def _provider_up(cfg: dict) -> bool:
    """Local OpenAI-compatible endpoints get a 3s reachability probe;
    remote providers are assumed up."""
    from wisp import brain as _brain
    p = _brain.provider(cfg)
    base = (p.get("base_url") or "").rstrip("/")
    if not base or "openrouter.ai" in base:
        return True
    if not re.search(r"127\.0\.0\.1|localhost", base):
        return True
    try:
        import urllib.request
        urllib.request.urlopen(f"{base}/models", timeout=3)
        return True
    except Exception:
        return False


def _run_suite(cfg, tasks, page, dom, suite_name, spec, model,
               total, teach=False, apps_page=False) -> list:
    from wisp import act, judge, train
    print(f"[clicklab] {total} tasks, brain={spec}")
    results = []
    for i, (task, expr, oracle_len) in enumerate(tasks, 1):
        # reset the scoreboard per task — cumulative state would let a
        # repeat pass on a previous task's leftovers. The apps page
        # keeps board/app state in __score so a reload is the cleanest
        # reset; index.html resets in place.
        if apps_page:
            bos("evaluate", {"page": page, "code": "location.reload()"})
            time.sleep(1.5)
        else:
            bos("evaluate", {"page": page, "code":
                             "window.__score={events:[],counts:{},"
                             "scroll_top:0,typed:{},lastClick:null};"
                             "document.querySelectorAll('input,textarea')"
                             ".forEach(e=>e.value='');"
                             "document.getElementById('scroller')"
                             ".scrollTop=0;"
                             "document.activeElement.blur();return 'r'"})
        if not dom:
            focus_browseros()
        ask = ("Teach the user as you go — briefly say what you are "
               "doing and why before each action, then do it: " + task
               if teach else task)
        t0 = time.time()
        run_steps: list = []
        verdict = act.run_act_loop(ask, cfg,
                                   confirm=lambda p: True,
                                   steps_out=run_steps)
        ms = int((time.time() - t0) * 1000)
        ok = check(page, expr)
        # Jev judges what the scoreboard can't: efficiency, waste kind,
        # and whether the agent's claimed outcome is real. Ground truth
        # still wins on success — the judge reconciles, not overrides.
        j = judge.verdict(task, run_steps, verdict, cfg,
                          verified=ok) if "--no-judge" not in sys.argv \
            else {"success": ok, "efficiency": None, "waste": "none",
                  "first_fault": -1}
        # indices of steps that actually executed (not error/skip/refuse)
        nonerr = [i for i, s in enumerate(run_steps)
                  if not str(s.get("result", "")).startswith(
                      ("ERROR", "SKIP", "REFUS"))]
        # first-fault fallback when the judge didn't name one: verified
        # fails fault at the last executed step, clean passes at none.
        if j.get("first_fault", -1) < 0 and ok is False:
            j["first_fault"] = nonerr[-1] if nonerr else -1
        # Objective efficiency when the suite carries an oracle:
        # minimal-steps / executed-steps, capped at 1.0. Jev's verdict
        # stays on the record for disagreement auditing; `efficiency`
        # resolves to the oracle when present.
        actual = len(nonerr)
        eff_obj = (min(1.0, oracle_len / max(actual, 1))
                   if oracle_len else None)
        eff = eff_obj if eff_obj is not None else j.get("efficiency")
        rec = {"i": i, "task": task, "suite": suite_name,
               "teach": teach or None,
               "check": expr, "verdict": verdict,
               "verified": ok, "judge": j, "surface": "browser-dom",
               "model": model, "provider": spec,
               "efficiency": eff, "oracle_len": oracle_len or None,
               "actual_len": actual,
               "flake": train.classify_flake(
                   {"verified": ok, "judge": j, "steps": run_steps,
                    "verdict": verdict}),
               "cost_usd": 0.0 if not spec.startswith("openrouter")
               else None,
               "steps": run_steps[:24], "ms": ms, "ts": time.time()}
        results.append(rec)
        entry = train.update_bank(rec)
        if entry.get("changed"):
            print(f"    [bank] {entry['status'].upper()}: "
                  f"{entry['task'][:60]}")
        print(f"[{i}/{len(tasks)}] {'PASS' if ok else 'FAIL'} "
              f"({ms}ms) {task}\n    {verdict[:140]}\n    "
              f"{judge.describe(j)}",
              flush=True)
        time.sleep(0.5)
    hits = sum(1 for r in results if r["verified"])
    print(f"[clicklab:{model}] {hits}/{len(results)} verified")
    return results


if __name__ == "__main__":
    main()
