//! Spoken replies (TTS) with barge-in — parity with wisp/speech.py.
//! speak() records the TTS pid and spawns a waiter thread that owns the
//! Child (reaps it on exit, then fires on_done). stop() kills by pid —
//! the waiter still reaps, so no zombies.
//! voice.cmd overrides the binary: whitespace-split argv, `{text}`
//! placeholder replaced by the message (else appended as last arg).

use std::process::{Command, Stdio};
use std::sync::Mutex;

use crate::config::Cfg;

// live TTS pid; the Child itself is owned by the waiter thread
static PROC: Mutex<Option<u32>> = Mutex::new(None);

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
    crate::platform::tts_argv(msg)
}

fn speak_cmd(msg: &str, cmd: &str,
             on_done: Option<Box<dyn FnOnce() + Send>>) -> bool {
    let Some((prog, args)) = argv(msg, cmd) else { return false };
    let Ok(mut child) = Command::new(&prog)
        .args(&args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    else {
        return false;
    };
    let pid = child.id();
    {
        let mut g = PROC.lock().unwrap();
        if let Some(old) = g.replace(pid) {
            let _ = Command::new("kill").arg(old.to_string()).status();
        }
    }
    std::thread::spawn(move || {
        let _ = child.wait(); // reaps — also after a stop() kill
        let mut g = PROC.lock().unwrap();
        if *g == Some(pid) {
            *g = None;
        }
        drop(g);
        if let Some(cb) = on_done {
            cb();
        }
    });
    true
}

pub fn speak(msg: &str, cfg: &Cfg,
             on_done: Option<Box<dyn FnOnce() + Send>>) -> bool {
    if !cfg.voice_out || msg.is_empty() {
        return false;
    }
    speak_cmd(msg, &cfg.voice_cmd, on_done)
}

pub fn stop() {
    if let Some(pid) = PROC.lock().unwrap().take() {
        // SIGTERM via kill(1); the waiter thread reaps the child
        let _ = Command::new("kill").arg(pid.to_string()).status();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Duration;

    fn sleep_script() -> (std::path::PathBuf, String) {
        let dir = std::env::temp_dir()
            .join(format!("wisp-tts-test-{}", std::process::id()));
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

    #[test]
    fn barge_in_and_override() {
        // single test fn: PROC is process-global
        let (_d, script) = sleep_script();

        stop();
        assert!(speak_cmd("hi", &script, None));
        assert!(PROC.lock().unwrap().is_some());
        // placeholder substitution + replace kills the previous proc
        assert!(speak_cmd("hi", &format!("{script} {{text}}"), None));
        // barge-in: stop clears tracking; waiter reaps
        stop();
        assert!(PROC.lock().unwrap().is_none());
        // on_done fires on natural exit
        let (tx, rx) = mpsc::channel();
        let dir2 = std::env::temp_dir()
            .join(format!("wisp-tts-fast-{}", std::process::id()));
        std::fs::create_dir_all(&dir2).unwrap();
        let p2 = dir2.join("t.sh");
        std::fs::write(&p2, "#!/bin/sh\nexit 0\n").unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            &p2,
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
        assert!(speak_cmd("hi", p2.to_str().unwrap(),
            Some(Box::new(move || { tx.send(()).unwrap(); }))));
        rx.recv_timeout(Duration::from_secs(5)).unwrap();
        let _ = std::fs::remove_dir_all(&_d);
        let _ = std::fs::remove_dir_all(&dir2);
    }
}
