"""The onboarding checklist and walk, drawn with the guiding light: one
lit step (the one to do next) and everything else quiet. Pure functions of
the status data, so tests render them without a terminal."""
from . import output


def _now_index(steps: list):
    """The step to do next: the first open required one, else the first
    open one, else none."""
    for want_required in (True, False):
        for i, s in enumerate(steps):
            if s["state"] == "todo" and (s["optional"] is False
                                         or not want_required):
                return i
    return None


def checklist(st: dict, *, color=False, glyphs=False, width=80) -> str:
    """`wispd onboard` without a terminal: a summary line, one row per
    step, the fix under the lit step only, and the next command."""
    steps = st["steps"]
    now = _now_index(steps)
    live = [s for s in steps if s["state"] != "na"]
    done = sum(1 for s in live if s["state"] == "done")
    cells, tones = [], []
    for i, s in enumerate(steps):
        state = "now" if i == now else s["state"]
        cells.append([output.step_marker(state, glyphs, color), s["name"],
                      s["detail"]])
        quiet = state in ("done", "na")
        tones.append([None, "muted" if quiet else None,
                      None if state == "now" else "muted"])
    tbl = output.table(["", "", ""], cells, tones, color, None, False,
                       width=min(width, 100) - 2, flex=2, glyphs=glyphs)
    out = [output.summary("wisp onboard",
                          [(None, f"{done} of {len(live)} done", "muted")],
                          min(width, 100), color, glyphs), ""]
    out += ["  " + ln for ln in tbl.splitlines()]
    if now is not None:
        s = steps[now]
        if s["try"]:
            out += [""] + output.wrap(f"next: {s['try']}", min(width, 100),
                                      "  ", "  ")
        a = f"wispd onboard --step {s['id']}"
        out += ["", f"  {a}   do this step",
                f"  {'wispd onboard':<{len(a)}}   walk through them"]
    elif st.get("finished") or st.get("ready"):
        out += ["", "  Setup is ready."]
    return "\n".join(out)


def step_header(title: str, k: int, n: int, *, color=False, glyphs=False,
                first: bool = False) -> list:
    """The lit step: `● Microphone   step 1 of 7`, then a quiet detail
    line is added by the caller."""
    dot = output.step_marker("now", glyphs, color)
    tail = f"step {k} of {n}"
    if color:
        tail = output.paint(tail, "muted")
    return ([""] if not first else []) + [
        f"{dot} {output.heading(title.capitalize() if title.islower() else title, color)}   {tail}"]


def opening(n: int, *, color=False, glyphs=False, version: str = "",
            width: int = 80) -> list:
    lines = output.banner(version, glyphs, color).splitlines()
    note = output.wrap(f"{n} steps. Press s to skip one, q to stop. Progress "
                       "is saved, and a skipped step writes nothing.",
                       min(width, 100), "", "")
    if color:
        note = [output.paint(x, "muted") for x in note]
    return lines + [""] + note


def detail_lines(text: str, width: int = 80) -> list:
    return output.wrap(text, min(width, 100), "  ", "  ")


def result_line(kind: str, text: str, *, color=False) -> str:
    """kind: done | fail | fix | undo | na. Quiet words, no marks."""
    word = {"done": "done", "fail": "not yet", "fix": "fix:",
            "undo": "undo:", "na": "n/a"}[kind]
    tone = {"done": "ok", "fail": "warn"}.get(kind, "muted")
    w = output.paint(word, tone) if color and kind in ("done", "fail") \
        else (output.paint(word, "muted") if color else word)
    return f"  {w} {text}"
