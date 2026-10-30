"""Named agents with a folder (B10): a helper you know, not a job number.

"Make me a research helper called Scout" creates
`<data>/agents/scout/` with an `AGENTS.md` identity, dated `notes/`, an
`output/` folder, a `tmp/` folder and an `inbox.md` for messages left while
it was busy. Every run of that agent starts in its folder and gets its
identity, recent notes and any inbox messages in the prompt, plus the
contract (ask once with bundled questions, a PROGRESS line at milestones,
the first sentence of the result is the spoken summary, say "drafted" for
drafts). "Tell Scout ..." and "what's running" route by name.
"""
import json
import re
from datetime import datetime, timezone

from . import config, util

PREFIX = "@agent:"          # route detail: PREFIX + json payload
NOTES_BUDGET = 2000         # chars of recent notes put in a prompt
MAX_NAME = 24

CONTRACT = (
    "How you work:\n"
    "- Your folder is the current directory. Keep files for the user in "
    "output/ and scratch in tmp/.\n"
    "- Ask the user at most once, with all your questions bundled in one "
    "message, then continue on your best judgement.\n"
    "- At each milestone print one line starting with PROGRESS: and what "
    "you just finished.\n"
    "- The first sentence of your final message is spoken aloud as the "
    "summary: make it complete on its own. If your result is a draft the "
    "user has not approved, say \"drafted\", never \"done\".\n"
    "- Before you finish, append a dated line about what you learned or "
    "did to notes/{today}.md so your next run can pick it up.")


def _root(root=None):
    return root or (config.DATA_DIR / "agents")


def _slug(name: str) -> str:
    return util.slug(name, max_len=MAX_NAME, default="agent")


def home(name: str, root=None):
    return _root(root) / _slug(name)


def exists(name: str, root=None) -> bool:
    return (home(name, root) / "AGENTS.md").is_file()


def known(root=None) -> list:
    """Display names of the agents that have a folder."""
    out = []
    try:
        for d in sorted(_root(root).iterdir()):
            f = d / "AGENTS.md"
            if f.is_file():
                m = re.search(r"^# (.+)$", f.read_text(), re.MULTILINE)
                out.append(m.group(1).strip() if m else d.name)
    except OSError:
        pass
    return out


def create(name: str, role: str = "", root=None) -> bool:
    """Make the agent's folder. False when it already exists (nothing is
    overwritten)."""
    h = home(name, root)
    ident = h / "AGENTS.md"
    if ident.exists():
        return False
    for sub in ("notes", "output", "tmp"):
        (h / sub).mkdir(parents=True, exist_ok=True)
    shown = (name or "").strip()[:MAX_NAME] or h.name
    ident.write_text(
        f"# {shown}\n\nRole: {role.strip() or 'general helper'}\n\n"
        "You are a named helper working for the user. Keep this file "
        "short; the user may edit it to change who you are.\n")
    return True


def _recent_notes(h, budget: int) -> str:
    try:
        files = sorted((h / "notes").glob("*.md"), reverse=True)
    except OSError:
        return ""
    parts, left = [], budget
    for f in files:
        try:
            text = f.read_text().strip()
        except OSError:
            continue
        if not text:
            continue
        parts.append(f"[{f.stem}]\n{text[-left:]}")
        left -= len(parts[-1])
        if left <= 0:
            break
    return "\n\n".join(reversed(parts))


def leave_message(name: str, text: str, root=None, now=None) -> None:
    """Queue a message for the agent's next run."""
    h = home(name, root)
    h.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M")
    with (h / "inbox.md").open("a") as f:
        f.write(f"- {stamp}: {text.strip()}\n")


def take_inbox(name: str, root=None) -> str:
    """The waiting messages, cleared once read."""
    f = home(name, root) / "inbox.md"
    try:
        text = f.read_text().strip()
        f.unlink()
    except OSError:
        return ""
    return text


def prompt(name: str, task: str, root=None, now=None) -> str:
    """The full prompt for one run: identity, contract, recent notes,
    waiting messages, then the task."""
    h = home(name, root)
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    try:
        ident = (h / "AGENTS.md").read_text().strip()
    except OSError:
        ident = f"# {name}"
    parts = [ident, CONTRACT.format(today=today)]
    notes = _recent_notes(h, NOTES_BUDGET)
    if notes:
        parts.append("Your notes from earlier runs:\n" + notes)
    inbox = take_inbox(name, root)
    if inbox:
        parts.append("Messages left for you while you were busy:\n" + inbox)
    parts.append("Task: " + task.strip())
    return "\n\n".join(parts)


# -- speech --------------------------------------------------------------

_CREATE = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?"
    r"(?:make|create|set\s+up|spin\s+up|start|build|get)\s+"
    r"(?:me\s+)?(?:an?\s+)?(?P<role>[\w\s-]{0,40}?)"
    r"\s*(?:helper|agent|assistant)\s+"
    r"(?:called|named)\s+(?P<name>[A-Za-z][\w-]{0,23})"
    r"(?:\s*(?:,|\.|to|that|who|and)\s*(?P<task>.+?))?[\s.!?]*$",
    re.IGNORECASE)
_TELL = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?"
    r"(?:tell|ask|message)\s+(?P<name>[A-Za-z][\w-]{0,23})\s+"
    r"(?:to\s+|that\s+|about\s+|if\s+|whether\s+)?(?P<msg>.+?)[\s.!?]*$",
    re.IGNORECASE)
_STATUS = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:what(?:'s|\s+is|\s+are)|which)\s+"
    r"(?:(?:my|the)\s+)?(?:agents?\s+(?:doing|running|up\s+to)|"
    r"running|working|in\s+the\s+background)[\s?.!]*$"
    r"|^\s*(?:agent|agents)\s+status[\s?.!]*$", re.IGNORECASE)


_CONTINUE = re.compile(
    r"^\s*(?:(?:hey\s+)?wisp[,\s]+)?(?:please\s+)?continue"
    r"(?:\s+(?:with\s+)?(?P<name>[A-Za-z][\w-]{0,23}))?[\s.!?]*$",
    re.IGNORECASE)


def parse_continue(text: str, pending=None):
    """The helper name ("" for the latest) for "continue" / "continue
    Scout" when a restart left an agent interrupted, else None. Plain
    "continue" is common speech, so it only counts then."""
    m = _CONTINUE.match(text or "")
    if not m:
        return None
    if pending is None:
        from . import agents
        pending = [r.get("agent") or r["name"] for r in agents.interrupted()]
    have = {_slug(n): n for n in pending}
    if not have:
        return None
    name = m.group("name") or ""
    return name if not name or _slug(name) in have else None


def parse_create(text: str):
    """{"name", "role", "task"} for "make me a research helper called
    Scout", else None."""
    m = _CREATE.match(text or "")
    if not m:
        return None
    return {"name": m.group("name"), "role": (m.group("role") or "").strip()
            + " helper" if (m.group("role") or "").strip() else "helper",
            "task": (m.group("task") or "").strip()}


def parse_tell(text: str, names=None):
    """(name, message) for "tell Scout to ..." when Scout is a known
    agent, else None."""
    m = _TELL.match(text or "")
    if not m:
        return None
    have = {n.lower(): n for n in (known() if names is None else names)}
    shown = have.get(m.group("name").lower())
    if not shown:
        return None
    return shown, m.group("msg").strip()


def is_status(text: str) -> bool:
    return bool(_STATUS.match(text or ""))


def encode(kind: str, **fields) -> str:
    return PREFIX + json.dumps({"kind": kind, **fields})


def decode(detail: str):
    if not (detail or "").startswith(PREFIX):
        return None
    try:
        data = json.loads(detail[len(PREFIX):])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def route_for(text: str):
    """(route, detail) when `text` is about a named agent, else None."""
    c = parse_create(text)
    if c:
        return "agent", encode("create", **c)
    t = parse_tell(text)
    if t:
        return "agent", encode("tell", name=t[0], message=t[1])
    if is_status(text):
        return "agent", encode("status")
    c = parse_continue(text)
    if c is not None:
        return "agent", encode("continue", name=c)
    return None
