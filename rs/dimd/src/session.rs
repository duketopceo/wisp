//! session.jsonl — persistent turns for follow-up context.
//! Parity with dim/session.py.
use serde_json::{json, Value};
use std::path::PathBuf;

fn file() -> PathBuf {
    crate::config::data_dir().join("session.jsonl")
}

pub fn append_turn(transcript: &str, route: &str, reply: &str, result: &str) {
    let f = file();
    if let Some(p) = f.parent() {
        std::fs::create_dir_all(p).ok();
    }
    if let Ok(mut fh) = std::fs::OpenOptions::new().append(true).create(true).open(&f) {
        use std::io::Write;
        let _ = writeln!(fh, "{}", json!({
            "ts": crate::state::now_iso(),
            "transcript": transcript, "route": route,
            "reply": reply, "result": result,
        }));
    }
}

pub fn tail(n: usize) -> Vec<Value> {
    use std::io::{Read, Seek, SeekFrom};
    let mut buf = Vec::new();
    if let Ok(mut f) = std::fs::File::open(file()) {
        // only the last 64KB — session.jsonl grows unboundedly
        let end = f.metadata().map(|m| m.len()).unwrap_or(0);
        if f.seek(SeekFrom::Start(end.saturating_sub(65536))).is_ok() {
            let _ = f.read_to_end(&mut buf);
        }
    }
    // seek can land mid-line/mid-UTF-8 — lossy decode, first partial
    // line just fails json parse like a torn write.
    // parity: Python parses only the last max(2n,16) RAW lines — torn
    // lines consume window slots there, so bound the same way.
    let text = String::from_utf8_lossy(&buf);
    let raw: Vec<&str> = text.lines().collect();
    let start = raw.len().saturating_sub((n * 2).max(16));
    raw[start..].iter()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .collect::<Vec<_>>()
        .into_iter().rev().take(n).rev().collect()
}

pub fn as_text(turns: &[Value]) -> String {
    // "user: / dim:" lines — parity with dim/session.py::as_text
    let mut parts = Vec::new();
    for t in turns {
        let said = t.get("transcript").and_then(|v| v.as_str()).unwrap_or("");
        // parity: `reply or result` — an empty reply falls back too
        let reply = t.get("reply").and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .or_else(|| t.get("result").and_then(|v| v.as_str()))
            .unwrap_or("");
        if !said.is_empty() {
            parts.push(format!("user: {said}"));
        }
        if !reply.is_empty() {
            parts.push(format!("dim: {reply}"));
        }
    }
    parts.join("\n")
}
