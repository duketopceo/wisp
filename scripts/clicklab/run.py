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
        [--adaptive] [--no-judge]

`--adaptive` (or `[clicklab] adaptive = "true"`): instead of marching
through the suite, each run's verdict feeds the rolling failure buckets
and the NEXT task is synthesized against the hottest bucket — same
skill, varied surface — until --tasks N (default 12) or the budget cap.
The verdict judge is `[clicklab] judge`: jev (default, brain fallback),
brain, or off — `--no-judge` is the same as off.
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

# U6: the run's cua recording root — session-filtered turn evidence
# under `clicklab-rec/<run-id>/`. Deliberately NOT `rec/`: wispd's
# startup orphan sweep discards every dir there whose turn never
# reached pack-write, which is all of a drill harness's.
CLICKLAB_REC = OUT.parent / "clicklab-rec"


def _cua_client():
    """The cua-driver `call` client the recording wrap drives; kept
    injectable so tests can fake the boundary offline."""
    from wisp import cua, record
    from wisp.pipeline import hypr_env
    return cua.Cua(timeout_s=record.CTRL_TIMEOUT_S, env=hypr_env())


class RunRecording:
    """Wrap the clicklab run in session-filtered cua recording.

    The process's cua session label becomes `clicklab-<run_id>` —
    `wisp.cua.SESSION` + `wisp.record.SESSION` are both rebound — so
    every dispatched call and the act loop's own per-turn recorder ride
    the run label. The outer `start_recording` then covers any cua
    dispatch made between act turns (focus repairs, adaptive probes)
    into `<CLICKLAB_REC>/<run_id>/`.

    The driver keeps ONE recording at a time daemon-wide and
    `stop_recording` is unconditional: each act turn's recorder steals
    the singleton (its `rec/<turn>` dirs are the per-turn evidence the
    row's `turn_dirs` cite) and stops it at turn end, so `rearm()` runs
    after every task to keep covering the gaps. Never raises — a down
    driver just means the run went unrecorded.

    Boundary: `start()` is called after run bring-up, so page focus and
    the --dom origin-probe click stay unrecorded by design (they're
    environment, not drill evidence). `replay`/`distill` run before it
    too — they remain the unrecorded regression harness.
    """

    def __init__(self, run_id: str, root=None, client=None):
        self.run_id = run_id
        self.label = f"clicklab-{run_id}"
        root = pathlib.Path(root) if root else CLICKLAB_REC
        self.dir = root / run_id
        self._client = client
        self.active = False
        self._orig = None          # (cua.SESSION, record.SESSION)

    def start(self) -> "RunRecording":
        try:
            self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.dir, 0o700)
        except OSError as e:
            print(f"[clicklab] rec dir failed: {e}")
            return self
        from wisp import cua, record
        self._orig = (cua.SESSION, record.SESSION)
        cua.SESSION = self.label
        record.SESSION = self.label
        return self.rearm()

    def rearm(self) -> "RunRecording":
        """(Re)issue start_session + start_recording — needed after
        each task because the act turn's recorder ends the global
        recording when its own stop fires."""
        try:
            c = self._client or _cua_client()
            c.call("start_session", {"session": self.label},
                   strict=False, timeout=5.0)
            c.call("start_recording",
                   {"session": self.label,
                    "output_dir": str(self.dir),
                    "include_accessibility_tree": False},
                   strict=False, timeout=5.0)
            self.active = True
        except Exception as e:
            print(f"[clicklab] recording unavailable: {e}")
            self.active = False
        return self

    def row_fields(self, run_steps: list) -> dict:
        """Recording refs folded into a clicklab.jsonl row: the run's
        outer dir + session label, plus the turn dirs the act loop
        attributed to this task's cua dispatches."""
        f = {"rec_dir": str(self.dir), "rec_session": self.label}
        dirs = sorted({str(s["turn_dir"]) for s in run_steps
                       if s.get("turn_dir")})
        if dirs:
            f["turn_dirs"] = dirs
        return f

    def stop(self) -> None:
        try:
            c = self._client or _cua_client()
            c.call("stop_recording", {"session": self.label},
                   strict=False, timeout=5.0)
        except Exception:
            pass
        self.active = False
        if self._orig:
            from wisp import cua, record
            cua.SESSION, record.SESSION = self._orig
            self._orig = None


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
    streak, not just exist in the bank.

    This is the regression harness for banked recipes — deliberately
    not wired into the act loop as a tool and not session-recorded."""
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
    cfg = config.load_config()
    bank = train.load_bank()
    cands = train.distill_candidates(bank, train.promote_after(cfg))
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
    from wisp import config, train
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
    if "--no-judge" in sys.argv:
        cfg.setdefault("clicklab", {})["judge"] = "off"
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
    # U6: wrap the run in session-filtered cua recording under the
    # `clicklab-<run>` session label — every cua dispatch from here on
    # (the act loop's included) rides it, so the run produces the same
    # turn evidence an act turn gets. A down driver just skips it.
    run_id = _flag("--run-id") or (
        time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
    recording = RunRecording(run_id).start()
    results = []
    try:
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
            if _adaptive_on(mcfg):
                results.extend(
                    _run_adaptive(mcfg, suite, page, dom, suite_name,
                                  spec, model, teach, page_name, seed,
                                  recording=recording))
            else:
                results.extend(
                    _run_suite(mcfg, tasks, page, dom, suite_name, spec,
                               model, len(tasks), teach=teach,
                               apps_page=page_name == "apps.html",
                               recording=recording))
    finally:
        recording.stop()

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
    b = train.rebuild_buckets()
    if b.get("fails"):
        cells = sorted(b["cells"].items(), key=lambda kv: -kv[1])[:3]
        print(f"[clicklab] buckets: {b['fails']} fails "
              f"({b['unjudged']} unjudged) — "
              + ", ".join(f"{k}×{v}" for k, v in cells)
              + f" → {train.BUCKETS_FILE}")


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
    except OSError:
        return False


def _evidence(page, cfg, dom) -> dict:
    """Post-run judge evidence: the scoreboard/DOM state dump always;
    a final screenshot only for vision providers outside DOM mode."""
    evd = {}
    try:
        out = ev(page, "return JSON.stringify(window.__score||{})"
                       ".slice(0,1500)")
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            evd["state"] = m.group(0)
    except Exception:
        pass
    if not dom:
        try:
            from wisp import brain as _b, tools as _t
            if _b.supports_vision(cfg):
                shot = _t.run("screenshot", "", cfg)
                if shot.startswith("SHOT "):
                    import base64
                    evd["image"] = base64.b64encode(pathlib.Path(
                        shot[5:].strip()).read_bytes()).decode()
        except Exception:
            pass
    return evd


def _run_task(cfg, page, dom, teach, apps_page, task, expr, oracle_len,
              suite_name, spec, model, i, total, meta=None,
              recording=None) -> dict:
    """One task: reset the board, run the act loop, oracle-check, judge,
    fold into the skill bank + verdict stream. `meta` (adaptive pick
    info) lands on the record so synthesized tasks are attributable."""
    from wisp import act, judge, ledger, train
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
    if recording is not None:
        # the act turn's recorder stopped the driver's (global)
        # recording at loop exit — re-arm the run's outer wrap so
        # out-of-turn dispatches keep landing in the run dir
        recording.rearm()
    usage = ledger.session_totals()
    ms = int((time.time() - t0) * 1000)
    ok = check(page, expr)
    # The judge (Jev, brain fallback, or the oracle alone per
    # [clicklab] judge) reconciles what the scoreboard can't see:
    # efficiency, waste kind, failure class — and whether the agent's
    # claimed outcome is real. Ground truth still wins on success.
    j = judge.verdict(task, run_steps, verdict, cfg, verified=ok,
                      evidence=_evidence(page, cfg, dom))
    # indices of steps that actually executed (not error/skip/refuse)
    nonerr = [n for n, s in enumerate(run_steps)
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
    if meta:
        rec["adaptive"] = meta
    if recording is not None:
        # U6: the run's session-filtered rec dir + this task's
        # attributed turn dirs — the row's evidence pointers
        rec.update(recording.row_fields(run_steps))
    entry = train.update_bank(rec, cfg=cfg)
    if entry.get("changed"):
        print(f"    [bank] {entry['status'].upper()}: "
              f"{entry['task'][:60]}")
    train.record_verdict(rec)
    src = f" [{meta['source']}]" if meta and meta.get("source") \
        != "suite" else ""
    print(f"[{i}/{total}] {'PASS' if ok else 'FAIL'}{src} "
          f"({ms}ms) {task}\n    {verdict[:140]}\n    "
          f"{judge.describe(j)}",
          flush=True)
    return rec


def _blocked(cfg) -> bool:
    from wisp import ledger
    if ledger.status(cfg)["blocked"]:
        print(f"[clicklab] BUDGET CAP reached "
              f"(${ledger.totals()['today_usd']:.2f} spent today) "
              "— stopping")
        return True
    return False


def _adaptive_on(cfg: dict) -> bool:
    return "--adaptive" in sys.argv \
        or cfg.get("clicklab", {}).get("adaptive") == "true"


def _run_adaptive(cfg, suite, page, dom, suite_name, spec, model,
                  teach, page_name, seed, recording=None) -> list:
    """Adaptive mode (U7): the task list is synthesized on the fly —
    each pick aims at the hottest failure bucket (same skill, varied
    surface) instead of marching through a fixed suite."""
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import adaptive as _ad
    import random as _rnd
    from wisp import ledger, train
    ledger.ACTIVE = True
    cap = int(_flag("--tasks", "12"))
    rng = _rnd.Random(seed or int(time.time()))
    history = train._load_jsonl(train.RESULTS)[-200:]
    done = []
    print(f"[clicklab] adaptive: cap {cap}, brain={spec}, "
          f"{len(history)} prior runs seed the buckets")

    def one(task, expr, olen, meta):
        rec = _run_task(cfg, page, dom, teach,
                        apps_page=page_name == "apps.html",
                        task=task, expr=expr, oracle_len=olen,
                        suite_name=suite_name, spec=spec, model=model,
                        i=len(done) + 1, total=cap, meta=meta,
                        recording=recording)
        done.append(rec)
        time.sleep(0.5)
        return rec

    _ad.run_adaptive(one, suite, cap, rng=rng, page=page_name,
                     history=history, halt=lambda: _blocked(cfg))
    hits = sum(1 for r in done if r["verified"])
    spent = sum(r.get("cost_usd") or 0 for r in done)
    print(f"[clicklab:{model}] adaptive {hits}/{len(done)} verified "
          f"(${spent:.4f} this run)")
    return done


def _run_suite(cfg, tasks, page, dom, suite_name, spec, model,
               total, teach=False, apps_page=False,
               recording=None) -> list:
    from wisp import ledger
    ledger.ACTIVE = True  # record every call in the one usage ledger
    print(f"[clicklab] {total} tasks, brain={spec}")
    results = []
    for i, (task, expr, oracle_len) in enumerate(tasks, 1):
        if _blocked(cfg):
            break
        results.append(_run_task(cfg, page, dom, teach, apps_page,
                                 task, expr, oracle_len, suite_name,
                                 spec, model, i, len(tasks),
                                 recording=recording))
        time.sleep(0.5)
    hits = sum(1 for r in results if r["verified"])
    spent = sum(r.get("cost_usd") or 0 for r in results)
    print(f"[clicklab:{model}] {hits}/{len(results)} verified "
          f"(${spent:.4f} this run, ${ledger.totals()['today_usd']:.2f} today)")
    return results


if __name__ == "__main__":
    main()
