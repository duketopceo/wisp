//! Generic harness: app catalog from .desktop files + PATH resolution.
//! Parity with the no-dayflow path of scripts/build_harness.py +
//! dim/tools/adapters.py. Writes data_dir/harness.json; pipeline reads it.
use serde_json::{json, Map, Value};
use std::path::PathBuf;

/// Rebuild harness.json generically: every .desktop app with a runnable
/// Exec binary becomes a launchable entry keyed by lowercase name.
pub fn build() -> Result<String, String> {
    let home = PathBuf::from(std::env::var("HOME").unwrap_or("/tmp".into()));
    let dirs = [
        home.join(".local/share/applications"),
        PathBuf::from("/usr/share/applications"),
        PathBuf::from("/var/lib/flatpak/exports/share/applications"),
    ];
    let mut apps = Map::new();
    for dir in dirs {
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().and_then(|x| x.to_str()) != Some("desktop") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&p) else { continue };
            let mut name = String::new();
            let mut exec = String::new();
            let mut nodisplay = false;
            for line in text.lines() {
                if let Some(v) = line.strip_prefix("Name=") {
                    if name.is_empty() { name = v.trim().to_string(); }
                } else if let Some(v) = line.strip_prefix("Exec=") {
                    exec = v.trim().to_string();
                } else if line.trim() == "NoDisplay=true" {
                    nodisplay = true;
                }
            }
            if name.is_empty() || exec.is_empty() || nodisplay {
                continue;
            }
            // strip field codes (%f %u ...)
            let exec: String = exec.split_whitespace()
                .filter(|t| !t.starts_with('%'))
                .collect::<Vec<_>>().join(" ");
            let bin = exec.split_whitespace().next().unwrap_or("");
            let bin_base = PathBuf::from(bin)
                .file_name().map(|f| f.to_string_lossy().to_string())
                .unwrap_or_default();
            if !crate::tools::which(&bin_base)
                && !home.join(".local/bin").join(&bin_base).exists() {
                continue;
            }
            let key = name.to_lowercase();
            apps.entry(key).or_insert(json!({
                "launch": exec,
                "cues": name.to_lowercase(),
            }));
        }
    }
    let harness = json!({
        "generated": crate::state::now_iso(),
        "source": "generic .desktop + PATH catalog (dimd-rs)",
        "apps": Value::Object(apps.clone()),
    });
    let out = crate::config::data_dir().join("harness.json");
    std::fs::create_dir_all(out.parent().unwrap()).ok();
    std::fs::write(&out, serde_json::to_string_pretty(&harness).unwrap() + "\n")
        .map_err(|e| e.to_string())?;
    Ok(format!("wrote {}: {} apps", out.display(), apps.len()))
}
