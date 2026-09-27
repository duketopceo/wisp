//! dimd — Dim companion core daemon (Rust parity port).
//! Contract: docs/IPC_CONTRACT.md. CLI mirrors the Python `dimd`.
mod agents;
mod brain;
mod config;
mod harness;
mod ipc;
mod learn;
mod memory;
mod pipeline;
mod points;
mod recall;
mod session;
mod skills;
mod state;
mod tools;
mod util;

use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

fn main() {
    let cmd = std::env::args().nth(1).unwrap_or_default();
    let code = match cmd.as_str() {
        "daemon" => daemon(),
        "trigger" => client(&json!({"cmd": "listen"}), true),
        "status" => client(&json!({"cmd": "status"}), false),
        "stop" => client(&json!({"cmd": "stop"}), false),
        "choice" => {
            let pick = std::env::args().nth(2).unwrap_or_default();
            client(&json!({"cmd": "choice", "pick": pick}), false)
        }
        "task_status" => {
            let n = std::env::args().nth(2).unwrap_or_default();
            client(&json!({"cmd": "task_status", "name": n}), false)
        }
        "task_cancel" => {
            let n = std::env::args().nth(2).unwrap_or_default();
            client(&json!({"cmd": "task_cancel", "name": n}), false)
        }
        "learn" => {
            let p = learn::weekly(7);
            if p.is_empty() { println!("nothing to propose"); }
            else { println!("{p}"); }
            0
        }
        "harness" => match harness::build() {
            Ok(s) => { println!("{s}"); 0 }
            Err(e) => { eprintln!("{e}"); 1 }
        }
        "backfill" => { println!("{}", recall::backfill()); 0 }
        "config" => {
            // `dimd config` → IPC get; `dimd config set section.key v`
            // → IPC set first, local write only when the daemon is down
            // (parity with the Python CLI).
            let args: Vec<String> = std::env::args().skip(2).collect();
            if args.first().map(|s| s.as_str()) == Some("set") {
                if args.len() < 3 {
                    eprintln!("usage: dimd config set section.key value");
                    std::process::exit(2);
                }
                let k = &args[1];
                let v = &args[2];
                if ipc::alive(&config::sock_file()) {
                    match ipc::send(&config::sock_file(),
                                    &json!({"cmd": "config",
                                            "set": {k: v}})) {
                        Ok(r) if r.get("ok") == Some(&json!(true)) => {}
                        Ok(r) => {
                            eprintln!("error: {}",
                                r.get("error")
                                    .and_then(|e| e.as_str())
                                    .unwrap_or("config set failed"));
                            std::process::exit(1);
                        }
                        Err(e) => { eprintln!("error: {e}");
                                    std::process::exit(1); }
                    }
                } else {
                    let (sec, key) =
                        k.split_once('.').unwrap_or(("", ""));
                    if let Err(e) = config::set_config(sec, key, v) {
                        eprintln!("error: {e}");
                        std::process::exit(1);
                    }
                }
                println!("{k} = {v}");
                0
            } else if ipc::alive(&config::sock_file()) {
                match ipc::send(&config::sock_file(),
                                &json!({"cmd": "config"})) {
                    Ok(r) => {
                        println!("{}", serde_json::to_string_pretty(
                            r.get("config").unwrap_or(&json!({}))).unwrap());
                        0
                    }
                    Err(e) => { eprintln!("dimd unreachable: {e}"); 1 }
                }
            } else {
                println!("{}", serde_json::to_string_pretty(
                    &flat_config(&config::load().raw)).unwrap());
                0
            }
        }
        _ => {
            eprintln!("usage: dimd [daemon|trigger|status|stop|choice|task_status|task_cancel|learn|harness|config [set k v]]");
            2
        }
    };
    std::process::exit(code);
}

fn client(cmd: &Value, spawn_if_down: bool) -> i32 {
    let sock = config::sock_file();
    if !ipc::alive(&sock) {
        if !spawn_if_down {
            eprintln!("dimd not running");
            return 1;
        }
        // inline fallback: run the listen cycle in-process (Python parity)
        let cfg = config::load();
        let st = Arc::new(state::State::new(config::state_file()));
        let ctl = pipeline::ChoiceCtl {
            pick: std::sync::Mutex::new(String::new()),
            event: std::sync::Condvar::new(),
        };
        let running = Arc::new(AtomicBool::new(true));
        return pipeline::run_listen(&cfg, &st, &ctl, running);
    }
    match ipc::send(&sock, cmd) {
        Ok(resp) => {
            if let Some(s) = resp.get("state") {
                println!("{}", serde_json::to_string_pretty(s).unwrap());
            } else if let Some(r) = resp.get("result") {
                println!("{}", r.as_str().unwrap_or(""));
            } else {
                println!("{}", serde_json::to_string(&resp).unwrap());
            }
            0
        }
        Err(e) => {
            eprintln!("error: {e}");
            1
        }
    }
}

fn daemon() -> i32 {
    let cfg = config::load();
    let st = Arc::new(state::State::new(config::state_file()));
    let running = Arc::new(AtomicBool::new(true));
    let busy = Arc::new(AtomicBool::new(false));
    let ctl = Arc::new(pipeline::ChoiceCtl {
        pick: std::sync::Mutex::new(String::new()),
        event: std::sync::Condvar::new(),
    });

    let st_h = st.clone();
    let running_h = running.clone();
    let busy_h = busy.clone();
    let ctl_h = ctl.clone();
    let cfg_h2 = Arc::new(std::sync::Mutex::new(cfg));
    let cfg_h = cfg_h2.clone();

    let handler = Arc::new(move |cmd: Value| -> Value {
        match cmd.get("cmd").and_then(|c| c.as_str()).unwrap_or("") {
            "status" => {
                // refresh tasks + republish state.json — Python dimd
                // calls st.transition(st.status) here
                let cur = st_h.status();
                st_h.transition(&cur, &[("tasks", agents::tasks())]);
                json!({"ok": true, "state": st_h.snapshot()})
            }
            "listen" => {
                if busy_h.swap(true, Ordering::SeqCst) {
                    return json!({"ok": false, "error": "busy"});
                }
                let st2 = st_h.clone();
                let cfg2 = cfg_h.clone();
                let ctl2 = ctl_h.clone();
                let running2 = running_h.clone();
                let busy2 = busy_h.clone();
                std::thread::spawn(move || {
                    let cfg_guard = cfg2.lock().unwrap().clone();
                    pipeline::run_listen(&cfg_guard, &st2, &ctl2, running2);
                    busy2.store(false, Ordering::SeqCst);
                });
                json!({"ok": true})
            }
            "choice" => {
                let pick = cmd.get("pick").and_then(|v| v.as_str()).unwrap_or("");
                ctl_h.set(pick);
                json!({"ok": true})
            }
            "task_status" => {
                let n = cmd.get("name").and_then(|v| v.as_str()).unwrap_or("");
                json!({"ok": true, "result": agents::status(n)})
            }
            "task_cancel" => {
                let n = cmd.get("name").and_then(|v| v.as_str()).unwrap_or("");
                json!({"ok": true, "result": agents::cancel(n)})
            }
            "learn" => {
                let p = learn::weekly(7);
                json!({"ok": true, "result": if p.is_empty() {
                    "nothing to propose".into() } else { p }})
            }
            "harness" => match harness::build() {
                Ok(s) => json!({"ok": true, "result": s}),
                Err(e) => json!({"ok": false, "error": e}),
            },
            "config" => {
                if let Some(set) = cmd.get("set").and_then(|v| v.as_object()) {
                    for (k, v) in set {
                        let (sec, key) = k.split_once('.').unwrap_or(("", ""));
                        if sec.is_empty() || key.is_empty() {
                            return json!({"ok": false,
                                "error": "config keys must be section.key"});
                        }
                        if let Err(e) = config::set_config(sec, key,
                                v.as_str().unwrap_or(&v.to_string())) {
                            return json!({"ok": false, "error": e});
                        }
                    }
                    *cfg_h2.lock().unwrap() = config::load();
                }
                // parity with Python: section -> {key: string} flat map
                json!({"ok": true,
                       "config": flat_config(&cfg_h2.lock().unwrap().raw)})
            }
            "stop" => {
                running_h.store(false, Ordering::SeqCst);
                json!({"ok": true})
            }
            c => json!({"ok": false, "error": format!("unknown cmd '{c}'")}),
        }
    });

    println!("dimd-rs listening on {}", config::sock_file().display());
    if let Err(e) = ipc::serve(config::sock_file(), handler, running.clone()) {
        eprintln!("serve error: {e}");
        return 1;
    }
    0
}

/// Flatten the parsed TOML config into section -> {key: string} — the
/// shape Python's flat parser returns over IPC (all values strings).
fn flat_config(raw: &toml::Value) -> Value {
    let mut out = serde_json::Map::new();
    if let Some(t) = raw.as_table() {
        for (sec, kv) in t {
            let mut sect = serde_json::Map::new();
            if let Some(m) = kv.as_table() {
                for (k, v) in m {
                    let s = match v {
                        toml::Value::String(s) => s.clone(),
                        toml::Value::Boolean(b) => b.to_string(),
                        other => other.to_string().trim_matches('"')
                            .to_string(),
                    };
                    sect.insert(k.clone(), json!(s));
                }
            }
            out.insert(sec.clone(), Value::Object(sect));
        }
    }
    Value::Object(out)
}

#[cfg(test)]
mod tests {
    //! Single test fn: HOME/XDG env is process-global, so all
    //! file-level contract checks live in one serial test.
    #[test]
    fn memory_recall_skills_contract() {
        let tmp = std::env::temp_dir()
            .join(format!("dimd-ut-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("HOME", &tmp);
        std::env::set_var("XDG_RUNTIME_DIR", &tmp);

        // memory: add/replace/remove + snapshot
        assert!(crate::memory::run("memory|add|prefers vim")
            .starts_with("OK"));
        assert!(crate::memory::run("memory|replace|vim|prefers nvim")
            .starts_with("OK"));
        assert!(crate::memory::run("memory|add|scratch")
            .starts_with("OK"));
        assert!(crate::memory::run("memory|remove|scratch")
            .starts_with("OK"));
        assert!(crate::memory::snapshot().contains("prefers nvim"));
        assert!(!crate::memory::snapshot().contains("scratch"));

        // recall: index + FTS5 top-k + tool form
        crate::recall::index_turn("how restart pipewire",
                                "systemctl --user restart wireplumber",
                                "");
        assert!(crate::recall::run("search pipewire")
            .contains("wireplumber"));
        assert!(crate::recall::search("zzzqqq", 5).is_empty());
        assert!(crate::recall::run("").contains("no recall hits"));

        // skills: create/list/view/edit/delete + tool registration
        assert!(crate::skills::run_manage(
            "create|echoer|echoes args|body").starts_with("OK"));
        assert!(crate::skills::run_manage("list").contains("echoer"));
        assert!(crate::skills::view("echoer").contains("name: echoer"));
        assert!(crate::skills::run_manage(
            "write_file|echoer|run.sh|echo SKILL:$1").starts_with("OK"));
        // declare the tool in frontmatter
        let f = crate::config::data_dir()
            .join("skills/echoer/SKILL.md");
        std::fs::write(&f, "---\nname: echoer\ndescription: echoes args\
                            \ntool: run.sh\ntier: safe\n---\nbody\n").unwrap();
        assert_eq!(crate::tools::risk_of("skill_echoer"), "safe");
        let (msg, _) = crate::skills::run_skill_tool("skill_echoer", "hi")
            .unwrap();
        assert!(msg.contains("SKILL:hi"));
        assert!(crate::skills::run_manage(
            "write_file|echoer|../evil|x").starts_with("FAIL"));
        assert!(crate::skills::run_manage("delete|echoer").starts_with("OK"));
        assert!(crate::skills::view("echoer").starts_with("FAIL"));

        // registry parity: new tools present with expected tiers
        assert_eq!(crate::tools::risk_of("memory"), "mutating");
        assert_eq!(crate::tools::risk_of("recall"), "safe");
        assert_eq!(crate::tools::risk_of("nonexistent"), "shell");
    }

    #[test]
    fn points_extract_and_map() {
        use serde_json::json;
        let (clean, pts) = crate::points::extract(
            "Click it [POINT:100,200:OK button] now.");
        assert!(!clean.contains("POINT"));
        assert_eq!(pts[0]["x"], json!(100));
        assert_eq!(pts[0]["label"], json!("OK button"));

        let (_, pts) = crate::points::extract(
            "Steps: [POINTS:[{\"x\":1,\"y\":2,\"label\":\"a\"},\
             {\"x\":3,\"y\":4,\"label\":\"b\"}]]");
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[1]["label"], json!("b"));

        // unclosed POINTS stays visible (parity: same as Python)
        let (clean, pts) = crate::points::extract("t [POINTS:not-json] m");
        assert!(clean.contains("POINTS"));
        assert!(pts.is_empty());

        // scale-2 eDP-1 + scale-1 DP-3 at logical (1728,0); the overlap
        // region [1728,3456) belongs to the later output (grim draws in
        // order, last wins)
        let mons = vec![
            json!({"x":0,"y":0,"width":3456,"height":2160,"scale":2}),
            json!({"x":1728,"y":0,"width":3440,"height":1440,"scale":1}),
        ];
        let out = crate::points::to_logical(
            &[json!({"x":1000,"y":400,"label":""}),
              json!({"x":2000,"y":50,"label":""}),
              json!({"x":99999,"y":0,"label":""})], &mons);
        assert_eq!(out[0]["x"], json!(500));
        assert_eq!(out[0]["y"], json!(200));
        assert_eq!(out[1]["x"], json!(2000));
        assert_eq!(out[2]["x"], json!(99999));
    }
}
