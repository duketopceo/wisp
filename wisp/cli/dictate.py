"""Dictation: personal corrections (`dictate correct`, `dictate list`) and
the kept-words safety net (`dictate history|retry|copy|clear`)."""
from .registry import CliError, GROUPS, command

GROUPS["dictate"] = "Dictation modes and personal corrections"


def _correct_args(p):
    p.add_argument("heard", help="what was transcribed")
    p.add_argument("meant", help="what should replace it")


@command("dictate correct",
         "Teach dictation a replacement: heard -> meant",
         ['wispd dictate correct "wisp dot ai" "wisp.ai"'],
         {"result": "str"}, args=_correct_args)
def dictate_correct(ctx, a):
    msg = {"cmd": "dictate_correct", "heard": a.heard, "meant": a.meant}
    try:
        r = ctx.send(msg)
    except CliError as e:
        if e.code != "E_DAEMON_DOWN":
            raise
        from .. import dictate
        res = dictate.add_correction(a.heard, a.meant)
        if res.startswith("SKIP"):
            raise CliError("E_USAGE", res, "wispd dictate correct --help")
        return ctx.emit({"result": res}, res)
    ctx.expect_ok(r)
    res = r.get("result") or ""
    if res.startswith("SKIP"):
        raise CliError("E_USAGE", res, "wispd dictate correct --help")
    return ctx.emit({"result": res}, res)


@command("dictate list", "Show dictation corrections and seen profiles",
         ["wispd dictate list"],
         {"corrections": "dict", "profiles_seen": "dict"})
def dictate_list(ctx, a):
    from .. import dictate
    corr = dictate.corrections()
    seen = dictate._read().get("profiles_seen", {})
    lines = ["corrections:"]
    lines += [f"  {h} -> {m}" for h, m in sorted(corr.items())] \
        or ["  (none)"]
    lines.append("apps dictated into:")
    lines += [f"  {app} x{r.get('n', 0)}" for app, r in
              sorted(seen.items())] or ["  (none)"]
    return ctx.emit({"corrections": corr, "profiles_seen": seen},
                    "\n".join(lines))


def _hist_rows(recs):
    return [f"{i}  {r.get('ts', '')[:19]}  {r.get('status', ''):<9} "
            f"{r.get('app', ''):<12} {r.get('text', '')[:70]}"
            for i, r in enumerate(recs)]


def _index_arg(p):
    p.add_argument("n", nargs="?", type=int, default=None, metavar="N",
                   help="entry number from `wispd dictate history` "
                   "(default: the newest that did not land)")


def _pick(a):
    from .. import dictate_history as h
    rec = h.get(a.n) if a.n is not None else (h.get(0, failed_only=True)
                                              or h.get(0))
    if rec is None:
        raise CliError("E_NOT_FOUND", "No kept dictation.",
                       "wispd dictate history")
    return rec


@command("dictate history",
         "List recent dictations, newest first (kept on this machine)",
         ["wispd dictate history", "wispd dictate history --limit 5"],
         {"entries": "list"},
         args=lambda p: p.add_argument("--limit", type=int, default=20,
                                       metavar="N",
                                       help="entries to show (default 20)"))
def dictate_history(ctx, a):
    from .. import dictate_history as h
    recs = h.entries(limit=max(1, a.limit))
    return ctx.emit({"entries": recs},
                    "\n".join(_hist_rows(recs)) or "(no dictations kept)")


@command("dictate retry",
         "Insert a kept dictation again at the focused cursor",
         ["wispd dictate retry", "wispd dictate retry 2 --delay 5"],
         {"result": "str"},
         args=lambda p: (_index_arg(p), p.add_argument(
             "--delay", type=float, default=3.0, metavar="SECONDS",
             help="wait this long first, to click into the target "
             "(default 3)")))
def dictate_retry(ctx, a):
    import time
    from .. import config, dictate
    rec = _pick(a)
    time.sleep(max(0.0, a.delay))
    res = dictate.retry(rec, config.load_config())
    if res.startswith(("SKIP", "REFUSED")):
        raise CliError("E_FAILED", res.split(". Your words")[0],
                       "wispd dictate history")
    return ctx.emit({"result": res}, res)


@command("dictate copy",
         "Copy a kept dictation to the clipboard",
         ["wispd dictate copy", "wispd dictate copy 1"],
         {"result": "str"}, args=_index_arg)
def dictate_copy(ctx, a):
    from .. import dictate
    rec = _pick(a)
    if not dictate.copy_to_clipboard(rec["text"]):
        raise CliError("E_FAILED", "Could not reach the clipboard "
                       "(wl-copy).", "wispd doctor")
    return ctx.emit({"result": "copied"}, "copied")


@command("dictate clear",
         "Wipe the dictation history and any interrupted-session text",
         ["wispd dictate clear"], {"removed": "int"})
def dictate_clear(ctx, a):
    from .. import dictate_history as h
    n = h.clear()
    return ctx.emit({"removed": n}, f"removed {n} kept dictations")
