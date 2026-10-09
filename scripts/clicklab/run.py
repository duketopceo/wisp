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
    src = _flag("--suite-file")
    suites = json.loads((pathlib.Path(src) if src
                         else SUITES_FILE).read_text())
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
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT),
                                                handler)
    except OSError:
        return None  # another run already serves the lab
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def bos(tool: str, args: dict) -> str:
    from wisp.tools import mcpclient
    return mcpclient.call(f"browseros-neo {tool} {json.dumps(args)}", {})


def _lab_url(cdp_host: str, page_name: str, seed: int) -> str:
    """Where the lab lives for a CDP endpoint: guests get the baked-in
    file:// copy; a local browser reaches the http server directly."""
    base = (f"http://127.0.0.1:{PORT}/{page_name}"
            if cdp_host in ("127.0.0.1", "localhost")
            else f"file:///opt/lab/{page_name}")
    return base + (f"?seed={seed}" if seed else "")


def open_lab(seed: int = 0, url: str | None = None) -> int:
    """Open clicklab in a new BrowserOS tab; return its page id.
    `seed` reshuffles the page layout (dots/buttons/shapes) so the
    agent can't memorize positions across runs."""
    url = (url or URL) + (f"?seed={seed}" if seed else "")
    # don't pile up clicklab tabs across runs — close stale ones, but
    # never a tab claimed by a live sibling run (parallel hammering)
    live = _live_pages()
    out = bos("tabs", {"action": "list"})
    for tid in re.findall(r"\[(\d+)\][^\n]*" + str(PORT), out):
        if int(tid) not in live:
            bos("tabs", {"action": "close", "page": int(tid)})
    out = bos("tabs", {"action": "new", "url": url})
    m = re.search(r"page (\d+)", out)
    if m:
        page = int(m.group(1))
        import atexit
        _claim(page)
        atexit.register(bos, "tabs", {"action": "close", "page": page})
        time.sleep(2)
        return page
    # fall back: find it in the tab list
    time.sleep(2)
    out = bos("tabs", {"action": "list"})
    ids = re.findall(r"\[(\d+)\][^\n]*" + str(PORT), out)
    if not ids:
        raise RuntimeError("clicklab tab not found:\n" + out)
    page = int(ids[-1])
    _claim(page)
    import atexit
    atexit.register(bos, "tabs", {"action": "close", "page": page})
    return page


import os

LIVE_DIR = (pathlib.Path.home()
            / ".local/share/wisp/clicklab-live")


def _live_pages() -> set:
    """Page ids claimed by running clicklab processes (pid liveness)."""
    out = set()
    try:
        for f in LIVE_DIR.glob("*.json"):
            try:
                rec = json.loads(f.read_text())
                pid = int(f.stem)
                os.kill(pid, 0)          # raises if dead
                out.add(int(rec["page"]))
            except (ValueError, OSError, json.JSONDecodeError,
                    KeyError):
                f.unlink(missing_ok=True)  # dead process: reclaim
    except OSError:
        pass
    return out


def _claim(page: int) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    f = LIVE_DIR / f"{os.getpid()}.json"
    f.write_text(json.dumps({"page": page, "ts": time.time()}))
    import atexit
    atexit.register(f.unlink, missing_ok=True)


def ev(page, code: str) -> str:
    """Evaluate JS on the lab page — CDP Page object or neo tab id."""
    if hasattr(page, "evaluate"):          # cdpx.Page
        try:
            return page.evaluate(code)
        except Exception as e:
            return f"CDP_ERR ({e})"
    return bos("evaluate", {"page": page, "code": code})


def check(page, expr: str) -> bool:
    code = (f"var s = window.__score || {{}}; {expr}")
    return "true" in ev(page, code).lower()


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
    """Re-run a graduated recipe's banked steps — no model, $0 — and
    re-check the ground truth on a fresh layout seed. Candidates are
    skipped unless --all is passed; a recipe must earn replay via the
    streak, not just exist in the bank."""
    from wisp import config, tools, train
    seed = int(_flag("--seed", "0"))
    bank = train.load_bank()
    m = match.lower()
    hits = [e for e in bank.values()
            if m in (e.get("task") or "").lower()
            or m == (e.get("recipe_id") or "").lower()]
    if "--all" not in sys.argv:
        skipped = [e for e in hits if e.get("status") != "graduated"]
        hits = [e for e in hits if e.get("status") == "graduated"]
        for e in skipped:
            print(f"[clicklab] skip {e.get('task')!r} "
                  f"(status={e.get('status')}, needs {train.GRAD_STREAK}"
                  f" verified streak)")
    if not hits:
        raise SystemExit(f"no graduated recipe matching '{match}'")
    serve()
    page = open_lab(seed)
    print(f"[clicklab] replay page {page} seed={seed}")
    cfg = config.load_config()
    cfg.setdefault("screen", {})["dom_page"] = page
    cfg["screen"]["dom_origin"] = [0, 0]
    failed = False
    for e in hits:
        bos("evaluate", {"page": page, "code":
                         "window.__score={events:[],counts:{},"
                         "scroll_top:0,typed:{},lastClick:null};"
                         "return 'r'"})
        rid = e.get("recipe_id") or "unpromoted"
        print(f"\n== {e['task']}  ({rid}, status={e['status']})")
        for s in e.get("steps") or []:
            r = tools.run(s["tool"], s.get("arg", ""), cfg)
            print(f"   {s['tool']} {s.get('arg','')[:40]} → {r[:60]}")
        if e.get("check"):
            ok = check(page, e["check"])
            failed = failed or not ok
            print(f"   → {'PASS' if ok else 'FAIL'} "
                  f"(re-verified on seed={seed})")
    if failed:
        raise SystemExit(1)


def distill():
    """Re-verify distilled (minimal) trajectories for streak-rich
    candidates and promote the ones that hold on a fresh seed —
    'reliable but wasteful' recipes become replayable graduates without
    another model run."""
    from wisp import config, tools, train
    seed = int(_flag("--seed", "0"))
    bank = train.load_bank()
    cands = train.distill_candidates(bank)
    if "--dry-run" in sys.argv or not cands:
        for e in cands:
            print(f"[distill] {e['task'][:60]!r} streak={e['streak']} "
                  f"{len(e['steps'])}→{len(train.distill_steps(e['steps']))} "
                  "steps")
        if not cands:
            print("[distill] no candidates")
        return
    serve()
    cdp = _flag("--cdp")
    cfg = config.load_config()
    cfg.setdefault("screen", {})

    def _open(page_name: str):
        """Fresh lab page for a candidate group — local http for a
        local CDP endpoint / BrowserOS, file://opt/lab on CubeVM."""
        if cdp:
            from wisp.tools import cdpx
            host, _, port = cdp.partition(":")
            return cdpx.open_page(host, _lab_url(host, page_name, seed),
                                  int(port or 9222))
        return open_lab(seed, f"http://127.0.0.1:{PORT}/{page_name}")

    def _page_for(e: dict) -> str:
        s = str(e.get("suite") or "")
        return "apps.html" if s.startswith("apps-") else "index.html"

    changed = False

    def _run_group(entries, page_name, retry_out=None):
        nonlocal changed
        if not entries:
            return
        page = _open(page_name)
        cfg["screen"]["dom_page"] = "cdp" if cdp else page
        if cdp:
            cfg["screen"]["dom_cdp_page"] = page
        cfg["screen"]["dom_origin"] = [0, 0]
        for e in entries:
            # reload per candidate: DOM mutations (stars, select
            # values, open files) persist across entries — a score
            # reset alone leaves stale state that flips checks
            ev(page, "location.reload(); return 'r'")
            for _ in range(20):
                time.sleep(0.3)
                if "object" in ev(
                        page, "return typeof window.__score"):
                    break
            d = train.distill_steps(e["steps"])
            print(f"\n== {e['task']}  {len(e['steps'])}→{len(d)} steps "
                  f"(streak={e['streak']})")
            for s in d:
                r = tools.run(s["tool"], s.get("arg", ""), cfg)
                print(f"   {s['tool']} {s.get('arg','')[:40]} → {r[:60]}")
            if check(page, e["check"]):
                train.promote(e, d)
                print(f"   → PASS — graduated {e['recipe_id']}")
            elif retry_out is not None:
                retry_out.append(e)
                print(f"   → miss on {page_name} — retrying other page")
                continue
            else:
                e["distill_fails"] = e.get("distill_fails", 0) + 1
                print("   → FAIL (stays candidate)")
            changed = True

    groups: dict = {}
    for e in cands:
        groups.setdefault(_page_for(e), []).append(e)
    for page_name, entries in groups.items():
        # suite-less entries (pre-suite-tagging records) can't be
        # routed — a miss on one page retries on the other
        unsuited = [e for e in entries if not e.get("suite")]
        suited = [e for e in entries if e.get("suite")]
        retry = []
        _run_group(suited, page_name)
        _run_group(unsuited, page_name, retry_out=retry)
        other = "index.html" if page_name == "apps.html" else "apps.html"
        _run_group(retry, other)
    if changed:
        train.save_bank(bank)


def main():
    from wisp import act, config, judge, train
    if "--replay" in sys.argv:
        replay(_flag("--replay"))
        return
    if "--distill" in sys.argv:
        distill()
        return
    suite_name = _flag("--suite", "core")
    seed = int(_flag("--seed", "0"))
    teach = "--teach" in sys.argv
    page_name = _flag("--page", "index.html")
    cdp = _flag("--cdp")                   # "host:port" of a chromium
    if cdp:
        # sandboxed chromium (CubeVM guest) gets the baked file:// lab;
        # a local CDP endpoint reaches this process's http server
        url = _lab_url(cdp.partition(":")[0], page_name, seed)
        serve()
        print(f"[clicklab] cdp={cdp} url={url} suite={suite_name}")
        from wisp.tools import cdpx
        chost, _, cport = cdp.partition(":")
        page = cdpx.open_page(chost, url, int(cport or 9222))
        import atexit
        atexit.register(page.close)
    else:
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
    print(f"[clicklab] page {page}")
    dom = "--dom" in sys.argv or bool(cdp)
    if not dom:
        focus_browseros()
        time.sleep(1)

    cfg = config.load_config()
    cfg.setdefault("screen", {})
    if dom:
        # DOM-schematic mode: screenshots are synthesized from element
        # rects — works with the panel powered off (lid closed)
        cfg["screen"]["dom_page"] = "cdp" if cdp else page
        if cdp:
            cfg["screen"]["dom_cdp_page"] = page
        cfg["screen"]["output"] = ""
        # clicks in dom mode are pure viewport CSS px — no compositor
        # origin involved; keep SHOT_ORIGIN bookkeeping consistent
        cfg["screen"]["dom_origin"] = [0, 0]
        # liveness probe: a DOM click at a known element's rect
        probe_id = "tab-chess" if page_name == "apps.html" \
            else "btn-alpha"
        out = ev(page,
                 f"var b=document.getElementById('{probe_id}');"
                 "if(!b)return 'miss';"
                 "var r=b.getBoundingClientRect();"
                 "return ''+Math.round(r.x+r.width/2)+','+"
                 "Math.round(r.y+r.height/2)")
        m = re.search(r"(\d+),(\d+)", out)
        if m:
            from wisp import tools
            print(f"[clicklab] probe click at {m.group(0)}")
            print(f"[clicklab] probe → "
                  f"{tools.run('click', m.group(0), cfg)}")
            ev(page, "window.__score={events:[],counts:{},"
                     "scroll_top:0,typed:{},lastClick:null};"
                     "'reset'")
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
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import arena_policy
    try:
        arena_policy.gate(specs)
    except arena_policy.PolicyError as e:
        raise SystemExit(f"[clicklab] refused: {e}")
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

    # parallel-worker attribution: hammer-parallel.sh passes --worker
    # and --sandbox-id so records can be grouped per CubeVM worker
    _stamp(results, _flag("--worker"), _flag("--sandbox-id"))

    hits = sum(1 for r in results if r["verified"])
    print(f"\n[clicklab] {hits}/{len(results)} verified "
          f"({100 * hits // max(len(results), 1)}%)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"[clicklab] results appended to {OUT}")


def _stamp(results: list, worker, sandbox_id):
    """Add worker/sandbox attribution to every record (parallel runs)."""
    if not worker and not sandbox_id:
        return
    for r in results:
        if worker:
            r["worker"] = int(worker) if str(worker).lstrip("-").isdigit() else worker
        if sandbox_id:
            r["sandbox_id"] = sandbox_id


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
    from wisp import act, judge, ledger, train
    ledger.ACTIVE = True  # record every call in the one usage ledger
    print(f"[clicklab] {total} tasks, brain={spec}")
    results = []
    for i, (task, expr, oracle_len) in enumerate(tasks, 1):
        if ledger.status(cfg)["blocked"]:
            print(f"[clicklab] BUDGET CAP reached "
                  f"(${ledger.totals()['today_usd']:.2f} spent today) "
                  f"— stopping")
            break
        # reset the scoreboard per task — cumulative state would let a
        # repeat pass on a previous task's leftovers. The apps page
        # keeps board/app state in __score so a reload is the cleanest
        # reset; index.html resets in place.
        if apps_page:
            ev(page, "location.reload();'reloading'")
            time.sleep(1.5)
        else:
            ev(page, "window.__score={events:[],counts:{},"
                     "scroll_top:0,typed:{},lastClick:null};"
                     "document.querySelectorAll('input,textarea')"
                     ".forEach(e=>e.value='');"
                     "var sc=document.getElementById('scroller');"
                     "if(sc)sc.scrollTop=0;"
                     "document.activeElement.blur();'r'")
        if not dom:
            focus_browseros()
        ask = ("Teach the user as you go — briefly say what you are "
               "doing and why before each action, then do it: " + task
               if teach else task)
        t0 = time.time()
        run_steps: list = []
        ledger.reset_session()
        verdict = act.run_act_loop(ask, cfg,
                                   confirm=lambda p: True,
                                   steps_out=run_steps)
        usage = ledger.session_totals()
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
               "cost_usd": usage["cost"],
               "tokens": {"prompt": usage["prompt_tokens"],
                          "completion": usage["completion_tokens"],
                          "calls": usage["calls"]},
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
    spent = sum(r.get("cost_usd") or 0 for r in results)
    print(f"[clicklab:{model}] {hits}/{len(results)} verified "
          f"(${spent:.4f} this run, ${ledger.totals()['today_usd']:.2f} today)")
    return results


if __name__ == "__main__":
    main()
