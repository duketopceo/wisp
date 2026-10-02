"""Deep recall — sqlite FTS5 store at recall.db (Hermes deep-recall shape).

Every completed turn, correction, and curated note is indexed here for
day-to-day context that outlives the session tail. Lexical FTS5 search
means recall works with zero API keys; a vector/embedding backend can be
layered on later without changing the tool surface (plan: sqlite-vec).
Single daemon writer; searches are read-only.
"""
import json
import queue
import sqlite3
import threading
import urllib.request
from datetime import datetime, timezone

from . import config

DB_FILE = config.DATA_DIR / "recall.db"
_KEEP = 5000  # retention cap — recall is recent-context, not an archive
_RRF_K = 60  # standard reciprocal-rank-fusion constant

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes
USING fts5(kind, body, ts, tokenize='porter');
CREATE TABLE IF NOT EXISTS recall_meta(key TEXT PRIMARY KEY, value TEXT);
"""

_EMBED_Q: "queue.Queue" = queue.Queue()
_embed_thread = None
_vec_failed = False  # sticky — one bad dims/model and we stop spamming the API


def _db(path=None) -> sqlite3.Connection:
    path = path or DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    try:
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
    except (ImportError, sqlite3.Error, AttributeError):
        pass  # FTS5-only fallback — vector ops degrade to no-ops
        # (AttributeError: GitHub/CI python builds without sqlite
        #  extension loading lack enable_load_extension entirely)
    db.executescript(_SCHEMA)
    return db


def vec_available() -> bool:
    """True only when sqlite-vec can actually be *loaded*.

    Importing the module is not enough: some Python builds (GitHub's
    macos-latest setup-python among them) ship a sqlite3 compiled without
    loadable-extension support, so `enable_load_extension` is absent and
    every vector call silently degrades to FTS-only. Callers that assert
    vector behaviour must probe this rather than trust the import.
    """
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False
    db = None
    try:
        db = sqlite3.connect(":memory:")
        if not hasattr(db, "enable_load_extension"):
            return False
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        return True
    except (sqlite3.Error, AttributeError, OSError):
        return False
    finally:
        if db is not None:
            db.close()


def _vec_provider(path=None) -> dict | None:
    """[recall] embedding config, or None when provider=none/absent or
    the sqlite-vec extension is unavailable."""
    global _vec_failed
    if _vec_failed:
        return None
    cfg = config.load_config().get("recall", {})
    if cfg.get("provider", "none") in ("", "none"):
        return None
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return None
    return cfg


def _embed(texts: list, cfg: dict) -> list:
    """OpenAI-compatible /embeddings POST (OpenRouter default)."""
    base = cfg.get("base_url", "https://openrouter.ai/api/v1")
    key = config.load_env_key(cfg.get("key_env", "OPENROUTER_API_KEY"))
    model = cfg.get("model", "openai/text-embedding-3-small")
    body = json.dumps({"model": model, "input": texts}).encode()
    from . import brain as _brain
    req = urllib.request.Request(
        f"{base}/embeddings", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "wisp/1.0",
                 **_brain.app_headers(base)})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return [d["embedding"] for d in data["data"]]


def _vec_store(db: sqlite3.Connection, rowid: int, emb: list) -> None:
    """Create/maintain vec_items sized to the live model's dims."""
    dims = db.execute(
        "SELECT value FROM recall_meta WHERE key='dims'").fetchone()
    if dims is None:
        db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_items "
            f"USING vec0(embedding float[{len(emb)}])")
        db.execute(
            "INSERT INTO recall_meta VALUES ('dims', ?)",
            (str(len(emb)),))
    elif int(dims[0]) != len(emb):
        db.execute("DROP TABLE IF EXISTS vec_items")  # model changed
        db.execute(
            f"CREATE VIRTUAL TABLE vec_items "
            f"USING vec0(embedding float[{len(emb)}])")
        db.execute(
            "UPDATE recall_meta SET value=? WHERE key='dims'",
            (str(len(emb)),))
    db.execute("INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)",
               (rowid, json.dumps(emb)))


def _embed_and_store(rowid: int, body: str, cfg: dict, path=None) -> None:
    global _vec_failed
    try:
        emb = _embed([body], cfg)[0]
    except Exception:
        _vec_failed = True  # API/model failure — stop spamming the API
        return
    try:
        db = _db(path)
        try:
            _vec_store(db, rowid, emb)
            db.commit()
        finally:
            db.close()
    except sqlite3.Error:
        pass  # transient store errors don't disable the provider


def _embed_worker() -> None:
    while True:
        job = _EMBED_Q.get()
        if job is None:
            return
        rowid, body, cfg, path = job
        _embed_and_store(rowid, body, cfg, path)


def _queue_embed(rowid: int, body: str, cfg: dict, path=None) -> None:
    global _embed_thread
    if _embed_thread is None or not _embed_thread.is_alive():
        _embed_thread = threading.Thread(target=_embed_worker, daemon=True)
        _embed_thread.start()
    _EMBED_Q.put((rowid, body, cfg, path))


def add(kind: str, body: str, path=None) -> None:
    if not body.strip():
        return
    try:
        db = _db(path)
        try:
            cur = db.execute(
                "INSERT INTO notes (kind, body, ts) VALUES (?, ?, ?)",
                (kind, body[:4000],
                 datetime.now(timezone.utc).isoformat()))
            rowid = cur.lastrowid
            db.execute(  # bounded store — drop oldest beyond retention
                "DELETE FROM notes WHERE rowid NOT IN "
                "(SELECT rowid FROM notes ORDER BY ts DESC LIMIT ?)",
                (_KEEP,))
            db.commit()
        finally:
            db.close()
        cfg = _vec_provider(path)
        if cfg:
            _queue_embed(rowid, body, cfg, path)
    except sqlite3.Error:
        pass  # recall is additive — never break a turn over indexing


def _vec_hits(db: sqlite3.Connection, query_emb: list,
              k: int) -> list[int]:
    """rowids by ANN distance, empty when vec_items is absent/empty."""
    try:
        return [r[0] for r in db.execute(
            "SELECT rowid FROM vec_items WHERE embedding MATCH ? "
            "AND k = ? ORDER BY distance",
            (json.dumps(query_emb), k)).fetchall()]
    except sqlite3.Error:
        return []


def index_turn(transcript: str, reply: str = "", result: str = "",
               path=None) -> None:
    add("turn", f"user: {transcript}\nwisp: {reply or result}", path)


def index_correction(rec: dict, path=None) -> None:
    add("correction",
        f"heard {rec.get('heard', '')} -> picked {rec.get('picked', '')}",
        path)


def search(query: str, k: int = 5, path=None) -> list:
    """Top-k recall: RRF merge of FTS5 rank + vec ANN (when a provider is
    configured). With provider=none this is byte-for-byte today's FTS5
    path. Empty/None-safe."""
    q = " ".join(w for w in query.split() if w.isalnum())
    cfg = _vec_provider(path)
    if not q and not cfg:
        return []
    try:
        db = _db(path)
        try:
            fts_rows = []
            if q:
                fts_rows = db.execute(
                    "SELECT rowid, kind, body, ts FROM notes "
                    "WHERE notes MATCH ? ORDER BY rank, ts DESC LIMIT ?",
                    (q, k * 2)).fetchall()
            scores: dict[int, float] = {}
            for i, r in enumerate(fts_rows):
                scores[r[0]] = scores.get(r[0], 0) + 1 / (_RRF_K + i + 1)
            if cfg:
                try:
                    emb = _embed([query], cfg)[0]
                    for i, rid in enumerate(_vec_hits(db, emb, k * 2)):
                        scores[rid] = (scores.get(rid, 0)
                                       + 1 / (_RRF_K + i + 1))
                except Exception:
                    pass  # embed outage → FTS-only, per plan
            top = sorted(scores, key=scores.get, reverse=True)[:k]
            if cfg and any(r not in {f[0] for f in fts_rows}
                           for r in top):
                ids = ",".join(str(r) for r in top)
                rows_by_id = {r[0]: r for r in db.execute(
                    f"SELECT rowid, kind, body, ts FROM notes "
                    f"WHERE rowid IN ({ids})").fetchall()}
            else:
                rows_by_id = {r[0]: r for r in fts_rows}
        finally:
            db.close()
        return [{"kind": r[1], "body": r[2], "ts": r[3]}
                for r in (rows_by_id.get(i) for i in top) if r]
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
