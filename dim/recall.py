"""Deep recall — sqlite FTS5 store at recall.db (Hermes deep-recall shape).

Every completed turn, correction, and curated note is indexed here for
day-to-day context that outlives the session tail. Lexical FTS5 search
means recall works with zero API keys; a vector/embedding backend can be
layered on later without changing the tool surface (plan: sqlite-vec).
Single daemon writer; searches are read-only.
"""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

DB_FILE = config.DATA_DIR / "recall.db"
_KEEP = 5000  # retention cap — recall is recent-context, not an archive

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes
USING fts5(kind, body, ts, tokenize='porter');
"""


def _db(path=None) -> sqlite3.Connection:
    path = path or DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.executescript(_SCHEMA)
    return db


def add(kind: str, body: str, path=None) -> None:
    if not body.strip():
        return
    try:
        db = _db(path)
        try:
            db.execute(
                "INSERT INTO notes (kind, body, ts) VALUES (?, ?, ?)",
                (kind, body[:4000],
                 datetime.now(timezone.utc).isoformat()))
            db.execute(  # bounded store — drop oldest beyond retention
                "DELETE FROM notes WHERE rowid NOT IN "
                "(SELECT rowid FROM notes ORDER BY ts DESC LIMIT ?)",
                (_KEEP,))
            db.commit()
        finally:
            db.close()
    except sqlite3.Error:
        pass  # recall is additive — never break a turn over indexing


def index_turn(transcript: str, reply: str = "", result: str = "",
               path=None) -> None:
    add("turn", f"user: {transcript}\ndim: {reply or result}", path)


def index_correction(rec: dict, path=None) -> None:
    add("correction",
        f"heard {rec.get('heard', '')} -> picked {rec.get('picked', '')}",
        path)


def search(query: str, k: int = 5, path=None) -> list:
    """FTS5 top-k; rank first, newest-first on ties. Empty/None-safe."""
    q = " ".join(w for w in query.split() if w.isalnum())
    if not q:
        return []
    try:
        db = _db(path)
        try:
            rows = db.execute(
                "SELECT kind, body, ts FROM notes "
                "WHERE notes MATCH ? ORDER BY rank, ts DESC LIMIT ?",
                (q, k)).fetchall()
        finally:
            db.close()
        return [{"kind": k_, "body": b, "ts": t} for k_, b, t in rows]
    except sqlite3.Error:
        return []


def run(arg: str) -> str:
    """Tool form: 'search <query>' or bare '<query>' -> text block."""
    parts = arg.split(None, 1)
    query = parts[1] if len(parts) > 1 and parts[0] == "search" else arg
    hits = search(query)
    if not hits:
        return f"no recall hits for {query!r}"
    return "\n".join(f"[{h['kind']} {h['ts'][:10]}] {h['body']}"
                     for h in hits)


def context_for(transcript: str, k: int = 3, path=None) -> str:
    """Top-k recall block for brain-call injection."""
    hits = search(transcript, k, path)
    if not hits:
        return ""
    return "\n".join(h["body"] for h in hits)


def backfill(path=None) -> int:
    """Index existing session.jsonl + corrections.jsonl once."""
    n = 0
    try:
        for line in config.SESSION_FILE.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            index_turn(rec.get("transcript", ""), rec.get("reply", ""),
                       rec.get("result", ""), path)
            n += 1
    except OSError:
        pass
    try:
        for line in config.CORRECTIONS.read_text().splitlines():
            try:
                index_correction(json.loads(line), path)
                n += 1
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return n
