//! Spoken replies (TTS) with barge-in — parity with dim/speech.py.
//! speak() tracks the TTS child; stop() kills it (SIGKILL — fast path).
//! voice.cmd overrides the binary: whitespace-split argv, `{text}`
//! placeholder replaced by the message (else appended as last arg).

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use crate::config::Cfg;
use crate::tools;

static PROC: Mutex<Option<Child>> = Mutex::new(None);

fn argv(msg: &str, cmd: &str) -> Option<(String, Vec<String>)> {
    if !cmd.is_empty() {
        let mut parts: Vec<String> =
            cmd.split_whitespace().map(String::from).collect();
        if parts.is_empty() {
            return None;
        }
        if let Some(i) = parts.iter().position(|p| p == "{text}") {
            parts[i] = msg.to_string();
        } else {
            parts.push(msg.to_string());
        }
        let prog = parts.remove(0);
        return Some((prog, parts));
    }
    let bin = if tools::which("espeak-ng") {
        "espeak-ng"
    } else if tools::which("espeak") {
        "espeak"
    } else {
        return None;
    };
    Some((bin.to_string(), vec![msg.to_string()]))
}

fn speak_cmd(msg: &str, cmd: &str) {
    let Some((prog, args)) = argv(msg, cmd) else { return };
    let Ok(child) = Command::new(&prog)
        .args(&args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    else {
        return;
    };
    if let Some(mut old) = PROC.lock().unwrap().replace(child) {
        let _ = old.kill();
        let _ = old.wait(); // reap — drop alone leaves a zombie
    }
}

pub fn speak(msg: &str, cfg: &Cfg) {
    if !cfg.voice_out || msg.is_empty() {
        return;
    }
    speak_cmd(msg, &cfg.voice_cmd);
}

pub fn stop() {
    if let Some(mut p) = PROC.lock().unwrap().take() {
        let _ = p.kill();
        let _ = p.wait(); // reap — drop alone leaves a zombie
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sleep_script() -> (std::path::PathBuf, String) {
        let dir = std::env::temp_dir()
            .join(format!("dim-tts-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("tts.sh");
        std::fs::write(&p, "#!/bin/sh\nsleep 60\n").unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            &p,
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
        let path = p.to_str().unwrap().to_string();
        (dir, path)
    }

    fn proc_alive() -> bool {
        PROC.lock().unwrap().is_some()
    }

    #[test]
    fn barge_in_and_override() {
        // single test fn: PROC is process-global
        let (_d, script) = sleep_script();

        // voice_out=false → no spawn
        stop();
        speak_cmd("hi", ""); // no espeak cmd and likely no binary:
        // can't assert negative reliably; override path is the test

        speak_cmd("hi", &script);
        assert!(proc_alive());
        // placeholder substitution uses the script too
        speak_cmd("hi", &format!("{script} {{text}}"));
        assert!(proc_alive());
        // barge-in
        stop();
        assert!(!proc_alive());
        let _ = std::fs::remove_dir_all(&_d);
    }
}
