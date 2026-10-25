"""Paper surface: per-conversation `note.md` with HeyClicky `::` markup.

One note file per conversation under `$XDG_STATE_HOME/wisp/notes/<conv>.md`
(or `%LOCALAPPDATA%/wisp/notes` on Windows). The agent rewrites the file in
place; each write parses the `::` grammar, fsyncs, and publishes a
`note_changed` bus event plus a `note` field on state.json for the panel.

Unknown / malformed markup degrades to letter-text segments — the parser
never raises on agent output (gap-closure U1).
"""
from __future__ import annotations

import os
import pathlib
import re
import threading
from typing import Any

# Plan markers recovered from the HeyClicky paper protocol.
PLAN_MARKERS = ("now", "pick", "needs")
# Single-colon object openers (`::tiles`, `::ticket[…]`, …).
LINE_KINDS = frozenset({"tiles", "ticket", "ask", "question"})
# Triple-colon fenced blocks.
BLOCK_KINDS = frozenset({"letter", "chart", "sketch"})
# Anything else is letter-text fallback.
KNOWN_KINDS = LINE_KINDS | BLOCK_KINDS

_PLAN_RE = re.compile(
    r"\{(?P<marker>now|pick|needs)\}(?:\s+(?P<body>[^\n{]*))?",
    re.IGNORECASE)
_OPEN_LINE_RE = re.compile(
    r"^::(?P<kind>[A-Za-z_][\w-]*)(?P<attrs>\[[^\]]*\])?\s*$")
_OPEN_BLOCK_RE = re.compile(
    r"^:::(?P<kind>[A-Za-z_][\w-]*)\s*$")
_CLOSE_BLOCK_RE = re.compile(r"^:::\s*$")
_CLOSE_LINE_RE = re.compile(r"^::\s*$")
_ATTR_RE = re.compile(r"([A-Za-z_][\w-]*)\s*=\s*([^,\]]+)")
_SAFE_CONV = re.compile(r"[^A-Za-z0-9._-]+")
# Line-start `::tiles` / `:::letter` only — not `std::vector` / `Foo::bar`.
_PAPER_HINT_RE = re.compile(r"^:{2,3}[A-Za-z_]", re.M)


def notes_dir(root: pathlib.Path | None = None) -> pathlib.Path:
    """Directory that holds conversation notes."""
    if root is not None:
        return pathlib.Path(root)
    env = os.environ.get("WISP_NOTES_DIR")
    if env:
        return pathlib.Path(env)
    base = os.environ.get("XDG_STATE_HOME")
    if not base:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") \
                or str(pathlib.Path.home() / "AppData" / "Local")
        else:
            base = str(pathlib.Path.home() / ".local" / "state")
    return pathlib.Path(base) / "wisp" / "notes"


def safe_conv_id(conv_id: str | None) -> str:
    """Filesystem-safe conversation id; empty/`None` → `current`."""
    raw = (conv_id or "").strip() or "current"
    cleaned = _SAFE_CONV.sub("-", raw).strip(".-") or "current"
    return cleaned[:120]


def note_path(conv_id: str | None = None, *,
              root: pathlib.Path | None = None) -> pathlib.Path:
    return notes_dir(root) / f"{safe_conv_id(conv_id)}.md"


def _parse_attrs(blob: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not blob:
        return out
    inner = blob.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    for m in _ATTR_RE.finditer(inner):
        out[m.group(1).lower()] = m.group(2).strip().strip("\"'")
    return out


def _obj(kind: str, body: str = "", *, attrs: dict | None = None,
         items: list | None = None) -> dict:
    o: dict[str, Any] = {"kind": kind, "body": body, "attrs": dict(attrs or {})}
    if items is not None:
        o["items"] = list(items)
    return o


def _tiles_items(body: str) -> list[str]:
    items = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("-", "*", "•")):
            s = s[1:].strip()
        items.append(s)
    return items


def parse(text: str) -> dict:
    """Parse paper markup into `{objects, plan, raw}`. Never raises."""
    raw = text if isinstance(text, str) else ""
    objects: list[dict] = []
    plan: list[dict] = []
    prose: list[str] = []

    def flush_prose() -> None:
        body = "\n".join(prose).strip()
        prose.clear()
        if body:
            objects.append(_obj("letter", body))

    def take_plan(chunk: str) -> str:
        """Pull `{now}`/`{pick}`/`{needs}` markers into `plan`; return
        the leftover text (markers stripped)."""
        parts: list[str] = []
        pos = 0
        for m in _PLAN_RE.finditer(chunk):
            parts.append(chunk[pos:m.start()])
            plan.append({
                "marker": m.group("marker").lower(),
                "text": (m.group("body") or "").strip(),
            })
            pos = m.end()
        parts.append(chunk[pos:])
        return "".join(parts)

    lines = raw.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        bm = _OPEN_BLOCK_RE.match(line)
        if bm:
            flush_prose()
            kind = bm.group("kind").lower()
            i += 1
            buf: list[str] = []
            closed = False
            while i < n:
                if _CLOSE_BLOCK_RE.match(lines[i]):
                    closed = True
                    i += 1
                    break
                buf.append(lines[i])
                i += 1
            body = take_plan("\n".join(buf)).strip()
            if kind in BLOCK_KINDS and closed:
                objects.append(_obj(kind, body))
            else:
                # unknown opener or unclosed fence → letter fallback
                fallback = body or take_plan(line).strip()
                if not closed and buf:
                    # include the unclosed opener line for visibility
                    fallback = take_plan(
                        "\n".join([line] + buf)).strip()
                if fallback:
                    objects.append(_obj("letter", fallback))
            continue

        lm = _OPEN_LINE_RE.match(line)
        if lm:
            flush_prose()
            kind = lm.group("kind").lower()
            attrs = _parse_attrs(lm.group("attrs") or "")
            i += 1
            buf = []
            while i < n:
                if _CLOSE_LINE_RE.match(lines[i]) \
                        or _OPEN_LINE_RE.match(lines[i]) \
                        or _OPEN_BLOCK_RE.match(lines[i]):
                    if _CLOSE_LINE_RE.match(lines[i]):
                        i += 1
                    break
                buf.append(lines[i])
                i += 1
            body = take_plan("\n".join(buf)).strip()
            if kind in LINE_KINDS:
                if kind == "tiles":
                    objects.append(_obj(
                        "tiles", body, attrs=attrs,
                        items=_tiles_items(body)))
                else:
                    objects.append(_obj(kind, body, attrs=attrs))
            else:
                # `::bogus` → letter text (tolerant)
                label = f"::{kind}"
                if attrs:
                    label += "[" + ",".join(
                        f"{k}={v}" for k, v in attrs.items()) + "]"
                fallback = (body or label).strip()
                if fallback:
                    objects.append(_obj("letter", fallback))
            continue

        # bare prose (may still carry plan markers)
        leftover = take_plan(line)
        prose.append(leftover)
        i += 1

    flush_prose()
    return {"objects": objects, "plan": plan, "raw": raw}


def looks_like_paper(text: str) -> bool:
    """True when `text` carries paper markup worth writing to a note.

    Colon openers must begin a line and an identifier (`::tiles`,
    `:::letter`); bare `::` inside speech (`std::vector`) is ignored.
    Plan markers stay unanchored — they appear in prose and block bodies.
    """
    if not text:
        return False
    return bool(_PAPER_HINT_RE.search(text) or _PLAN_RE.search(text))


def render_text(parsed: dict | None, *, include_plan: bool | None = None,
                closed: bool = False) -> str:
    """Human-readable rendering for CLI / panel. Plan strip is omitted
    when `closed` or `include_plan` is false."""
    if not parsed:
        return ""
    show_plan = (not closed) if include_plan is None else include_plan
    lines: list[str] = []
    if show_plan:
        for step in parsed.get("plan") or []:
            marker = step.get("marker", "now")
            body = (step.get("text") or "").strip()
            lines.append(f"[{marker}] {body}".rstrip())
        if lines and (parsed.get("objects") or []):
            lines.append("")
    for obj in parsed.get("objects") or []:
        kind = obj.get("kind") or "letter"
        body = (obj.get("body") or "").strip()
        attrs = obj.get("attrs") or {}
        if kind == "tiles":
            items = obj.get("items") or _tiles_items(body)
            if items:
                lines.extend(f"• {it}" for it in items)
            elif body:
                lines.append(body)
        elif kind == "ticket":
            tag = attrs.get("status") or attrs.get("id") or "ticket"
            lines.append(f"[{tag}] {body}".rstrip())
        elif kind in ("ask", "question"):
            lines.append(f"? {body}".rstrip())
        elif kind in ("chart", "sketch"):
            # v1: text fallback (no ClearScript clone)
            label = "chart" if kind == "chart" else "sketch"
            lines.append(f"({label}) {body}".rstrip() if body
                         else f"({label})")
        else:
            if body:
                lines.append(body)
    return "\n".join(lines).strip()


def spoken_text(parsed: dict | None) -> str:
    """Short spoken form: letter bodies, else rendered text without plan."""
    if not parsed:
        return ""
    letters = []
    for obj in parsed.get("objects") or []:
        if obj.get("kind") in ("letter", "text"):
            body = (obj.get("body") or "").strip()
            if body:
                letters.append(body)
    if letters:
        return "\n".join(letters).strip()
    return render_text(parsed, include_plan=False)


def _payload(conv_id: str, path: pathlib.Path, parsed: dict, *,
             closed: bool) -> dict:
    return {
        "conv_id": safe_conv_id(conv_id),
        "path": str(path),
        "raw": parsed.get("raw", ""),
        "objects": list(parsed.get("objects") or []),
        "plan": [] if closed else list(parsed.get("plan") or []),
        "closed": bool(closed),
        "rendered": render_text(parsed, closed=closed),
    }


class NotePad:
    """Rewrite-in-place note for one conversation.

    `set`/`patch` whole-file rewrite (HeyClicky semantics); `close`
    clears the live plan strip while keeping the file contents.
    """

    def __init__(self, conv_id: str | None = None, *, bus=None,
                 turn_id: str | None = None,
                 root: pathlib.Path | None = None):
        self.conv_id = safe_conv_id(conv_id)
        self.path = note_path(self.conv_id, root=root)
        self._bus = bus
        self._turn_id = turn_id
        self._lock = threading.Lock()
        self._closed = False
        self._parsed: dict = {"objects": [], "plan": [], "raw": ""}

    def read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def set(self, text: str) -> dict:
        """Rewrite the note file, parse, publish. Returns the payload."""
        return self._write(text if isinstance(text, str) else "",
                           closed=False)

    def patch(self, text: str) -> dict:
        """Alias of `set` — rewrite-in-place is the whole protocol."""
        return self.set(text)

    def close(self) -> dict:
        """Mark the paper closed: plan strip drops from the live view;
        file contents are left as last written."""
        with self._lock:
            raw = self._parsed.get("raw") or self.read()
            parsed = parse(raw) if raw else self._parsed
            self._parsed = parsed
            self._closed = True
            payload = _payload(self.conv_id, self.path, parsed, closed=True)
        self._publish(payload)
        return payload

    def _write(self, text: str, *, closed: bool) -> dict:
        parsed = parse(text)
        with self._lock:
            data = text if text.endswith("\n") or text == "" else text + "\n"
            # Atomic rewrite: temp + 0600 + fsync; failures propagate so
            # callers never publish a note_changed for a non-durable write.
            _atomic_write_text(self.path, data)
            self._parsed = parsed
            self._closed = closed
            payload = _payload(self.conv_id, self.path, parsed,
                               closed=closed)
        self._publish(payload)
        return payload

    def _publish(self, payload: dict) -> None:
        bus = self._bus
        if bus is None:
            return
        try:
            bus.emit_event("note_changed", **payload)
        except (OSError, TypeError, AttributeError, ValueError, KeyError):
            pass
        # Prefer turn-scoped publish so a stale turn cannot overwrite;
        # fall back to daemon-level when no turn id is bound.
        try:
            if self._turn_id is not None and hasattr(bus, "publish"):
                bus.publish(self._turn_id, note=payload)
            elif hasattr(bus, "publish"):
                bus.publish(None, note=payload)
            elif hasattr(bus, "transition"):
                # bare State (tests) — merge into snapshot
                bus.transition(getattr(bus, "status", "idle"), note=payload)
        except (OSError, TypeError, AttributeError, ValueError, KeyError):
            pass


def _atomic_write_text(path: pathlib.Path, data: str) -> None:
    """Write `data` via unique temp file, mode 0o600, fsync file + dir.

    File fsync / replace failures propagate — callers must not treat a
    failed sync as a durable success. Directory fsync is best-effort on
    platforms that cannot open a directory fd (Windows).
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1  # fdopen owns it
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    # Durability of the directory entry itself.
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        if os.name == "nt":
            return  # replace already committed the name
        raise
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _note_snap(bus=None, state=None) -> dict | None:
    """Live `state.note` payload, or None."""
    for src in (state, bus):
        if src is None:
            continue
        try:
            n = getattr(src, "note", None)
            if isinstance(n, dict) and ("conv_id" in n or "objects" in n):
                return n
            if hasattr(src, "snapshot"):
                full = src.snapshot() or {}
                n = full.get("note") if isinstance(full, dict) else None
                if isinstance(n, dict):
                    return n
        except (OSError, TypeError, AttributeError, ValueError, KeyError):
            continue
    return None


def live_conv_id(bus=None, state=None,
                 conv_id: str | None = None) -> str:
    """Conversation-stable note id for the live paper.

    Prefer an explicit id, then the open note already on the bus/state,
    else the resolvable default `current` (what bare `wispd note` reads).
    Never use a turn id — turns change every PTT press.
    """
    if conv_id:
        return safe_conv_id(conv_id)
    snap = _note_snap(bus, state)
    if isinstance(snap, dict):
        cid = snap.get("conv_id")
        if cid and not snap.get("closed"):
            return safe_conv_id(cid)
    return "current"


def current_note(*, root: pathlib.Path | None = None,
                 conv_id: str | None = None) -> dict | None:
    """Load + parse a note from disk (no bus publish)."""
    path = note_path(conv_id, root=root)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed = parse(raw)
    return _payload(safe_conv_id(conv_id), path, parsed, closed=False)


def publish_from_text(text: str, *, bus=None, turn_id: str | None = None,
                      conv_id: str | None = None,
                      root: pathlib.Path | None = None,
                      state=None) -> dict | None:
    """Write a paper when `text` carries markup; else return None.

    Callers (speak stage, agent note ops) use this to keep the file,
    `note_changed` event, and state.note field in sync. `turn_id` is
    only for bus staleness — the file key is conversation-stable.
    """
    if not looks_like_paper(text):
        return None
    cid = live_conv_id(bus, state, conv_id)
    pad = NotePad(cid, bus=bus, turn_id=turn_id, root=root)
    return pad.set(text)


def close_live(bus=None, *, turn_id: str | None = None,
               conv_id: str | None = None,
               root: pathlib.Path | None = None,
               state=None) -> dict | None:
    """Clear the live plan strip at turn end. No-op when no note."""
    snap = _note_snap(bus, state)
    if isinstance(snap, dict) and snap.get("closed"):
        # Already closed — do not republish a duplicate note_changed.
        return snap
    if not isinstance(snap, dict) and conv_id is None:
        # No live note and no explicit conv — nothing to close.
        return None
    cid = live_conv_id(bus, state, conv_id or (
        snap.get("conv_id") if isinstance(snap, dict) else None))
    pad = NotePad(cid, bus=bus or state, turn_id=turn_id, root=root)
    if not pad.path.exists() and not isinstance(snap, dict):
        return None
    if isinstance(snap, dict) and snap.get("raw") and not pad.path.exists():
        # state has the note but file vanished — republish closed view
        parsed = parse(snap.get("raw") or "")
        payload = _payload(cid, pad.path, parsed, closed=True)
        pad._parsed = parsed
        pad._closed = True
        pad._publish(payload)
        return payload
    return pad.close()
