"""Self-authored skills — ~/.local/share/wisp/skills/*/SKILL.md.

Hermes semantics: a skill is a directory holding SKILL.md with
frontmatter (`name`, `description`, optional `tool` + `tier`) plus any
support files. `skill_manage` lets the act loop create/edit/delete
skills and write support files; `skill_view` gives progressive
disclosure — the system context carries only the index (name + one-line
description), bodies load on demand. Re-learning a topic folds into the
existing file (edit, not duplicate). `delete` backs the skill up for
BACKUP_DAYS days (`restore` / `list_backups` undo it) — deleting a
skill is reversible, not a bare rmtree.

A skill may declare `tool: <file>` — the file is executed as
`bash <file> <arg>` and registered in the toolbelt as `skill_<name>`.
`tier:` sets the risk tier (default shell — honest, since the script is
arbitrary; a skill can declare `tier: safe` only for genuinely read-only
work).
"""
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from . import config, util

SKILLS_DIR = config.DATA_DIR / "skills"
BACKUPS_DIR = SKILLS_DIR.parent / "skills-backups"
BACKUP_DAYS = 60  # Perplexity's retention: a delete is undoable for
                  # two months, then the backup ages out

# Seed retirement (Perplexity's template_version + retired_entries
# pattern). seed() is deliberately idempotent — it never overwrites a
# user's edits — which makes it append-only: a retired or rewritten
# seed stays on the user's disk forever. Two counters fix that without
# breaking the never-clobber promise:
#   SEED_VERSION is bumped in-tree whenever staged seed *content*
#   changes; skills still matching their seed's recorded version are
#   refreshed (user edits never match, so they never clobber).
#   RETIRED_SEEDS are names whose staged copies were removed or
#   renamed; seed() prunes an installed copy only when its recorded
#   provenance shows it is an unmodified seed (a user's own edits are
#   never pruned — the tombstone prunes stale copies, not user work).
SEED_VERSION = 2
RETIRED_SEEDS: frozenset[str] = frozenset()

_TEMPLATE = """\
---
name: {name}
description: {desc}
---
# {name}

{body}
"""


def _slug(name: str) -> str:
    return util.slug(name, max_len=48, default="skill")


def _backup_dir(slug: str) -> Path:
    """Backups are never in SKILLS_DIR (a backup must not be indexed as
    a skill) and are timestamped so repeated delete/restore cycles keep
    every prior state."""
    return BACKUPS_DIR / slug


def _newest_backup(b: Path) -> Path | None:
    """The newest backup snapshot under one skill's backup dir, or None.
    Snapshot names are %Y%m%d-%H%M%S stamps so name order IS time order;
    mtime ordering would be disturbed by a later copy into an old dir."""
    if not b.is_dir():
        return None
    snaps = sorted((d for d in b.iterdir() if d.is_dir()),
                   key=lambda d: d.name, reverse=True)
    for s in snaps:
        if (s / "SKILL.md").is_file():
            return s
    return None


def _backup(d: Path) -> Path | None:
    """Copy a skill dir into BACKUPS_DIR before deletion. Returns the
    snapshot dir. Failure to back up is itself a refusal — deleting
    without a backup would be irreversible, which is the bug this
    fixes."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snap = _backup_dir(d.name) / stamp
    try:
        snap.mkdir(parents=True, exist_ok=True)
        shutil.copytree(d, snap, dirs_exist_ok=True)
    except OSError:
        return None
    _prune_backups(_backup_dir(d.name))
    return snap


def _prune_backups(b: Path) -> None:
    """Drop snapshots older than BACKUP_DAYS. Best-effort: an OSError
    here only means a snapshot outlives its window."""
    cutoff = time.time() - BACKUP_DAYS * 86400
    try:
        for d in b.iterdir():
            if d.is_dir():
                try:
                    if d.stat().st_mtime < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


def _mark_edited(d: Path) -> None:
    """A manage op touched this skill — it is no longer a pure seed
    copy, so seed refresh/retire must never touch it."""
    st = _seed_state(d)
    if st:
        st["edited"] = True
        try:
            (d / ".seed-state.json").write_text(json.dumps(st))
        except OSError:
            pass


def _dir(name: str):
    return SKILLS_DIR / _slug(name)


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip():
                meta[k.strip()] = v.strip().strip('"')
    return meta


def _header(f) -> str | None:
    """Just enough of a SKILL.md for _frontmatter — no whole-body read.
    None when unreadable (same contract as the old try/except sites)."""
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            return fh.read(4096)
    except OSError:
        return None


INDEX_BUDGET = 2400  # chars — skill list stays a hint, not a wall


def write_index_json() -> Path:
    """Snapshot index() → skills.json for the shell panel's FileView."""
    out = SKILLS_DIR.parent / "skills.json"
    try:
        out.write_text(json.dumps(index()))
    except OSError:
        pass
    return out


def _binary_present(meta: dict) -> bool:
    """`requires_bin` satisfied right now — checked at advertisement
    time, not only at seed-copy time (a skill whose binary is installed
    later must appear, and one whose binary is removed must stop being
    advertised instead of failing at call time)."""
    need = meta.get("requires_bin")
    return not need or bool(shutil.which(need))


def index() -> list:
    """[{'name','description','tool'}] for every skill — the injected index."""
    out = []
    if not SKILLS_DIR.is_dir():
        return out
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        head = _header(f)
        if head is None:
            continue
        meta = _frontmatter(head)
        if not _binary_present(meta):
            continue
        out.append({"name": meta.get("name", d.name),
                    "description": meta.get("description", ""),
                    "tool": bool(meta.get("tool")),
                    "pulls_tools": _list_field(meta.get("pulls_tools")),
                    "read": _list_field(meta.get("read"))})
    return out


def index_text(transcript: str = "") -> str:
    """One-line-per-skill block for system-context injection. Executable
    (tool:) skills always list; doc skills rank by keyword overlap with
    the transcript; capped at INDEX_BUDGET chars so a big library doesn't
    drown the prompt — the skill_view tool reads full bodies on demand."""
    sks = index()
    words = {w.strip(".,!?;:'\"()[]").lower() for w in transcript.split()}
    words.discard("")
    def score(s):
        hay = (s["name"] + " " + s["description"]).lower()
        return sum(2 if w in s["name"].lower() else 1
                   for w in words if len(w) > 3 and w in hay)
    tool_skills = [s for s in sks if s["tool"]]
    doc_skills = sorted((s for s in sks if not s["tool"]),
                        key=lambda s: -score(s))
    lines, used = [], 0
    for s in tool_skills + doc_skills:
        if not s["description"]:
            continue
        line = f"- {s['name']}: {s['description']}"
        if s.get("pulls_tools"):
            # what this skill depends on, so the model knows before loading
            # it whether the tools it needs are here at all
            line += f" (needs: {', '.join(s['pulls_tools'])})"
        if s.get("read"):
            # reference-on-demand (§4e of the Clicky transfer): the
            # situation that should make the model reach for the detail,
            # named in the index so the trigger itself is visible without
            # loading anything
            line += f" (read it when: {'; '.join(s['read'])})"
        if used + len(line) > INDEX_BUDGET:
            break
        lines.append(line)
        used += len(line)
    if len(lines) < sum(1 for s in sks if s["description"]):
        lines.append(f"- … {len(sks) - len(lines)} more "
                     "(skill_view / `wispd skills` for the full list)")
    return "\n".join(lines)


def view(name: str) -> str:
    """SKILL.md body, or one reference file: `skill_view name:refs/x.md`
    reads that file inside the skill dir (no `..`, no leading `/`) —
    the reference-on-demand path the index's `read it when` points at."""
    target, _, ref = name.partition(":")
    if ref:
        if ref.startswith("/") or ".." in ref:
            return "FAIL (bad reference path)"
        f = _dir(target) / ref
        try:
            return f.read_text()
        except OSError:
            return f"FAIL (no reference {ref!r} in {target!r})"
    f = _dir(name) / "SKILL.md"
    try:
        return f.read_text()
    except OSError:
        return f"FAIL (no skill {name!r})"


def manage(op: str, name: str, body: str = "",
           description: str = "", filename: str = "") -> str:
    """skill_manage: create|edit|delete|restore|list_backups|
    write_file|remove_file|list."""
    if op == "list":
        names = [s["name"] for s in index()]
        return "OK " + (", ".join(names) if names else "(no skills)")
    if not name.strip() and op not in ("list_backups",):
        return "FAIL (skill name required)"
    d = _dir(name)
    if op == "create":
        if (d / "SKILL.md").exists():
            return f"FAIL (skill {_slug(name)!r} exists — use edit)"
        d.mkdir(parents=True, exist_ok=True)
        if not body:
            return "FAIL (create needs a SKILL.md body — no stub skills)"
        (d / "SKILL.md").write_text(_TEMPLATE.format(
            name=_slug(name), desc=description or "(undescribed)",
            body=body))
        _mark_edited(d)
        return f"OK (created {_slug(name)})"
    if op == "edit":
        f = d / "SKILL.md"
        if not f.exists():
            return f"FAIL (no skill {_slug(name)!r} — use create)"
        if not body:
            return "FAIL (edit needs the full new SKILL.md in body)"
        f.write_text(body if body.endswith("\n") else body + "\n")
        _mark_edited(d)
        return f"OK (edited {_slug(name)})"
    if op == "delete":
        if not d.exists():
            return f"FAIL (no skill {_slug(name)!r})"
        backup = _backup(d)
        if backup is None:
            # no snapshot, no delete: an irreversible rmtree is the bug
            # this backup exists to prevent
            return (f"FAIL (could not back up {_slug(name)} — "
                    "delete refused until the backup succeeds)")
        shutil.rmtree(d)
        return (f"OK (deleted {_slug(name)} — restorable for "
                f"{BACKUP_DAYS} days: skill_manage restore|{_slug(name)})")
    if op == "write_file":
        if not filename or "/" in filename or ".." in filename:
            return "FAIL (write_file needs a bare filename)"
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(body)
        _mark_edited(d)
        return f"OK (wrote {_slug(name)}/{filename})"
    if op == "remove_file":
        if not filename or "/" in filename or ".." in filename:
            return "FAIL (remove_file needs a bare filename)"
        f = d / filename
        if not f.exists():
            return f"FAIL (no file {_slug(name)}/{filename})"
        f.unlink()
        return f"OK (removed {_slug(name)}/{filename})"
    if op == "restore":
        b = _backup_dir(_slug(name))
        newest = _newest_backup(b)
        if newest is None:
            return f"FAIL (no backup of {_slug(name)})"
        if (d / "SKILL.md").exists():
            return f"FAIL (skill {_slug(name)!r} exists — delete it first)"
        shutil.copytree(newest, d)
        # a restore is the user's content back — never re-prunable by a
        # seed retire, so strip the seed marker
        try:
            (d / ".seed-state.json").unlink()
        except OSError:
            pass
        return f"OK (restored {_slug(name)} from {newest.parent.name})"
    if op == "list_backups":
        if not name.strip():
            # no name: list every skill that has a backup
            if not BACKUPS_DIR.is_dir():
                return "OK (no skill backups)"
            rows = []
            for b in sorted(BACKUPS_DIR.iterdir()):
                newest = _newest_backup(b)
                if newest is None:
                    continue
                age_days = int((time.time() - newest.stat().st_mtime) // 86400)
                rows.append(f"- {b.name}: backed up {age_days}d ago "
                            f"({len(list(newest.iterdir()))} files)")
            return "OK\n" + "\n".join(rows) if rows \
                else "OK (no skill backups)"
        b = _backup_dir(_slug(name))
        newest = _newest_backup(b)
        if newest is None:
            return f"FAIL (no backup of {_slug(name)})"
        age_days = int((time.time() - newest.stat().st_mtime) // 86400)
        return (f"OK - {_slug(name)}: backed up {age_days}d ago "
                f"({len(list(newest.iterdir()))} files); "
                f"restore with skill_manage restore|{_slug(name)}")
    return f"FAIL (op must be create|edit|delete|restore|list_backups|" \
           f"write_file|remove_file|list)"


def run_manage(arg: str) -> str:
    """Tool form: 'op|name|field|body' — field is a description for
    create, a filename for write_file/remove_file, unused otherwise."""
    parts = [p.strip() for p in arg.split("|", 3)]
    parts += [""] * (4 - len(parts))
    op, name, field, body = parts
    if op in ("write_file", "remove_file"):
        return manage(op, name, body=body, filename=field)
    return manage(op, name, body=body, description=field)


def run_view(arg: str) -> str:
    return view(arg.strip())


def _skill_meta(name: str) -> dict | None:
    """Frontmatter for a skill_<name> tool name, or None."""
    if not name.startswith("skill_"):
        return None
    # slug the suffix — the name comes from a model tool call and must
    # never resolve outside SKILLS_DIR
    f = SKILLS_DIR / _slug(name[6:]) / "SKILL.md"
    head = _header(f)
    return _frontmatter(head) if head is not None else None


def tier_of(name: str) -> str:
    """Risk tier for a skill_<name> tool — `tier:` frontmatter, shell by
    default (the script is arbitrary code). A `tool:` script can never
    self-declare `safe`: it runs bash, so its floor is `mutating` —
    anything less would bypass allow_shell and the denylist."""
    meta = _skill_meta(name) or {}
    tier = meta.get("tier", "shell")
    if tier not in ("safe", "mutating", "shell"):
        tier = "shell"
    if meta.get("tool") and tier == "safe":
        tier = "mutating"
    return tier


def run_tool(name: str, arg: str) -> str | None:
    """Execute a skill_<name>'s declared `tool:` script. None when the
    skill or its script doesn't exist."""
    meta = _skill_meta(name)
    script = (meta or {}).get("tool", "")
    if not script or "/" in script or ".." in script:
        return None
    if not _binary_present(meta or {}):
        return None
    sp = SKILLS_DIR / _slug(name[6:]) / script
    if not sp.is_file():
        return None
    bash = shutil.which("bash")
    if not bash:
        return "SKIP (no bash)"
    from . import tools as _tools
    if _tools.denied(arg):
        return "REFUSED (denylisted command)"
    try:
        r = subprocess.run([bash, sp.as_posix()] + shlex.split(arg),
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()[:2000] or \
            f"(exit {r.returncode})"
    except subprocess.TimeoutExpired:
        return "FAIL (skill script timed out)"


def _seed_dir():
    import pathlib
    return pathlib.Path(__file__).resolve().parent / "skills_seed"


def _seed_state(d: Path) -> dict:
    """A skill dir's recorded seed bookkeeping (a JSON sidecar next to
    SKILL.md): which seed it came from and at which SEED_VERSION."""
    try:
        return json.loads((d / ".seed-state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_seed_state(d: Path, seed_name: str) -> None:
    try:
        (d / ".seed-state.json").write_text(json.dumps(
            {"seed": seed_name, "version": SEED_VERSION}))
    except OSError:
        pass


def _is_prunable(d: Path, seed_name: str) -> bool:
    """True when d is an unmodified copy of a retired seed: its state
    names that seed and its SKILL.md body still matches the recorded
    version's body is NOT checkable after the seed is gone, so the
    state marker alone decides — a user-edited skill keeps the same
    marker, so retirement prunes only skills the user never touched
    per the marker plus an `edited` flag the manage ops set."""
    st = _seed_state(d)
    return st.get("seed") == seed_name and not st.get("edited")


def seed() -> None:
    """Install bundled skills (skills_seed/*/) into SKILLS_DIR. Existing
    installs are never overwritten — except a still-unmodified seed copy
    whose staged content moved to a new SEED_VERSION, which is refreshed
    (that is how a fixed guide reaches machines that already ran the
    old seed). Retired seeds prune their unmodified copies. User edits
    mark the state `edited` and are never touched by either."""
    src = _seed_dir()
    if not src.is_dir():
        return
    staged = {d.name: d for d in src.iterdir()
              if d.is_dir() and (d / "SKILL.md").is_file()}
    _seed_pass(SKILLS_DIR, staged)
    apps_src = src / "apps"
    if apps_src.is_dir():
        staged_apps = {d.name: d for d in apps_src.iterdir()
                       if d.is_dir() and (d / "SKILL.md").is_file()}
        _seed_pass(SKILLS_DIR / "apps", staged_apps)
    # prune unmodified copies of retired seeds (both roots)
    for root in (SKILLS_DIR, SKILLS_DIR / "apps"):
        if not root.is_dir():
            continue
        for name in RETIRED_SEEDS:
            d = root / name
            if d.is_dir() and _is_prunable(d, name):
                shutil.rmtree(d, ignore_errors=True)


def _seed_pass(dst_root: Path, staged: dict) -> None:
    """One seed root: install missing skills, refresh unmodified ones
    whose recorded version is behind SEED_VERSION."""
    if not dst_root.is_dir() and not staged:
        return
    dst_root.mkdir(parents=True, exist_ok=True)
    for name, sd in sorted(staged.items()):
        f = sd / "SKILL.md"
        need = _frontmatter(_header(f) or "").get("requires_bin")
        if need and not shutil.which(need):
            continue        # the program it teaches is not installed
        dst = dst_root / name
        if (dst / "SKILL.md").exists():
            st = _seed_state(dst)
            # refresh only an unmodified copy of this same seed at an
            # older version; anything else (user edit, foreign skill,
            # current version) is left alone
            if (st.get("seed") == name and not st.get("edited")
                    and st.get("version", 0) < SEED_VERSION):
                shutil.rmtree(dst, ignore_errors=True)
                try:
                    shutil.copytree(sd, dst)
                    _write_seed_state(dst, name)
                except OSError:
                    pass
            continue
        try:
            shutil.copytree(sd, dst)
            _write_seed_state(dst, name)
        except OSError:
            pass


APP_SKILL_BUDGET = 1600  # chars (~400 tokens) cap for one matched app skill


def _list_field(raw) -> list[str]:
    """Parse a frontmatter list field (`a, b` or `[a, b]`) into normalized
    lowercase items. `read:` items are phrases, not words — `|` separates
    them and spaces stay inside one item."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        s = str(raw).strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        if "|" in s:
            items = [p for p in s.split("|")]
        else:
            items = re.split(r"[,\s]+", s) if "," in s else s.split()
    out: list[str] = []
    for item in items:
        tok = item.strip().strip("'\"")
        if tok and tok not in out:
            out.append(tok if "|" in str(raw) else tok.lower())
    return out


def asks_field(raw, limit: int = 3, width: int = 60) -> list[str]:
    """A frontmatter `asks:` line (`;` separated) as up to `limit` short
    questions. Not lower-cased: they are shown to the user."""
    out: list[str] = []
    for part in str(raw or "").split(";"):
        t = " ".join(part.split()).strip(" ?.")
        if t and len(t) <= width and t + "?" not in out:
            out.append(t + "?")
    return out[:limit]


def _norm_host(url_or_host: str | None) -> str:
    """Normalize a URL or host string to a bare lowercase hostname without
    `www.` or port."""
    if not url_or_host:
        return ""
    s = str(url_or_host).strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    if ":" in s:
        s = s.split(":", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip(".")


def _strip_frontmatter(text: str) -> str:
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    return text[m.end():].strip() if m else text.strip()


def _host_score(target_host: str, candidate_host: str) -> int:
    cand = _norm_host(candidate_host)
    if not target_host or not cand:
        return 0
    if target_host == cand:
        return 3
    if target_host.endswith("." + cand):
        return 2
    return 0


def _class_score(target_cls: str, candidate_cls: str) -> int:
    cand = (candidate_cls or "").strip().lower()
    if not target_cls or not cand:
        return 0
    if target_cls == cand:
        return 3
    parts = [p for p in re.split(r"[._\-/\s]+", target_cls) if p]
    if cand in parts or target_cls.endswith("." + cand):
        return 2
    return 0


def _iter_skill_files(skills_dir: Path | str | None = None,
                      dedupe: bool = True) -> list[Path]:
    """Collect candidate SKILL.md paths. When `skills_dir` is given, scan
    `skills_dir/apps/*/SKILL.md` and `skills_dir/*/SKILL.md` only. When
    `skills_dir` is None, scan `SKILLS_DIR` plus bundled `skills_seed/apps`.
    A user copy shadows the bundled one of the same name unless `dedupe` is
    off (teaching lookup: see `teaching_guide`)."""
    roots: list[Path] = []
    if skills_dir is not None:
        base = Path(skills_dir)
        roots.extend([base / "apps", base])
    else:
        roots.extend([SKILLS_DIR / "apps", SKILLS_DIR, _seed_dir() / "apps", _seed_dir()])
    seen_names: set[str] = set()
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name == "apps":
                continue
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            key = d.name.lower()
            if dedupe and key in seen_names:
                continue
            seen_names.add(key)
            files.append(f)
    return files


def match_app_skill_info(
    window_class: str,
    url_host: str | None = None,
    skills_dir: Path | str | None = None,
    budget_chars: int = APP_SKILL_BUDGET,
) -> dict | None:
    """Match at most one app skill by `url_hosts` or `app_classes` frontmatter.
    Browser `url_host` match always takes precedence over `window_class` match.
    Returns metadata dict with truncated `body`, or None when nothing matches."""
    target_cls = (window_class or "").strip().lower()
    target_host = _norm_host(url_host)
    if not target_cls and not target_host:
        return None
    cap = APP_SKILL_BUDGET if budget_chars is None else int(budget_chars)
    if cap <= 0:
        raise ValueError(f"app skill budget must be positive, got {budget_chars!r}")

    best_host: tuple[int, str, dict] | None = None
    best_cls: tuple[int, str, dict] | None = None

    for f in _iter_skill_files(skills_dir):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _frontmatter(text)
        name = meta.get("name", f.parent.name)
        hosts = _list_field(meta.get("url_hosts") or meta.get("hosts"))
        classes = _list_field(meta.get("app_classes") or meta.get("classes"))
        body = _strip_frontmatter(text)[:cap]

        if target_host and hosts:
            hscore = max((_host_score(target_host, h) for h in hosts), default=0)
            if hscore > 0:
                entry = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "matched_by": "url_host",
                    "asks": asks_field(meta.get("asks")),
                    "pulls_tools": _list_field(meta.get("pulls_tools")),
                    "body": body,
                    "path": str(f),
                }
                if best_host is None or hscore > best_host[0]:
                    best_host = (hscore, name, entry)

        if target_cls and classes:
            cscore = max((_class_score(target_cls, c) for c in classes), default=0)
            if cscore > 0:
                entry = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "matched_by": "window_class",
                    "asks": asks_field(meta.get("asks")),
                    "pulls_tools": _list_field(meta.get("pulls_tools")),
                    "body": body,
                    "path": str(f),
                }
                if best_cls is None or cscore > best_cls[0]:
                    best_cls = (cscore, name, entry)

    if best_host is not None:
        return best_host[2]
    if best_cls is not None:
        return best_cls[2]
    return None


# -- teaching guides (teaching plan U9) ----------------------------------

# Ceiling for the guide text added to one planner prompt. 400 tokens
# (1600 chars at 4 chars per token) is the budget `APP_SKILL_BUDGET`
# already gave an app note, so a guide never grows the step prompt more
# than that note did. It is not derived from a harness run yet: every
# shipped guide's Teaching section must fit under it
# (tests/test_teaching_guides.py), so truncation is only a safety net for
# longer user-written guides, and the U1 per-app first-time-correct numbers
# are what should retune it.
CHARS_PER_TOKEN = 4
TEACH_GUIDE_TOKEN_CAP = 400
TEACH_GUIDE_CHAR_CAP = TEACH_GUIDE_TOKEN_CAP * CHARS_PER_TOKEN


def teaching_section(body: str) -> str:
    """The text under `## Teaching` (to the next `## ` heading), else ""."""
    m = re.search(r"^## Teaching[ \t]*\n(.*?)(?=^## |\Z)", body or "",
                  re.S | re.M)
    return m.group(1).strip() if m else ""


def truncate_at_section(text: str, cap: int) -> tuple[str, bool]:
    """`text` cut to at most `cap` chars at a section boundary: whole
    `### ` subsections are kept while they fit, so a guide never ends
    mid-sentence. A first section that alone exceeds the cap is cut at its
    last whole line that fits. Returns (text, was_truncated)."""
    text = (text or "").strip()
    if len(text) <= cap:
        return text, False
    blocks = [b.strip() for b in re.split(r"(?m)^(?=#{2,3} )", text)
              if b.strip()]
    kept, size = [], 0
    for b in blocks:
        add = len(b) + (2 if kept else 0)
        if size + add > cap:
            break
        kept.append(b)
        size += add
    if kept:
        return "\n\n".join(kept), True
    lines, out, size = blocks[0].splitlines(), [], 0
    for ln in lines:
        if size + len(ln) + 1 > cap:
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out).strip(), True


def teaching_guide(window_class: str, app_name: str = "",
                   skills_dir: Path | str | None = None,
                   cap_chars: int = TEACH_GUIDE_CHAR_CAP) -> dict | None:
    """The one teaching guide for the focused app, or None.

    Matches `app_classes` against the window class and the accessibility
    app name (elementtree `app_name`), best score wins. Only skills with a
    `## Teaching` section count, so an installed copy seeded before the
    section existed never hides the newer bundled one; between equals the
    user's own copy comes first. The text is that section, cut at a
    section boundary to `cap_chars`."""
    targets = [("window_class", (window_class or "").strip().lower()),
               ("app_name", (app_name or "").strip().lower())]
    targets = [(k, t) for k, t in targets if t]
    if not targets:
        return None
    best = None
    for f in _iter_skill_files(skills_dir, dedupe=False):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        section = teaching_section(_strip_frontmatter(text))
        if not section:
            continue
        meta = _frontmatter(text)
        classes = _list_field(meta.get("app_classes") or meta.get("classes"))
        score, via = 0, ""
        for kind, t in targets:
            sc = max((_class_score(t, c) for c in classes), default=0)
            if sc > score:
                score, via = sc, kind
        if score and (best is None or score > best[0]):
            best = (score, via, meta, section, f)
    if best is None:
        return None
    _, via, meta, section, f = best
    body, cut = truncate_at_section(section, int(cap_chars))
    return {"name": meta.get("name", f.parent.name), "matched_by": via,
            "body": body, "truncated": cut, "path": str(f)}


def match_app_skill(
    window_class: str,
    url_host: str | None = None,
    skills_dir: Path | str | None = None,
    budget_chars: int = APP_SKILL_BUDGET,
    max_chars: int | None = None,
    token_budget: int | None = None,
) -> str:
    """Return at most one matched app skill body within the char/token budget.
    Browser `url_host` match takes precedence over `window_class` match.
    Returns `""` when no skill matches."""
    if max_chars is not None:
        cap = int(max_chars)
    elif token_budget is not None:
        cap = int(token_budget) * 4
    else:
        cap = int(budget_chars)
    info = match_app_skill_info(
        window_class=window_class,
        url_host=url_host,
        skills_dir=skills_dir,
        budget_chars=cap,
    )
    return info["body"] if info else ""


def import_dir(src: str, preview: bool = False) -> str:
    """`wispd skills import <dir>` — copy */SKILL.md trees (e.g. a
    luke-agents _LUKE checkout) into SKILLS_DIR. Skips names that
    already exist; never symlinks (a snapshot, not a live mount)."""
    import pathlib
    base = pathlib.Path(src).expanduser()
    if not base.is_dir():
        return f"FAIL (no dir {src!r})"
    found = [d for d in sorted(base.iterdir())
             if (d / "SKILL.md").is_file()]
    if not found:
        return f"FAIL (no */SKILL.md under {src!r})"
    if preview:
        return "would import: " + ", ".join(d.name for d in found)
    imported, skipped = [], []
    for d in found:
        dst = SKILLS_DIR / _slug(d.name)
        if (dst / "SKILL.md").exists():
            skipped.append(d.name)
            continue
        try:
            shutil.copytree(d, dst)
            # provenance line at the top of the body
            f = dst / "SKILL.md"
            body = f.read_text()
            f.write_text(body.rstrip("\n") +
                         f"\n\n<!-- imported from {src} "
                         f"({d.name}) -->\n")
            imported.append(d.name)
        except OSError:
            skipped.append(d.name)
    return (f"OK (imported {len(imported)}"
            + (f": {', '.join(imported)}" if imported else "")
            + (f"; skipped existing: {', '.join(skipped)}"
               if skipped else "") + ")")


def register_tools() -> None:
    """Register `skill_<name>` toolbelt entries so they appear in
    tool_schemas()/describe(). risk_of()/run() also resolve them
    dynamically — skills authored mid-session work without restart."""
    from . import tools
    if not SKILLS_DIR.is_dir():
        return
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        head = _header(f)
        if head is None:
            continue
        meta = _frontmatter(head)
        if not meta.get("tool"):
            continue
        if not _binary_present(meta):
            continue    # its binary is gone — advertise nothing
        name = f"skill_{_slug(d.name)}"
        tier = tier_of(name)
        tools.REGISTRY[name] = (
            lambda arg, _n=name: run_tool(_n, arg) or
            f"SKIP ({_n} script missing)",
            tier, meta.get("description", f"skill {d.name}"),
            # a `tool:` script runs bash — never T1-or-lower, never
            # promised undoable (risk floor is mutating for the same
            # reason); maps through the risk→autonomy table like the
            # dynamic skill_* names policy resolves
            {"tier": tools.RISK_AUTONOMY.get(tier, "T2"),
             "reversible": False, "external": True})


