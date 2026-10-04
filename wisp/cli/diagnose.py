"""Diagnostics: doctor, health, latency, spend, binds, onboard."""
import datetime
import json
import shutil
import subprocess

from .. import config
from .registry import CliError, GROUPS, command

GROUPS["health"] = "Local model endpoint health"


# -- doctor ---------------------------------------------------------------

def doctor_sections(cfg: dict) -> list:
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
    row("whisper model", wm.name, wm.exists())
    row("stt provider", cfg.get("stt", {}).get("provider", "local"))
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
    from . import cua as _cua
    live = _cua.is_live()
    want = cfg.get("pointer", {}).get("backend", "auto")
    row("cua driver", "reachable" if live else "not reachable",
        live or want != "cua")

    row = section("integrations")
    row("dayflow", shutil.which("dayflow") or "not installed",
        bool(shutil.which("dayflow")))
    row("codegraph (CBM)", shutil.which("codebase-memory-mcp")
        or "not installed")
    row("hyprctl", shutil.which("hyprctl") or "not on PATH",
        bool(shutil.which("hyprctl")))
    row("sense enabled", cfg.get("sense", {}).get("enabled", "false"))

    row = section("data")
    row("skills", str(len(skills.index())) + " installed")
    for f in ("decisions.jsonl", "labels.jsonl", "activity.jsonl"):
        fp = config.DATA_DIR / f
        row(f, f"{fp.stat().st_size // 1024}KB" if fp.exists()
            else "absent")
    return sections


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

def _since_args(p):
    p.add_argument("--since", default="24h", metavar="AGE",
                   help="window: 24h, 90m, 2d (default 24h)")


@command("latency", "p50 and p90 per budget path from recent turns",
         ["wispd latency", "wispd latency --since 6h --json"],
         {"since_h": "float", "turns": "int", "rows": "list"},
         args=_since_args)
def latency(ctx, a):
    from .. import telemetry
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


# -- spend ----------------------------------------------------------------

@command("spend", "Paid model spend today and the daily cap",
         ["wispd spend", "wispd spend --json"],
         {"today_usd": "float", "calls_today": "int",
          "cap_usd": "float|null", "paid_allowed": "bool",
          "source": "str"})
def spend(ctx, a):
    # TODO(W14): read the real usage ledger and cap once it lands; until
    # then this reads DATA_DIR/usage.jsonl rows {ts, usd, model, paid}.
    ledger = config.DATA_DIR / "usage.jsonl"
    today = datetime.date.today().isoformat()
    total, calls, source = 0.0, 0, "none"
    try:
        lines = ledger.read_text().splitlines()
        source = ledger.name
    except OSError:
        lines = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and str(r.get("ts", ""))[:10] == today:
            total += float(r.get("usd") or 0)
            calls += 1
    try:
        cap = float(ctx.cfg.get("budget", {}).get("daily_usd", ""))
    except ValueError:
        cap = None
    paid = ctx.cfg.get("brain", {}).get("allow_paid", "false") == "true"
    data = {"today_usd": round(total, 4), "calls_today": calls,
            "cap_usd": cap, "paid_allowed": paid, "source": source}
    text = ctx.table(["", ""], [
        ["spent today", f"${total:.4f} over {calls} calls"],
        ["daily cap", "none set" if cap is None else f"${cap:.2f}"],
        ["paid fallback", "allowed" if paid else "off (local only)"],
        ["ledger", source]], header=False)
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
                                  "arg": b.get("arg", "")})
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

@command("onboard", "Check first-run setup and say what to do next",
         ["wispd onboard", "wispd onboard --json"],
         {"ready": "bool", "steps": "list"})
def onboard(ctx, a):
    # TODO(W28): the interactive first-run flow lives there; this is the
    # non-interactive readiness checklist it will build on.
    from .. import ipc
    cfg = ctx.cfg
    wm = config.whisper_model(cfg)
    snap = _snapshot(ctx)
    down = sorted(n for n, h in snap.items() if not h["ok"])
    steps = [
        ("config file", config.CFG_FILE.exists(), "wispd config show"),
        ("speech model", wm.exists(), "scripts/fetch_whisper.sh"),
        ("recorder (pw-record)", bool(shutil.which("pw-record")),
         "omarchy pkg add pipewire"),
        ("model endpoints", not down, "wispd health start"),
        ("daemon running", ipc.alive(), "wispd daemon install"),
    ]
    out = [{"name": n, "ok": bool(ok), "try": hint}
           for n, ok, hint in steps]
    data = {"ready": all(s["ok"] for s in out), "steps": out}
    rows = [["ok" if s["ok"] else "TODO", s["name"],
             "" if s["ok"] else "Try: " + s["try"]] for s in out]
    tones = [["ok" if s["ok"] else "warn", None, "muted"] for s in out]
    text = ctx.table(["", "", ""], rows, tones, header=False)
    if data["ready"]:
        return ctx.emit(data, text)
    if not ctx.json and not ctx.flags.quiet:
        print(text)
    n = sum(1 for s in out if not s["ok"])
    raise CliError("E_NOT_READY", f"{n} setup step"
                   f"{'s' if n != 1 else ''} still to do.",
                   next(s["try"] for s in out if not s["ok"]), data=data)
