//! Toolbelt parity port: same registry, tiers, denylist, results.
//! Linux adapters shell out (grim/wtype/hyprctl/notify-send) — research
//! showed enigo/xcap weaker than these on Wayland. macOS/Windows
//! adapters (enigo/xcap/global-hotkey) land in Wave 4 behind cfg gates.
use crate::config::Cfg;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;

pub const SHELL_DENYLIST: &[&str] = &[
    "rm -rf /", "rm -rf ~", "rm -rf $HOME", "mkfs", "dd if=", ":(){ ",
    "shutdown", "reboot",
];

/// name -> (tier, description). Order matters for schema output.
pub const REGISTRY: &[(&str, &str, &str)] = &[
    ("launch", "safe", "open an application"),
    ("focus", "safe", "focus a window by class"),
    ("close", "mutating", "close the active/matching window"),
    ("workspace", "mutating", "switch Hyprland workspace"),
    ("notify", "safe", "send a desktop notification"),
    ("screenshot", "safe", "capture the screen to a file"),
    ("type_text", "mutating", "type text into the focused window"),
    ("shell", "shell", "run a shell command"),
    ("search_files", "safe", "find files by name under ~"),
    ("agent_spawn", "safe", "spawn a named ori opencode agent"),
    ("task_status", "safe", "report a named agent's status"),
    ("task_cancel", "mutating", "cancel a named agent"),
    ("memory", "mutating", "curate long-term memory — 'memory|add|fact', \
     'memory|replace|old|new', 'memory|remove|old' (target 'user' for USER.md)"),
    ("recall", "safe", "search long-term recall — 'search <query>'"),
    ("skill_manage", "mutating", "author a self-taught skill — \
     'create|name|description|body', 'edit|name||body', 'delete|name', \
     'write_file|name|filename|body', 'remove_file|name|filename', 'list'"),
    ("skill_view", "safe", "read a skill's full SKILL.md by name"),
];

/// All tool entries — static REGISTRY plus skill_<name> tools from
/// self-authored skills (parity: Python mutates REGISTRY at daemon
/// start and resolves skill_* dynamically).
pub fn entries() -> Vec<(String, &'static str, String)> {
    let mut v: Vec<(String, &'static str, String)> = REGISTRY
        .iter()
        .map(|(n, t, d)| (n.to_string(), *t, d.to_string()))
        .collect();
    v.extend(crate::skills::tool_entries());
    v
}

pub fn get(name: &str) -> Option<()> {
    if name.starts_with("skill_") {
        return if crate::skills::skill_meta_exists(name) {
            Some(()) } else { None };
    }
    REGISTRY.iter().find(|(n, _, _)| *n == name).map(|_| ())
}

/// Criteria text for Jev's tool question (name -> description).
pub fn describe() -> std::collections::HashMap<String, String> {
    entries().into_iter().map(|(n, _, d)| (n, d)).collect()
}

pub fn risk_of(name: &str) -> &'static str {
    if name.starts_with("skill_") {
        return crate::skills::skill_tier(name);
    }
    REGISTRY
        .iter()
        .find(|(n, _, _)| *n == name)
        .map(|(_, t, _)| *t)
        .unwrap_or("shell") // unknown => safest tier
}

pub fn denied(cmd: &str) -> bool {
    let c = cmd.to_lowercase();
    SHELL_DENYLIST.iter().any(|d| c.contains(d))
}

/// OpenAI-style tool schemas derived from REGISTRY (parity with
/// tools.tool_schemas() — one string `arg` per tool).
pub fn tool_schemas() -> Value {
    let arr: Vec<Value> = entries()
        .iter()
        .map(|(name, tier, desc)| {
            json!({
                "type": "function",
                "function": {
                    "name": name,
                    "description": format!("[{tier}] {desc}"),
                    "parameters": {
                        "type": "object",
                        "properties": {"arg": {"type": "string",
                            "description": "the argument or payload for this tool"}},
                        "required": []
                    }
                }
            })
        })
        .collect();
    json!(arr)
}

/// Try each command in order; `Some` = first output satisfying the
/// platform's wm verdict (`platform::wm_ok`). Runs every command —
/// later entries are fallbacks (hyprctl eval → legacy dispatch).
fn try_cmds(cmds: &mut [Command]) -> Option<std::process::Output> {
    for c in cmds {
        if let Ok(o) = c.output() {
            if crate::platform::wm_ok(&o) {
                return Some(o);
            }
        }
    }
    None
}

pub fn which(bin: &str) -> bool {
    let sep = if cfg!(windows) { ';' } else { ':' };
    let candidates: Vec<String> = if cfg!(windows) {
        // Executables on Windows are extension-carrying; PATHEXT order.
        vec![format!("{bin}.exe"), format!("{bin}.cmd"),
             format!("{bin}.bat"), format!("{bin}.ps1"), bin.to_string()]
    } else {
        vec![bin.to_string()]
    };
    if let Ok(path) = std::env::var("PATH") {
        return path.split(sep).any(|d| {
            candidates.iter().any(|name| {
                let p = PathBuf::from(d).join(name);
                if !p.is_file() {
                    return false;
                }
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    return p.metadata()
                        .map(|m| m.permissions().mode() & 0o111 != 0)
                        .unwrap_or(false);
                }
                #[cfg(not(unix))]
                true
            })
        });
    }
    false
}

fn resolve_apps(cfg: &Cfg) -> HashMap<String, String> {
    let mut apps = HashMap::new();
    if let Some(t) = cfg.raw.get("apps").and_then(|v| v.as_table()) {
        for (k, v) in t {
            if let Some(s) = v.as_str() {
                apps.insert(k.clone(), s.to_string());
            }
        }
    }
    let harness = crate::config::data_dir().join("harness.json");
    if let Ok(text) = std::fs::read_to_string(harness) {
        if let Ok(v) = serde_json::from_str::<Value>(&text) {
            if let Some(m) = v.get("apps").and_then(|a| a.as_object()) {
                for (k, a) in m {
                    if let Some(l) = a.get("launch").and_then(|l| l.as_str()) {
                        apps.insert(k.clone(), l.to_string());
                    }
                }
            }
        }
    }
    apps
}

/// Execute a tool. Gating happens upstream (act gate / pipeline); this
/// is the bare executor, same result strings as Python.
pub fn run(name: &str, arg: &str, cfg: &Cfg) -> String {
    let t0 = std::time::Instant::now();
    crate::trace::emit(&crate::trace::current(), "tool_call", "tool",
        serde_json::json!({"name": name, "args": arg}), None);
    let out = run_inner(name, arg, cfg);
    crate::trace::emit(&crate::trace::current(), "tool_result", "tool",
        serde_json::json!({"name": name, "result": out}),
        Some(t0.elapsed().as_millis() as i64));
    out
}

fn run_inner(name: &str, arg: &str, cfg: &Cfg) -> String {
    match name {
        "launch" => launch(arg, cfg),
        "focus" => focus(arg),
        "close" => close(arg),
        "workspace" => workspace(arg),
        "notify" => {
            if let Some(mut c) = crate::platform::notify_cmd("Wisp", arg) {
                c.spawn().ok();
            }
            "NOTIFIED".into()
        }
        "screenshot" => screenshot(),
        "type_text" => {
            if arg.is_empty() {
                return "SKIP (nothing to type)".into();
            }
            let Some(mut c) = crate::platform::type_text_cmd(arg) else {
                return format!("SKIP (no typer — {})",
                    crate::platform::missing_deps_hint());
            };
            let ok = c.output().map(|o| o.status.success())
                .unwrap_or(false);
            if ok { "TYPED".into() } else { "SKIP (typer failed)".into() }
        }
        "shell" => {
            if arg.is_empty() {
                return "SKIP (empty command)".into();
            }
            match Command::new("sh").args(["-c", arg]).output() {
                Ok(o) => {
                    let out = String::from_utf8_lossy(
                        if o.stdout.is_empty() { &o.stderr } else { &o.stdout });
                    let out: String = out.trim().chars().take(200).collect();
                    format!("SHELL rc={} {out}", o.status.code().unwrap_or(-1))
                }
                Err(e) => format!("ERROR ({e})"),
            }
        }
        "search_files" => search_files(arg),
        "agent_spawn" => crate::agents::spawn(arg, cfg),
        "task_status" => crate::agents::status(arg),
        "task_cancel" => crate::agents::cancel(arg),
        "memory" => crate::memory::run(arg),
        "recall" => crate::recall::run(arg),
        "skill_manage" => crate::skills::run_manage(arg),
        "skill_view" => crate::skills::view(arg.trim()),
        _ => match crate::skills::run_skill_tool(name, arg) {
            Some((msg, _)) => msg,
            None => format!("SKIP (tool {name:?} unavailable)"),
        },
    }
}

fn launch(app: &str, cfg: &Cfg) -> String {
    let apps = resolve_apps(cfg);
    let Some(binname) = apps.get(app) else {
        return format!("SKIP (unknown app {app:?})");
    };
    let mut binname = binname.as_str();
    let binary = binname.split_whitespace().next().unwrap_or("");
    let local = crate::config::data_dir()
        .join("../../bin")
        .join(binary);
    if !which(binary) && !local.exists() {
        // terminal: fall back to the desktop's configured default
        // (xdg-terminal-exec) — e.g. ghostty isn't packaged on Asahi
        if app == "terminal" && which("xdg-terminal-exec") {
            binname = "xdg-terminal-exec";
        } else {
            return format!("SKIP ({app} -> {binary:?} not installed)");
        }
    }
    // platform launcher (Hyprland eval+dispatch on Linux, direct
    // spawn on macOS) — verdict via wm_ok
    let mut cmds = crate::platform::launch_exec_cmds(binname);
    if try_cmds(&mut cmds).is_none() {
        return format!("SKIP (launch {binname} failed — {})",
            crate::platform::missing_deps_hint());
    }
    format!("LAUNCHED {app} -> {binname}")
}

fn focus(classname: &str) -> String {
    let mut cmds = crate::platform::focus_cmds(classname);
    if cmds.is_empty() {
        return format!("SKIP (focus unsupported — {})",
            crate::platform::missing_deps_hint());
    }
    match try_cmds(&mut cmds) {
        Some(_) => format!("FOCUSED {classname}"),
        None => format!("SKIP (no window matching class {classname:?})"),
    }
}

fn close(classname: &str) -> String {
    let target = if classname.is_empty() {
        "active window".to_string()
    } else {
        classname.to_string()
    };
    let mut cmds = crate::platform::close_cmds(classname);
    match try_cmds(&mut cmds) {
        Some(_) => format!("CLOSED {target}"),
        None => format!("SKIP (nothing closed for {classname:?})"),
    }
}

fn workspace(n: &str) -> String {
    match n.trim().parse::<i64>() {
        Ok(num) => {
            let mut cmds = crate::platform::workspace_cmds(num);
            if cmds.is_empty() {
                return format!("SKIP (workspace {num} unsupported — {})",
                    crate::platform::missing_deps_hint());
            }
            try_cmds(&mut cmds);
            format!("WORKSPACE {num}")
        }
        Err(_) => format!("SKIP (workspace {n:?} not a number)"),
    }
}

fn screenshot() -> String {
    let dir = crate::config::data_dir().join("shots");
    std::fs::create_dir_all(&dir).ok();
    let f = dir.join(format!("shot-{}.png",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs()));
    let Some(mut c) = crate::platform::screenshot_cmd(&f) else {
        return format!("SKIP (no screenshot tool — {})",
            crate::platform::missing_deps_hint());
    };
    let ok = c.output().map(|o| o.status.success()).unwrap_or(false);
    if ok && f.exists() {
        format!("SHOT {}", f.display())
    } else {
        "SKIP (screenshot failed)".into()
    }
}

fn search_files(pattern: &str) -> String {
    if pattern.is_empty() {
        return "SKIP (empty pattern)".into();
    }
    let home = PathBuf::from(std::env::var("HOME").unwrap_or("/tmp".into()));
    let mut hits = vec![];
    let mut stack = vec![home];
    while let Some(dir) = stack.pop() {
        if hits.len() >= 10 {
            break;
        }
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() {
                let p = e.path();
                let name = e.file_name().to_string_lossy().to_string();
                if p.is_dir() {
                    if !name.starts_with('.') && name != ".git" {
                        stack.push(p);
                    }
                } else if name.contains(pattern) {
                    hits.push(p.display().to_string());
                    if hits.len() >= 10 {
                        break;
                    }
                }
            }
        }
    }
    if hits.is_empty() {
        format!("SKIP (no files matching {pattern:?})")
    } else {
        format!("FILES {}", hits.join("\n"))
    }
}
