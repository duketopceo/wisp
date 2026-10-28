"""`wispd bugreport`: one markdown file a maintainer can use.

The file holds: the version and deployed commit, endpoint health, the last
typed errors, how many trace events of each kind there were (counts, never
content), the config with every value masked, and a blank "what happened"
section. It is built only from fields that cannot carry what you said:
no transcripts, replies, window titles, file names, notes, typed text,
keys or paths. The whole text then goes through the same scrubber error
reports use (tokens, home paths, long encoded blobs).

Nothing is sent. You read the file and, if you want, open a GitHub issue
yourself.
"""
import collections
import platform as _platform
import re
import tomllib
from datetime import datetime

from . import config, deploy, errlog, report, trace

SECRET = re.compile(r"(token|secret|passw|dsn|auth|cookie|credential|"
                    r"api_?key|key_env|_key$)", re.I)
TRACE_TAIL = 2000
SECTIONS = ("version", "health", "errors", "trace", "config",
            "what happened")


def mask_config(cfg: dict) -> list:
    """[(section, key, shown)] with values masked: `default` when it is
    the shipped value, booleans and numbers as they are, anything else as
    `set` with its length, secrets always `hidden`."""
    try:
        base = tomllib.loads(config.DEFAULT_CONFIG)
    except ValueError:
        base = {}
    rows = []
    for sect in sorted(cfg):
        vals = cfg[sect]
        if not isinstance(vals, dict):
            continue
        for key in sorted(vals):
            v = vals[key]
            if isinstance(v, dict):
                rows.append((sect, key, "set (table)"))
                continue
            dv = base.get(sect, {})
            dv = dv.get(key) if isinstance(dv, dict) else None
            if SECRET.search(key):
                shown = "hidden" if str(v) != "" else "empty"
            elif dv is not None and str(dv).lower() == str(v).lower():
                shown = "default"
            elif isinstance(v, bool) or str(v).lower() in ("true", "false"):
                shown = str(v).lower()
            elif isinstance(v, (int, float)) or re.fullmatch(
                    r"-?\d+(\.\d+)?", str(v)):
                shown = str(v)
            elif str(v) == "":
                shown = "empty"
            else:
                shown = f"set ({len(str(v))} chars)"
            rows.append((sect, key, shown))
    return rows


def trace_kinds(events: list) -> list:
    def name(v):        # code-defined names only, never free text
        v = str(v)
        return v if re.fullmatch(r"[a-z0-9_]{1,32}", v) else "other"

    c = collections.Counter(f"{name(e.get('kind', '?'))}/"
                            f"{name(e.get('step', '?'))}"
                            for e in events if isinstance(e, dict))
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


def _health(cfg: dict, probe) -> list:
    try:
        snap = probe(cfg)
    except Exception as e:                       # a report must not fail
        return [("probe", False, type(e).__name__)]
    return [(n, bool(h.get("ok")), h.get("code") or
             (f"{h['latency_ms']} ms" if h.get("latency_ms") is not None
              else "")) for n, h in sorted(snap.items())]


def _probe(cfg):
    from . import health
    return health.HealthRegistry(cfg).probe_all()


def build(cfg: dict, n_errors: int = 10, probe=None, events=None,
          now=None) -> str:
    from . import update
    now = now or datetime.now()
    d = deploy.read() or {}
    ev = trace.read(tail=TRACE_TAIL) if events is None else events
    out = [f"# Wisp bug report {now:%Y-%m-%d %H:%M}", "",
           "Nothing in this file was sent anywhere. It holds no "
           "transcripts, replies, window titles, file names, typed text "
           "or keys. Read it, then open an issue yourself if you want to.",
           "", "## Version", "",
           f"- wisp: {update.installed_version()}",
           f"- deployed commit: {(d.get('commit') or 'unknown')[:12]}",
           f"- installed at: {d.get('time') or 'unknown'}",
           f"- python: {_platform.python_version()} on "
           f"{_platform.system()} {_platform.machine()}",
           "", "## Health", ""]
    rows = _health(cfg, probe or _probe)
    out += [f"- {n}: {'ok' if ok else 'DOWN'}" + (f" ({x})" if x else "")
            for n, ok, x in rows] or ["- no local endpoints configured"]
    out += ["", f"## Last {n_errors} errors", ""]
    errs = errlog.recent(n_errors)
    out += [f"- {e['ts']} {e['code']}" + (f" ({e['exc']})" if e["exc"]
                                          else "") for e in errs] \
        or ["- none recorded"]
    out += ["", "## Trace events by kind", "",
            f"Counts over the last {TRACE_TAIL} events; no content.", ""]
    kinds = trace_kinds(ev)
    out += [f"- {k}: {n}" for k, n in kinds[:40]] or ["- no trace"]
    out += ["", "## Config", "",
            "`default` is the shipped value; `set (N chars)` is a value "
            "you changed, not shown.", ""]
    out += [f"- [{s}] {k} = {v}" for s, k, v in mask_config(cfg)]
    out += ["", "## What happened", "", "<!-- what you did, what you "
            "expected, what you saw -->", "", ""]
    # scrub_text caps its input, so it runs a line at a time
    return "\n".join(report.scrub_text(ln) for ln in "\n".join(out)
                      .split("\n"))
