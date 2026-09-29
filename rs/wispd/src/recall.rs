//! Deep recall — sqlite FTS5 + optional sqlite-vec embeddings at
//! recall.db (parity with wisp/recall.py). Write-through on turns +
//! corrections; lexical FTS5 needs no keys. When `[recall] provider`
//! is set, writes embed async into vec_items and search merges both
//! ranks with RRF. rusqlite is bundled so recall.db is byte-compatible
//! with the Python core's.
use crate::config;
use rusqlite::{ffi::sqlite3_auto_extension, Connection};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::OnceLock;

const RRF_K: f64 = 60.0; // reciprocal-rank-fusion constant (Python _RRF_K)
static VEC_FAILED: AtomicBool = AtomicBool::new(false); // sticky on API fail
static VEC_EXT: std::sync::Once = std::sync::Once::new();
static EMBED_TX: OnceLock<mpsc::Sender<(i64, String, Option<PathBuf>)>> =
    OnceLock::new();

fn db_path() -> PathBuf {
    config::data_dir().join("recall.db")
}

fn register_vec_ext() {
    VEC_EXT.call_once(|| unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(
            sqlite_vec::sqlite3_vec_init as *const ())));
    });
}

fn db(path: Option<&Path>) -> Option<Connection> {
    register_vec_ext();
    let p = path.map(PathBuf::from).unwrap_or_else(db_path);
    p.parent().map(|d| std::fs::create_dir_all(d).ok());
    let c = Connection::open(&p).ok()?;
    c.execute_batch(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes \
         USING fts5(kind, body, ts, tokenize='porter'); \
         CREATE TABLE IF NOT EXISTS recall_meta\
         (key TEXT PRIMARY KEY, value TEXT);").ok()?;
    Some(c)
}

fn vec_provider() -> Option<()> {
    if VEC_FAILED.load(Ordering::Relaxed) {
        return None;
    }
    let cfg = config::load();
    if cfg.recall_provider.is_empty() || cfg.recall_provider == "none" {
        return None;
    }
    Some(())
}

/// OpenAI-compatible /embeddings POST — parity with Python `_embed`.
fn embed(texts: &[String]) -> Result<Vec<Vec<f64>>, String> {
    let cfg = config::load();
    let key = config::env_key(&cfg.recall_key_env)
        .ok_or_else(|| format!("no key at {}", cfg.recall_key_env))?;
    let url = format!("{}/embeddings",
                      cfg.recall_base_url.trim_end_matches('/'));
    let body = json!({"model": cfg.recall_model, "input": texts});
    let resp = ureq::post(&url)
        .set("User-Agent", "wisp/1.0")
        .set("Authorization", &format!("Bearer {key}"))
        .timeout(std::time::Duration::from_secs(30))
        .send_json(&body)
        .map_err(|e| e.to_string())?;
    let v: Value = resp.into_json().map_err(|e| e.to_string())?;
    v.get("data").and_then(|d| d.as_array())
        .map(|rows| rows.iter().filter_map(|r| {
            r.get("embedding")?.as_array().map(|e| {
                e.iter().filter_map(|f| f.as_f64()).collect()
            })
        }).collect())
        .ok_or_else(|| "no data[] in embeddings response".into())
}

/// Create/maintain vec_items sized to the live model's dims — parity
/// with Python `_vec_store` (model change drops and recreates).
fn vec_store(c: &Connection, rowid: i64, emb: &[f64]) {
    let dims: Option<String> = c.query_row(
        "SELECT value FROM recall_meta WHERE key='dims'", [],
        |r| r.get(0)).ok();
    match dims {
        None => {
            c.execute_batch(&format!(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_items \
                 USING vec0(embedding float[{}]);", emb.len())).ok();
            c.execute("INSERT INTO recall_meta VALUES ('dims', ?1)",
                      (emb.len().to_string(),)).ok();
        }
        Some(d) if d.parse::<usize>().ok() != Some(emb.len()) => {
            c.execute_batch("DROP TABLE IF EXISTS vec_items;").ok();
            c.execute_batch(&format!(
                "CREATE VIRTUAL TABLE vec_items \
                 USING vec0(embedding float[{}]);", emb.len())).ok();
            c.execute("UPDATE recall_meta SET value=?1 WHERE key='dims'",
                      (emb.len().to_string(),)).ok();
        }
        _ => {}
    }
    let blob = serde_json::to_string(emb).unwrap_or_default();
    c.execute("INSERT INTO vec_items(rowid, embedding) VALUES (?1, ?2)",
              (rowid, blob)).ok();
}

fn embed_and_store(rowid: i64, body: &str, path: Option<&Path>) {
    match embed(&[body.to_string()]) {
        Ok(v) if !v.is_empty() => {
            if let Some(c) = db(path) {
                vec_store(&c, rowid, &v[0]);
            }
        }
        _ => VEC_FAILED.store(true, Ordering::Relaxed), // API/model fail
    }
}

fn embed_worker(rx: mpsc::Receiver<(i64, String, Option<PathBuf>)>) {
    while let Ok((rowid, body, path)) = rx.recv() {
        embed_and_store(rowid, &body, path.as_deref());
    }
}

fn queue_embed(rowid: i64, body: &str, path: Option<PathBuf>) {
    let tx = EMBED_TX.get_or_init(|| {
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || embed_worker(rx));
        tx
    });
    tx.send((rowid, body.to_string(), path)).ok();
}

pub fn add(kind: &str, body: &str) {
    add_at(kind, body, None);
}

fn add_at(kind: &str, body: &str, path: Option<&Path>) {
    if body.trim().is_empty() {
        return;
    }
    let mut rowid = None;
    if let Some(c) = db(path) {
        let body: String = body.chars().take(4000).collect();
        if c.execute(
            "INSERT INTO notes (kind, body, ts) VALUES (?1, ?2, ?3)",
            (kind, &body, crate::state::now_iso())).is_ok() {
            rowid = Some(c.last_insert_rowid());
        }
        // bounded store — parity with _KEEP in wisp/recall.py
        c.execute(
            "DELETE FROM notes WHERE rowid NOT IN \
             (SELECT rowid FROM notes ORDER BY ts DESC LIMIT 5000)",
            []).ok();
        if let (Some(rid), Some(())) = (rowid, vec_provider()) {
            queue_embed(rid, &body, path.map(PathBuf::from));
        }
    }
}

/// rowids by ANN distance — empty when vec_items absent. Parity with
/// Python `_vec_hits`.
fn vec_hits(c: &Connection, emb: &[f64], k: usize) -> Vec<i64> {
    let blob = serde_json::to_string(emb).unwrap_or_default();
    let mut st = match c.prepare(
        "SELECT rowid FROM vec_items WHERE embedding MATCH ?1 \
         AND k = ?2 ORDER BY distance") {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    st.query_map((blob, k as i64), |r| r.get::<_, i64>(0))
        .map(|rows| rows.flatten().collect())
        .unwrap_or_default()
}

pub fn index_turn(transcript: &str, reply: &str, result: &str) {
    add("turn", &format!("user: {transcript}\nwisp: {}",
                         if reply.is_empty() { result } else { reply }));
}

pub fn index_correction(heard: &str, picked: &str) {
    add("correction", &format!("heard {heard} -> picked {picked}"));
}

/// Search with an injected embedder — the seam tests use for vector
/// fixtures without hitting a real API.
fn search_with<E>(query: &str, k: usize, path: Option<&Path>,
                  emb_fn: Option<E>) -> Vec<(String, String, String)>
where E: Fn(&str) -> Option<Vec<f64>> {
    let q: String = query.split_whitespace()
        .filter(|w| w.chars().all(|c| c.is_alphanumeric()))
        .collect::<Vec<_>>().join(" ");
    let Some(c) = db(path) else { return vec![] };
    let mut scores: std::collections::HashMap<i64, f64> =
        std::collections::HashMap::new();
    let mut rows: std::collections::HashMap<
        i64, (String, String, String)> = std::collections::HashMap::new();
    if !q.is_empty() {
        if let Ok(mut st) = c.prepare(
            "SELECT rowid, kind, body, ts FROM notes WHERE notes MATCH ?1 \
             ORDER BY rank, ts DESC LIMIT ?2") {
            if let Ok(it) = st.query_map((&q, (k * 2) as i64), |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?, r.get::<_, String>(3)?))
            }) {
                for (i, r) in it.flatten().enumerate() {
                    *scores.entry(r.0).or_default() +=
                        1.0 / (RRF_K + i as f64 + 1.0);
                    rows.insert(r.0, (r.1, r.2, r.3));
                }
            }
        }
    }
    if let Some(ef) = emb_fn {
        if let Some(emb) = ef(query) {
            for (i, rid) in vec_hits(&c, &emb, k * 2).iter().enumerate() {
                *scores.entry(*rid).or_default() +=
                    1.0 / (RRF_K + i as f64 + 1.0);
            }
        }
    }
    // fetch any vec-only hits not already loaded from the FTS path
    let mut top: Vec<i64> = scores.keys().cloned().collect();
    top.sort_by(|a, b| scores[b].partial_cmp(&scores[a])
        .unwrap_or(std::cmp::Ordering::Equal));
    top.truncate(k);
    let missing: Vec<i64> = top.iter().cloned()
        .filter(|r| !rows.contains_key(r)).collect();
    for rid in &missing {
        if let Ok(r) = c.query_row(
            "SELECT kind, body, ts FROM notes WHERE rowid=?1",
            [rid], |r| Ok((r.get::<_, String>(0)?,
                           r.get::<_, String>(1)?,
                           r.get::<_, String>(2)?))) {
            rows.insert(*rid, r);
        }
    }
    top.iter().filter_map(|r| rows.get(r).cloned()).collect()
}

pub fn search(query: &str, k: usize) -> Vec<(String, String, String)> {
    let ef = if vec_provider().is_some() {
        Some(|q: &str| embed(&[q.to_string()])
            .ok().and_then(|v| v.into_iter().next()))
    } else {
        None
    };
    search_with(query, k, None, ef)
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
/// wisp/recall.py::backfill. Returns rows indexed.
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

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_embed(texts: &[String]) -> Result<Vec<Vec<f64>>, String> {
        let vocab = ["restart", "audio", "daemon", "pipewire", "reboot"];
        Ok(texts.iter().map(|t| {
            if t.to_lowercase().split_whitespace()
                .any(|w| vocab.contains(&w)) {
                vec![1.0, 0.0]
            } else {
                vec![0.0, 1.0]
            }
        }).collect())
    }

    #[test]
    fn vec_store_and_ann() {
        register_vec_ext();
        let dir = std::env::temp_dir()
            .join(format!("wisp-vec-{}", std::process::id()));
        std::fs::create_dir_all(&dir).ok();
        let path = dir.join("recall.db");
        let c = db(Some(&path)).unwrap();
        vec_store(&c, 1, &[1.0, 0.0]);
        vec_store(&c, 2, &[0.0, 1.0]);
        let hits = vec_hits(&c, &[1.0, 0.0], 2);
        assert_eq!(hits.first(), Some(&1));
        // dims mismatch recreates the table (parity with Python)
        vec_store(&c, 3, &[1.0, 0.0, 0.0]);
        let dims: String = c.query_row(
            "SELECT value FROM recall_meta WHERE key='dims'", [],
            |r| r.get(0)).unwrap();
        assert_eq!(dims, "3");
    }

    #[test]
    fn rrf_merges_fts_and_vec() {
        register_vec_ext();
        let dir = std::env::temp_dir()
            .join(format!("wisp-rrf-{}", std::process::id()));
        std::fs::create_dir_all(&dir).ok();
        let path = dir.join("recall.db");
        add_at("turn", "user: reboot audio daemon", Some(&path));
        add_at("turn", "user: unrelated groceries list", Some(&path));
        let c = db(Some(&path)).unwrap();
        for (i, e) in fake_embed(&[
            "user: reboot audio daemon".into(),
            "user: unrelated groceries list".into()])
            .unwrap().iter().enumerate() {
            vec_store(&c, (i + 1) as i64, e);
        }
        drop(c);
        // paraphrase query — vec hit should surface row 1
        let hits = search_with("restart pipewire", 5, Some(&path),
            Some(|q: &str| fake_embed(&[q.to_string()]).ok()
                .and_then(|v| v.into_iter().next())));
        assert!(!hits.is_empty());
        assert!(hits[0].1.contains("audio daemon"));
    }
}
