//! Config: ~/.config/wisp/config.toml + .env secrets.
//! Parity with wisp/config.py — same paths, same keys, same defaults.
use serde::Deserialize;
use std::process::Command;
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Cfg {
    pub audio_seconds: u32,
    pub model: String,
    pub answer_model: String,
    pub risk_threshold: f64,
    pub confidence_ambiguous: f64,
    pub allow_shell: bool,
    pub screenshots: bool,
    pub session_turns: usize,
    pub voice_out: bool,
    pub voice_cmd: String,
    pub whisper_bin: PathBuf,
    pub whisper_model: PathBuf,
    pub router: String, // jev | chat | off
    // [stt] — "local" (whisper.cpp) or "openai" (OpenAI-compatible
    // /audio/transcriptions: Groq, OpenAI, vLLM, ...)
    pub stt_provider: String,
    pub stt_base_url: String,
    pub stt_model: String,
    pub stt_key_env: String,
    pub stt_prompt: String, // whisper `prompt` vocab-priming field
    // [recall] embeddings — "none" = FTS5-only; any other provider hits
    // an OpenAI-compatible /embeddings endpoint (OpenRouter default)
    pub recall_provider: String,
    pub recall_base_url: String,
    pub recall_model: String,
    pub recall_key_env: String,
    pub raw: toml::Value,
}

#[derive(Deserialize, Default)]
struct FileCfg {
    audio: Option<HashMap<String, toml::Value>>,
    agent: Option<HashMap<String, toml::Value>>,
    voice: Option<HashMap<String, toml::Value>>,
    brain: Option<HashMap<String, toml::Value>>,
    stt: Option<HashMap<String, toml::Value>>,
    recall: Option<HashMap<String, toml::Value>>,
}

pub fn cfg_dir() -> PathBuf {
    crate::platform::dirs(&dirs_home()).0
}
pub fn data_dir() -> PathBuf {
    // XDG_DATA_HOME is a *parent* dir — the app dir is appended
    // (parity with wisp/config.py; the platform default already ends
    // in wisp)
    if let Ok(x) = std::env::var("XDG_DATA_HOME") {
        return PathBuf::from(x).join("wisp");
    }
    crate::platform::dirs(&dirs_home()).1
}
pub fn runtime_dir() -> PathBuf {
    crate::platform::dirs(&dirs_home()).2
}
pub fn sock_file() -> PathBuf {
    runtime_dir().join("wispd.sock")
}
pub fn state_file() -> PathBuf {
    runtime_dir().join("state.json")
}
fn dirs_home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into()))
}

fn get<'a>(map: &'a Option<HashMap<String, toml::Value>>, key: &str) -> Option<&'a toml::Value> {
    map.as_ref()?.get(key)
}
fn s(v: Option<&toml::Value>, default: &str) -> String {
    v.and_then(|v| v.as_str()).unwrap_or(default).to_string()
}

// config.toml mixes native TOML types with `config set` writes, which
// are always quoted strings — accept both, like Python's flat parser.
fn truthy(v: Option<&toml::Value>) -> Option<bool> {
    v.and_then(|v| v.as_bool()
        .or_else(|| v.as_str().map(|s| s == "true")))
}
fn inty(v: Option<&toml::Value>) -> Option<i64> {
    v.and_then(|v| v.as_integer()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok())))
}
fn floaty(v: Option<&toml::Value>) -> Option<f64> {
    v.and_then(|v| v.as_float()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok())))
}

pub fn load() -> Cfg {
    let path = cfg_dir().join("config.toml");
    let text = std::fs::read_to_string(&path).unwrap_or_default();
    let f: FileCfg = toml::from_str(&text).unwrap_or_default();
    let home = dirs_home();
    Cfg {
        audio_seconds: inty(get(&f.audio, "seconds"))
            .unwrap_or(5) as u32,
        model: s(get(&f.agent, "model"), "typesafe/jev-1.13"),
        answer_model: s(
            get(&f.agent, "answer_model"),
            "meta-llama/llama-4-maverick",
        ),
        risk_threshold: floaty(get(&f.agent, "risk_threshold"))
            .unwrap_or(1.5),
        confidence_ambiguous: floaty(get(&f.agent, "confidence_ambiguous"))
            .unwrap_or(0.8),
        allow_shell: truthy(get(&f.agent, "allow_shell"))
            .unwrap_or(false),
        screenshots: truthy(get(&f.agent, "screenshots"))
            .unwrap_or(true),
        session_turns: inty(get(&f.agent, "session_turns"))
            .unwrap_or(8) as usize,
        // [voice].enabled — TTS replies (Python: cfg["voice"]["enabled"])
        voice_out: truthy(get(&f.voice, "enabled"))
            .unwrap_or(false),
        // [voice].cmd — custom TTS argv (whitespace-split, `{text}`
        // placeholder; empty = espeak default)
        voice_cmd: s(get(&f.voice, "cmd"), ""),
        stt_provider: s(get(&f.stt, "provider"), "local"),
        stt_base_url: s(get(&f.stt, "base_url"),
                        "https://api.groq.com/openai/v1"),
        stt_model: s(get(&f.stt, "model"), "whisper-large-v3-turbo"),
        stt_key_env: s(get(&f.stt, "key_env"), "GROQ_API_KEY"),
        stt_prompt: s(get(&f.stt, "prompt"), ""),
        recall_provider: s(get(&f.recall, "provider"), "none"),
        recall_base_url: s(get(&f.recall, "base_url"),
                           "https://openrouter.ai/api/v1"),
        recall_model: s(get(&f.recall, "model"),
                        "openai/text-embedding-3-small"),
        recall_key_env: s(get(&f.recall, "key_env"),
                          "OPENROUTER_API_KEY"),
        whisper_bin: home.join("src/whisper.cpp/build/bin/whisper-cli"),
        // audio.whisper_model is a filename under the whisper models
        // dir (Python: whisper_model() joins WHISPER_HOME/models)
        whisper_model: get(&f.audio, "whisper_model")
            .and_then(|v| v.as_str())
            .map(|n| {
                let p = PathBuf::from(n);
                if p.is_absolute() { p } else {
                    home.join("src/whisper.cpp/models").join(p)
                }
            })
            .unwrap_or_else(|| {
                home.join("src/whisper.cpp/models/ggml-small.en.bin")
            }),
        router: s(get(&f.brain, "router"), "jev"),
        raw: toml::from_str(&text).unwrap_or(toml::Value::Table(Default::default())),
    }
}

/// Same starter config as Python's DEFAULT_CONFIG — seeded before a
/// `config set` so a fresh file carries every documented key.
const DEFAULT_CONFIG: &str = "[hotkey]\nmod = \"SUPER\"\nkey = \"D\"\n\n[audio]\nseconds = 60\n# whisper.cpp model filename under ~/src/whisper.cpp/models/\nwhisper_model = \"ggml-small.en.bin\"\n\n[agent]\nmodel = \"typesafe/jev-1.13\"\nanswer_model = \"meta-llama/llama-4-maverick\"\nsession_turns = 8\nscreenshots = true\nrisk_threshold = 1.5\nconfidence_instant = 0.95\nconfidence_ambiguous = 0.8\n\n[voice]\nenabled = false\n\n[apps]\nbrowser = \"chromium\"\nterminal = \"ghostty\"\nfiles = \"nautilus\"\nvscode = \"code\"\nmusic = \"spotify\"\nsettings = \"gnome-control-center\"\nbrowser_new_tab = \"chromium\"\n";

/// Update one `section.key` in config.toml preserving comments/order.
/// Appends the key under its section (or a new section) when absent.
pub fn set_config(section: &str, key: &str, value: &str)
        -> Result<(), String> {
    if value.chars().any(|c| matches!(c, '"' | '\\' | '#' | '\n')) {
        return Err("config values may not contain \" \\ # or newline".into());
    }
    // section may be nested ("brain.ollama"); key stays a bare name
    let ok = |s: &str, dots: bool| !s.is_empty()
        && s.chars().all(|c| c.is_ascii_alphanumeric()
                         || c == '_' || c == '-'
                         || (dots && c == '.'));
    if !ok(section, true) || !ok(key, false) {
        return Err("config section/key must match \
                   [A-Za-z0-9_.-]+ / [A-Za-z0-9_-]+".into());
    }
    let path = cfg_dir().join("config.toml");
    std::fs::create_dir_all(cfg_dir()).ok();
    if !path.exists() {
        std::fs::write(&path, DEFAULT_CONFIG).ok();
    }
    let mut lines: Vec<String> = std::fs::read_to_string(&path)
        .unwrap_or_default()
        .lines().map(String::from).collect();
    let mut cur = String::new();
    let mut section_start: Option<usize> = None;
    let mut section_end = lines.len();
    let mut written = false;
    let mut replace_at: Option<usize> = None;
    for (i, raw) in lines.iter().enumerate() {
        let line = raw.split('#').next().unwrap_or("").trim().to_string();
        if line.starts_with('[') {
            if cur == section { section_end = i; }
            cur = line.trim_matches(['[', ']']).to_string();
            if cur == section { section_start = Some(i); }
            continue;
        }
        if cur == section && line.contains('=') {
            let k = line.split('=').next().unwrap().trim().to_string();
            if k == key {
                replace_at = Some(i);
                written = true;
            }
        }
    }
    if let Some(i) = replace_at {
        lines[i] = format!("{key} = \"{value}\"");
    }
    if !written {
        if section_start.is_none() {
            lines.push(String::new());
            lines.push(format!("[{section}]"));
            lines.push(format!("{key} = \"{value}\""));
        } else {
            lines.insert(section_end, format!("{key} = \"{value}\""));
        }
    }
    let tmp = path.with_extension("toml.tmp");
    std::fs::write(&tmp, lines.join("\n") + "\n")
        .map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, &path).map_err(|e| e.to_string())
}

/// Resolve a secret: .env file first, then process environment
/// (parity with Python load_env_key).
pub fn env_key(name: &str) -> Option<String> {
    if let Some(ref_) = name.strip_prefix("omaseal://") {
        let (svc, acct) = ref_.split_once('/')?;
        return Command::new("omaseal")
            .args(["get", svc, acct])
            .output().ok()
            .filter(|o| o.status.success())
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
    }
    if let Ok(v) = std::env::var(name) {
        if !v.is_empty() {
            return Some(v);
        }
    }
    let env_file = cfg_dir().join(".env");
    if let Ok(text) = std::fs::read_to_string(&env_file) {
        let prefix = format!("{name}=");
        for line in text.lines() {
            if let Some(v) = line.strip_prefix(&prefix) {
                return Some(v.trim().trim_matches('"').to_string());
            }
        }
    }
    None
}

pub fn api_key() -> Result<String, String> {
    env_key("OPENROUTER_API_KEY").ok_or_else(|| "no OPENROUTER_API_KEY".into())
}
