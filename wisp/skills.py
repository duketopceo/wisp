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
        try:
            meta = _frontmatter(f.read_text())
        except OSError:
            continue
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
    try:
        return _frontmatter(f.read_text())
    except OSError:
        return None


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
        r = subprocess.run([bash, str(sp)] + shlex.split(arg),
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
        dst = SKILLS_DIR / d.name
        if (dst / "SKILL.md").exists():
            continue
        try:
            shutil.copytree(d, dst)
        except OSError:
            pass


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
        try:
            meta = _frontmatter(f.read_text())
        except OSError:
            continue
        if not meta.get("tool"):
            continue
        name = f"skill_{_slug(d.name)}"
        tools.REGISTRY[name] = (
            lambda arg, _n=name: run_tool(_n, arg) or
            f"SKIP ({_n} script missing)",
            tier_of(name), meta.get("description", f"skill {d.name}"))
