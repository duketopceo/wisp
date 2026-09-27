//! Named agent spawns: `ori opencode run <task>` detached, tasks.jsonl
//! registry, tasks/<id>.log. Parity with dim/agents.py.
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::Command;

fn tasks_file() -> PathBuf {
    crate::config::data_dir().join("tasks.jsonl")
}
fn log_dir() -> PathBuf {
    crate::config::data_dir().join("tasks")
}

fn slug(text: &str) -> String {
    crate::util::slug(text, 32, "task")
}

fn records() -> Vec<Value> {
    std::fs::read_to_string(tasks_file())
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|l| serde_json::from_str(l).ok())
        .collect()
}

fn log_line(rec: &Value) {
    let f = tasks_file();
    if let Some(p) = f.parent() {
        let _ = std::fs::create_dir_all(p);
    }
    if let Ok(mut file) = std::fs::OpenOptions::new().append(true).create(true).open(f) {
        use std::io::Write;
        let _ = writeln!(file, "{}", serde_json::to_string(rec).unwrap());
    }
}

fn find(name: &str) -> Option<Value> {
    let name = name.trim().to_lowercase();
    records().into_iter().rev().find(|r| {
        r.get("name").and_then(|v| v.as_str()).map(|s| s.to_lowercase()) == Some(name.clone())
            || r.get("id").and_then(|v| v.as_str()).map(|s| s.to_lowercase()) == Some(name.clone())
    })
}

fn alive(pid: i64) -> bool {
    PathBuf::from(format!("/proc/{pid}")).exists()
}

pub fn spawn(task: &str) -> String {
    if !crate::tools::which("ori") {
        return "SKIP (ori not installed)".into();
    }
    let task = task.trim();
    if task.is_empty() {
        return "SKIP (empty agent task)".into();
    }
    let mut name = slug(task);
    let existing: Vec<String> = records().iter()
        .filter_map(|r| r.get("name").and_then(|v| v.as_str()).map(String::from))
        .collect();
    let mut i = 2;
    while existing.contains(&name) {
        name = format!("{}-{}", slug(task), i);
        i += 1;
    }
    std::fs::create_dir_all(log_dir()).ok();
    let log = log_dir().join(format!("{name}.log"));
    let lf = match std::fs::OpenOptions::new().append(true).create(true).open(&log) {
        Ok(f) => f,
        Err(e) => return format!("SKIP (log open failed: {e})"),
    };
    let child = Command::new("ori")
        .args(["opencode", "run", task])
        .stdout(lf.try_clone().unwrap())
        .stderr(lf)
        .stdin(std::process::Stdio::null())
        .spawn();
    match child {
        Ok(c) => {
            log_line(&json!({"id": name, "name": name, "task": task,
                             "pid": c.id(), "cmd": format!("ori opencode run {task}"),
                             "status": "running"}));
            format!("SPAWNED {name} (pid {})", c.id())
        }
        Err(e) => format!("SKIP (ori spawn failed: {e})"),
    }
}

pub fn status(name: &str) -> String {
    let Some(rec) = find(name) else {
        return format!("SKIP (no task {name:?})");
    };
    let running = alive(rec.get("pid").and_then(|v| v.as_i64()).unwrap_or(-1));
    let log = log_dir().join(format!("{}.log",
        rec.get("id").and_then(|v| v.as_str()).unwrap_or("")));
    let tail = std::fs::read_to_string(&log).unwrap_or_default()
        .lines().filter(|l| !l.trim().is_empty()).last()
        .map(|l| l.chars().take(160).collect::<String>())
        .unwrap_or_default();
    let state = if running { "running" } else {
        rec.get("status").and_then(|v| v.as_str()).unwrap_or("exited")
    };
    format!("TASK {} [{}] {}",
        rec.get("name").and_then(|v| v.as_str()).unwrap_or(""), state, tail)
        .trim().to_string()
}

pub fn cancel(name: &str) -> String {
    let Some(rec) = find(name) else {
        return format!("SKIP (no task {name:?})");
    };
    let pid = rec.get("pid").and_then(|v| v.as_i64()).unwrap_or(-1);
    if !alive(pid) {
        return format!("SKIP ({name} not running)");
    }
    libc_kill(pid as i32);
    log_line(&json!({"id": rec["id"], "name": rec["name"],
                     "status": "cancelled"}));
    format!("CANCELLED {name}")
}

fn libc_kill(pid: i32) {
    // kill -TERM via sh to avoid a libc dep
    Command::new("kill").args(["-TERM", &pid.to_string()]).output().ok();
}

pub fn tasks() -> Value {
    let mut out = serde_json::Map::new();
    for rec in records() {
        let pid = rec.get("pid").and_then(|v| v.as_i64()).unwrap_or(-1);
        let status = if alive(pid) { "running" } else {
            rec.get("status").and_then(|v| v.as_str()).unwrap_or("exited")
        };
        if let Some(n) = rec.get("name").and_then(|v| v.as_str()) {
            out.insert(n.to_string(), json!({
                "status": status,
                "task": rec.get("task").and_then(|v| v.as_str()).unwrap_or(""),
            }));
        }
    }
    Value::Object(out)
}
