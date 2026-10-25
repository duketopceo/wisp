"""Paper surface CLI: `wispd note` — show or tail the live note."""
from __future__ import annotations

import json
import sys

from .registry import CliError, command


def _note_args(p):
    p.add_argument("conv", nargs="?", default="",
                   help="conversation id (default: current / daemon)")
    p.add_argument("--raw", action="store_true",
                   help="print the verbatim note.md file")
    p.add_argument("--tail", "-f", action="store_true",
                   help="follow note_changed events from the daemon")


def _from_state(ctx, conv: str) -> dict | None:
    """Prefer the daemon's live `note` field; fall back to disk."""
    try:
        reply = ctx.send({"cmd": "status"})
    except (OSError, CliError, ConnectionError, TimeoutError):
        reply = None
    if isinstance(reply, dict) and reply.get("ok"):
        note = (reply.get("state") or {}).get("note")
        if isinstance(note, dict):
            if not conv or note.get("conv_id") == conv:
                return note
    from .. import note as note_mod
    return note_mod.current_note(conv_id=conv or None)


def _print_note(note: dict | None, *, raw: bool) -> int:
    if note is None:
        raise CliError("E_NOT_FOUND", "No note is on file yet.",
                       "wispd note --help")
    if raw:
        text = note.get("raw")
        if text is None:
            from pathlib import Path
            try:
                text = Path(note.get("path", "")).read_text(encoding="utf-8")
            except OSError:
                text = ""
        sys.stdout.write(text if text.endswith("\n") or text == ""
                         else text + "\n")
        return 0
    rendered = note.get("rendered")
    if rendered is None:
        from .. import note as note_mod
        rendered = note_mod.render_text(
            {"objects": note.get("objects") or [],
             "plan": note.get("plan") or []},
            closed=bool(note.get("closed")))
    if rendered:
        print(rendered)
    return 0


@command("note", "Show or follow the live paper (note.md)",
         ["wispd note", "wispd note --raw", "wispd note --tail",
          "wispd note agent-42"],
         {"note": "any"}, args=_note_args, stream=True)
def note_cmd(ctx, a):
    if a.tail:
        return _tail(ctx, a)
    note = _from_state(ctx, a.conv)
    if ctx.json:
        if note is None:
            raise CliError("E_NOT_FOUND", "No note is on file yet.",
                           "wispd note --help")
        return ctx.emit({"note": note})
    return _print_note(note, raw=a.raw)


def _tail(ctx, a):
    """Follow note_changed on the bus; print rendered (or raw) updates."""
    from .. import ipc
    from .. import note as note_mod
    note = _from_state(ctx, a.conv)
    if note is not None and not ctx.flags.quiet:
        if ctx.json:
            print(json.dumps(note), flush=True)
        else:
            _print_note(note, raw=a.raw)
            if not a.raw:
                print("---", flush=True)
    try:
        for ev in ipc.watch(["events"]):
            if ev.get("type") != "event" or ev.get("name") != "note_changed":
                continue
            data = ev.get("data") or {}
            if a.conv and data.get("conv_id") != a.conv:
                continue
            if ctx.json:
                print(json.dumps(data), flush=True)
                continue
            if a.raw:
                raw = data.get("raw") or ""
                sys.stdout.write(raw)
                if raw and not raw.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()
            else:
                text = data.get("rendered")
                if text is None:
                    text = note_mod.render_text(
                        {"objects": data.get("objects") or [],
                         "plan": data.get("plan") or []},
                        closed=bool(data.get("closed")))
                print(text, flush=True)
                print("---", flush=True)
    except KeyboardInterrupt:
        pass
    return 0
