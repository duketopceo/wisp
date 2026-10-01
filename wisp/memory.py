"""Curated long-term memory — MEMORY.md + USER.md (Hermes pattern).

Two bounded files under DATA_DIR: MEMORY.md (facts Wisp learned, ~800
token budget) and USER.md (who the user is, ~500 tokens). Both are
injected as a frozen snapshot into every brain call's system context, so
context survives across days without a service. The `memory` tool lets
the act loop curate them itself: add / replace / remove, substring
matched — one bullet per line, `# ` headers preserved.
"""
from . import config

MEMORY_FILE = config.DATA_DIR / "MEMORY.md"
USER_FILE = config.DATA_DIR / "USER.md"

# rough token bound (chars / 4); files stay small enough to inject whole
MEMORY_BUDGET = 800 * 4
USER_BUDGET = 500 * 4

_MEMORY_HEAD = "# Memory\n"
_USER_HEAD = "# User\n"


def _load(path, head: str) -> str:
    try:
        return path.read_text()
    except OSError:
        return head


def _save(path, text: str, budget: int) -> str | None:
    if len(text) > budget:
        return f"over budget ({len(text)} chars > {budget}) — remove or shorten lines"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return None


def edit(target: str, op: str, old: str = "", new: str = "") -> str:
    """memory tool entry: target 'memory'|'user', op add|replace|remove.

    add:    append `- new` bullet
    replace: rewrite the bullet containing substring `old` to `- new`
    remove: drop the bullet containing substring `old`
    write:  replace the whole body (GUI editor; `new` is the full text)
    """
    if target not in ("memory", "user"):
        return f"FAIL (target must be 'memory' or 'user', got {target!r})"
    path = MEMORY_FILE if target == "memory" else USER_FILE
    head = _MEMORY_HEAD if target == "memory" else _USER_HEAD
    budget = MEMORY_BUDGET if target == "memory" else USER_BUDGET
    text = _load(path, head)
    lines = text.splitlines()
    if op == "write":
        body = new or old
        lines = head.splitlines() + ([""] + body.splitlines()
                                    if body.strip() else [])
        err = _save(path, "\n".join(lines).rstrip() + "\n", budget)
        return f"FAIL ({err})" if err else f"OK ({target} write)"
    if op == "add":
        new = new or old  # tool form 'memory|add|fact' lands in old
        if not new:
            return "FAIL (add needs new=)"
        core = new.lstrip("- ").strip().lower()
        if any(l.strip().startswith("-") and core
               and core in l.lower() for l in lines):
            return f"OK ({target} add — already known)"
        bullet = new if new.lstrip().startswith("-") else f"- {new}"
        lines.append(bullet)
    elif op in ("replace", "remove"):
        idx = [i for i, l in enumerate(lines)
               if l.strip().startswith("-") and old and old in l]
        if not idx:
            return f"FAIL (no line containing {old!r})"
        if op == "replace":
            for i in idx:
                lines[i] = new if new.lstrip().startswith("-") else f"- {new}"
        else:
            lines = [l for i, l in enumerate(lines) if i not in idx]
    else:
        return f"FAIL (op must be add|replace|remove, got {op!r})"
    err = _save(path, "\n".join(lines).rstrip() + "\n", budget)
    return f"FAIL ({err})" if err else f"OK ({target} {op})"


_SYNC_BEGIN = "## luke-agents"
_SYNC_END = "## /luke-agents"

_CONSTITUTION_FACTS = [
    "user is Luke Kimball (Khan) — github duketopceo, machine <host> (M1 Max, Asahi Linux ARM, Hyprland)",
    "luke-agents repo (~/Documents/github/personal/luke-agents) is the canonical agent constitution — AGENTS.md is the king file, QUICK_START.md is the fast digest",
    "voice: precise, concise, no fluff; tables over paragraphs; no emojis; disagree with weak ideas",
    "never use the words scrape/scraping/crawl — say collect/extract/fetch",
    "never use Reddit as a source",
    "eval/model spend bills the orchestral OpenRouter key, never default",
    "hyprland config is Lua; machine-specific files are stash-canonical under ~/.local/share/machine/<user>/ — sync-watch reverts ~/.config/hypr/",
    "never edit /usr/share/omarchy — package-owned; user config under ~/.config/",
    "package installs: omarchy pkg add or yay, never raw makepkg",
    "personal knowledge brain: Kurultai personal lane (Ulaanbaatar); agent identity = codename@instance_id",
]


def sync_constitution(repo: str | None = None) -> str:
    """Refresh the managed ## luke-agents block in MEMORY.md from the
    constitution repo, and dedupe the whole file. Idempotent — safe on
    every daemon start."""
    import pathlib
    base = pathlib.Path(repo).expanduser() if repo else \
        pathlib.Path.home() / "Documents/github/personal/luke-agents"
    if not (base / "AGENTS.md").exists():
        return f"FAIL (no luke-agents repo at {base})"
    facts = list(_CONSTITUTION_FACTS)
    qs = base / "QUICK_START.md"
    if qs.exists():
        facts.append(
            "full digest on demand: luke-agents QUICK_START.md "
            "(or the `luke-agents` skill index)")
    body_lines = ([f"- {f}" for f in facts])
    block = [_SYNC_BEGIN, *body_lines, _SYNC_END]

    lines = _load(MEMORY_FILE, _MEMORY_HEAD).splitlines()
    # drop existing managed block
    out, skip = [], False
    for l in lines:
        if l.strip() == _SYNC_BEGIN:
            skip = True
        if not skip:
            out.append(l)
        if l.strip() == _SYNC_END:
            skip = False
    # dedupe bullets (keep first occurrence, case-insensitive)
    seen, deduped = set(), []
    for l in out:
        key = l.strip().lstrip("- ").strip().lower()
        if l.strip().startswith("-") and key in seen:
            continue
        if l.strip().startswith("-"):
            seen.add(key)
        deduped.append(l)
    out = deduped + [""] + block
    err = _save(MEMORY_FILE, "\n".join(out).rstrip() + "\n",
                MEMORY_BUDGET)
    if err:
        return f"FAIL ({err})"
    return f"OK (constitution synced — {len(facts)} facts, deduped)"


def run(arg: str) -> str:
    """Tool form: 'target|op|old|new' — act loop passes one string."""
    parts = [p.strip() for p in arg.split("|", 3)]
    parts += [""] * (4 - len(parts))
    return edit(parts[0], parts[1], parts[2], parts[3])


def snapshot() -> str:
    """Frozen context block injected into every brain call. Empty when
    neither file has content beyond its header."""
    parts = []
    for path, label in ((MEMORY_FILE, "memory"), (USER_FILE, "user")):
        text = _load(path, "")
        body = [l for l in text.splitlines()
                if l.strip() and not l.startswith("# ")]
        if body:
            parts.append(f"[{label}]\n" + "\n".join(body))
    return "\n\n".join(parts)


def context_block(transcript: str = "") -> str:
    """One assembled context block — memory snapshot + skills index +
    recall top-k — shared by the Jev-state path and chat path so the two
    injection formats can't drift."""
    from . import recall, skills
    parts = []
    snap = snapshot()
    if snap:
        parts.append(snap)
    sidx = skills.index_text(transcript)
    if sidx:
        parts.append(f"[skills]\n{sidx}")
    if transcript:
        rec = recall.context_for(transcript)
        if rec:
            parts.append(f"[recall]\n{rec}")
    return "\n\n".join(parts)
