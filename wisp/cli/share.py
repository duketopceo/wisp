"""Share: export a lesson, skill or helper; import one; routines."""
import json
import pathlib
import sys

from .. import share
from .registry import CliError, GROUPS, command

GROUPS["export"] = "Write a lesson, skill or helper to one shareable file"
GROUPS["routine"] = "Scheduled routines: list, pause, resume"


def _fail(e: Exception, hint: str = "wispd export --help") -> CliError:
    return CliError("E_FAILED", str(e), hint)


def _write(ctx, bundle: dict, out, notes: list, label: str) -> int:
    path = pathlib.Path(out).expanduser() if out else pathlib.Path(
        f"{bundle['name']}.wisp-{bundle['kind']}.json")
    text = json.dumps(bundle, indent=1, sort_keys=True,
                      ensure_ascii=False) + "\n"
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(text)
    except FileExistsError:
        raise CliError("E_USAGE", f"{path} exists already.",
                       f"wispd export {bundle['kind']} {bundle['name']} "
                       "--out <another file>")
    except OSError as e:
        raise CliError("E_FAILED", f"Could not write {path}: "
                       f"{e.strerror or e}.", "wispd export --help")
    lines = [f"wrote {path} ({len(text)} bytes)", f"hash: {bundle['hash']}"]
    lines += [f"note: {n}" for n in notes]
    lines.append("It holds no keys, home paths or memory. Read it before "
                 "you send it; whoever imports it sees all of this text "
                 "and must say yes.")
    return ctx.emit({"path": str(path), "hash": bundle["hash"],
                     "kind": bundle["kind"], "name": bundle["name"],
                     "notes": notes, "bytes": len(text)}, "\n".join(lines))


def _out(p):
    p.add_argument("--out", metavar="FILE",
                   help="where to write it (default: NAME.wisp-KIND.json "
                   "here; never overwrites)")


def _lesson_args(p):
    p.add_argument("name", help="the lesson's title")
    _out(p)


@command("export lesson", "Write a saved walkthrough lesson to one file",
         ["wispd export lesson \"set up a git remote\"",
          "wispd export lesson cleanup --out ~/cleanup.json"],
         {"path": "str", "hash": "str", "kind": "str", "name": "str",
          "notes": "list", "bytes": "int"}, args=_lesson_args)
def export_lesson(ctx, a):
    try:
        return _write(ctx, share.export_lesson(a.name), a.out, [], "lesson")
    except share.ShareError as e:
        raise _fail(e)


def _skill_args(p):
    p.add_argument("name", help="the skill's name")
    _out(p)


@command("export skill", "Write a skill (text only) to one file",
         ["wispd export skill git-tips"],
         {"path": "str", "hash": "str", "kind": "str", "name": "str",
          "notes": "list", "bytes": "int"}, args=_skill_args)
def export_skill(ctx, a):
    try:
        bundle, notes = share.export_skill(a.name)
        return _write(ctx, bundle, a.out, notes, "skill")
    except share.ShareError as e:
        raise _fail(e)


def _helper_args(p):
    p.add_argument("name", help="the helper's name")
    p.add_argument("--routine", action="append", default=[], metavar="ID",
                   help="include one of its scheduled routines (it "
                   "arrives paused); repeat for more")
    _out(p)


@command("export helper", "Write a helper's identity (and chosen "
         "routines) to one file",
         ["wispd export helper Scout",
          "wispd export helper Scout --routine weekly-digest"],
         {"path": "str", "hash": "str", "kind": "str", "name": "str",
          "notes": "list", "bytes": "int"}, args=_helper_args)
def export_helper(ctx, a):
    try:
        bundle, notes = share.export_helper(a.name, a.routine)
        return _write(ctx, bundle, a.out, notes, "helper")
    except share.ShareError as e:
        raise _fail(e)


def _import_args(p):
    p.add_argument("source", help="a bundle file or an https address")
    p.add_argument("--yes", action="store_true",
                   help="import without the prompt; needs --hash")
    p.add_argument("--hash", metavar="SHA256",
                   help="the hash shown for the text you read; with --yes "
                   "it must match, so you import exactly what you read")


@command("import", "Show a shared lesson, skill or helper and import it "
         "only on a yes",
         ["wispd import cleanup.wisp-lesson.json",
          "wispd import https://example.com/scout.wisp-helper.json",
          "wispd import FILE --yes --hash sha256:..."],
         {"imported": "bool", "kind": "str", "name": "str", "hash": "str",
          "text": "str", "status": "str", "stored": "str",
          "permissions": "list"}, args=_import_args)
def import_(ctx, a):
    try:
        v = share.load(a.source)
    except share.ShareError as e:
        raise CliError("E_FAILED", str(e), "wispd import --help")
    text = share.describe(v)
    base = {"kind": v["kind"], "name": v["name"], "hash": v["hash"],
            "permissions": share.permissions(v), "imported": False}
    done = share._manifest().get(v["hash"])
    if done and pathlib.Path(done.get("stored", "")).exists():
        return ctx.emit({**base, "status": "unchanged",
                         "stored": done["stored"], "text": text},
                        f"{v['kind']} {v['name']} is already imported "
                        f"({done['stored']}); nothing changed.")
    yes = False
    if a.yes:
        if a.hash != v["hash"]:
            raise CliError(
                "E_USAGE", "--yes needs --hash " + v["hash"] + ", the hash "
                "of the text you read.", "wispd import FILE")
        yes = True
    elif not ctx.json and sys.stdin and sys.stdin.isatty():
        print(text)
        sys.stderr.write("\nImport this? [y/N] ")
        sys.stderr.flush()
        yes = sys.stdin.readline().strip().lower() in ("y", "yes")
        if not yes:
            return ctx.emit({**base, "status": "declined", "text": text},
                            "nothing imported.")
    if not yes:
        msg = (text + "\n\nnothing imported. Read the text, then run: "
               f"wispd import {a.source} --yes --hash {v['hash']}")
        return ctx.emit({**base, "status": "needs_yes", "text": text}, msg)
    try:
        r = share.apply(v)
    except share.ShareError as e:
        raise CliError("E_FAILED", str(e), "wispd import --help")
    except OSError as e:
        raise CliError("E_FAILED", f"Could not write it: "
                       f"{e.strerror or e}.", "wispd doctor")
    verb = "imported" if r["status"] == "imported" else "unchanged"
    line = f"{verb} {r['kind']} {r['name']} ({r['stored']})"
    if r.get("note"):
        line += f"\n{r['note']}"
    if r.get("paused"):
        line += ("\nThe routine(s) are paused and no timer is installed. "
                 "Resume one with: wispd routine resume <id>")
    return ctx.emit({**base, "imported": r["status"] == "imported",
                     "status": r["status"], "stored": r["stored"],
                     "text": text}, line)


# -- routines -------------------------------------------------------------

def _store():
    from .. import routines
    return routines.RoutineStore()


@command("routine list", "List scheduled routines and whether they run",
         ["wispd routine list", "wispd routine list --json"],
         {"routines": "list"})
def routine_list(ctx, a):
    rows = []
    for r in _store().list():
        rows.append({"id": r.id, "name": r.name, "schedule": r.schedule,
                     "paused": bool(r.paused),
                     "state": "paused" if r.paused or not r.enabled
                     else "scheduled", "task": r.task})
    if not rows:
        return ctx.emit({"routines": []}, "no routines")
    text = ctx.table(["id", "state", "schedule", "name"],
                     [[r["id"], r["state"], r["schedule"], r["name"]]
                      for r in rows],
                     [[None, "warn" if r["paused"] else "ok", "muted", None]
                      for r in rows])
    return ctx.emit({"routines": rows}, text)


def _id_args(p):
    p.add_argument("id", help="the routine id from `wispd routine list`")


@command("routine resume", "Resume a paused routine and install its timer",
         ["wispd routine resume weekly-digest"],
         {"id": "str", "scheduled": "bool", "note": "str"}, args=_id_args)
def routine_resume(ctx, a):
    from .. import routines
    st = _store()
    r = st.resume(a.id)
    if r is None:
        raise CliError("E_NOT_FOUND", f"No routine {a.id!r}.",
                       "wispd routine list")
    units = routines.install_systemd_units(r, activate=True)
    ok = bool(units.get("scheduled", True))
    note = "" if ok else f"timer not started: {units.get('schedule_error')}"
    return ctx.emit({"id": r.id, "scheduled": ok, "note": note},
                    f"resumed {r.id} ({r.schedule})"
                    + (f"; {note}" if note else ""))


@command("routine pause", "Pause a routine",
         ["wispd routine pause weekly-digest"],
         {"id": "str"}, args=_id_args)
def routine_pause(ctx, a):
    r = _store().pause(a.id)
    if r is None:
        raise CliError("E_NOT_FOUND", f"No routine {a.id!r}.",
                       "wispd routine list")
    return ctx.emit({"id": r.id}, f"paused {r.id}")
