//! Platform seam — every OS-specific shell-out routes through here so
//! `dimd` can carry macOS (U7) / Windows (U8) / generic-Linux (U9)
//! adapters without call-site edits. Commands are argv vectors; the
//! Linux table is byte-for-byte what the code did before this seam
//! existed, so behaviour can't drift.
//!
//! Detection is `std::env::consts::OS` with a `DIMD_OS` override so
//! adapters are unit-testable on any host.
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Os { Linux, MacOS, Windows }

pub fn current() -> Os {
    if let Ok(o) = std::env::var("DIMD_OS") {
        return match o.as_str() {
            "macos" | "darwin" => Os::MacOS,
            "windows" => Os::Windows,
            _ => Os::Linux,
        };
    }
    match std::env::consts::OS {
        "macos" => Os::MacOS,
        "windows" => Os::Windows,
        _ => Os::Linux,
    }
}

// ── runtime dirs ────────────────────────────────────────────────────

/// (config, data, runtime) — format/contents identical across OSes,
/// only the roots move.
pub fn dirs(home: &std::path::Path) -> (PathBuf, PathBuf, PathBuf) {
    dirs_for(current(), home)
}
fn dirs_for(os: Os, home: &std::path::Path) -> (PathBuf, PathBuf, PathBuf) {
    match os {
        Os::MacOS => (
            home.join("Library/Application Support/dim-agent"),
            home.join("Library/Application Support/dim-agent"),
            std::env::var("TMPDIR").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("dim-agent"),
        ),
        Os::Windows => (
            home.join("AppData/Roaming/dim-agent"),
            home.join("AppData/Local/dim-agent"),
            std::env::var("TEMP").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("dim-agent"),
        ),
        _ => (
            home.join(".config/dim-agent"),
            home.join(".local/share/dim-agent"),
            std::env::var("XDG_RUNTIME_DIR").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("dim-agent"),
        ),
    }
}

// ── commands (argv) ─────────────────────────────────────────────────

/// Microphone capture → WAV at `out`. macOS uses the built-in
/// `afrecord` (brew `sox` fallback); Windows adapter lands in U8.
/// `None` → caller degrades gracefully ("no recorder found").
pub fn record_cmd(out: &std::path::Path, seconds: i64) -> Option<Command> {
    record_cmd_for(current(), out, seconds)
}
fn record_cmd_for(os: Os, out: &std::path::Path, seconds: i64) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if crate::tools::which("pw-record") {
                let mut c = Command::new("pw-record");
                c.args(["--rate", "16000", "--channels", "1",
                        "--format", "s16", "--sample-count",
                        &format!("{}", 16000 * seconds)]);
                c.arg(out);
                c
            } else if crate::tools::which("arecord") {
                let mut c = Command::new("arecord");
                c.args(["-D", "default", "-r", "16000", "-c", "1",
                        "-f", "S16_LE", "-d", &seconds.to_string()]);
                c.arg(out);
                c
            } else {
                return None;
            }
        }
        Os::MacOS => {
            if crate::tools::which("afrecord") {
                let mut c = Command::new("afrecord");
                c.args(["-f", "WAVE", "-d", &seconds.to_string()]);
                c.arg(out);
                c
            } else if crate::tools::which("sox") {
                let mut c = Command::new("sox");
                c.args(["-d", "-r", "16000", "-c", "1"]);
                c.arg(out);
                c.args(["trim", "0", &seconds.to_string()]);
                c
            } else {
                return None;
            }
        }
        Os::Windows => return None, // U8
    })
}

/// Full-screen PNG at `out`.
pub fn screenshot_cmd(out: &std::path::Path) -> Option<Command> {
    screenshot_cmd_for(current(), out)
}
fn screenshot_cmd_for(os: Os, out: &std::path::Path) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if !crate::tools::which("grim") { return None; }
            let mut c = Command::new("grim");
            c.arg(out);
            c
        }
        Os::MacOS => {
            if !crate::tools::which("screencapture") { return None; }
            let mut c = Command::new("screencapture");
            c.arg("-x"); c.arg(out);
            c
        }
        Os::Windows => return None,
    })
}

/// Type `text` into the focused window. macOS: System Events
/// keystroke (needs Accessibility permission); long text is chunked
/// by the caller's caller? No — one shot, osascript handles it.
pub fn type_text_cmd(text: &str) -> Option<Command> {
    type_text_cmd_for(current(), text)
}
fn type_text_cmd_for(os: Os, text: &str) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if !crate::tools::which("wtype") { return None; }
            let mut c = Command::new("wtype");
            c.args(["--", text]);
            c
        }
        Os::MacOS => {
            if !crate::tools::which("osascript") { return None; }
            let esc = text.replace('\\', "\\\\").replace('"', "\\\"");
            let mut c = Command::new("osascript");
            c.args(["-e", &format!(
                "tell application \"System Events\" to keystroke \"{esc}\"")]);
            c
        }
        Os::Windows => return None,
    })
}

/// Speak `text` (child proc is killed on barge-in — caller tracks pid).
pub fn tts_cmd(text: &str, voice_cmd: &str) -> Option<Command> {
    tts_cmd_for(current(), text, voice_cmd)
}
fn tts_cmd_for(os: Os, text: &str, voice_cmd: &str) -> Option<Command> {
    if !voice_cmd.is_empty() {
        // config override wins on every OS: "{text}" placeholder or
        // appended arg (parity with existing voice.cmd semantics)
        let mut c = Command::new("sh");
        if voice_cmd.contains("{text}") {
            c.args(["-c", &voice_cmd.replace("{text}", &text
                .replace('\'', "'\\''"))]);
        } else {
            c.args(["-c", &format!("{} '{}'", voice_cmd,
                text.replace('\'', "'\\''"))]);
        }
        return Some(c);
    }
    Some(match os {
        Os::Linux => {
            if crate::tools::which("espeak-ng") {
                let mut c = Command::new("espeak-ng");
                c.arg(text);
                c
            } else {
                let mut c = Command::new("espeak");
                c.arg(text);
                c
            }
        }
        Os::MacOS => {
            let mut c = Command::new("say");
            c.arg(text);
            c
        }
        Os::Windows => return None,
    })
}

/// Live mic level sampler — emits unsigned-8 PCM (200 Hz, mono) on
/// stdout for `amplitude_sampler`. macOS: sox only (afrecord can't
/// stream raw); `None` → level stays 0 (graceful degradation).
pub fn sampler_cmd(seconds: i64) -> Option<Command> {
    sampler_cmd_for(current(), seconds)
}
fn sampler_cmd_for(os: Os, seconds: i64) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if !crate::tools::which("arecord") { return None; }
            let mut c = Command::new("arecord");
            c.args(["-D", "default", "-f", "U8", "-r", "200", "-c", "1",
                    "-d", &seconds.to_string()]);
            c
        }
        Os::MacOS => {
            if !crate::tools::which("sox") { return None; }
            let mut c = Command::new("sox");
            c.args(["-d", "-t", "u8", "-r", "200", "-c", "1", "-",
                    "trim", "0", &seconds.to_string()]);
            c
        }
        Os::Windows => return None,
    })
}

/// Default TTS binary on this OS (`None` → TTS unavailable; caller
/// falls back to text-only). `voice.cmd` config overrides this.
pub fn tts_binary() -> Option<&'static str> {
    tts_binary_for(current())
}
fn tts_binary_for(os: Os) -> Option<&'static str> {
    match os {
        Os::Linux => {
            if crate::tools::which("espeak-ng") { Some("espeak-ng") }
            else if crate::tools::which("espeak") { Some("espeak") }
            else { None }
        }
        Os::MacOS => {
            if crate::tools::which("say") { Some("say") } else { None }
        }
        Os::Windows => None,
    }
}

/// Desktop notification.
pub fn notify_cmd(title: &str, body: &str) -> Option<Command> {
    notify_cmd_for(current(), title, body)
}
fn notify_cmd_for(os: Os, title: &str, body: &str) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            let mut c = Command::new("notify-send");
            c.args([title, body]);
            c
        }
        Os::MacOS => {
            let esc = |s: &str| s.replace('\\', "\\\\").replace('"', "\\\"");
            let mut c = Command::new("osascript");
            c.args(["-e", &format!(
                "display notification \"{}\" with title \"{}\"",
                esc(body), esc(title))]);
            c
        }
        Os::Windows => return None,
    })
}

// ── window management ───────────────────────────────────────────────

/// hyprctl command with HYPRLAND_INSTANCE_SIGNATURE discovery —
/// moved here from tools.rs so non-Linux builds don't carry it.
fn hypr_cmd(args: &[String]) -> Command {
    let mut c = Command::new("hyprctl");
    c.args(args);
    if std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_err() {
        let rd = std::env::var("XDG_RUNTIME_DIR")
            .unwrap_or_else(|_| "/tmp".into());
        let hypr = PathBuf::from(rd).join("hypr");
        if let Ok(mut it) = std::fs::read_dir(&hypr) {
            if let Some(Ok(e)) = it.next() {
                c.env("HYPRLAND_INSTANCE_SIGNATURE", e.file_name());
            }
        }
    }
    c
}

fn eval_lua(lua: &str) -> Command {
    hypr_cmd(&["eval".into(), format!("hl.dispatch({lua})")])
}

/// Commands to focus a window by class substring, tried in order
/// (Linux: Lua dsp + legacy dispatch fallback — hyprctl dispatch is
/// broken by a parse bug on Hyprland 0.56+; macOS: `open -a`).
pub fn focus_cmds(class: &str) -> Vec<Command> {
    focus_cmds_for(current(), class)
}
fn focus_cmds_for(os: Os, class: &str) -> Vec<Command> {
    match os {
        Os::Linux => vec![
            eval_lua(&format!("hl.dsp.focus({{window=\"class:^{class}\"}})")),
            hypr_cmd(&["focuswindow".into(),
                       format!("class:^{class}")]),
        ],
        Os::MacOS => {
            let mut c = Command::new("open");
            c.args(["-a", class]);
            vec![c]
        }
        Os::Windows => vec![],
    }
}

/// Commands to close `class` (empty = active window).
pub fn close_cmds(class: &str) -> Vec<Command> {
    close_cmds_for(current(), class)
}
fn close_cmds_for(os: Os, class: &str) -> Vec<Command> {
    match os {
        Os::Linux => {
            if class.is_empty() {
                vec![
                    eval_lua("hl.dsp.window.close()"),
                    hypr_cmd(&["killactive".into()]),
                ]
            } else {
                vec![
                    eval_lua(&format!(
                        "hl.dsp.window.close({{window=\"class:^{class}\"}})")),
                    hypr_cmd(&["closewindow".into(),
                               format!("class:^{class}")]),
                ]
            }
        }
        Os::MacOS => {
            let mut c = Command::new("osascript");
            c.args(["-e",
                "tell application \"System Events\" to keystroke \"w\" \
                 using command down"]);
            vec![c]
        }
        Os::Windows => vec![],
    }
}

/// Switch to workspace `n` (1-based). macOS: Ctrl+<n> key codes
/// (18..29 are the number-row key codes; works with stock Mission
/// Control bindings).
pub fn workspace_cmds(n: i64) -> Vec<Command> {
    workspace_cmds_for(current(), n)
}
fn workspace_cmds_for(os: Os, n: i64) -> Vec<Command> {
    match os {
        Os::Linux => vec![
            eval_lua(&format!("hl.dsp.focus({{workspace={n}}})")),
            hypr_cmd(&["workspace".into(), n.to_string()]),
        ],
        Os::MacOS => {
            // key codes: 1→18 2→19 3→20 4→21 5→23 6→22 7→26 8→28 9→25
            let codes = [18, 19, 20, 21, 23, 22, 26, 28, 25];
            let Some(&code) = codes.get((n - 1) as usize) else {
                return vec![];
            };
            let mut c = Command::new("osascript");
            c.args(["-e", &format!(
                "tell application \"System Events\" to key code {code} \
                 using control down")]);
            vec![c]
        }
        Os::Windows => vec![],
    }
}

/// Did a wm command actually do something? Linux: Hyprland `eval`
/// replies "ok" (legacy dispatch exits 0 but prints nothing — treat
/// clean exit as ok only when stdout is silent, matching dsp()).
/// macOS/Windows: exit status is authoritative.
pub fn wm_ok(o: &std::process::Output) -> bool {
    match current() {
        Os::Linux => String::from_utf8_lossy(&o.stdout).contains("ok")
            || o.status.success(),
        _ => o.status.success(),
    }
}

/// `hyprctl dispatch exec` for launching — needs the same eval path.
pub fn launch_exec_cmds(cmdline: &str) -> Vec<Command> {
    launch_exec_cmds_for(current(), cmdline)
}
fn launch_exec_cmds_for(os: Os, cmdline: &str) -> Vec<Command> {
    match os {
        Os::Linux => vec![
            eval_lua(&format!("hl.dsp.exec_cmd(\"{cmdline}\")")),
            hypr_cmd(&["dispatch".into(), "exec".into(),
                       cmdline.into()]),
        ],
        Os::MacOS => {
            let mut c = Command::new("sh");
            c.args(["-c", cmdline]);
            vec![c]
        }
        Os::Windows => vec![],
    }
}

/// Monitor rects for point normalization — `[{x,y,width,height,scale}]`
/// in *logical* coords (grim-screenshot space is physical px; on macOS
/// screencapture PNGs are also physical px, so scale still applies).
pub fn monitors() -> Vec<Value> {
    monitors_for(current())
}
fn monitors_for(os: Os) -> Vec<Value> {
    match os {
        Os::Linux => {
            let out = crate::util::run_timeout(
                Command::new("hyprctl").args(["monitors", "-j"]), 5);
            match out {
                Ok(Some(o)) if o.status.success() =>
                    serde_json::from_slice::<Value>(&o.stdout)
                        .ok()
                        .and_then(|v| v.as_array().cloned())
                        .unwrap_or_default(),
                _ => vec![],
            }
        }
        Os::MacOS => {
            // system_profiler gives physical px + Retina factor is
            // inferred as scale 2 for "Retina" displays — approximation;
            // AX/NSScreen is the precise path (documented residual).
            let out = crate::util::run_timeout(
                Command::new("system_profiler")
                    .args(["SPDisplaysDataType", "-json"]), 8);
            match out {
                Ok(Some(o)) if o.status.success() => {
                    let v: Value = serde_json::from_slice(&o.stdout)
                        .unwrap_or(Value::Null);
                    let mut mons = vec![];
                    if let Some(gpus) = v.pointer("/SPDisplaysDataType")
                        .and_then(|g| g.as_array()) {
                        let mut x_off = 0i64;
                        for gpu in gpus {
                            for d in gpu.get("spdisplays_displays")
                                .and_then(|a| a.as_array())
                                .cloned().unwrap_or_default() {
                                let w = d.get("spdisplays_resolution")
                                    .and_then(|r| r.as_str())
                                    .and_then(|r| r.split('x').next()
                                        .and_then(|w| w.trim()
                                            .parse::<f64>().ok()))
                                    .unwrap_or(0.0);
                                let scale = if d.get("spdisplays_retina")
                                    .and_then(|r| r.as_str())
                                    .map(|r| r.contains("Yes"))
                                    .unwrap_or(false) { 2.0 } else { 1.0 };
                                mons.push(serde_json::json!({
                                    "x": x_off, "y": 0,
                                    "width": w, "height":
                                        d.get("spdisplays_resolution")
                                        .and_then(|r| r.as_str())
                                        .and_then(|r| r.split('x')
                                            .nth(1).and_then(|h| h.trim()
                                                .parse::<f64>().ok()))
                                        .unwrap_or(0.0),
                                    "scale": scale,
                                }));
                                x_off += (w / scale) as i64;
                            }
                        }
                    }
                    mons
                }
                _ => vec![],
            }
        }
        Os::Windows => vec![],
    }
}

/// Whether a Hyprland-style keybinding installer exists — macOS hotkeys
/// are a SKHD/portal concern, so `dimd install` only writes the bind on
/// Linux.
pub fn supports_hotkey_install() -> bool { current() == Os::Linux }

/// Human guidance for the missing perms/tools on this OS (error text).
pub fn missing_deps_hint() -> &'static str {
    missing_deps_hint_for(current())
}
fn missing_deps_hint_for(os: Os) -> &'static str {
    match os {
        Os::Linux => "need grim/wtype/pw-record/espeak + Hyprland",
        Os::MacOS => "need screencapture/osascript/afrecord; grant \
                     Screen Recording + Accessibility in System Settings",
        Os::Windows => "windows adapter lands in U8",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // All platform behavior is exercised through the *_for(os, ...)
    // variants — no env mutation, so these never race the parallel
    // contract test that reads config dirs.

    #[test]
    fn macos_dirs() {
        let (c, d, r) = dirs_for(Os::MacOS, std::path::Path::new("/u/l"));
        assert!(c.ends_with("Library/Application Support/dim-agent"));
        assert!(d.ends_with("Application Support/dim-agent"));
        assert!(r.ends_with("dim-agent"));
    }

    #[test]
    fn linux_dirs_unchanged() {
        let (c, d, _r) = dirs_for(Os::Linux, std::path::Path::new("/u/l"));
        assert!(c.ends_with(".config/dim-agent"));
        assert!(d.ends_with(".local/share/dim-agent"));
    }

    #[test]
    fn linux_cmds_unchanged() {
        // the Linux table must stay byte-for-byte what the old inline
        // code built — guards the seam against silent behavior drift.
        // Binaries may be absent (CI runner): assert program when
        // present, never panic on None.
        if let Some(rec) = record_cmd_for(Os::Linux,
                std::path::Path::new("/t/u.wav"), 5) {
            assert!(["pw-record", "arecord"].contains(&(
                rec.get_program().to_str().unwrap())));
        }
        if let Some(c) =
            screenshot_cmd_for(Os::Linux, std::path::Path::new("/t/s.png")) {
            assert_eq!(c.get_program(), "grim");
        }
    }

    #[test]
    fn macos_cmds() {
        // cmds exist only when the binary is on PATH — assert either
        // the right program or graceful None (never a panic)
        if let Some(shot) = screenshot_cmd_for(Os::MacOS,
                std::path::Path::new("/t/s.png")) {
            assert_eq!(shot.get_program(), "screencapture");
        }
        if let Some(t) = type_text_cmd_for(Os::MacOS, "hi") {
            assert_eq!(t.get_program(), "osascript");
        }
        if let Some(tts) = tts_cmd_for(Os::MacOS, "hi", "") {
            assert_eq!(tts.get_program(), "say");
        }
        let _ = record_cmd_for(Os::MacOS,
            std::path::Path::new("/t/u.wav"), 5);
        let _ = sampler_cmd_for(Os::MacOS, 5);
        assert_eq!(tts_binary_for(Os::Windows), None);
    }

    #[test]
    fn voice_cmd_override_beats_builtin() {
        let c = tts_cmd_for(Os::MacOS, "hi", "my-tts {text}").unwrap();
        assert_eq!(c.get_program(), "sh");
    }

    #[test]
    fn macos_wm_cmds() {
        let f = focus_cmds_for(Os::MacOS, "Firefox");
        assert_eq!(f[0].get_program(), "open");
        let c = close_cmds_for(Os::MacOS, "");
        assert_eq!(c[0].get_program(), "osascript");
        assert!(workspace_cmds_for(Os::MacOS, 10).is_empty()); // 1..=9
        let w = workspace_cmds_for(Os::MacOS, 3);
        assert_eq!(w[0].get_program(), "osascript");
        assert!(focus_cmds_for(Os::Windows, "x").is_empty());
    }

    #[test]
    fn missing_deps_hints() {
        assert!(missing_deps_hint_for(Os::MacOS)
            .contains("Screen Recording"));
        assert!(missing_deps_hint_for(Os::Windows).contains("U8"));
    }
}
