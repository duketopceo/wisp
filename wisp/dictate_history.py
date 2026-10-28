"""Dictation safety net (B24): your dictated words are never lost.

Every finished dictation is appended to a local history, whether it landed
or not. A failed insert keeps the text so `wispd dictate retry` can try
again and `wispd dictate copy` can put it on the clipboard. A long
recording writes each transcribed chunk to a session journal as it goes, so
a crash or kill keeps what was said; the next start moves it into the
history.

The history lives in `~/.local/share/wisp/dictation-history.jsonl` (mode
0600), is bounded by `[dictation] history_max` entries and `history_days`
days, can be turned off with `[dictation] history = "false"`, and is wiped
by `wispd dictate clear`. It never leaves the machine and never enters a
prompt: nothing but the `dictate` commands reads it.
"""
import json
import os
import pathlib
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config

FILE = config.DATA_DIR / "dictation-history.jsonl"
JOURNAL = config.DATA_DIR / "dictation-session.jsonl"
DEFAULT_MAX = 100
DEFAULT_DAYS = 7
_LOCK = threading.Lock()


def settings(cfg) -> dict:
    d = (cfg or {}).get("dictation", {}) or {}

    def num(key, default, hi):
        try:
            return max(1, min(int(d.get(key, default)), hi))
        except (TypeError, ValueError):
            return default
    return {"enabled": str(d.get("history", "true")).lower() != "false",
            "max": num("history_max", DEFAULT_MAX, 10000),
            "days": num("history_days", DEFAULT_DAYS, 3650)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path=None) -> list:
    out = []
    try:
        lines = (path or FILE).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("text"):
            out.append(rec)
    return out


def _write(recs: list, path=None) -> None:
    """Rewrite the file atomically with mode 0600."""
    p = pathlib.Path(path or FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _keep(recs: list, s: dict, now=None) -> list:
    """Apply the age and count bounds (newest entries win)."""
    cutoff = (now or _now()) - timedelta(days=s["days"])
    fresh = []
    for r in recs:
        try:
            at = datetime.fromisoformat(r.get("ts", ""))
        except ValueError:
            continue
        if at >= cutoff:
            fresh.append(r)
    return fresh[-s["max"]:]


def add(text: str, status: str, cfg=None, app: str = "", via: str = "",
        raw: str = "", note: str = "", path=None) -> dict | None:
    """Append one dictation. status: inserted | failed | ignored |
    recovered. Returns the record, or None when history is off."""
    s = settings(cfg)
    text = (text or "").strip()
    if not s["enabled"] or not text:
        return None
    rec = {"ts": _now().isoformat(), "status": status, "text": text}
    for k, v in (("app", app), ("via", via), ("raw", raw if raw != text
                                                else ""), ("note", note)):
        if v:
            rec[k] = v
    try:
        with _LOCK:
            recs = _keep(_read(path) + [rec], s)
            _write(recs, path)
    except OSError:
        return None
    return rec


def entries(limit: int = 0, path=None) -> list:
    """Newest first."""
    recs = list(reversed(_read(path)))
    return recs[:limit] if limit else recs


def get(index: int = 0, failed_only: bool = False, path=None):
    """The `index`-th newest entry (0 = newest); with `failed_only` the
    newest of those that did not land."""
    recs = entries(path=path)
    if failed_only:
        recs = [r for r in recs if r.get("status") in ("failed",
                                                       "recovered")]
    return recs[index] if 0 <= index < len(recs) else None


def mark(ts: str, status: str, path=None) -> None:
    with _LOCK:
        recs = _read(path)
        for r in recs:
            if r.get("ts") == ts:
                r["status"] = status
        _write(recs, path)


def clear(path=None, journal=None) -> int:
    """Wipe the history and any session journal; the number of entries
    removed."""
    n = len(_read(path))
    for p in (path or FILE, journal or JOURNAL):
        try:
            pathlib.Path(p).unlink()
        except OSError:
            pass
    return n


# -- session journal ---------------------------------------------------

class Journal:
    """The transcribed chunks of one long recording, written as they
    arrive so an interruption keeps what was said."""

    def __init__(self, cfg=None, path=None, history=None):
        self.path = pathlib.Path(path or JOURNAL)
        self.history = history
        self.on = settings(cfg)["enabled"]
        self.cfg = cfg

    def start(self) -> None:
        if self.on:
            recover(self.cfg, self.path, self.history)

    def add(self, text: str) -> None:
        if not self.on or not (text or "").strip():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                         0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps({"ts": _now().isoformat(),
                                    "text": text.strip()}) + "\n")
        except OSError:
            pass

    def done(self) -> None:
        """The recording finished normally: its text is in the turn."""
        try:
            self.path.unlink()
        except OSError:
            pass


def recover(cfg=None, journal=None, history=None) -> str:
    """Move a journal left by a killed recording into the history. The
    text that was said, "" when there was none."""
    p = pathlib.Path(journal or JOURNAL)
    try:
        lines = p.read_text().splitlines()
    except OSError:
        return ""
    parts = []
    for line in lines:
        try:
            parts.append(json.loads(line).get("text", ""))
        except ValueError:
            pass
    try:
        p.unlink()
    except OSError:
        pass
    text = " ".join(t for t in parts if t).strip()
    if text:
        add(text, "recovered", cfg, note="the recording was interrupted",
            path=history)
    return text


# -- faithful cleanup ---------------------------------------------------

_FILLER = {"um", "uh", "umm", "uhh", "hmm", "mm", "mmm", "er", "erm",
           "ah", "eh", "huh", "hm"}
# what a speech model writes for silence or a tap with no speech
_SILENCE = {"you", "thank you", "thanks for watching",
            "thank you for watching", "bye", "bye bye",
            "subtitles by the amara.org community"}
_WORD = re.compile(r"[\w']+", re.UNICODE)


def words(text: str) -> list:
    return [w.lower() for w in _WORD.findall(text or "")]


def is_silence(text: str) -> bool:
    """True for a transcript with nothing said: empty, punctuation,
    filler sounds only, or the stock phrase a speech model invents for
    near-silence. Cleanup and compose never run on it."""
    ws = words(text)
    if not ws or all(w in _FILLER for w in ws):
        return True
    return " ".join(ws) in _SILENCE


def faithful(spoken: str, written: str, extra=()) -> bool:
    """Cleanup never adds words that were not spoken. `written` may drop
    words and change case or punctuation; it may bring in only a few new
    ones (a spelling fix), not a sentence. `extra` are allowed words (the
    right-hand side of personal corrections)."""
    said = set(words(spoken)) | {w for e in extra for w in words(e)}
    new = [w for w in words(written) if w not in said]
    return len(new) <= max(2, len(words(spoken)) // 4)
