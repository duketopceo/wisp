//! Deep recall — sqlite FTS5 store at recall.db (parity with
//! dim/recall.py). Write-through on turns + corrections; lexical FTS5
//! search needs no keys. rusqlite is bundled so recall.db is
//! byte-compatible with the Python core's.
use crate::config;
use rusqlite::Connection;
use std::path::{Path, PathBuf};

fn db_path() -> PathBuf {
    config::data_dir().join("recall.db")
}

fn db(path: Option<&Path>) -> Option<Connection> {
    let p = path.map(PathBuf::from).unwrap_or_else(db_path);
    p.parent().map(|d| std::fs::create_dir_all(d).ok());
    let c = Connection::open(&p).ok()?;
    c.execute_batch(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes \
         USING fts5(kind, body, ts, tokenize='porter');").ok()?;
    Some(c)
}

pub fn add(kind: &str, body: &str) {
    if body.trim().is_empty() {
        return;
    }
    if let Some(c) = db(None) {
        let body: String = body.chars().take(4000).collect();
        c.execute(
            "INSERT INTO notes (kind, body, ts) VALUES (?1, ?2, ?3)",
            (kind, &body, crate::state::now_iso())).ok();
        // bounded store — parity with _KEEP in dim/recall.py
        c.execute(
            "DELETE FROM notes WHERE rowid NOT IN \
             (SELECT rowid FROM notes ORDER BY ts DESC LIMIT 5000)",
            []).ok();
    }
}

pub fn index_turn(transcript: &str, reply: &str, result: &str) {
    add("turn", &format!("user: {transcript}\ndim: {}",
                         if reply.is_empty() { result } else { reply }));
}

pub fn index_correction(heard: &str, picked: &str) {
    add("correction", &format!("heard {heard} -> picked {picked}"));
}

pub fn search(query: &str, k: usize) -> Vec<(String, String, String)> {
    let q: String = query.split_whitespace()
        .filter(|w| w.chars().all(|c| c.is_alphanumeric()))
        .collect::<Vec<_>>().join(" ");
    if q.is_empty() {
        return vec![];
    }
    let Some(c) = db(None) else { return vec![] };
    let mut st = match c.prepare(
        "SELECT kind, body, ts FROM notes WHERE notes MATCH ?1 \
         ORDER BY rank, ts DESC LIMIT ?2") {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    st.query_map((&q, k as i64), |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?,
            r.get::<_, String>(2)?))
    }).map(|rows| rows.flatten().collect()).unwrap_or_default()
}

/// Tool form: 'search <query>' or bare '<query>' — parity with Python's
/// whitespace-split first-token check (handles tabs/leading space).
pub fn run(arg: &str) -> String {
    let mut it = arg.split_whitespace();
    let rest: Vec<&str> = it.by_ref().collect();
    // Python: strip the "search" verb only when a query follows it
    let q = if rest.first() == Some(&"search") && rest.len() > 1 {
        rest[1..].join(" ")
    } else {
        arg.to_string()
    };
    let hits = search(&q, 5);
    if hits.is_empty() {
        return format!("no recall hits for '{q}'");
    }
    hits.iter()
        .map(|(k, b, t)| format!("[{} {}] {}", k,
                                 t.chars().take(10).collect::<String>(), b))
        .collect::<Vec<_>>().join("\n")
}

pub fn context_for(transcript: &str, k: usize) -> String {
    search(transcript, k).iter().map(|(_, b, _)| b.clone())
        .collect::<Vec<_>>().join("\n")
}

/// Index existing session.jsonl + corrections.jsonl once — parity with
/// dim/recall.py::backfill. Returns rows indexed.
pub fn backfill() -> usize {
    let mut n = 0;
    let data = config::data_dir();
    for (file, is_corr) in
        [("session.jsonl", false), ("corrections.jsonl", true)]
    {
        if let Ok(text) = std::fs::read_to_string(data.join(file)) {
            for line in text.lines() {
                let Ok(rec) =
                    serde_json::from_str::<serde_json::Value>(line)
                else { continue };
                if is_corr {
                    index_correction(
                        rec.get("heard").and_then(|v| v.as_str())
                            .unwrap_or(""),
                        rec.get("picked").and_then(|v| v.as_str())
                            .unwrap_or(""));
                } else {
                    index_turn(
                        rec.get("transcript").and_then(|v| v.as_str())
                            .unwrap_or(""),
                        rec.get("reply").and_then(|v| v.as_str())
                            .unwrap_or(""),
                        rec.get("result").and_then(|v| v.as_str())
                            .unwrap_or(""));
                }
                n += 1;
            }
        }
    }
    n
}
