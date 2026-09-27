//! Brain layer: Jev typed decisions + chat completions (OpenRouter or
//! any OpenAI-compatible endpoint). Provider-agnostic per requirements:
//! chat_url/chat_model/chat_key come from config so Ollama, LM Studio,
//! MLX (mlx-lm server) and corporate gateways all plug via base_url.
use crate::config::Cfg;
use serde_json::{json, Value};

pub const JEV_URL: &str = "https://openrouter.ai/api/alpha/decisions";
pub const CHAT_URL: &str = "https://openrouter.ai/api/v1/chat/completions";

fn post(url: &str, key: &str, body: &Value) -> Result<Value, String> {
    ureq::post(url)
        .set("Authorization", &format!("Bearer {key}"))
        .set("HTTP-Referer", "https://github.com/duketopceo/dim-agent")
        .set("X-Title", "Dim")
        .timeout(std::time::Duration::from_secs(60))
        .send_json(body)
        .map_err(|e| e.to_string())?
        .into_json::<Value>()
        .map_err(|e| e.to_string())
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
    post(JEV_URL, &key, &body)
}

/// Chat completion. `images` carries base64 jpeg/png data-URLs when the
/// route needs screen context. `tools` = OpenAI-style tool schemas;
/// returns the raw `choices[0].message` so callers can read tool_calls.
pub fn chat(cfg: &Cfg, system: &str, user: &str, session: &str,
            images: &[String], tools: Option<Value>) -> Result<Value, String> {
    let key = crate::config::api_key()?;
    let mut content = vec![json!({"type": "text", "text": user})];
    for img in images {
        content.push(json!({"type": "image_url",
                            "image_url": {"url": img}}));
    }
    let mut sys = system.to_string();
    if !session.is_empty() {
        sys.push_str("\n\nRecent conversation:\n");
        sys.push_str(session);
    }
    let mut body = json!({
        "model": cfg.answer_model,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": content}
        ],
        "max_tokens": 600,
    });
    if let Some(t) = tools {
        body["tools"] = t;
        body["tool_choice"] = json!("auto");
    }
    let resp = post(CHAT_URL, &key, &body)?;
    resp.get("choices")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("message"))
        .cloned()
        .ok_or_else(|| "empty chat response".into())
}
