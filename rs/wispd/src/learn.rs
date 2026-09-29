//! Learning loop: corrections -> staged weekly proposals -> approved
//! criteria overrides. Human-gated by design (parity with wisp/learn.py).
use serde_json::{json, Map, Value};
use std::path::PathBuf;

fn overrides_file() -> PathBuf {
    dirs_cfg().join("criteria_overrides.json")
}
fn corrections_file() -> PathBuf {
    crate::config::data_dir().join("corrections.jsonl")
}
fn proposals_dir() -> PathBuf {
    crate::config::data_dir().join("proposals")
}
fn dirs_cfg() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or("/tmp".into()))
        .join(".config/wisp")
}

fn read_jsonl(path: &PathBuf) -> Vec<Value> {
    std::fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|l| serde_json::from_str(l).ok())
        .collect()
}

pub fn record_correction(transcript: &str, picked: &str, answers: &Value) {
    let f = corrections_file();
    if let Some(p) = f.parent() {
        std::fs::create_dir_all(p).ok();
    }
    if let Ok(mut fh) = std::fs::OpenOptions::new().append(true).create(true).open(&f) {
        use std::io::Write;
        let _ = writeln!(fh, "{}", json!({
            "ts": crate::state::now_iso(),
            "heard": transcript,
            "picked": picked,
            "jev_said": {
                "app": answers.pointer("/app/choice"),
                "route": answers.pointer("/route/choice"),
            },
        }));
    }
}

fn load_overrides() -> Value {
    std::fs::read_to_string(overrides_file())
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(json!({}))
}

/// Overlay approved criteria text onto an app catalog (build_questions).
pub fn apply_overrides(criteria: &mut Map<String, Value>) {
    let o = load_overrides();
    let Some(app) = o.get("app").and_then(|v| v.as_object()) else {
        return;
    };
    for (name, cue) in app {
        let cue = cue.as_str().unwrap_or("");
        let merged = match criteria.get(name).and_then(|v| v.as_str()) {
            Some(existing) => format!("{existing} | user-corrected: {cue}"),
            None => format!("user-corrected: {cue}"),
        };
        criteria.insert(name.clone(), json!(merged));
    }
}

/// Aggregate last `days` of corrections into proposals/YYYY-WW.md.
/// Returns the proposal path, or empty string when nothing to propose.
pub fn weekly(days: i64) -> String {
    let cutoff_secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs()
        .saturating_sub((days * 86400) as u64);
    let recent: Vec<Value> = read_jsonl(&corrections_file())
        .into_iter()
        .filter(|r| {
            r.get("ts").and_then(|v| v.as_str())
                .and_then(|s| parse_iso_secs(s))
                .map(|t| t >= cutoff_secs)
                .unwrap_or(false)
        })
        .collect();
    if recent.is_empty() {
        return String::new();
    }
    let mut counts: std::collections::HashMap<String, u32> = Default::default();
    for r in &recent {
        let p = r.get("picked").and_then(|v| v.as_str()).unwrap_or("");
        *counts.entry(p.to_string()).or_default() += 1;
    }
    let (y, w) = iso_week();
    let dir = proposals_dir();
    std::fs::create_dir_all(&dir).ok();
    let out = dir.join(format!("{y}-W{w:02}.md"));
    let mut lines = vec![
        format!("# Wisp learning proposal — {y}-W{w:02}"),
        String::new(),
        format!("{} corrections in the last {days} days.", recent.len()),
        String::new(),
        "## Picks".into(),
        String::new(),
    ];
    for r in &recent {
        lines.push(format!(
            "- heard {:?} -> picked `{}` (jev said app={})",
            r.get("heard").and_then(|v| v.as_str()).unwrap_or(""),
            r.get("picked").and_then(|v| v.as_str()).unwrap_or(""),
            r.pointer("/jev_said/app").and_then(|v| v.as_str()).unwrap_or("?")));
    }
    lines.push("".into());
    lines.push("## Suggested criteria emphasis".into());
    lines.push("".into());
    let mut sorted: Vec<_> = counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1));
    for (pick, n) in sorted {
        let value = pick.split(':').nth(1).unwrap_or(&pick);
        lines.push(format!(
            "- `{value}` chosen {n}x — strengthen its criteria text or add the heard phrases as cues (approve to apply)"));
    }
    std::fs::write(&out, lines.join("\n") + "\n").ok();
    out.display().to_string()
}

/// Merge approved overrides (never auto-applied).
/// Parity API — invoked from the UI/CLI approval flow, not yet wired.
#[allow(dead_code)]
pub fn approve(overrides: &Value) {
    let mut cur = load_overrides();
    if let Some(app_new) = overrides.get("app").and_then(|v| v.as_object()) {
        let app = cur.as_object_mut().unwrap()
            .entry("app").or_insert(json!({}));
        for (k, v) in app_new {
            app.as_object_mut().unwrap().insert(k.clone(), v.clone());
        }
    }
    let f = overrides_file();
    std::fs::create_dir_all(f.parent().unwrap()).ok();
    std::fs::write(&f, serde_json::to_string_pretty(&cur).unwrap()).ok();
}

fn parse_iso_secs(s: &str) -> Option<u64> {
    // lenient: accept "YYYY-MM-DDTHH:MM:SS" prefix, optional Z/+offset ignored
    let (date, time) = s.split_once('T')?;
    let dp: Vec<i64> = date.split('-').filter_map(|v| v.parse().ok()).collect();
    let tp: Vec<i64> = time.trim_end_matches('Z').split(':')
        .take(3).filter_map(|v| v.split('+').next()
            .and_then(|x| x.parse().ok())).collect();
    if dp.len() != 3 || tp.len() < 2 {
        return None;
    }
    let days = days_from_civil(dp[0], dp[1] as u32, dp[2] as u32);
    Some(days as u64 * 86400 + tp[0] as u64 * 3600 + tp[1] as u64 * 60
         + tp.get(2).copied().unwrap_or(0) as u64)
}

fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let mp = (m + 9) % 12;
    let doy = (153 * mp as i64 + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn iso_week() -> (i64, u32) {
    // good enough for proposal filenames
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
    let days = (secs / 86400) as i64;
    let mut week = 1u32;
    let mut d = days_from_civil(1970, 1, 4); // first ISO week Mon
    while d + 7 <= days {
        d += 7;
        week += 1;
    }
    let (mut y, _) = (1970i64, 0u32);
    // recompute year from days
    let mut days_left = days;
    loop {
        let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
        let len = if leap { 366 } else { 365 };
        if days_left < len {
            break;
        }
        days_left -= len;
        y += 1;
    }
    (y, week.min(53))
}
