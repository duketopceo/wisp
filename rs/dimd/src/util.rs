//! Small shared helpers.

use std::io;
use std::process::{Command, Output};
use std::time::{Duration, Instant};

/// Run a command with a wall-clock timeout; kills the child on expiry
/// (parity with subprocess.run(timeout=N)).
pub fn run_timeout(cmd: &mut Command, secs: u64) -> io::Result<Option<Output>> {
    let mut child = cmd
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(secs);
    loop {
        if child.try_wait()?.is_some() {
            return Ok(Some(child.wait_with_output()?));
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Filesystem/tool-name-safe slug — shared by agents and skills so
/// naming can't drift (parity with dim/util.py::slug).
pub fn slug(text: &str, max_len: usize, default: &str) -> String {
    let mut s = String::with_capacity(max_len);
    let mut dash = false;
    for ch in text.to_lowercase().chars() {
        if ch.is_ascii_alphanumeric() {
            s.push(ch);
            dash = false;
        } else if !dash && !s.is_empty() {
            s.push('-');
            dash = true;
        }
        if s.len() >= max_len {
            break;
        }
    }
    let s = s.trim_end_matches('-').to_string();
    if s.is_empty() { default.into() } else { s }
}
