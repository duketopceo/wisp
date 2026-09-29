//! Brain providers — pluggable chat backends (parity with wisp/brain.py).
//! `[brain] default = "provider:model"` selects the answer brain; each
//! `[brain.<name>]` section declares kind/base_url/key_env/vision/tools.
//! Kinds: openai_compat (OpenRouter, LM Studio, vLLM, MLX, gateways) and
//! ollama (native /api/chat). Jev routing stays on the OpenRouter
//! decisions endpoint — that's the router, not the answer provider.
use crate::config::Cfg;
use serde_json::{json, Value};

pub const JEV_URL: &str = "https://openrouter.ai/api/alpha/decisions";

#[derive(Clone, Debug)]
pub struct Provider {
    pub name: String,
    pub kind: String, // "openai_compat" | "ollama"
    pub base_url: String,
    pub key_env: String,
    pub model: String,
    pub vision: bool,
    pub tools: bool,
}

fn builtin(name: &str) -> Provider {
    let (kind, base_url, key_env, vision, tools) = match name {
        "openrouter" => ("openai_compat",
                         "https://openrouter.ai/api/v1",
                         "OPENROUTER_API_KEY", true, true),
        "ollama" => ("ollama", "http://localhost:11434", "", false, false),
        "lmstudio" => ("openai_compat", "http://localhost:1234/v1",
                       "", false, false),
        "mlx" => ("openai_compat", "http://localhost:8080/v1",
                  "", false, false),
        _ => ("openai_compat", "", "", false, false),
    };
    Provider { name: name.into(), kind: kind.into(),
               base_url: base_url.into(), key_env: key_env.into(),
               model: String::new(), vision, tools }
}

/// Resolve `[brain] default = "name:model"` — parity with Python's
/// provider(): overrides merge from `[brain.<name>]`, legacy
/// agent.answer_model is the fallback model.
pub fn provider(cfg: &Cfg) -> Provider {
    let default = cfg.raw.get("brain")
        .and_then(|b| b.get("default"))
        .and_then(|v| v.as_str()).unwrap_or("");
    // legacy fallback mirrors Python: agent.answer_model from the raw
    // file first, then the typed field
    let legacy = cfg.raw.get("agent")
        .and_then(|a| a.get("answer_model"))
        .and_then(|v| v.as_str()).map(String::from)
        .unwrap_or_else(|| cfg.answer_model.clone());
    let (name, model) = match default.split_once(':') {
        Some((n, m)) => (n.to_string(), m.to_string()),
        None => (
            if default.is_empty() { "openrouter" } else { default }
                .to_string(),
            legacy),
    };
    let mut p = builtin(&name);
    if let Some(sec) = cfg.raw.get("brain").and_then(|b| b.get(&name)) {
        let s = |k: &str| sec.get(k).and_then(|v| v.as_str());
        let b = |k: &str| sec.get(k).and_then(|v| v.as_bool()
            .or_else(|| v.as_str().map(|s| s == "true")));
        if let Some(v) = s("kind") { p.kind = v.into(); }
        if let Some(v) = s("base_url") { p.base_url = v.into(); }
        if let Some(v) = s("key_env") { p.key_env = v.into(); }
        if let Some(v) = b("vision") { p.vision = v; }
        if let Some(v) = b("tools") { p.tools = v; }
    }
    p.model = model;
    p
}

pub fn supports_vision(cfg: &Cfg) -> bool { provider(cfg).vision }
pub fn supports_tools(cfg: &Cfg) -> bool { provider(cfg).tools }

/// Local providers get a fast reachability probe (U6 health probe) —
/// failures are explicit, not silent remote-shaped errors.
fn probe(p: &Provider) -> Result<(), String> {
    if !(p.base_url.starts_with("http://localhost")
         || p.base_url.starts_with("http://127.0.0.1")) {
        return Ok(());
    }
    let url = if p.kind == "ollama" { "/api/tags" } else { "/models" };
    ureq::get(&format!("{}{}", p.base_url.trim_end_matches('/'), url))
        .timeout(std::time::Duration::from_secs(2)).call()
        .map(|_| ())
        .map_err(|e| format!("brain provider '{}' unreachable at {} ({e})",
                             p.name, p.base_url))
}

fn post(url: &str, headers: &[(&str, String)], body: &Value)
        -> Result<Value, String> {
    let mut r = ureq::post(url)
        .set("User-Agent", "wisp/1.0")
        .timeout(std::time::Duration::from_secs(60));
    for (k, v) in headers {
        r = r.set(k, v);
    }
    r.send_json(body).map_err(|e| e.to_string())?
        .into_json::<Value>().map_err(|e| e.to_string())
}

/// Provider-agnostic chat → the message object (OpenAI shape or
/// ollama `message`). Parity with Python brain.chat.
pub fn chat_messages(messages: Value, cfg: &Cfg,
                     tools: Option<Value>) -> Result<Value, String> {
    let p = provider(cfg);
    if p.base_url.is_empty() {
        return Err(format!("brain provider '{}' needs \
                           brain.{}.base_url", p.name, p.name));
    }
    probe(&p)?;
    let base = p.base_url.trim_end_matches('/');
    if p.kind == "ollama" {
        // native /api/chat — images ride on the user message
        let msgs: Vec<Value> = messages.as_array()
            .cloned().unwrap_or_default().into_iter().map(|mut m| {
                if let Some(parts) = m.get("content")
                    .and_then(|c| c.as_array()).cloned() {
                    let text: String = parts.iter()
                        .filter(|c| c.get("type") == Some(&json!("text")))
                        .filter_map(|c| c.get("text")
                            .and_then(|t| t.as_str()).map(String::from))
                        .collect();
                    let imgs: Vec<Value> = parts.iter()
                        .filter(|c| c.get("type")
                            == Some(&json!("image_url")))
                        .filter_map(|c| c.pointer("/image_url/url")
                            .and_then(|u| u.as_str())
                            .and_then(|u| u.split_once(',')
                                .map(|(_, b)| b.to_string())
                                .or_else(|| Some(u.to_string()))))
                        .map(|s| json!(s)).collect();
                    m["content"] = json!(text);
                    if !imgs.is_empty() { m["images"] = json!(imgs); }
                }
                m
            }).collect();
        let mut body = json!({"model": p.model, "messages": msgs,
                              "stream": false});
        if tools.is_some() && p.tools { body["tools"] = tools.unwrap(); }
        let resp = post(&format!("{base}/api/chat"), &[], &body)?;
        return Ok(resp.get("message").cloned().unwrap_or(json!({})));
    }
    let mut headers: Vec<(&str, String)> = vec![];
    if !p.key_env.is_empty() {
        if let Some(k) = crate::config::env_key(&p.key_env) {
            headers.push(("Authorization", format!("Bearer {k}")));
        }
    }
    if p.name == "openrouter" {
        headers.push(("HTTP-Referer",
            "https://github.com/duketopceo/wisp".into()));
        headers.push(("X-Title", "Wisp".into()));
    }
    let mut body = json!({"model": p.model, "messages": messages,
                          "max_tokens": 600});
    if tools.is_some() && p.tools {
        body["tools"] = tools.unwrap();
        body["tool_choice"] = json!("auto");
    }
    let resp = post(&format!("{base}/chat/completions"), &headers, &body)?;
    resp.get("choices").and_then(|c| c.get(0))
        .and_then(|c| c.get("message")).cloned()
        .ok_or_else(|| "empty chat response".into())
}

/// One typed Jev question. kinds: "noul" | "choice" | "score".
/// Parity API — not yet called; the learn/proposal path will use it.
#[allow(dead_code)]
pub fn jev_question(kind: &str, text: &str, criteria: Option<Value>) -> Value {
    let mut q = json!({"type": kind, "question": text});
    if let Some(c) = criteria {
        q["criteria"] = c;
    }
    q
}

pub fn ask_jev(cfg: &Cfg, transcript: &str, context: &str,
               questions: Value) -> Result<Value, String> {
    let key = crate::config::api_key()?;
    // parity: Python sends `state` as a text blob, not an object
    let state_txt = if context.is_empty() {
        format!("The user said: \"{transcript}\"")
    } else {
        format!("{context}\n\nThe user said: \"{transcript}\"")
    };
    let body = json!({
        "model": cfg.model,
        "state": state_txt,
        "questions": questions,
    });
    post(JEV_URL, &[("Authorization", format!("Bearer {key}"))], &body)
}

/// Chat completion built from parts — the convenience shape ask_chat
/// uses. `images` carries base64 data-URLs and is dropped when the
/// provider lacks vision (U6 capability gating).
pub fn chat(cfg: &Cfg, system: &str, user: &str, session: &str,
            images: &[String], tools: Option<Value>) -> Result<Value, String> {
    let mut content = vec![json!({"type": "text", "text": user})];
    if supports_vision(cfg) {
        for img in images {
            content.push(json!({"type": "image_url",
                                "image_url": {"url": img}}));
        }
    }
    let mut sys = system.to_string();
    if !session.is_empty() {
        sys.push_str("\n\nRecent conversation:\n");
        sys.push_str(session);
    }
    chat_messages(
        json!([{"role": "system", "content": sys},
               {"role": "user", "content": content}]), cfg, tools)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg_with(toml_text: &str) -> Cfg {
        let mut c = crate::config::load();
        c.raw = toml::from_str(toml_text)
            .unwrap_or(toml::Value::Table(Default::default()));
        c
    }

    #[test]
    fn provider_parsing() {
        let c = cfg_with("[brain]\ndefault=\"ollama:llama3.1\"");
        let p = provider(&c);
        assert_eq!(p.name, "ollama");
        assert_eq!(p.model, "llama3.1");
        assert_eq!(p.kind, "ollama");
        assert_eq!(p.base_url, "http://localhost:11434");
    }

    #[test]
    fn fallback_legacy_answer_model() {
        let c = cfg_with("[agent]\nanswer_model=\"foo/bar\"");
        let p = provider(&c);
        assert_eq!(p.name, "openrouter");
        assert_eq!(p.model, "foo/bar");
        assert!(p.vision && p.tools);
    }

    #[test]
    fn custom_section_overrides() {
        let c = cfg_with(
            "[brain]\ndefault=\"vllm:qwen\"\n\
             [brain.vllm]\nkind=\"openai_compat\"\n\
             base_url=\"http://gpu:8000/v1\"\nvision=true\ntools=true");
        let p = provider(&c);
        assert_eq!(p.base_url, "http://gpu:8000/v1");
        assert!(p.vision && p.tools);
    }
}
