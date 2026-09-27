"""Self-authored skills — ~/.local/share/dim-agent/skills/*/SKILL.md.

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
import re
import shlex
import shutil
import subprocess

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


def index() -> list:
    """[{'name','description'}] for every skill — the injected index."""
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
                    "description": meta.get("description", "")})
    return out


def index_text() -> str:
    """One-line-per-skill block for system-context injection."""
    return "\n".join(f"- {s['name']}: {s['description']}"
                     for s in index() if s["description"])


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
        (d / "SKILL.md").write_text(_TEMPLATE.format(
            name=_slug(name), desc=description or "(undescribed)",
            body=body or "TODO"))
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
    default (the script is arbitrary code)."""
    meta = _skill_meta(name) or {}
    tier = meta.get("tier", "shell")
    return tier if tier in ("safe", "mutating", "shell") else "shell"


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
    try:
        r = subprocess.run([bash, str(sp)] + shlex.split(arg),
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()[:2000] or \
            f"(exit {r.returncode})"
    except subprocess.TimeoutExpired:
        return "FAIL (skill script timed out)"


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
