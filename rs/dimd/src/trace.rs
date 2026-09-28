//! Dev trace — full-fidelity event stream, parity with dim/trace.py.
//! One JSONL event per line at <data_dir>/trace.jsonl; thread-local
//! turn ids so implicit emitters (tools::run) tag the right turn.
//! NEVER log secrets — callers pass endpoint/model/status only.
use crate::config;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::OnceLock;

const MAX_MB: u64 = 10;      // rotate trace.jsonl -> trace.1.jsonl
const DATA_BYTES: usize = 8192; // per-string truncation
static ENABLED: OnceLock<bool> = OnceLock::new();

// daemon serializes listen cycles behind a busy flag, so one active
// turn id at a time is safe (Python uses a thread-local)
static TURN_ID: std::sync::Mutex<Option<String>> =
    std::sync::Mutex::new(None);

fn trace_file() -> PathBuf {
    config::data_dir().join("trace.jsonl")
}

fn enabled() -> bool {
    *ENABLED.get_or_init(|| {
        let raw = config::load().raw;
        let v = raw.get("debug").and_then(|d| d.get("trace"));
        match v {
            Some(toml::Value::Boolean(b)) => *b,
            Some(toml::Value::String(s)) =>
                !matches!(s.as_str(), "false" | "0" | "no" | "off"),
            _ => true, // [debug] trace defaults on
        }
    })
}

/// Mint + bind a turn id for this thread's listen cycle.
pub fn new_turn() -> String {
    let id = format!("t{:08x}", rand_u32());
    *TURN_ID.lock().unwrap() = Some(id.clone());
    id
}

fn rand_u32() -> u32 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let n = SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos()).unwrap_or(0);
    ((n ^ (n >> 33) ^ (std::process::id() as u128)) & 0xFFFF_FFFF) as u32
}

/// Current turn id ("sys" outside a listen cycle) — parity with
/// Python's thread-local `current()`.
pub fn current() -> String {
    TURN_ID.lock().unwrap().clone().unwrap_or_else(|| "sys".into())
}

fn clip(v: &Value) -> Value {
    match v {
        Value::String(s) if s.len() > DATA_BYTES => {
            let mut cut = s.clone();
            cut.truncate(DATA_BYTES);
            Value::String(format!("{cut}…"))
        }
        Value::Object(m) => Value::Object(
            m.iter().map(|(k, v)| (k.clone(), clip(v))).collect()),
        Value::Array(a) => Value::Array(a.iter().map(clip).collect()),
        _ => v.clone(),
    }
}

fn rotate(path: &PathBuf) {
    if let Ok(m) = std::fs::metadata(path) {
        if m.len() > MAX_MB * 1024 * 1024 {
            let prev = path.with_file_name("trace.1.jsonl");
            std::fs::remove_file(&prev).ok();
            std::fs::rename(path, prev).ok();
        }
    }
}

/// Append one event — silent no-op when disabled or on IO failure.
pub fn emit(turn: &str, step: &str, kind: &str,
            data: Value, ms: Option<i64>) {
    if !enabled() {
        return;
    }
    let ev = json!({"ts": crate::state::now_iso(), "turn": turn,
                    "step": step, "kind": kind, "ms": ms,
                    "data": clip(&data)});
    let path = trace_file();
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d).ok();
    }
    rotate(&path);
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true).append(true).open(&path) {
        writeln!(f, "{}", serde_json::to_string(&ev)
            .unwrap_or_default()).ok();
    }
}

/// Parse events back with filters — parity with Python `read()`.
pub fn read(tail: usize, turn: &str, kind: &str) -> Vec<Value> {
    let mut evs: Vec<Value> = std::fs::read_to_string(trace_file())
        .unwrap_or_default()
        .lines()
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        // valid JSON but not a trace event — parity with Python read()
        .filter(|e| e.get("turn").is_some() && e.get("step").is_some())
        .filter(|e| turn.is_empty()
            || e.get("turn").and_then(|v| v.as_str()) == Some(turn))
        .filter(|e| kind.is_empty()
            || e.get("kind").and_then(|v| v.as_str()) == Some(kind))
        .collect();
    if evs.len() > tail {
        evs.drain(..evs.len() - tail);
    }
    evs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn emit_schema_parity() {
        // same key set Python asserts in tests/test_trace.py
        let t = new_turn();
        emit(&t, "listen_start", "lifecycle",
             json!({"seconds": 5}), Some(12));
        let evs = read(50, &t, "lifecycle");
        assert_eq!(evs.len(), 1);
        let ev = &evs[0];
        for k in ["ts", "turn", "step", "kind", "ms", "data"] {
            assert!(ev.get(k).is_some(), "missing key {k}");
        }
        assert_eq!(ev["turn"], t);
        assert_eq!(ev["ms"], 12);
    }

    #[test]
    fn read_filters() {
        emit(&new_turn(), "a", "tool", json!({}), None);
        emit("sys", "ipc", "ipc", json!({"cmd": "status"}), None);
        let evs = read(50, "sys", "ipc");
        assert!(!evs.is_empty());
        assert!(evs.iter().all(|e| e["turn"] == "sys"));
    }
}

/// `dimd-rs trace [--tail N] [--turn id] [--kind k]` — parity CLI.
pub fn main(args: &[String]) -> i32 {
    let mut tail = 50usize;
    let mut turn = String::new();
    let mut kind = String::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--tail" =>
                tail = it.next().and_then(|v| v.parse().ok()).unwrap_or(50),
            "--turn" => turn = it.next().cloned().unwrap_or_default(),
            "--kind" => kind = it.next().cloned().unwrap_or_default(),
            _ => {}
        }
    }
    for ev in read(tail, &turn, &kind) {
        let ms = ev.get("ms").and_then(|v| v.as_i64())
            .map(|m| format!(" {m}ms")).unwrap_or_default();
        let ts = ev.get("ts").and_then(|v| v.as_str()).unwrap_or("");
        let short = if ts.len() >= 19 { &ts[11..19] } else { ts };
        println!("{} {} {}/{}{} {}", short,
                 ev.get("turn").and_then(|v| v.as_str()).unwrap_or(""),
                 ev.get("kind").and_then(|v| v.as_str()).unwrap_or(""),
                 ev.get("step").and_then(|v| v.as_str()).unwrap_or(""),
                 ms,
                 ev.get("data").map(|d| {
                     let s = d.to_string();
                     if s.len() > 400 { format!("{}…", &s[..400]) } else { s }
                 }).unwrap_or_default());
    }
    0
}
