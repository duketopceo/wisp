//! Self-authored skills — skills/*/SKILL.md (parity with dim/skills.py).
//! skill_manage / skill_view tools; index_text() injected into brain
//! calls; `tool:`+`tier:` frontmatter registers skill_<name> entries.
use crate::config;
use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;

fn dir() -> PathBuf {
    config::data_dir().join("skills")
}

fn slug(name: &str) -> String {
    crate::util::slug(name, 48, "skill")
}

fn frontmatter(text: &str) -> HashMap<String, String> {
    let mut m = HashMap::new();
    if let Some(rest) = text.strip_prefix("---\n") {
        if let Some(end) = rest.find("\n---\n") {
            for line in rest[..end].lines() {
                if let Some((k, v)) = line.split_once(':') {
                    m.insert(k.trim().to_string(),
                             v.trim().trim_matches('"').to_string());
                }
            }
        }
    }
    m
}

pub fn index_text() -> String {
    // one line per described skill, sorted by dir (parity: index())
    index().into_iter()
        .filter(|(_, d)| !d.is_empty())
        .map(|(n, d)| format!("- {n}: {d}"))
        .collect::<Vec<_>>().join("\n")
}

/// Names + descriptions sorted by directory (parity with index() in
/// dim/skills.py) — basis for both `list` and `index_text`.
fn index() -> Vec<(String, String)> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(dir()) {
        let mut ents: Vec<_> = rd.flatten()
            .map(|e| e.path())
            .filter(|p| p.is_dir() && p.join("SKILL.md").is_file())
            .collect();
        ents.sort();
        for p in ents {
            let name = p.file_name().unwrap().to_string_lossy().into_owned();
            let fm = std::fs::read_to_string(p.join("SKILL.md"))
                .map(|t| frontmatter(&t)).unwrap_or_default();
            out.push((fm.get("name").cloned().unwrap_or(name),
                      fm.get("description").cloned().unwrap_or_default()));
        }
    }
    out
}

/// skill_<name> entries for the tool registry (tool_schemas/describe).
pub fn tool_entries() -> Vec<(String, &'static str, String)> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(dir()) {
        let mut ents: Vec<_> = rd.flatten()
            .map(|e| e.path())
            .filter(|p| p.is_dir() && p.join("SKILL.md").is_file())
            .collect();
        ents.sort();
        for p in ents {
            let fm = std::fs::read_to_string(p.join("SKILL.md"))
                .map(|t| frontmatter(&t)).unwrap_or_default();
            if !fm.contains_key("tool") {
                continue;
            }
            let dir_name =
                p.file_name().unwrap().to_string_lossy().into_owned();
            out.push((
                format!("skill_{}", slug(&dir_name)),
                tier_of(&fm),
                fm.get("description").cloned()
                    .unwrap_or_else(|| format!("skill {dir_name}")),
            ));
        }
    }
    out
}

pub fn view(name: &str) -> String {
    let f = dir().join(slug(name)).join("SKILL.md");
    std::fs::read_to_string(&f)
        .unwrap_or_else(|_| format!("FAIL (no skill {name:?})"))
}

/// Tool form: 'op|name|field|body' (field = description | filename)
pub fn run_manage(arg: &str) -> String {
    let mut parts = arg.splitn(4, '|').map(str::trim);
    let op = parts.next().unwrap_or("");
    let name = parts.next().unwrap_or("");
    let field = parts.next().unwrap_or("");
    let body = parts.next().unwrap_or("");
    if op != "list" && name.trim().is_empty() {
        return "FAIL (skill name required)".into();
    }
    let d = dir().join(slug(name));
    match op {
        "list" => {
            let names: Vec<String> =
                index().into_iter().map(|(n, _)| n).collect();
            if names.is_empty() { "OK (no skills)".into() }
            else { format!("OK {}", names.join(", ")) }
        }
        "create" => {
            if d.join("SKILL.md").exists() {
                return format!("FAIL (skill {:?} exists — use edit)", slug(name));
            }
            if let Err(e) = std::fs::create_dir_all(&d)
                .and_then(|_| std::fs::write(d.join("SKILL.md"), format!(
                    "---\nname: {}\ndescription: {}\n---\n# {}\n\n{}\n",
                    slug(name),
                    if field.is_empty() { "(undescribed)" } else { field },
                    slug(name),
                    if body.is_empty() { "TODO" } else { body })))
            {
                return format!("FAIL ({e})");
            }
            format!("OK (created {})", slug(name))
        }
        "edit" => {
            let f = d.join("SKILL.md");
            if !f.exists() {
                return format!("FAIL (no skill {:?} — use create)", slug(name));
            }
            if body.is_empty() {
                return "FAIL (edit needs the full new SKILL.md in body)".into();
            }
            // Python: body + "\n" only when missing — trailing blank
            // lines are preserved
            let text = if body.ends_with('\n') {
                body.to_string() } else { format!("{body}\n") };
            if let Err(e) = std::fs::write(&f, text) {
                return format!("FAIL ({e})");
            }
            format!("OK (edited {})", slug(name))
        }
        "delete" => {
            if !d.exists() {
                return format!("FAIL (no skill {:?})", slug(name));
            }
            if let Err(e) = std::fs::remove_dir_all(&d) {
                return format!("FAIL ({e})");
            }
            format!("OK (deleted {})", slug(name))
        }
        "write_file" | "remove_file" => {
            if field.is_empty() || field.contains('/') || field.contains("..") {
                return format!("FAIL ({op} needs a bare filename)");
            }
            let f = d.join(field);
            if op == "write_file" {
                if let Err(e) = std::fs::create_dir_all(&d)
                    .and_then(|_| std::fs::write(&f, body))
                {
                    return format!("FAIL ({e})");
                }
                format!("OK (wrote {}/{field})", slug(name))
            } else if f.exists() {
                if let Err(e) = std::fs::remove_file(&f) {
                    return format!("FAIL ({e})");
                }
                format!("OK (removed {}/{field})", slug(name))
            } else {
                format!("FAIL (no file {}/{field})", slug(name))
            }
        }
        _ => "FAIL (op must be create|edit|delete|write_file|remove_file|list)"
            .into(),
    }
}

fn skill_meta(name: &str) -> Option<HashMap<String, String>> {
    let skill = name.strip_prefix("skill_")?;
    // slug the suffix — the name comes from a model tool call and must
    // never resolve outside the skills dir
    let f = dir().join(slug(skill)).join("SKILL.md");
    let text = std::fs::read_to_string(&f).ok()?;
    Some(frontmatter(&text))
}

pub fn skill_meta_exists(name: &str) -> bool {
    skill_meta(name).is_some()
}

fn tier_of(fm: &HashMap<String, String>) -> &'static str {
    match fm.get("tier").map(|s| s.as_str()) {
        Some("safe") => "safe",
        Some("mutating") => "mutating",
        _ => "shell",
    }
}

/// skill_<name> dispatch: run the skill's declared `tool:` script.
/// Returns None when no such skill tool exists.
pub fn run_skill_tool(name: &str, arg: &str) -> Option<(String, &'static str)> {
    let skill = name.strip_prefix("skill_")?;
    let fm = skill_meta(name)?;
    let script = fm.get("tool")?;
    if script.contains('/') || script.contains("..") {
        return None;
    }
    let sp = dir().join(slug(skill)).join(script);
    if !sp.is_file() {
        return None;
    }
    let tier = tier_of(&fm);
    let out = crate::util::run_timeout(
        Command::new("bash").arg(&sp).args(split_args(arg)),
        60);  // Python: subprocess.run(timeout=60)
    let msg = match out {
        Ok(None) => "FAIL (skill script timed out)".into(),
        Ok(Some(o)) => {
            let s = String::from_utf8_lossy(if o.stdout.is_empty() {
                &o.stderr
            } else {
                &o.stdout
            }).trim().chars().take(2000).collect::<String>();
            if s.is_empty() {
                format!("(exit {})", o.status.code().unwrap_or(-1))
            } else {
                s
            }
        }
        Err(_) => "SKIP (no bash)".into(),
    };
    Some((msg, tier))
}

/// Risk tier for a skill_<name> tool (shell unless the skill declares
/// lower). Unknown skill tools stay shell — safest default.
pub fn skill_tier(name: &str) -> &'static str {
    skill_meta(name).map(|fm| tier_of(&fm)).unwrap_or("shell")
}

/// Minimal shlex: whitespace-split honoring single/double quotes
/// (parity with Python shlex.split for skill script args).
fn split_args(arg: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut quote = '\0';
    for c in arg.chars() {
        match c {
            '\'' | '"' if quote == '\0' => quote = c,
            _ if c == quote => quote = '\0',
            c if c.is_whitespace() && quote == '\0' => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
            c => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}
