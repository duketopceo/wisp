"""Self-authored skills — ~/.local/share/wisp/skills/*/SKILL.md.

Hermes semantics: a skill is a directory holding SKILL.md with
frontmatter (`name`, `description`, optional `tool` + `tier`) plus any
support files. `skill_manage` lets the act loop create/edit/delete
skills and write support files; `skill_view` gives progressive
disclosure — the system context carries only the index (name + one-line
description), bodies load on demand. Re-learning a topic folds into the
existing file (edit, not duplicate).

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
from pathlib import Path

from . import config, util

SKILLS_DIR = config.DATA_DIR / "skills"

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
        out.append({"name": meta.get("name", d.name),
                    "description": meta.get("description", ""),
                    "tool": bool(meta.get("tool"))})
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
        if used + len(line) > INDEX_BUDGET:
            break
        lines.append(line)
        used += len(line)
    if len(lines) < sum(1 for s in sks if s["description"]):
        lines.append(f"- … {len(sks) - len(lines)} more "
                     "(skill_view / `wispd skills` for the full list)")
    return "\n".join(lines)


def view(name: str) -> str:
    f = _dir(name) / "SKILL.md"
    try:
        return f.read_text()
    except OSError:
        return f"FAIL (no skill {name!r})"


def manage(op: str, name: str, body: str = "",
           description: str = "", filename: str = "") -> str:
    """skill_manage: create|edit|delete|write_file|remove_file|list."""
    if op == "list":
        names = [s["name"] for s in index()]
        return "OK " + (", ".join(names) if names else "(no skills)")
    if not name.strip():
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
        return f"OK (created {_slug(name)})"
    if op == "edit":
        f = d / "SKILL.md"
        if not f.exists():
            return f"FAIL (no skill {_slug(name)!r} — use create)"
        if not body:
            return "FAIL (edit needs the full new SKILL.md in body)"
        f.write_text(body if body.endswith("\n") else body + "\n")
        return f"OK (edited {_slug(name)})"
    if op == "delete":
        if not d.exists():
            return f"FAIL (no skill {_slug(name)!r})"
        shutil.rmtree(d)
        return f"OK (deleted {_slug(name)})"
    if op == "write_file":
        if not filename or "/" in filename or ".." in filename:
            return "FAIL (write_file needs a bare filename)"
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text(body)
        return f"OK (wrote {_slug(name)}/{filename})"
    if op == "remove_file":
        if not filename or "/" in filename or ".." in filename:
            return "FAIL (remove_file needs a bare filename)"
        f = d / filename
        if not f.exists():
            return f"FAIL (no file {_slug(name)}/{filename})"
        f.unlink()
        return f"OK (removed {_slug(name)}/{filename})"
    return f"FAIL (op must be create|edit|delete|write_file|remove_file|list)"


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


def seed() -> None:
    """Install bundled skills (skills_seed/*/) into SKILLS_DIR when the
    skill doesn't already exist — idempotent, never overwrites user
    edits. Provenance is a comment line in the SKILL.md itself."""
    src = _seed_dir()
    if not src.is_dir():
        return
    for d in sorted(src.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        need = _frontmatter(_header(f) or "").get("requires_bin")
        if need and not shutil.which(need):
            continue        # the program it teaches is not installed
        dst = SKILLS_DIR / d.name
        if (dst / "SKILL.md").exists():
            continue
        try:
            shutil.copytree(d, dst)
        except OSError:
            pass
    apps_src = src / "apps"
    if apps_src.is_dir():
        for d in sorted(apps_src.iterdir()):
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            dst = SKILLS_DIR / "apps" / d.name
            if (dst / "SKILL.md").exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(d, dst)
            except OSError:
                pass


APP_SKILL_BUDGET = 1600  # chars (~400 tokens) cap for one matched app skill


def _list_field(raw) -> list[str]:
    """Parse a frontmatter list field (`a, b` or `[a, b]`) into normalized
    lowercase items."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        s = str(raw).strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        items = re.split(r"[,\s]+", s) if "," in s else s.split()
    out: list[str] = []
    for item in items:
        tok = item.strip().strip("'\"").lower()
        if tok and tok not in out:
            out.append(tok)
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


def _iter_skill_files(skills_dir: Path | str | None = None) -> list[Path]:
    """Collect candidate SKILL.md paths. When `skills_dir` is given, scan
    `skills_dir/apps/*/SKILL.md` and `skills_dir/*/SKILL.md` only. When
    `skills_dir` is None, scan `SKILLS_DIR` plus bundled `skills_seed/apps`."""
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
            if key in seen_names:
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
    """`wispd skills import <dir>` — copy */SKILL.md trees (any local
    skill checkout the user points at) into SKILLS_DIR. Skips names that
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


def migrate_routines(routines_file: Path | None = None,
                     skills_dir: Path | None = None) -> int:
    """Lift JSON routines (routines.json) into SKILL.md skills — same
    shape as clacky's migrate_legacy. Each routine becomes a doc skill
    draft named routine-<id>; existing skill dirs are skipped; the JSON
    store is left untouched as backup. Returns count migrated."""
    src = skills_dir or SKILLS_DIR
    path = routines_file or (config.DATA_DIR / "routines.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    entries = data.get("routines", data)
    if not isinstance(entries, dict):
        return 0
    n = 0
    for rid, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        slug = f"routine-{_slug(entry.get('name') or rid)}"
        d = src / slug
        if (d / "SKILL.md").exists():
            continue
        task = (entry.get("task") or "").strip()
        if not task:
            continue
        sched = entry.get("schedule") or "daily"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            "---\n"
            f"name: {slug}\n"
            f"description: Routine '{entry.get('name') or rid}' "
            f"({sched}) — {task[:80]}\n"
            "provenance: migrated-from-routines\n"
            "draft: unverified\n"
            "---\n\n"
            f"# {entry.get('name') or rid}\n\n"
            f"Scheduled routine: **{sched}**\n\n"
            f"Task: {task}\n",
            encoding="utf-8")
        n += 1
    return n


# slug -> url_host guesses for backfilling app skills that predate the
# url_hosts/app_classes router. Conservative: only well-known domains.
_HOST_GUESSES = {
    "gmail": "mail.google.com", "outlook": "outlook.office.com",
    "github": "github.com", "gitlab": "gitlab.com",
    "notion": "notion.so", "slack": "app.slack.com",
    "discord": "discord.com", "figma": "figma.com",
    "linear": "linear.app", "perplexity": "perplexity.ai",
    "chatgpt": "chatgpt.com", "claude": "claude.ai",
    "calendar": "calendar.google.com", "docs": "docs.google.com",
    "sheets": "docs.google.com", "drive": "drive.google.com",
    "cloudflare": "dash.cloudflare.com", "vercel": "vercel.com",
    "jira": "atlassian.net", "confluence": "atlassian.net",
    "spotify": "open.spotify.com", "youtube": "youtube.com",
    "twitter": "x.com", "x": "x.com", "reddit": "reddit.com",
    "stackoverflow": "stackoverflow.com", "trello": "trello.com",
    "asana": "app.asana.com", "clickup": "app.clickup.com",
    "airtable": "airtable.com", "dropbox": "dropbox.com",
    "tallyline": "tallyline.app",
}


def backfill_routing(skills_dir: Path | str | None = None,
                     dry_run: bool = True) -> list[str]:
    """Add `url_hosts` to <name>-app skills that lack any routing key
    (url_hosts/app_classes). Guesses the host from _HOST_GUESSES keyed
    on the slug minus the -app suffix; skips unknown slugs. Never
    touches skills that already route. Returns slugs changed (or that
    would change under dry_run)."""
    src = Path(skills_dir) if skills_dir else SKILLS_DIR
    changed = []
    for d in sorted(src.iterdir()):
        if not d.is_dir() or not d.name.endswith("-app"):
            continue
        f = d / "SKILL.md"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        meta = _frontmatter(text)
        if meta.get("url_hosts") or meta.get("app_classes") \
                or meta.get("hosts") or meta.get("classes"):
            continue
        base = d.name[:-4]  # strip "-app"
        host = _HOST_GUESSES.get(base)
        if not host:
            continue
        changed.append(d.name)
        if dry_run:
            continue
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            continue
        fm = m.group(1) + f"\nurl_hosts: {host}\n"
        f.write_text(text[:m.start(1)] + fm + text[m.end(1):],
                     encoding="utf-8")
    return changed
