//! Listen cycle: record -> whisper -> route (Jev|chat) -> execute.
//! Parity with dim/pipeline.py, incl. timing_ms + decisions.jsonl.
use crate::{brain, config::Cfg, learn, memory, recall, session,
            state::State, tools};
use serde_json::{json, Value};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// Shared choice channel for await_choice / act-confirm.
pub struct ChoiceCtl {
    pub pick: Mutex<String>,
    pub event: std::sync::Condvar,
}

impl ChoiceCtl {
    pub fn wait(&self, timeout_secs: u64) -> Option<String> {
        let mut g = self.pick.lock().unwrap();
        *g = String::new();
        let (g, timeout) = self
            .event
            .wait_timeout(g, std::time::Duration::from_secs(timeout_secs))
            .unwrap();
        if timeout.timed_out() || g.is_empty() {
            None
        } else {
            Some(g.clone())
        }
    }
    pub fn set(&self, pick: &str) {
        *self.pick.lock().unwrap() = pick.to_string();
        self.event.notify_all();
    }
}

pub fn build_questions(cfg: &Cfg) -> Value {
    // parity with dim/pipeline.py::JEV_QUESTIONS
    let tools_desc: serde_json::Map<String, Value> = tools::describe()
        .iter()
        .map(|(n, d)| (n.clone(), json!(d)))
        .collect();
    json!({
        "route": {"type": "choice",
            "instructions": "What kind of request is this?",
            "criteria": {
                "launch": "open, start, or close an application",
                "tool": "a desktop/system action — window ops, workspace switch, type text, screenshot, notify, run a command, find files",
                "agent": "spawn a background agent for a coding, research, or multi-step task — phrases like 'agent', 'have an agent', 'spawn', 'delegate'",
                "learn": "the user wants Dim to learn or remember how to do something — 'learn X', 'remember this', 'add a skill for'",
                "act": "a multi-step desktop task — do several things, or imperative instructions like 'open X and go to workspace 2' or 'type this into the window'",
                "answer": "the user is asking a question or chatting — respond in text, no desktop action",
                "clarify": "the request is too ambiguous to act on",
            }},
        "app": {"type": "choice",
            "instructions": "Which application is the user asking about? Choose 'none' if the user is asking a question, chatting, or not requesting an app.",
            "criteria": app_criteria(cfg)},
        "action": {"type": "choice",
            "instructions": "What should be done?",
            "criteria": {
                "launch": "open or start it",
                "close": "close or quit it",
                "type_text": "type some text",
                "run_shell": "run a shell command",
                "answer": "respond to the user in text — questions, chat, or anything that is not a desktop action",
            }},
        "risk": {"type": "score",
            "instructions": "0 read-only launch, 2 mutating",
            "criteria": ["read-only", "navigational", "mutating"]},
        "tool": {"type": "choice",
            "instructions": "Which tool should run? Only relevant when the route is 'tool'.",
            "criteria": tools_desc},
        "needs_screen": {"type": "noul",
            "instructions": "Does fulfilling this request require seeing what is on the screen — reading an error, describing a window, referencing visible content?"}
    })
}

fn app_criteria(_cfg: &Cfg) -> Value {
    // parity with build_questions in dim/pipeline.py: harness catalog
    // when present (with frequency hints), else the static map
    const NONE: &str = "no application — the user is asking a question, \
                        chatting, or the request is unclear";
    let mut c = serde_json::Map::new();
    let h = crate::config::data_dir().join("harness.json");
    let mut used_harness = false;
    if let Ok(v) = std::fs::read_to_string(&h)
        .and_then(|t| serde_json::from_str::<Value>(&t)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e)))
    {
        if let Some(apps) = v.get("apps").and_then(|a| a.as_object()) {
            used_harness = true;
            for (k, a) in apps {
                let mut s = a.get("cues").and_then(|x| x.as_str())
                    .unwrap_or(k).to_string();
                if a.get("seen").and_then(|x| x.as_i64()).unwrap_or(0) >= 5 {
                    s += &format!(" (frequently used: {}x)",
                                  a["seen"].as_i64().unwrap());
                }
                c.insert(k.clone(), json!(s));
            }
        }
    }
    if !used_harness {
        for (k, d) in [
            ("none", NONE),
            ("browser", "user wants a web browser or a website"),
            ("terminal", "user wants a terminal or shell"),
            ("files", "user wants a file manager"),
            ("vscode", "user wants the code editor"),
            ("music", "user wants a music player"),
            ("settings", "user wants system settings"),
            ("browser_new_tab", "user wants a new browser tab"),
        ] {
            c.insert(k.into(), json!(d));
        }
    } else {
        c.insert("none".into(), json!(NONE));
    }
    learn::apply_overrides(&mut c);
    json!(c)
}

fn notify(msg: &str) {
    Command::new("notify-send").args(["Dim", msg]).spawn().ok();
}

/// Breathing darkness: sample mic RMS via arecord, publish `level` for
/// the overlay — parity with dim/pipeline.py::_amplitude_sampler.
fn amplitude_sampler(seconds: u64, st: Arc<State>) {
    if !tools::which("arecord") {
        return;
    }
    use std::io::Read;
    let mut proc = match Command::new("arecord")
        .args(["-D", "default", "-f", "U8", "-r", "200", "-c", "1",
               "-d", &seconds.to_string()])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(p) => p,
        Err(_) => return,
    };
    let Some(mut out) = proc.stdout.take() else { return };
    let mut chunk = [0u8; 200];
    while let Ok(n) = out.read(&mut chunk) {
        if n == 0 {
            break;
        }
        for w in chunk[..n.saturating_sub(19)].chunks(20) {
            let rms: f64 = w.iter()
                .map(|b| (*b as i32 - 128).unsigned_abs() as f64)
                .sum::<f64>() / (w.len() * 128) as f64;
            st.set_level((rms * 6.0).min(1.0));
        }
    }
    let _ = proc.wait();
}

fn record(cfg: &Cfg, st: &Arc<State>) -> Result<std::path::PathBuf, String> {
    // keep wav under the user-only config dir — /tmp is
    // shared/predictable (Python uses CFG_DIR too)
    let dir = crate::config::cfg_dir();
    std::fs::create_dir_all(&dir).ok();
    let out = dir.join("utterance.wav");
    let secs = cfg.audio_seconds;
    let sampler_st = st.clone();
    std::thread::spawn(move || amplitude_sampler(secs as u64, sampler_st));
    let rec = if tools::which("pw-record") {
        crate::util::run_timeout(
            Command::new("pw-record")
                .args(["--rate", "16000", "--channels", "1",
                       "--format", "s16",
                       "--sample-count",
                       &format!("{}", 16000 * secs)])
                .arg(&out),
            secs as u64 + 10)  // Python: timeout=seconds+10
    } else if tools::which("arecord") {
        crate::util::run_timeout(
            Command::new("arecord")
                .args(["-D", "default", "-r", "16000", "-c", "1",
                       "-f", "S16_LE", "-d", &secs.to_string()])
                .arg(&out),
            secs as u64 + 10)
    } else {
        return Err("no pw-record or arecord found".into());
    };
    // pw-record exits 1 on clean --sample-count shutdown (pipewire
    // 1.6.x) — trust the output file, not the exit code (Python parity)
    let _ = rec;
    std::thread::sleep(std::time::Duration::from_millis(300));
    st.set_level(0.0);
    let ok = std::fs::metadata(&out).map(|m| m.len() > 44).unwrap_or(false);
    if ok { Ok(out) } else {
        Err(format!("recording produced no audio: {}", out.display()))
    }
}

fn transcribe(wav: &std::path::Path, cfg: &Cfg) -> Result<String, String> {
    if !cfg.whisper_bin.exists() || !cfg.whisper_model.exists() {
        return Err(format!("whisper.cpp missing: {} / {}",
                           cfg.whisper_bin.display(),
                           cfg.whisper_model.display()));
    }
    let out = crate::util::run_timeout(
        Command::new(&cfg.whisper_bin)
            .args(["-m"])
            .arg(&cfg.whisper_model)
            .args(["-nt", "-f"])
            .arg(wav),
        120)  // Python: subprocess.run(timeout=120)
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "whisper timed out".to_string())?;
    Ok(String::from_utf8_lossy(&out.stdout).split_whitespace()
        .collect::<Vec<_>>().join(" "))
}

fn log_decision(rec: &Value) {
    let f = crate::config::data_dir().join("decisions.jsonl");
    if let Some(p) = f.parent() {
        std::fs::create_dir_all(p).ok();
    }
    if let Ok(mut file) = std::fs::OpenOptions::new().append(true).create(true).open(f) {
        use std::io::Write;
        let _ = writeln!(file, "{}", serde_json::to_string(rec).unwrap());
    }
}



fn capture_screen_b64() -> Option<String> {
    if !tools::which("grim") {
        return None;
    }
    let dir = crate::config::runtime_dir();
    std::fs::create_dir_all(&dir).ok();
    let f = dir.join("screen.png");
    let ok = crate::util::run_timeout(
        Command::new("grim").arg(&f), 10)
        .map(|o| o.map(|x| x.status.success()).unwrap_or(false))
        .unwrap_or(false);
    if !ok {
        return None;
    }
    let bytes = std::fs::read(&f).ok()?;
    std::fs::remove_file(&f).ok();  // Python unlinks after reading
    Some(format!("data:image/png;base64,{}", base64::Engine::encode(
        &base64::engine::general_purpose::STANDARD, bytes)))
}

fn is_low_confidence(answers: &Value, cfg: &Cfg) -> bool {
    // parity: Python gates on the app question's own confidence field
    answers.get("app").and_then(|a| a.get("confidence"))
        .and_then(|v| v.as_f64())
        .map(|s| s < cfg.confidence_ambiguous)
        .unwrap_or(false)
}

/// Canned reply when the answer model fails — parity with
/// dim/pipeline.py::answer_text.
fn canned_reply(transcript: &str) -> String {
    let low = transcript.to_lowercase();
    if low.contains("what can") || low.contains("help")
        || low.contains("commands") {
        return "Try \"open discord\", \"screenshot\", \
                \"go to workspace 2\", or \"agent, research X\" — \
                I route to apps, tools, and agents.".into();
    }
    format!("You said: \"{transcript}\". Not a desktop action I can take yet.")
}

fn ask_chat(transcript: &str, cfg: &Cfg, session: &str,
            needs_screen: bool) -> Result<String, String> {
    let img = if needs_screen && cfg.screenshots {
        capture_screen_b64().into_iter().collect::<Vec<_>>()
    } else {
        vec![]
    };
    let mut system = "You are Dim, a terse desktop voice assistant. Answer in \
                  one or two short sentences, plain speech, no markdown."
        .to_string();
    if !img.is_empty() {
        system.push_str(
            " A screenshot of the user's screen is attached. Describe what \
             is relevant to the question. When the user asks where \
             something is or where to click, point at it: append one or \
             more tags like [POINT:x,y:label] using the screenshot's pixel \
             coordinates, or for a multi-step sequence \
             [POINTS:[{\"x\":x,\"y\":y,\"label\":\"step\"}]]. Keep the \
             spoken text free of the tags; they render as an overlay.");
    }
    let block = memory::context_block("");
    if !block.is_empty() {
        system.push_str(&format!("\n\n{block}"));
    }
    brain::chat(cfg, &system, transcript, session, &img, None)
        .and_then(|m| m.get("content").and_then(|c| c.as_str())
            .map(|s| s.trim().to_string())
            .ok_or_else(|| "empty chat reply".to_string()))
}

/// Bounded tool-call loop — parity with dim/act.py.
fn act_loop(task: &str, cfg: &Cfg, st: &State, ctl: &ChoiceCtl) -> String {
    const MAX_STEPS: usize = 8;
    const MAX_ERRORS: u32 = 2;
    let system = "You are Dim's hands on a Linux desktop (Hyprland). \
                  Complete the user's task using the provided tools — \
                  keep steps minimal and prefer safe tools. When done, \
                  reply with one short sentence. If a tool is refused or \
                  skipped, do not retry it; work around or report.";
    let mut messages = vec![
        json!({"role": "system", "content": system}),
        json!({"role": "user", "content": task}),
    ];
    let mut steps: Vec<(String, String, String)> = vec![];
    let mut errors = 0u32;

    while steps.len() < MAX_STEPS {
        // rebuild request each round from message log
        let key = match crate::config::api_key() {
            Ok(k) => k,
            Err(e) => return format!("ABORTED (no key: {e})"),
        };
        let body = json!({"model": cfg.answer_model, "messages": messages,
                          "tools": tools::tool_schemas(),
                          "tool_choice": "auto", "max_tokens": 400});
        let resp = ureq::post(brain::CHAT_URL)
            .set("Authorization", &format!("Bearer {key}"))
            .timeout(std::time::Duration::from_secs(60))
            .send_json(&body);
        let data: Value = match resp {
            Ok(r) => match r.into_json() {
                Ok(v) => v,
                Err(e) => return format!("ABORTED (bad json: {e})"),
            },
            Err(e) => return format!("ABORTED (http: {e})"),
        };
        let msg = data.get("choices").and_then(|c| c.get(0))
            .and_then(|c| c.get("message")).cloned().unwrap_or(json!({}));
        let calls = msg.get("tool_calls").and_then(|t| t.as_array())
            .cloned().unwrap_or_default();
        if calls.is_empty() {
            let text = msg.get("content").and_then(|c| c.as_str())
                .unwrap_or("").trim().to_string();
            return format!("ACTED ({} steps): {}", steps.len(),
                           if text.is_empty() { "done".into() } else { text });
        }
        messages.push(msg.clone());
        for call in calls {
            let f = call.get("function").cloned().unwrap_or(json!({}));
            let name = f.get("name").and_then(|v| v.as_str())
                .unwrap_or("").to_string();
            let arg = f.get("arguments").and_then(|a| a.as_str())
                .and_then(|a| serde_json::from_str::<Value>(a).ok())
                .and_then(|v| v.get("arg").and_then(|a| a.as_str())
                    .map(String::from))
                .unwrap_or_default();
            // gate — same order as Python: denylist, allow_shell, confirm
            let tier = tools::risk_of(&name);
            let result = if tier == "shell" && tools::denied(&arg) {
                "REFUSED (denylisted command)".to_string()
            } else if tier == "shell" && !cfg.allow_shell {
                "SKIPPED (shell disabled — set allow_shell=true)".to_string()
            } else if matches!(tier, "mutating" | "shell") {
                st.transition("awaiting_choice", &[
                    ("choices", json!([format!("run {name}: {arg} — yes"), "no"]))]);
                match ctl.wait(30) {
                    Some(pick) if pick.contains("yes") => {
                        st.transition("acting", &[("choices", json!([]))]);
                        tools::run(&name, &arg, cfg)
                    }
                    _ => {
                        st.transition("acting", &[("choices", json!([]))]);
                        format!("SKIPPED ({name} declined by user)")
                    }
                }
            } else {
                tools::run(&name, &arg, cfg)
            };
            steps.push((name.clone(), arg.clone(), result.clone()));
            st.transition("acting", &[(
                "result", json!(format!("act step {}: {name}", steps.len())))]);
            if result.starts_with("ERROR") || result.starts_with("SKIP")
                || result.starts_with("REFUS") {
                errors += 1;
            } else {
                errors = 0;
            }
            messages.push(json!({"role": "tool",
                "tool_call_id": call.get("id").and_then(|v| v.as_str())
                    .unwrap_or(""),
                "content": result}));
            if errors > MAX_ERRORS {
                return format!("ABORTED (repeated failures): {}",
                    tail(&steps));
            }
            if steps.len() >= MAX_STEPS {
                break;
            }
        }
    }
    format!("ABORTED (max {MAX_STEPS} steps): {}", tail(&steps))
}

fn tail(steps: &[(String, String, String)]) -> String {
    steps.iter().rev().take(3).rev()
        .map(|(n, _, r)| format!("{n}→{r}"))
        .collect::<Vec<_>>().join("; ")
}

/// Full listen cycle — contract states: listening→transcribing→deciding
/// →(awaiting_choice)→acting→done|error.
pub fn run_listen(cfg: &Cfg, st: &Arc<State>, ctl: &ChoiceCtl,
                  running: Arc<AtomicBool>) -> i32 {
    let t0 = Instant::now();
    let mut timing = serde_json::Map::new();
    let result: Result<String, String> = (|| {
        st.transition("listening", &[
            ("transcript", json!("")), ("result", json!("")),
            ("answer", json!("")), ("choices", json!([])),
            ("points", json!([])), ("error", json!(""))]);
        let wav = record(cfg, st)?;
        timing.insert("record_ms".into(), json!(t0.elapsed().as_millis()));
        st.transition("transcribing", &[]);
        let text = transcribe(&wav, cfg)?;
        timing.insert("stt_ms".into(),
                      json!(t0.elapsed().as_millis()
                            - timing["record_ms"].as_u64().unwrap_or(0) as u128));
        st.transition("deciding", &[("transcript", json!(text.clone()))]);
        if text.is_empty() || text.contains("[BLANK") {
            st.transition("done", &[("result", json!("heard nothing"))]);
            return Ok("heard nothing".into());
        }
        if !running.load(Ordering::Relaxed) {
            return Err("stopping".into());
        }

        // route: jev (default) | chat (straight to answer model) | off
        let mut context = active_window_text();
        let session_text = session::as_text(&session::tail(cfg.session_turns));
        if !session_text.is_empty() {
            context.push_str(&format!("\nRecent conversation:\n{session_text}"));
        }
        let block = memory::context_block(&text);
        if !block.is_empty() {
            context.push_str(&format!("\n{block}"));
        }
        let answers = match cfg.router.as_str() {
            "chat" => json!({"route": {"choice": "answer"},
                            "needs_screen": {"noul": 1.0}}),
            "off" => json!({"route": {"choice": "clarify"}}),
            _ => brain::ask_jev(cfg, &text, &context, build_questions(cfg))?
                .get("answers").cloned().unwrap_or(json!({})),
        };
        timing.insert("jev_ms".into(),
                      json!(t0.elapsed().as_millis()
                            - timing["record_ms"].as_u64().unwrap_or(0) as u128
                            - timing["stt_ms"].as_u64().unwrap_or(0) as u128));

        // low-confidence → choice prompt (parity: labels are
        // app:X / action:Y from each question's probabilities)
        let mut answers = answers;
        let low_conf = is_low_confidence(&answers, cfg);
        let mut corrected = false;
        if low_conf {
            let top3 = |q: &str| -> Vec<String> {
                let mut v: Vec<(String, f64)> = answers
                    .pointer(&format!("/{q}/probabilities"))
                    .and_then(|p| p.as_object())
                    .map(|m| m.iter()
                        .map(|(k, x)| (k.clone(),
                                       x.as_f64().unwrap_or(0.0)))
                        .collect())
                    .unwrap_or_default();
                v.sort_by(|a, b| b.1.partial_cmp(&a.1)
                    .unwrap_or(std::cmp::Ordering::Equal));
                v.into_iter().take(3).map(|(k, _)| k).collect()
            };
            let labels: Vec<String> = top3("app").into_iter()
                .map(|k| format!("app:{k}"))
                .chain(top3("action").into_iter()
                    .map(|k| format!("action:{k}")))
                .collect();
            if !labels.is_empty() {
                st.transition("awaiting_choice",
                              &[("choices", json!(labels))]);
                let pick = ctl.wait(30);
                st.transition("acting", &[("choices", json!([]))]);
                if let Some(pick) = pick {
                    // apply_choice: rewrite the app or action choice
                    let value = pick.split_once(':')
                        .map(|(_, v)| v).unwrap_or("");
                    if let Some(a) = answers.get_mut(
                            if pick.starts_with("app:") { "app" }
                            else { "action" }) {
                        a["choice"] = json!(value);
                    }
                    answers["corrected_by_user"] = json!(true);
                    corrected = true;
                    learn::record_correction(&text, &pick, &answers);
                    recall::index_correction(&text, &pick);
                }
            }
        }
        if low_conf && !corrected {
            let r = "CANCELLED (low confidence, no pick made)".to_string();
            st.transition("done", &[("result", json!(r))]);
            notify(&r);
            log_decision(&json!({"ts": crate::state::now_iso(),
                "transcript": text, "answers": answers,
                "result": r, "corrected": false}));
            return Ok(r);
        }

        st.transition("acting", &[]);
        // execute() — parity with dim/pipeline.py route-aware dispatch.
        // Risk gate applies to mutating work only; a plain launch or a
        // text answer is never blocked (Jev's launch score band straddles
        // the navigational/mutating line).
        let route = answers.pointer("/route/choice")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        let action = answers.pointer("/action/choice")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        let app = answers.pointer("/app/choice")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        let risk = answers.pointer("/risk/score")
            .and_then(|v| v.as_f64()).unwrap_or(2.0);
        let gated = !matches!(route.as_str(), "launch" | "answer")
            && !matches!(action.as_str(), "launch" | "answer");

        let res = if gated && risk > cfg.risk_threshold {
            format!("BLOCKED (risk={risk:.2} > {})", cfg.risk_threshold)
        } else if route == "agent" {
            crate::agents::spawn(
                if !text.is_empty() { &text } else { &app })
        } else if route == "act" {
            act_loop(&text, cfg, st, ctl)
        } else if route == "learn" {
            act_loop(&format!(
                "Author a reusable skill for this request using the \
                 skill_manage and skill_view tools. If a skill on this \
                 topic already exists, view it and fold improvements in \
                 with edit; otherwise create it. Keep the SKILL.md body \
                 concise and procedural. Request: {text}"),
                cfg, st, ctl)
        } else if route == "tool" {
            let name = answers.pointer("/tool/choice")
                .and_then(|v| v.as_str()).unwrap_or("");
            let tier = tools::risk_of(name);
            if tier == "shell" && tools::denied(&text) {
                "REFUSED (denylisted command)".into()
            } else if tier == "shell" && !cfg.allow_shell {
                "BLOCKED (shell tool needs allow_shell=true in config)".into()
            } else if tier == "mutating" && risk > cfg.risk_threshold {
                format!("BLOCKED (tool {name:?} needs confirmation)")
            } else if tier == "safe" || risk <= cfg.risk_threshold {
                tools::run(name, &text, cfg)
            } else {
                format!("BLOCKED (tool {name:?} needs confirmation)")
            }
        } else if route == "answer" || action == "answer" || app == "none" {
            // screen_b64 parity: screenshot when needs>=0.7 or the
            // answer route fired
            let needs = route == "answer"
                || answers.pointer("/needs_screen/noul")
                    .and_then(|v| v.as_f64()).unwrap_or(0.0) >= 0.7;
            let (reply, result) = match ask_chat(&text, cfg,
                                               &session_text, needs) {
                Ok(r) => (r, "ANSWERED".to_string()),
                Err(e) => (canned_reply(&text),
                           format!("ANSWER_FAILED ({e})")),
            };
            let (reply, pts) = crate::points::extract(&reply);
            let pts = if pts.is_empty() {
                pts
            } else {
                crate::points::to_logical(&pts, &crate::points::monitors())
            };
            st.transition("done", &[("result", json!(result.clone())),
                                    ("answer", json!(reply.clone())),
                                    ("points", json!(pts))]);
            if cfg.voice_out {
                speak(&reply);
            }
            session::append_turn(&text, &route, &reply, &result);
            recall::index_turn(&text, &reply, &result);
            timing.insert("act_ms".into(), json!(t0.elapsed().as_millis()));
            log_decision(&json!({"ts": crate::state::now_iso(),
                "transcript": text, "answers": answers, "result": result,
                "timing_ms": timing, "corrected": corrected}));
            notify(&result);
            return Ok(result);
        } else if route == "launch" || action == "launch" {
            tools::run("launch", &app, cfg)
        } else if tools::get(&action).is_some() {
            tools::run(&action, &text, cfg)
        } else {
            format!("SKIP (route={route:?} action={action:?} unhandled)")
        };
        session::append_turn(&text, &route, "", &res);
        recall::index_turn(&text, "", &res);
        st.transition("done", &[("result", json!(res.clone()))]);
        timing.insert("act_ms".into(), json!(t0.elapsed().as_millis()));
        log_decision(&json!({"ts": crate::state::now_iso(),
            "transcript": text, "answers": answers, "result": res,
            "timing_ms": timing, "corrected": corrected}));
        Ok(res)
    })();

    match result {
        Ok(r) => {
            notify(&r);
            0
        }
        Err(e) => {
            st.transition("error", &[("error", json!(e.clone()))]);
            log_decision(&json!({"ts": crate::state::now_iso(),
                "result": format!("ERROR ({e})"),
                "timing_ms": timing}));
            notify(&format!("error: {e}"));
            1
        }
    }
}

fn speak(msg: &str) {
    let bin = if tools::which("espeak-ng") { "espeak-ng" }
        else if tools::which("espeak") { "espeak" } else { return };
    Command::new(bin).arg(msg).spawn().ok();
}

fn active_window_text() -> String {
    let out = Command::new("hyprctl").args(["activewindow", "-j"])
        .output().ok();
    out.and_then(|o| serde_json::from_str::<Value>(
        &String::from_utf8_lossy(&o.stdout)).ok())
        .map(|w| format!("Active window: {} — {}",
            w.get("class").and_then(|v| v.as_str()).unwrap_or(""),
            w.get("title").and_then(|v| v.as_str()).unwrap_or("")))
        .unwrap_or_default()
}
