"""Diagnostics: doctor, health, latency, spend, binds, onboard, whatsnew,
bugreport."""
import datetime
import json
import shutil
import subprocess

from .. import config
from .registry import CliError, GROUPS, command

GROUPS["health"] = "Local model endpoint health"


# -- doctor ---------------------------------------------------------------

def doctor_sections(cfg: dict, cua_probe=None) -> list:
    """[{name, rows:[{name, value, ok}]}] for everything wispd needs."""
    from .. import agents, brain, health as _health, ipc, \
        platform as _plat, skills
    sections = []

    def section(name):
        rows = []
        sections.append({"name": name, "rows": rows})

        def row(label, value, ok=True):
            rows.append({"name": label, "value": str(value),
                         "ok": bool(ok)})
        return row

    row = section("daemon")
    row("wispd", "running" if ipc.alive() else "not running")

    from .. import svc
    svc_rows = svc.doctor_rows() if _plat.current() == "linux" else []
    if svc_rows:
        row = section("services")
        for r in svc_rows:
            row(r["name"], r["value"], r["ok"])

    row = section("agent runtimes")
    found = agents.detect_runtimes()
    chosen = agents.resolve_runtime(cfg)
    for rt in ("opencode", "codex", "claude", "devin"):
        mark = " (selected)" if rt == chosen else ""
        if rt in found:
            row(rt, found[rt] + mark)
        else:
            # a missing runtime only fails doctor when it's the
            # explicitly configured one; auto falls back
            row(rt, f"not on PATH{mark}", ok=(rt != chosen or not mark))
    if cfg.get("brain", {}).get("agent_runtime", "auto") == "auto" \
            and not chosen:
        row("agent_runtime", "auto but nothing detected", ok=False)

    row = section("stt / audio")
    wm = config.whisper_model(cfg)
    stt = config.stt_settings(cfg)["provider"]
    # whisper.cpp is opt-in; hosted STT needs no local model
    row("whisper model", wm.name, stt != "local" or wm.exists())
    row("stt provider", stt)
    for b in ("pw-record", "wtype", "grim"):
        row(b, shutil.which(b) or "not on PATH", bool(shutil.which(b)))

    row = section("brain / router")
    p = brain.provider(cfg)
    row("answer provider", f"{p['name']}:{p['model']}")
    row("vision", p.get("vision"))
    row("tools", p.get("tools"))
    key = config.load_env_key(p.get("key_env", "")) \
        if p.get("key_env") else "n/a"
    row("api key", "set" if key == "set" or (key and key != "n/a")
        else key or "MISSING", bool(key))

    row = section("health")
    snap = _health.HealthRegistry(cfg).probe_all()
    if not snap:
        row("endpoints", "none local to probe")
    for name, h in snap.items():
        row(name, f"{h['latency_ms']} ms" if h["ok"]
            else f"DOWN ({h['code']})", h["ok"])

    row = section("pointer")
    pb = _plat.pointer_backend(cfg)
    row("pointer backend", pb or "none, guide mode only")
    row("pointer mode", cfg.get("pointer", {}).get("mode", "guide"))
    _cua_rows(row, cfg, cua_probe)

    row = section("integrations")
    row("dayflow", shutil.which("dayflow") or "not installed",
        bool(shutil.which("dayflow")))
    row("codegraph (CBM)", shutil.which("codebase-memory-mcp")
        or "not installed")
    row("hyprctl", shutil.which("hyprctl") or "not on PATH",
        bool(shutil.which("hyprctl")))
    row("sense enabled", cfg.get("sense", {}).get("enabled", "false"))

    row = section("voice")
    _voice_rows(row, cfg)

    row = section("reporting")
    from .. import report as _report
    on, depth = _report.status(cfg)
    row("error reporting", f"on, {depth} queued" if on else "off")

    row = section("data")
    row("skills", str(len(skills.index())) + " installed")
    for f in ("decisions.jsonl", "labels.jsonl", "activity.jsonl"):
        fp = config.DATA_DIR / f
        row(f, f"{fp.stat().st_size // 1024}KB" if fp.exists()
            else "absent")
    return sections


def _voice_rows(row, cfg: dict) -> None:
    """Who speaks now, the last Groq error with its fix, and when Groq is
    retried. Reads the daemon's voice_groq.json; no network call."""
    from .. import speech, tts_groq
    name, why = speech.backend(cfg)
    row("voice backend", f"{name}: {why}")
    if tts_groq.provider(cfg) != "groq":
        return
    err = tts_groq.last_error()
    until = tts_groq.backoff_until()
    if not err:
        row("groq last error", "none")
    else:
        kind = err["class"]
        if kind == "terms":
            fix = ("accept the Orpheus terms once at "
                   + tts_groq.TERMS_LINK)
        elif kind == "rate_limit":
            fix = (f"rate limited until {tts_groq.fmt_time(until)}; a paid "
                   "Groq tier lifts the limit" if until else "rate limited")
        elif kind == "auth":
            fix = "Groq rejected the key; fix groq/default in omaseal"
        else:
            fix = err.get("detail") or "see the daemon log"
        row("groq last error", f"{kind}: {fix}")
    now = tts_groq._now()
    row("groq retry", f"at {tts_groq.fmt_time(until)}" if until > now
        else "now")


def _cua_rows(row, cfg: dict, probe=None) -> None:
    """cua driver state, pinned version, safety modes, audit log (W10)."""
    from .. import cua_safety, probes_cua
    r = (probe or probes_cua.CuaProbe(cfg)).check()
    st = r["state"]
    want = cfg.get("pointer", {}).get("backend", "auto") == "cua"
    label = st.replace("_", " ")
    if st == "absent":
        row("cua driver", "not installed: wispd install --cua",
            not want)
    elif r["ok"]:
        row("cua driver", label)
    else:
        row("cua driver", f"{label}: {r['fix']}", False)
    if r["binary"]:
        v = r["version"] or "unknown"
        pin = r["pin"] or "unpinned"
        row("cua version", f"{v} (pin {pin})",
            st != "version_mismatch")
    s = cua_safety.settings(cfg)
    from .. import delivery as _del
    modes = ["KILL SWITCH ON" if r["kill"] else "kill off",
             "dry-run on" if s["dry_run"] else "dry-run off",
             f"delivery {_del.mode(cfg)}",
             f"{s['per_min']}/min, {s['per_turn']}/turn"]
    row("cua safety", ("safety on, " if s["safety"] else "SAFETY OFF, ")
        + ", ".join(modes), s["safety"])
    ap = cua_safety.audit_default_path()
    row("cua audit log", f"{ap} ({ap.stat().st_size // 1024}KB)"
        if ap.exists() else f"{ap} (empty)")
    from .. import record as _rec
    pr = _rec.probe(cfg)
    row("turn recording", pr["detail"], pr["ok"] or pr["skipped"])


@command("doctor", "Check every dependency wisp needs",
         ["wispd doctor", "wispd doctor --json"],
         {"healthy": "bool", "sections": "list"})
def doctor(ctx, a):
    sections = doctor_sections(ctx.cfg)
    bad = sum(1 for s in sections for r in s["rows"] if not r["ok"])
    data = {"healthy": bad == 0, "sections": sections}
    if not ctx.json and not ctx.flags.quiet:
        if True:
            for s in sections:
                print(f"{s['name']}:")
                rows = [["ok" if r["ok"] else "MISS", r["name"], r["value"]]
                        for r in s["rows"]]
                tones = [["ok" if r["ok"] else "fail", None, None]
                         for r in s["rows"]]
                print("\n".join("  " + ln for ln in ctx.table(
                    ["", "", ""], rows, tones, header=False).splitlines()))
    if bad:
        raise CliError("E_UNHEALTHY", f"{bad} check"
                       f"{'s' if bad != 1 else ''} need attention.",
                       "Fix the MISS rows above, then run wispd doctor "
                       "again", data=data)
    return ctx.emit(data)


# -- health ---------------------------------------------------------------

def _snapshot(ctx) -> dict:
    from .. import health as _health
    return _health.HealthRegistry(ctx.cfg).probe_all()


@command("health", "Probe the local model endpoints",
         ["wispd health", "wispd health --json"],
         {"healthy": "bool", "endpoints": "list"})
def health(ctx, a):
    snap = _snapshot(ctx)
    eps = [{"name": n, "ok": bool(h["ok"]),
            "latency_ms": h.get("latency_ms"), "code": h.get("code")}
           for n, h in snap.items()]
    if ctx.legacy:  # `wispd models`: the pre-W19 lines, always exit 0
        if not eps:
            print("no local endpoints configured")
        for e in eps:
            print(f"{'ok  ' if e['ok'] else 'DOWN'} {e['name']:<16} "
                  + (f"{e['latency_ms']} ms" if e["ok"] else e["code"]))
        return 0
    down = [e for e in eps if not e["ok"]]
    data = {"healthy": not down, "endpoints": eps}
    if not eps:
        return ctx.emit(data, "no local endpoints configured")
    rows = [[e["name"], "ok" if e["ok"] else "DOWN",
             f"{e['latency_ms']} ms" if e["ok"] else "-", e["code"] or ""]
            for e in eps]
    tones = [[None, "ok" if e["ok"] else "fail", "muted", "muted"]
             for e in eps]
    text = ctx.table(["endpoint", "status", "latency", "code"], rows, tones)
    if not down:
        return ctx.emit(data, text)
    if not ctx.json and not ctx.flags.quiet:
        print(text)
    raise CliError("E_UNHEALTHY", f"{len(down)} of {len(eps)} local "
                   "endpoints are down.", "wispd health start", data=data)


def _idle_args(p):
    p.add_argument("--seconds", type=float, default=3.0, metavar="N",
                   help="how long to watch the idle daemon "
                        "(1 to 60, default 3)")


@command("health idle",
         "Measure the running daemon's idle CPU and memory against its "
         "budgets",
         ["wispd health idle", "wispd health idle --seconds 10 --json"],
         {"pid": "int", "seconds": "float", "cpu_pct": "float",
          "rss_mb": "float", "budget_cpu_pct": "float",
          "budget_rss_mb": "float", "ok": "bool", "over": "list"},
         args=_idle_args)
def health_idle(ctx, a):
    from .. import idle, instance
    if not 1 <= a.seconds <= 60:
        raise CliError("E_USAGE", "--seconds must be between 1 and 60.",
                       "wispd health idle --seconds 3")
    pid = instance.holder()
    s = idle.sample(pid, a.seconds) if pid else None
    if s is None:
        raise CliError("E_DAEMON_DOWN", "No running wispd to measure.",
                       "wispd daemon run")
    b = idle.budgets()
    over = idle.breaches(s, b)
    data = {**s, "budget_cpu_pct": b["cpu_pct"],
            "budget_rss_mb": b["rss_mb"], "ok": not over, "over": over}
    text = (f"pid {s['pid']}, {s['seconds']} s idle: "
            f"CPU {s['cpu_pct']}% (budget {b['cpu_pct']:g}%), "
            f"memory {s['rss_mb']} MB (budget {b['rss_mb']:g} MB)")
    if not over:
        return ctx.emit(data, text)
    if not ctx.json and not ctx.flags.quiet:
        print(text)
    raise CliError("E_UNHEALTHY", "; ".join(over) + ".",
                   "wispd trace", data=data)


def _start_args(p):
    p.add_argument("--run", action="store_true",
                   help="execute the systemctl command (default: print it)")


@command("health start",
         "Print (or with --run, execute) the command that starts down "
         "endpoints",
         ["wispd health start", "wispd health start --run"],
         {"units": "list", "command": "str|null", "ran": "bool"},
         args=_start_args)
def health_start(ctx, a):
    from .. import health as _health
    units = _health.units_to_start(ctx.cfg, _snapshot(ctx))
    if not units:
        return ctx.emit({"units": [], "command": None, "ran": False},
                        "nothing to start (no down endpoint has units in "
                        "[health.units])")
    cmd = _health.start_command(units)
    line = " ".join(cmd)
    if not a.run:
        return ctx.emit({"units": units, "command": line, "ran": False},
                        line + "\n(dry run — add --run to execute)")
    rc = subprocess.run(cmd).returncode
    if rc:
        raise CliError("E_FAILED", f"systemctl exited {rc}.",
                       "wispd doctor", data={"units": units,
                                             "command": line, "ran": True})
    return ctx.emit({"units": units, "command": line, "ran": True})


# -- latency --------------------------------------------------------------

def _latency_args(p):
    p.add_argument("--since", default="24h", metavar="AGE",
                   help="window: 24h, 90m, 2d (default 24h)")
    p.add_argument("--budgets", action="store_true",
                   help="print the budget table instead of a report")
    p.add_argument("--baseline", action="store_true",
                   help="show the committed harness baseline (fakes)")
    p.add_argument("--harness", action="store_true",
                   help="measure now from the replay harness (fakes, "
                        "needs a repo checkout)")


@command("latency", "p50 and p90 per budget path from recent turns",
         ["wispd latency", "wispd latency --since 6h --json",
          "wispd latency --budgets", "wispd latency --harness"],
         {"since_h": "float", "turns": "int", "rows": "list"},
         args=_latency_args)
def latency(ctx, a):
    from .. import telemetry
    if a.budgets:
        t = telemetry.load_budgets()
        return ctx.emit({"paths": t["paths"], "resources": t["resources"],
                         "p90_factor": t["p90_factor"]},
                        telemetry.budgets_text())
    if a.baseline or a.harness:
        return _latency_harness(ctx, a)
    hours = telemetry.parse_since(a.since)
    rep = telemetry.latency_report(hours)
    data = {"since_h": hours, "turns": rep["turns"], "rows": rep["rows"]}
    h = f"{hours:g}h"
    if not rep["turns"]:
        return ctx.emit(data, f"no spans in the last {h} "
                              "(run a turn first)")
    rows = [[r["id"], r["label"], r["n"],
             "-" if r["p50"] is None else r["p50"],
             "-" if r["p90"] is None else r["p90"], r["budget_p50"],
             r["verdict"]] for r in rep["rows"]]
    tones = [[None] * 6 + [{"ok": "ok", "MISS": "fail"}.get(r["verdict"],
                                                            "muted")]
             for r in rep["rows"]]
    text = f"latency {h}, {rep['turns']} turns (ms)\n" + ctx.table(
        ["id", "path", "n", "p50", "p90", "budget", "verdict"], rows, tones)
    return ctx.emit(data, text)


def _latency_harness(ctx, a):
    """Harness numbers: the committed baseline, or a fresh fake run."""
    from .. import telemetry
    if a.harness:
        import pathlib
        import sys
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        if not (root / "tests" / "harness").is_dir():
            raise CliError("E_NOT_FOUND", "the replay harness needs a "
                           "repo checkout (tests/harness is missing).",
                           "wispd latency --baseline")
        sys.path.insert(0, str(root / "tests"))
        from harness import latency as hl
        series = hl.measure(3)
        doc = {"fakes_only": True, "paths": hl.summarize(series),
               "regressions": hl.check(series)}
    else:
        doc = telemetry.load_baseline()
        if not doc:
            raise CliError("E_NOT_FOUND", "no committed harness baseline.",
                           "python scripts/latency_baseline.py --record")
    rows = [[pid, r["label"], r["n"], r["p50"], r["p90"],
             r["budget_p50_ms"]] for pid, r in doc["paths"].items()]
    text = ("latency from the replay harness (fake models, ms)\n"
            + ctx.table(["id", "path", "n", "p50", "p90", "budget"], rows))
    for b in doc.get("regressions", []):
        text += f"\nREGRESSION: {b}"
    return ctx.emit(doc, text)


# -- spend ----------------------------------------------------------------

@command("spend", "Model usage today and the daily and monthly caps",
         ["wispd spend", "wispd spend --json"],
         {"today_usd": "float", "month_usd": "float",
          "calls_today": "int", "cap_usd": "float|null",
          "monthly_cap_usd": "float|null", "blocked": "bool",
          "paid_allowed": "bool", "models": "list", "source": "str"})
def spend(ctx, a):
    from .. import ledger
    target = ledger.path()
    try:
        st = ledger.status(ctx.cfg)
    except OSError as e:
        raise CliError("E_FAILED", f"Cannot read the usage ledger: {e}.",
                       "Check the permissions on " + str(target))
    source = target.name if target.exists() else "none"
    paid = ctx.cfg.get("brain", {}).get("allow_paid", "false") == "true"
    models = [{"model": k, **v} for k, v in sorted(
        st["by_model"].items(), key=lambda kv: -kv[1]["usd"])]
    data = {"today_usd": round(st["today_usd"], 4),
            "month_usd": round(st["month_usd"], 4),
            "calls_today": st["calls_today"], "cap_usd": st["cap_usd"],
            "monthly_cap_usd": st["monthly_cap_usd"],
            "blocked": st["blocked"], "paid_allowed": paid,
            "models": models, "source": source}

    def cap(v):
        return "none set" if v is None else f"${v:.2f}"
    rows = [["spent today", f"${st['today_usd']:.4f} over "
             f"{st['calls_today']} calls"],
            ["daily cap", cap(st["cap_usd"])],
            ["spent this month", f"${st['month_usd']:.4f}"],
            ["monthly cap", cap(st["monthly_cap_usd"])],
            ["paid fallback",
             "BLOCKED: " + st["reason"].replace("_", " ")
             if st["blocked"] else "allowed" if paid
             else "off (local only)"],
            ["ledger", source]]
    text = ctx.table(["", ""], rows, header=False)
    if models:
        text += "\n" + ctx.table(
            ["model today", "calls", "tokens", "usd"],
            [[m["model"], str(m["calls"]), f"{m['in']}/{m['out']}",
              f"${m['usd']:.4f}"] for m in models])
    return ctx.emit(data, text)


# -- binds ----------------------------------------------------------------

@command("binds", "Show the push-to-talk hotkey and its Hyprland binds",
         ["wispd binds", "wispd binds --json"],
         {"hotkey": "dict", "hyprland": "bool", "binds": "list"})
def binds(ctx, a):
    from .. import hypr
    hk = ctx.cfg.get("hotkey", {})
    mod, key = hk.get("mod", "SUPER"), hk.get("key", "D")
    found, up = [], False
    try:
        up = hypr.available()
        if up:
            for b in hypr.query("binds"):
                blob = json.dumps(b).lower()
                if "wisp" in blob:
                    found.append({"key": b.get("key", ""),
                                  "modmask": b.get("modmask", 0),
                                  "arg": b.get("arg", ""),
                                  "submap": b.get("submap", "") or ""})
    except Exception:  # the socket is best effort here
        up = False
    data = {"hotkey": {"mod": mod, "key": key, "chord": f"{mod}+{key}"},
            "hyprland": up, "binds": found}
    rows = [["hotkey", f"{mod}+{key} (hold to talk)"],
            ["hyprland", "reachable" if up else "not reachable"]]
    rows += [["bind", f"{b['key']} {b['arg']}".strip()] for b in found]
    if up and not found:
        rows.append(["bind", "none registered: run wispd daemon install"])
    return ctx.emit(data, ctx.table(["", ""], rows, header=False))


# -- onboard --------------------------------------------------------------

def _onboard_args(p):
    p.add_argument("--status", action="store_true",
                   help="print the checklist and exit 0 (the Panel card "
                   "reads this)")
    p.add_argument("--step", metavar="ID",
                   help="run one step: mic, models, keys, cua, "
                   "notifications, keybinding")
    p.add_argument("--yes", action="store_true",
                   help="with --step notifications: send the test now")
    p.add_argument("--undo", metavar="ID", help="forget one recorded step")
    p.add_argument("--finish", action="store_true",
                   help="mark setup finished (hides the Panel card)")
    p.add_argument("--reset", action="store_true",
                   help="forget all progress")
    p.add_argument("--tour", nargs="?", const="all", metavar="STEP",
                   help="the first-minute tour: five spoken steps "
                        "(hello, draw, circle, ask, dictation); name one "
                        "step to replay just that one")
    p.add_argument("--starter", action="store_true",
                   help="four spoken questions, then three starters to "
                        "accept or skip (say skip any time to stop)")
    p.add_argument("--interactive", action="store_true",
                   help="walk the steps even without a terminal")


def _onboard_tour(ctx, a, cfg, progress):
    from .. import speech, tour
    ids = [s.id for s in tour.STEPS]
    only = "" if a.tour == "all" else a.tour
    if only and only not in ids:
        raise CliError("E_USAGE", f"Unknown tour step {only!r}. Choose "
                       f"{', '.join(ids)}.", "wispd onboard --help")
    quiet = ctx.json or ctx.flags.quiet

    def say(line):
        if not quiet:
            print(line)
        proc = speech.speak(line, cfg)
        if proc is not None:
            proc.wait()

    res = tour.run(say, tour.turns_since, progress.tour_mark,
                   log=(lambda s: None) if quiet else print, only=only,
                   done=progress.tour)
    n = sum(1 for r in res if r["status"] in ("passed", "already"))
    return ctx.emit({"steps": res, "passed": n, "total": len(res)},
                    f"tour: {n} of {len(res)} steps passed")


def _onboard_starter(ctx, a, cfg, progress):
    """B32: the spoken starter pack. Answers are the user's next voice
    turns, read back from the decision log; nothing is injected."""
    import time as _t
    from .. import agent_home, memory, routines, speech, starter_pack
    quiet = ctx.json or ctx.flags.quiet

    def say(line):
        if not quiet:
            print(line)
        proc = speech.speak(line, cfg)
        if proc is not None:
            proc.wait()

    def ask(question, wait_s=90.0):
        since = starter_pack.clock_iso()
        say(question)
        end = _t.monotonic() + wait_s
        while _t.monotonic() < end:
            _t.sleep(1.0)
            got = starter_pack.transcripts_since(since)
            if got:
                return got[0]
        return None

    def confirm(prompt):
        reply = ask(prompt + " Say yes or no.")
        return bool(reply) and reply.strip().lower().strip(".! ") in (
            "yes", "yeah", "yep", "sure", "ok", "okay", "keep it going")

    def write_profile(lines):
        for line in lines:
            memory.edit("user", "add", new=line)

    res = starter_pack.run(
        ask, confirm, say, write_profile=write_profile,
        make_helper=lambda h: agent_home.create(h["name"], h["role"]),
        make_routine=lambda r: routines.teach_routine(
            r, cfg, confirm=lambda *_a, **_k: True),
        note=lambda t: memory.edit("user", "add", new=t),
        mark=progress.starter_mark,
        log=(lambda s: None) if quiet else print)
    return ctx.emit(res, f"starter pack: {res['status']}, "
                         f"{len(res['accepted'])} accepted")


def _onboard_rows(ctx, st):
    mark = {"done": "ok", "todo": "TODO", "na": "n/a"}
    rows = [[mark[s["state"]], s["name"],
             s["detail"] if s["state"] != "todo" or not s["try"]
             else s["detail"] + ". Try: " + s["try"]]
            for s in st["steps"]]
    tones = [[{"done": "ok", "todo": "warn", "na": "muted"}[s["state"]],
              None, "muted"] for s in st["steps"]]
    return ctx.table(["", "", ""], rows, tones, header=False)


@command("onboard", "Walk through first-run setup (every step skippable)",
         ["wispd onboard", "wispd onboard --status --json",
          "wispd onboard --step notifications --yes",
          "wispd onboard --undo mic", "wispd onboard --tour"],
         {"ready": "bool", "finished": "bool", "done_count": "int",
          "total": "int", "steps": "list"},
         args=_onboard_args)
def onboard(ctx, a):
    import sys
    from .. import onboard as ob
    progress, probes = ob.Progress(), ob.Probes()
    # a fresh machine has no config.toml, and ctx.cfg would write one;
    # onboarding reads the defaults instead and writes nothing
    cfg = ctx.cfg if config.CFG_FILE.exists() \
        else config._default_cfg_dict()
    ctx._cfg = cfg   # so table() cannot load (and write) the real file
    ids = [s.id for s in ob.STEPS]
    for name in (a.step, a.undo):
        if name and name not in ids:
            raise CliError("E_USAGE", f"Unknown step {name!r}. Choose "
                           f"{', '.join(ids)}.", "wispd onboard --help")
    if a.reset:
        progress.reset()
        return ctx.emit({"reset": True}, "progress cleared")
    if a.undo:
        r = ob.undo(a.undo, progress)
        return ctx.emit(r, f"{a.undo}: " + ("undone" if r["undone"]
                                            else "nothing to undo"))
    if a.tour:
        return _onboard_tour(ctx, a, cfg, progress)
    if a.starter:
        return _onboard_starter(ctx, a, cfg, progress)
    if a.finish:
        progress.finish()
        return ctx.emit({"finished": True}, "setup marked finished")
    if a.step:
        r = ob.run_step(a.step, cfg, probes, progress, confirm=a.yes)
        if r["done"]:
            return ctx.emit(r, f"{a.step}: {r['detail']}")
        hint = r["fix"] or "wispd onboard"
        if a.step == "notifications" and not a.yes \
                and r["state"] == "todo" and r["detail"].startswith("ready"):
            hint = "wispd onboard --step notifications --yes"
        raise CliError("E_NOT_READY", f"{r['name']}: {r['detail']}.", hint,
                       data=r)
    if a.interactive or (sys.stdin.isatty() and sys.stdout.isatty()
                         and not ctx.json and not a.status):
        res = ob.walk(cfg, probes, progress, input, print)
        return ctx.emit(res, "setup finished" if res["finished"]
                        else "progress saved, run wispd onboard to resume")
    st = ob.status(cfg, probes, progress)
    text = _onboard_rows(ctx, st)
    if st["ready"] or a.status:
        return ctx.emit(st, text)
    if not ctx.json and not ctx.flags.quiet:
        print(text)
    todo = [s for s in st["steps"] if not s["optional"] and not s["ok"]]
    raise CliError("E_NOT_READY", f"{len(todo)} setup step"
                   f"{'s' if len(todo) != 1 else ''} still to do.",
                   todo[0]["try"] or "wispd onboard", data=st)


# -- captures -------------------------------------------------------------

def _captures_args(p):
    p.add_argument("turn", nargs="?", default="",
                   help="pack turn id to show (default: list packs)")
    p.add_argument("--full", action="store_true",
                   help="include transcript lines and AT-SPI state "
                        "dumps (sensitive: utterances, window text)")


def _verdict_str(v: dict) -> str:
    return " ".join(f"{k}:{n}" for k, n in sorted(v.items())) or "-"


@command("captures",
         "List capture packs, or show one pack's manifest",
         ["wispd captures", "wispd captures t-1a2b3c --full",
          "wispd captures --json"],
         {"packs": "list", "manifest": "dict|null"},
         args=_captures_args)
def captures(ctx, a):
    # read-only over IPC; the daemon never scrapes pack dirs for this —
    # packs.captures_response serves metadata, and transcript/state-dump
    # text only under --full (untrusted-data gate, KTD4)
    reply = ctx.expect_ok(ctx.send(
        {"cmd": "captures", "turn": a.turn, "full": a.full}))
    if a.turn:
        m = reply.get("manifest") or {}
        return ctx.emit({"packs": [], "manifest": m},
                        json.dumps(m, indent=2, ensure_ascii=False))
    rows = reply.get("packs") or []
    data = {"packs": rows, "manifest": None}
    if not rows:
        return ctx.emit(data, "[]")
    text = ctx.table(
        ["turn", "time", "actions", "verdicts", "frames", "suppr"],
        [[r.get("turn") or "",
          datetime.datetime.fromtimestamp(
              r.get("ts") or 0).strftime("%m-%d %H:%M"),
          str(r.get("actions") or 0),
          _verdict_str(r.get("verdicts") or {}),
          str(r.get("frames") or 0),
          "yes" if r.get("suppressed") else ""]
         for r in rows])
    return ctx.emit(data, text)


# -- whatsnew and bugreport ----------------------------------------------

def _whatsnew_args(p):
    p.add_argument("--seen", action="store_true",
                   help="mark this version's card as seen")
    p.add_argument("--all", action="store_true",
                   help="print the whole changelog instead of the card")


@command("whatsnew", "Show what changed in the version you have installed",
         ["wispd whatsnew", "wispd whatsnew --json", "wispd whatsnew --all",
          "wispd whatsnew --seen"],
         {"version": "str", "card": "dict|null", "seen": "bool"},
         args=_whatsnew_args)
def whatsnew(ctx, a):
    from .. import update, whatsnew as wn
    if a.seen:
        v = wn.mark_seen()
        return ctx.emit({"version": v, "card": None, "seen": True},
                        f"marked {v} as seen")
    if a.all:
        try:
            text = wn.changelog_path().read_text()
        except OSError:
            raise CliError("E_FAILED", "No CHANGELOG.md is installed.",
                           "wispd daemon install")
        return ctx.emit({"version": update.installed_version(),
                         "sections": wn.parse(text), "card": None,
                         "seen": False}, text.rstrip())
    c = wn.card()
    v = update.installed_version()
    if c is None:
        return ctx.emit({"version": v, "card": None, "seen": True},
                        "nothing new since you last looked")
    lines = [f"What's new in {c['title']}"
             + (f" ({c['date']})" if c["date"] else "")] \
        + [f"  - {t}" for t in c["lines"]]
    if c["more"]:
        lines.append(f"  and {c['more']} more: wispd whatsnew --all")
    lines.append(f"  {c['url']}")
    return ctx.emit({"version": v, "card": c, "seen": False},
                    "\n".join(lines))


def _bugreport_args(p):
    p.add_argument("--out", metavar="FILE",
                   help="where to write it (default: wisp-bugreport-"
                   "<date>.md in this folder)")
    p.add_argument("--errors", type=int, default=10, metavar="N",
                   help="how many recent typed errors to include "
                   "(default 10)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be written and its size; "
                   "write nothing")


@command("bugreport", "Write one markdown file for a bug report (nothing "
         "is sent)",
         ["wispd bugreport", "wispd bugreport --dry-run",
          "wispd bugreport --out ~/wisp-bug.md --errors 20"],
         {"path": "str", "bytes": "int", "sections": "list",
          "written": "bool"},
         args=_bugreport_args)
def bugreport(ctx, a):
    import pathlib
    import time
    from .. import bugreport as br, private
    if a.errors < 0 or a.errors > 200:
        raise CliError("E_USAGE", "--errors takes 0 to 200.",
                       "wispd bugreport --help")
    text = br.build(ctx.cfg, n_errors=a.errors)
    path = pathlib.Path(a.out).expanduser() if a.out else pathlib.Path(
        f"wisp-bugreport-{time.strftime('%Y%m%d-%H%M%S')}.md")
    size = len(text.encode())
    data = {"path": str(path), "bytes": size,
            "sections": list(br.SECTIONS), "written": False}
    if a.dry_run:
        return ctx.emit(data, "would write %s (%d bytes)\nsections: %s\n"
                        "dry run: nothing was written."
                        % (path, size, ", ".join(br.SECTIONS)))
    if path.exists():
        raise CliError("E_USAGE", f"{path} exists already.",
                       "wispd bugreport --out <another file>")
    try:
        with private.open_write(path) as f:
            f.write(text)
    except OSError as e:
        raise CliError("E_FAILED", f"Could not write {path}: "
                       f"{e.strerror or e}.", "wispd bugreport --out <file>")
    data["written"] = True
    return ctx.emit(data, f"wrote {path} ({size} bytes). Read it, then "
                    "open an issue yourself if you want to. Nothing was "
                    "sent.")
