"""Dictation: personal corrections (`dictate correct`, `dictate list`)."""
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
