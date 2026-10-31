"""Curated long-term memory — MEMORY.md + USER.md (Hermes pattern),
plus a decaying VOLATILE.md layer (H8).

VOLATILE.md holds recent context that should fade instead of polluting
USER.md: one bullet per line with an expiry, `- fact | until: YYYY-MM-DD`.
Expired lines are dropped on load, the file is capped by a char and line
budget (soonest-expiring lines are evicted first), and a line worth
keeping can be promoted to MEMORY.md.

Two bounded files under DATA_DIR: MEMORY.md (facts Wisp learned, ~800
token budget) and USER.md (who the user is, ~500 tokens). Both are
injected as a frozen snapshot into every brain call's system context, so
context survives across days without a service. The `memory` tool lets
the act loop curate them itself: add / replace / remove, substring
matched — one bullet per line, `# ` headers preserved.
"""
import dataclasses
import re
from datetime import date, datetime, timedelta

from . import config

MEMORY_FILE = config.DATA_DIR / "MEMORY.md"
USER_FILE = config.DATA_DIR / "USER.md"
VOLATILE_FILE = config.DATA_DIR / "VOLATILE.md"

# rough token bound (chars / 4); files stay small enough to inject whole
MEMORY_BUDGET = 800 * 4
USER_BUDGET = 500 * 4
VOLATILE_BUDGET = 400 * 4
VOLATILE_MAX_LINES = 40
VOLATILE_TTL_DAYS = 7

_MEMORY_HEAD = "# Memory\n"
_USER_HEAD = "# User\n"
_VOLATILE_HEAD = "# Volatile\n"


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
    """memory tool entry: target 'memory'|'user'|'volatile', op add|replace|remove|promote.

    add:    append `- new` bullet
    replace: rewrite the bullet containing substring `old` to `- new`
    remove: drop the bullet containing substring `old`
    write:  replace the whole body (GUI editor; `new` is the full text)
    promote: promote a volatile entry matching `old` (or `new`) to MEMORY.md
    """
    if op == "promote":
        return promote_volatile_entry(old or new)
    if target == "volatile":
        if op == "add":
            return add_volatile(new or old)
        if op == "remove":
            entries = load_volatile()
            kept = [e for e in entries if not (old and old in e.text)]
            if len(kept) == len(entries):
                return f"FAIL (no line containing {old!r})"
            _write_volatile_entries(kept)
            return "OK (volatile remove)"
        if op == "replace":
            entries = load_volatile()
            matched = False
            for e in entries:
                if old and old in e.text:
                    parsed = parse_volatile_line(new)
                    if parsed:
                        e.text, e.until = parsed.text, parsed.until
                    else:
                        e.text = new.strip().lstrip("- ").strip()
                    matched = True
            if not matched:
                return f"FAIL (no line containing {old!r})"
            _write_volatile_entries(entries)
            return "OK (volatile replace)"
        if op == "write":
            body = new or old
            n_lines = sum(1 for l in body.splitlines()
                          if l.strip() and not l.strip().startswith("#"))
            if n_lines > VOLATILE_MAX_LINES:
                return (f"FAIL (over line cap ({n_lines} lines > "
                        f"{VOLATILE_MAX_LINES}))")
            lines = _VOLATILE_HEAD.splitlines() + (
                [""] + body.splitlines() if body.strip() else []
            )
            err = _save(
                VOLATILE_FILE, "\n".join(lines).rstrip() + "\n", VOLATILE_BUDGET
            )
            return f"FAIL ({err})" if err else "OK (volatile write)"
        return f"FAIL (op must be add|replace|remove, got {op!r})"
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


_SYNC_BEGIN = "## constitution"
_SYNC_END = "## /constitution"

# Shipped defaults carry NO personal constitution — Wisp is open-source
# ready, not owner-config ready. `sync_constitution` only runs when the
# user explicitly points it at their own constitution repo
# (`wispd settings sync-constitution --repo <path>`); facts are read from
# that repo's CONSTITUTION.md (one "label: fact" bullet per line), never
# bundled.


def sync_constitution(repo: str | None = None) -> str:
    """Refresh the managed ## constitution block in MEMORY.md from an
    explicitly configured constitution repo, and dedupe the whole file.
    No repo configured = skip cleanly — personal memory sync is opt-in,
    never shipped as a default."""
    import pathlib
    if not repo:
        return "SKIP (no constitution repo configured — opt-in only)"
    base = pathlib.Path(repo).expanduser()
    if not (base / "AGENTS.md").exists():
        return f"FAIL (no constitution repo at {base})"
    facts = []
    cf = base / "CONSTITUTION.md"
    if cf.exists():
        facts = [l.strip() for l in cf.read_text().splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
    qs = base / "QUICK_START.md"
    if qs.exists():
        facts.append(
            f"full digest on demand: {base.name} QUICK_START.md")
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


def volatile_snapshot(today=None, path=None, persist: bool = True) -> str:
    """`[recent]` block of live (unexpired) VOLATILE.md lines, or "".

    Expired entries are also removed from disk (persist=True) so they do not
    linger when nothing else edits the file."""
    target = path or VOLATILE_FILE
    if not target.exists():
        return ""
    entries = load_volatile(today=today, path=target, persist=persist)
    if not entries:
        return ""
    return "[recent]\n" + "\n".join(
        format_volatile_line(e.text, e.until) for e in entries)


_UNTIL_RE = re.compile(
    r"^(?P<body1>.*?)\s*(?:\|\s*|\()?\buntil:\s*(?P<date>\d{4}-\d{2}-\d{2})\)?\s*$",
    re.IGNORECASE,
)


def _coerce_date(d: str | date | datetime | None) -> date:
    if d is None or d == "":
        return date.today()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d).strip()[:10])


@dataclasses.dataclass
class VolatileEntry:
    text: str
    until: str

    def __getitem__(self, key: str):
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


def parse_volatile_line(line: str) -> VolatileEntry | None:
    """Parse `- text | until: YYYY-MM-DD` (or `(until: YYYY-MM-DD)` /
    `until: YYYY-MM-DD`) into `VolatileEntry(text, until)`. Returns None
    when `line` is not a valid bullet with a parseable ISO date."""
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("-"):
        s = s[1:].strip()
    m = _UNTIL_RE.match(s)
    if not m:
        return None
    raw_date = m.group("date")
    try:
        date.fromisoformat(raw_date)
    except ValueError:
        return None
    body = m.group("body1").strip().rstrip("|").strip()
    if not body:
        return None
    return VolatileEntry(text=body, until=raw_date)


def format_volatile_line(text: str, until: str | date | datetime) -> str:
    """Format a volatile fact and its expiry date as `- <text> | until: YYYY-MM-DD`."""
    d_str = _coerce_date(until).isoformat()
    clean = (text or "").strip()
    if clean.startswith("-"):
        clean = clean[1:].strip()
    parsed = parse_volatile_line(clean)
    if parsed is not None:
        clean = parsed.text
    return f"- {clean} | until: {d_str}"


def _enforce_volatile_caps(
    entries: list[VolatileEntry],
    budget_chars: int = VOLATILE_BUDGET,
    max_lines: int = VOLATILE_MAX_LINES,
) -> list[VolatileEntry]:
    kept = list(entries)
    while max_lines > 0 and len(kept) > max_lines:
        # Drop the soonest-expiring (or oldest) entry first
        soonest_idx = min(range(len(kept)), key=lambda i: kept[i].until)
        kept.pop(soonest_idx)
    while kept:
        rendered = (
            _VOLATILE_HEAD
            + "\n".join(format_volatile_line(e.text, e.until) for e in kept)
            + "\n"
        )
        if len(rendered) <= budget_chars:
            break
        soonest_idx = min(range(len(kept)), key=lambda i: kept[i].until)
        kept.pop(soonest_idx)
    return kept


def _write_volatile_entries(
    entries: list[VolatileEntry],
    path=None,
    budget_chars: int = VOLATILE_BUDGET,
    max_lines: int = VOLATILE_MAX_LINES,
) -> list[VolatileEntry]:
    target_path = path or VOLATILE_FILE
    kept = _enforce_volatile_caps(
        entries, budget_chars=budget_chars, max_lines=max_lines
    )
    body = "\n".join(format_volatile_line(e.text, e.until) for e in kept)
    content = _VOLATILE_HEAD + (body + "\n" if body else "")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content)
    return kept


def load_volatile(
    today: str | date | datetime | None = None,
    *,
    path=None,
    budget_chars: int = VOLATILE_BUDGET,
    max_lines: int = VOLATILE_MAX_LINES,
    persist: bool = True,
) -> list[VolatileEntry]:
    """Load VOLATILE.md, drop entries whose `until < today`, enforce line and
    character budget caps, and optionally persist the compacted file."""
    target_path = path or VOLATILE_FILE
    cur_str = _coerce_date(today).isoformat()
    raw = _load(target_path, _VOLATILE_HEAD)
    entries: list[VolatileEntry] = []
    dropped_or_trimmed = False
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        parsed = parse_volatile_line(line)
        if parsed is None:
            dropped_or_trimmed = True
            continue
        if parsed.until < cur_str:
            dropped_or_trimmed = True
            continue
        entries.append(parsed)
    capped = _enforce_volatile_caps(
        entries, budget_chars=budget_chars, max_lines=max_lines
    )
    if len(capped) != len(entries):
        dropped_or_trimmed = True
    if persist and target_path.exists() and dropped_or_trimmed:
        _write_volatile_entries(
            capped,
            path=target_path,
            budget_chars=budget_chars,
            max_lines=max_lines,
        )
    return capped


def add_volatile(
    text: str,
    until: str | date | datetime | None = None,
    *,
    today: str | date | datetime | None = None,
    ttl_days: int = VOLATILE_TTL_DAYS,
    path=None,
    budget_chars: int = VOLATILE_BUDGET,
    max_lines: int = VOLATILE_MAX_LINES,
) -> str:
    """Add or refresh a volatile entry with `until: YYYY-MM-DD`, enforcing
    expiry compaction and char/line budgets."""
    target_path = path or VOLATILE_FILE
    cur = _coerce_date(today)
    # A fact is one file line: fold any embedded newlines/tabs into spaces.
    text = " ".join((text or "").split())
    parsed = parse_volatile_line(text)
    if parsed is not None:
        fact = parsed.text
        until_str = (
            _coerce_date(until).isoformat() if until is not None else parsed.until
        )
    else:
        fact = (text or "").strip().lstrip("- ").strip()
        if not fact:
            return "FAIL (add_volatile needs text)"
        if until is not None:
            until_str = _coerce_date(until).isoformat()
        else:
            until_str = (cur + timedelta(days=int(ttl_days))).isoformat()

    if len(format_volatile_line(fact, until_str)) + len(_VOLATILE_HEAD) > budget_chars:
        return f"FAIL (over budget ({len(fact)} chars > {budget_chars}))"

    entries = load_volatile(
        today=cur,
        path=target_path,
        budget_chars=budget_chars,
        max_lines=max_lines,
        persist=False,
    )
    # Reject a past expiry before touching any existing entry.
    if until_str < cur.isoformat():
        return f"FAIL (expiry {until_str} is in the past)"
    # Deduplicate existing entry with same text (case-insensitive)
    entries = [e for e in entries if e.text.lower() != fact.lower()]
    new_entry = VolatileEntry(text=fact, until=until_str)
    entries.append(new_entry)
    capped = _enforce_volatile_caps(
        entries, budget_chars=budget_chars, max_lines=max_lines)
    if not any(e is new_entry for e in capped):
        return "FAIL (volatile caps would evict this fact; nothing saved)"
    _write_volatile_entries(
        entries,
        path=target_path,
        budget_chars=budget_chars,
        max_lines=max_lines,
    )
    return "OK (volatile add)"


def promote_volatile_entry(
    query: str,
    *,
    today: str | date | datetime | None = None,
    volatile_path=None,
) -> str:
    """Promote a volatile entry matching `query` (substring, case-insensitive)
    into `MEMORY.md` without its `until:` tag, and remove it from `VOLATILE.md`."""
    target_path = volatile_path or VOLATILE_FILE
    q = (query or "").strip()
    if not q:
        return "FAIL (promote needs a query)"
    entries = load_volatile(today=today, path=target_path, persist=False)
    matched = [e for e in entries if q.lower() in e.text.lower()]
    if not matched:
        return f"FAIL (no volatile line containing {q!r})"
    chosen = matched[0]
    # Exact-equivalent check only: a substring match in an unrelated memory
    # bullet must not cause the volatile fact to be dropped unpromoted.
    mem_lines = _load(MEMORY_FILE, _MEMORY_HEAD).splitlines()
    want = chosen.text.strip().lstrip("- ").strip().lower()
    known = any(l.strip().startswith("-")
                and l.strip().lstrip("- ").strip().lower() == want
                for l in mem_lines)
    if not known:
        mem_lines.append(f"- {chosen.text.strip().lstrip('- ').strip()}")
        err = _save(MEMORY_FILE, "\n".join(mem_lines).rstrip() + "\n",
                    MEMORY_BUDGET)
        if err:
            return f"FAIL ({err})"
    remaining = [e for e in entries if e is not chosen]
    _write_volatile_entries(remaining, path=target_path)
    return f"OK (promoted to memory: {chosen.text})"


def context_block(transcript: str = "") -> str:
    """One assembled context block — memory snapshot + skills index +
    recall top-k — shared by the Jev-state path and chat path so the two
    injection formats can't drift."""
    from . import recall, skills
    parts = []
    snap = snapshot()
    if snap:
        parts.append(snap)
    try:
        vol = volatile_snapshot()
    except (OSError, ValueError):
        vol = ""
    if vol:
        parts.append(vol)
    sidx = skills.index_text(transcript)
    if sidx:
        parts.append(f"[skills]\n{sidx}")
    if transcript:
        rec = recall.context_for(transcript)
        if rec:
            parts.append(f"[recall]\n{rec}")
    return "\n\n".join(parts)
