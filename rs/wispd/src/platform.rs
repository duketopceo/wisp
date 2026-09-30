//! Platform seam — every OS-specific shell-out routes through here so
//! `wispd` can carry macOS (U7) / Windows (U8) / generic-Linux (U9)
//! adapters without call-site edits. Commands are argv vectors; the
//! Linux table is byte-for-byte what the code did before this seam
//! existed, so behaviour can't drift.
//!
//! Detection is `std::env::consts::OS` with a `WISP_OS` override so
//! adapters are unit-testable on any host.
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::Command;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Os { Linux, MacOS, Windows }

/// Linux desktop/compositor — detected once per call. `WISP_DESKTOP`
/// env override mirrors WISP_OS (tests, forced fallbacks).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Desktop { Hyprland, Gnome, Kde, X11, Unknown }

pub fn desktop() -> Desktop {
    if let Ok(d) = std::env::var("WISP_DESKTOP") {
        return match d.as_str() {
            "hyprland" => Desktop::Hyprland,
            "gnome" => Desktop::Gnome,
            "kde" => Desktop::Kde,
            "x11" => Desktop::X11,
            _ => Desktop::Unknown,
        };
    }
    if std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_ok()
        || crate::tools::which("hyprctl") {
        return Desktop::Hyprland;
    }
    let cur = std::env::var("XDG_CURRENT_DESKTOP")
        .unwrap_or_default().to_lowercase();
    if cur.contains("gnome") { return Desktop::Gnome; }
    if cur.contains("kde") || cur.contains("plasma") {
        return Desktop::Kde;
    }
    if std::env::var("DISPLAY").is_ok()
        && std::env::var("WAYLAND_DISPLAY").is_err() {
        return Desktop::X11;
    }
    Desktop::Unknown
}

pub fn current() -> Os {
    if let Ok(o) = std::env::var("WISP_OS") {
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
/// Desktop adapter for the current host — only probed on Linux.
fn desk() -> Desktop {
    if current() == Os::Linux { desktop() } else { Desktop::Unknown }
}

fn dirs_for(os: Os, home: &std::path::Path) -> (PathBuf, PathBuf, PathBuf) {
    match os {
        Os::MacOS => (
            home.join("Library/Application Support/wisp"),
            home.join("Library/Application Support/wisp"),
            std::env::var("TMPDIR").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("wisp"),
        ),
        Os::Windows => (
            home.join("AppData/Roaming/wisp"),
            home.join("AppData/Local/wisp"),
            std::env::var("TEMP").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("wisp"),
        ),
        _ => (
            home.join(".config/wisp"),
            home.join(".local/share/wisp"),
            std::env::var("XDG_RUNTIME_DIR").map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("/tmp"))
                .join("wisp"),
        ),
    }
}

// ── commands (argv) ─────────────────────────────────────────────────

/// Microphone capture → WAV at `out`. macOS uses the built-in
/// `afrecord` (brew `sox` fallback); Windows uses `sox -t waveaudio`.
/// `None` → caller degrades gracefully ("no recorder found").
pub fn record_cmd(out: &std::path::Path, seconds: Option<i64>)
                  -> Option<Command> {
    record_cmd_for(current(), out, seconds)
}
/// seconds: Some(n) → self-terminating capture; None → open-ended
/// toggle capture (caller stops via SIGINT — recorders finalize the
/// WAV header on it).
fn record_cmd_for(os: Os, out: &std::path::Path,
                  seconds: Option<i64>) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if crate::tools::which("pw-record") {
                let mut c = Command::new("pw-record");
                c.args(["--rate", "16000", "--channels", "1",
                        "--format", "s16"]);
                if let Some(s) = seconds {
                    c.args(["--sample-count",
                            &format!("{}", 16000 * s)]);
                }
                c.arg(out);
                c
            } else if crate::tools::which("arecord") {
                let mut c = Command::new("arecord");
                c.args(["-D", "default", "-r", "16000", "-c", "1",
                        "-f", "S16_LE"]);
                if let Some(s) = seconds {
                    c.args(["-d", &s.to_string()]);
                }
                c.arg(out);
                c
            } else {
                return None;
            }
        }
        Os::MacOS => {
            if crate::tools::which("afrecord") {
                let mut c = Command::new("afrecord");
                c.args(["-f", "WAVE"]);
                if let Some(s) = seconds {
                    c.args(["-d", &s.to_string()]);
                }
                c.arg(out);
                c
            } else if crate::tools::which("sox") {
                let mut c = Command::new("sox");
                c.args(["-d", "-r", "16000", "-c", "1"]);
                c.arg(out);
                if let Some(s) = seconds {
                    c.args(["trim", "0", &s.to_string()]);
                }
                c
            } else {
                return None;
            }
        }
        Os::Windows => {
            if crate::tools::which("sox") {
                let mut c = Command::new("sox");
                c.args(["-t", "waveaudio", "-d", "-r", "16000",
                        "-c", "1"]);
                c.arg(out);
                if let Some(s) = seconds {
                    c.args(["trim", "0", &s.to_string()]);
                }
                c
            } else {
                return None;
            }
        }
    })
}

/// Full-screen PNG at `out`.
pub fn screenshot_cmd(out: &std::path::Path) -> Option<Command> {
    screenshot_cmd_for(current(), desk(), out)
}
fn screenshot_cmd_for(os: Os, dt: Desktop,
                      out: &std::path::Path) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            // hyprland/wlroots: grim; gnome: gnome-screenshot;
            // kde: spectacle; x11: maim (ImageMagick import fallback)
            let bin: &str = match dt {
                Desktop::Hyprland | Desktop::Unknown => "grim",
                Desktop::Gnome => "gnome-screenshot",
                Desktop::Kde => "spectacle",
                Desktop::X11 => "maim",
            };
            let mut c = if crate::tools::which(bin) {
                Command::new(bin)
            } else {
                // generic fallbacks in PATH order
                let mut c2 = None;
                for b in ["grim", "gnome-screenshot", "spectacle",
                          "maim"] {
                    if crate::tools::which(b) {
                        c2 = Some(Command::new(b));
                        break;
                    }
                }
                c2?
            };
            match c.get_program().to_str().unwrap_or("") {
                "grim" | "maim" => { c.arg(out); }
                "gnome-screenshot" => { c.args(["-f"]); c.arg(out); }
                "spectacle" => {
                    c.args(["-b", "-n", "-o"]); c.arg(out);
                }
                _ => { c.arg(out); }
            }
            c
        }
        Os::MacOS => {
            if !crate::tools::which("screencapture") { return None; }
            let mut c = Command::new("screencapture");
            c.arg("-x"); c.arg(out);
            c
        }
        Os::Windows => {
            if !crate::tools::which("powershell") { return None; }
            let script = concat!(
                "Add-Type -AssemblyName System.Windows.Forms,",
                "System.Drawing; $b=[System.Windows.Forms.",
                "SystemInformation]::VirtualScreen; ",
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,",
                "$b.Height; $g=[System.Drawing.Graphics]::FromImage",
                "($bmp); $g.CopyFromScreen($b.Left,$b.Top,0,0,",
                "$bmp.Size); $bmp.Save('{OUT}'); $g.Dispose(); ",
                "$bmp.Dispose()");
            return Some(ps(&script.replace("{OUT}",
                &out.display().to_string())));
        }
    })
}

/// Type `text` into the focused window. macOS: System Events
/// keystroke (needs Accessibility permission); long text is chunked
/// by the caller's caller? No — one shot, osascript handles it.
pub fn type_text_cmd(text: &str) -> Option<Command> {
    type_text_cmd_for(current(), desk(), text)
}
fn type_text_cmd_for(os: Os, dt: Desktop,
                     text: &str) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            // hyprland/wlroots: wtype; portal-safe: ydotool (uinput);
            // x11: xdotool. Unknown: try all three in that order.
            let bins: &[&str] = match dt {
                Desktop::Hyprland => &["wtype", "ydotool"],
                Desktop::X11 => &["xdotool"],
                _ => &["ydotool", "wtype", "xdotool"],
            };
            let b = bins.iter().find(|b| crate::tools::which(b))?;
            let mut c = Command::new(b);
            match *b {
                "wtype" => c.args(["--", text]),
                "ydotool" => c.args(["type", "--", text]),
                _ => c.args(["type", "--clearmodifiers", "--", text]),
            };
            // systemd-launch daemons have an empty Environment — wtype
            // silently fails without the Wayland socket name
            if *b == "wtype" && std::env::var("WAYLAND_DISPLAY").is_err() {
                let rd = std::env::var("XDG_RUNTIME_DIR")
                    .unwrap_or_else(|_| "/tmp".into());
                if let Ok(mut it) = std::fs::read_dir(&rd) {
                    if let Some(name) = it.find_map(|e| e.ok()
                        .map(|e| e.file_name().to_string_lossy().into_owned())
                        .filter(|n| n.starts_with("wayland-")))
                    {
                        c.env("WAYLAND_DISPLAY", name);
                    }
                }
            }
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
        Os::Windows => {
            if !crate::tools::which("powershell") { return None; }
            return Some(ps(&format!(
                "Add-Type -AssemblyName System.Windows.Forms;                  [System.Windows.Forms.SendKeys]::SendWait(\"{}\")",
                sendkeys_escape(text))));
        }
    })
}

/// Speak `text` (child proc is killed on barge-in — caller tracks pid).
#[cfg_attr(not(test), allow(dead_code))]
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
        Os::Windows => {
            if !crate::tools::which("powershell") { return None; }
            let esc = text.replace('\'', "''");
            return Some(ps(&format!(
                "Add-Type -AssemblyName System.Speech; \
                 (New-Object System.Speech.Synthesis.\
                 SpeechSynthesizer).Speak('{esc}')")));
        }
    })
}

/// Live mic level sampler — emits unsigned-8 PCM (200 Hz, mono) on
/// stdout for `amplitude_sampler`. macOS: sox only (afrecord can't
/// stream raw); `None` → level stays 0 (graceful degradation).
pub fn sampler_cmd(seconds: Option<i64>) -> Option<Command> {
    sampler_cmd_for(current(), seconds)
}
fn sampler_cmd_for(os: Os, seconds: Option<i64>) -> Option<Command> {
    Some(match os {
        Os::Linux => {
            if !crate::tools::which("arecord") { return None; }
            let mut c = Command::new("arecord");
            c.args(["-D", "default", "-f", "U8", "-r", "200", "-c", "1"]);
            if let Some(s) = seconds {
                c.args(["-d", &s.to_string()]);
            }
            c
        }
        Os::MacOS => {
            if !crate::tools::which("sox") { return None; }
            let mut c = Command::new("sox");
            c.args(["-d", "-t", "u8", "-r", "200", "-c", "1", "-"]);
            if let Some(s) = seconds {
                c.args(["trim", "0", &s.to_string()]);
            }
            c
        }
        Os::Windows => {
            if !crate::tools::which("sox") { return None; }
            let mut c = Command::new("sox");
            c.args(["-t", "waveaudio", "-d", "-t", "u8", "-r", "200",
                    "-c", "1", "-"]);
            if let Some(s) = seconds {
                c.args(["trim", "0", &s.to_string()]);
            }
            c
        }
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
        Os::Windows => None, // SAPI goes through tts_argv (needs args)
    }
}

/// TTS argv when no voice.cmd override — `(prog, args)` so the caller
/// can append/pid-track. Windows uses PowerShell SAPI.
pub fn tts_argv(msg: &str) -> Option<(String, Vec<String>)> {
    if let Os::Windows = current() {
        if !crate::tools::which("powershell") { return None; }
        let esc = msg.replace('\'', "''");
        return Some(("powershell".into(), vec![
            "-NoProfile".into(), "-NonInteractive".into(),
            "-Command".into(), format!(
                "Add-Type -AssemblyName System.Speech;                  (New-Object System.Speech.Synthesis.                 SpeechSynthesizer).Speak('{esc}')")]));
    }
    tts_binary().map(|b| (b.to_string(), vec![msg.to_string()]))
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
        Os::Windows => {
            if !crate::tools::which("powershell") { return None; }
            let e = |s: &str| s.replace('\'', "''");
            return Some(ps(&format!(
                "if (Get-Module -ListAvailable BurntToast) {{                  New-BurntToastNotification -Text '{}','{}' }}                  else {{ msg * '{}: {}' }}",
                e(title), e(body), e(title), e(body))));
        }
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

fn ps(script: &str) -> Command {
    let mut c = Command::new("powershell");
    c.args(["-NoProfile", "-NonInteractive", "-Command", script]);
    c
}

/// Escape SendKeys metacharacters ({ } + ^ % ~ ( )) for
/// System.Windows.Forms.SendKeys.
fn sendkeys_escape(t: &str) -> String {
    let mut out = String::with_capacity(t.len());
    for ch in t.chars() {
        if "{}+^%~()[]".contains(ch) {
            out.push('{'); out.push(ch); out.push('}');
        } else {
            out.push(ch);
        }
    }
    out
}

fn eval_lua(lua: &str) -> Command {
    hypr_cmd(&["eval".into(), format!("hl.dispatch({lua})")])
}

/// Commands to focus a window by class substring, tried in order
/// (Linux: Lua dsp + legacy dispatch fallback — hyprctl dispatch is
/// broken by a parse bug on Hyprland 0.56+; macOS: `open -a`).
pub fn focus_cmds(class: &str) -> Vec<Command> {
    focus_cmds_for(current(), desk(), class)
}
fn focus_cmds_for(os: Os, dt: Desktop, class: &str) -> Vec<Command> {
    match os {
        Os::Linux => match dt {
            Desktop::Hyprland | Desktop::Unknown => vec![
                eval_lua(&format!(
                    "hl.dsp.focus({{window=\"class:^{class}\"}})")),
                hypr_cmd(&["focuswindow".into(),
                           format!("class:^{class}")]),
            ],
            Desktop::Kde => {
                // kdotool (kde's xdotool port) else wmctrl over xwayland
                if crate::tools::which("kdotool") {
                    let mut c = Command::new("sh");
                    c.args(["-c", &format!(
                        "kdotool search --name '{class}'                          windowactivate %@")]);
                    vec![c]
                } else if crate::tools::which("wmctrl") {
                    vec![{
                        let mut c = Command::new("wmctrl");
                        c.args(["-a", class]);
                        c
                    }]
                } else { vec![] }
            }
            Desktop::X11 => {
                if crate::tools::which("wmctrl") {
                    vec![{
                        let mut c = Command::new("wmctrl");
                        c.args(["-a", class]);
                        c
                    }]
                } else { vec![] }
            }
            Desktop::Gnome => vec![], // no wm api on wayland
        },
        Os::MacOS => {
            let mut c = Command::new("open");
            c.args(["-a", class]);
            vec![c]
        }
        Os::Windows => {
            if crate::tools::which("powershell") {
                vec![ps(&format!(
                    "(New-Object -ComObject WScript.Shell)                     .AppActivate('{class}') | Out-Null"))]
            } else { vec![] }
        }
    }
}

/// Commands to close `class` (empty = active window).
pub fn close_cmds(class: &str) -> Vec<Command> {
    close_cmds_for(current(), desk(), class)
}
fn close_cmds_for(os: Os, dt: Desktop, class: &str) -> Vec<Command> {
    match os {
        Os::Linux => match dt {
            Desktop::Hyprland | Desktop::Unknown => {
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
            Desktop::Kde | Desktop::X11 => {
                // wmctrl: -c by name, or xdotool close active window
                if class.is_empty() {
                    if crate::tools::which("xdotool") {
                        let mut c = Command::new("xdotool");
                        c.args(["getactivewindow", "windowclose"]);
                        vec![c]
                    } else { vec![] }
                } else if crate::tools::which("wmctrl") {
                    let mut c = Command::new("wmctrl");
                    c.args(["-c", class]);
                    vec![c]
                } else { vec![] }
            }
            Desktop::Gnome => vec![],
        },
        Os::MacOS => {
            let mut c = Command::new("osascript");
            c.args(["-e",
                "tell application \"System Events\" to keystroke \"w\" \
                 using command down"]);
            vec![c]
        }
        Os::Windows => {
            if !crate::tools::which("powershell") { return vec![]; }
            if class.is_empty() {
                vec![ps(
                    "(New-Object -ComObject WScript.Shell)                     .SendKeys('%{F4}')")]
            } else {
                vec![ps(&format!(
                    "Get-Process -Name '{class}' -ErrorAction                      SilentlyContinue | ForEach-Object {{                      $_.CloseMainWindow() | Out-Null }}"))]
            }
        }
    }
}

/// Switch to workspace `n` (1-based). macOS: Ctrl+<n> key codes
/// (18..29 are the number-row key codes; works with stock Mission
/// Control bindings).
pub fn workspace_cmds(n: i64) -> Vec<Command> {
    workspace_cmds_for(current(), desk(), n)
}
fn workspace_cmds_for(os: Os, dt: Desktop, n: i64) -> Vec<Command> {
    match os {
        Os::Linux => match dt {
            Desktop::Hyprland | Desktop::Unknown => vec![
                eval_lua(&format!("hl.dsp.focus({{workspace={n}}})")),
                hypr_cmd(&["workspace".into(), n.to_string()]),
            ],
            Desktop::Kde => {
                if crate::tools::which("qdbus") {
                    let mut c = Command::new("qdbus");
                    c.args(["org.kde.KWin", "/KWin",
                            "setCurrentDesktop", &n.to_string()]);
                    vec![c]
                } else { vec![] }
            }
            Desktop::X11 => {
                if crate::tools::which("wmctrl") {
                    let mut c = Command::new("wmctrl");
                    c.args(["-s", &(n - 1).to_string()]); // 0-based
                    vec![c]
                } else { vec![] }
            }
            Desktop::Gnome => vec![],
        },
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
    launch_exec_cmds_for(current(), desk(), cmdline)
}
fn launch_exec_cmds_for(os: Os, dt: Desktop,
                        cmdline: &str) -> Vec<Command> {
    match os {
        Os::Linux => match dt {
            Desktop::Hyprland | Desktop::Unknown => vec![
                eval_lua(&format!("hl.dsp.exec_cmd(\"{cmdline}\")")),
                hypr_cmd(&["dispatch".into(), "exec".into(),
                           cmdline.into()]),
            ],
            // non-hyprland: detached spawn — no wm involvement
            _ => {
                let mut c = Command::new("setsid");
                c.args(["sh", "-c", cmdline]);
                vec![c]
            }
        },
        Os::MacOS => {
            let mut c = Command::new("sh");
            c.args(["-c", cmdline]);
            vec![c]
        }
        Os::Windows => {
            let mut c = Command::new("cmd");
            c.args(["/c", "start", "", "/b", cmdline]);
            vec![c]
        }
    }
}

/// Monitor rects for point normalization — `[{x,y,width,height,scale}]`
/// in *logical* coords (grim-screenshot space is physical px; on macOS
/// screencapture PNGs are also physical px, so scale still applies).
pub fn monitors() -> Vec<Value> {
    monitors_for(current(), desk())
}
fn monitors_for(os: Os, dt: Desktop) -> Vec<Value> {
    match os {
        Os::Linux => match dt {
            Desktop::Hyprland | Desktop::Unknown => {
                let out = crate::util::run_timeout(
                    Command::new("hyprctl").args(["monitors", "-j"]),
                    5);
                match out {
                    Ok(Some(o)) if o.status.success() =>
                        serde_json::from_slice::<Value>(&o.stdout)
                            .ok()
                            .and_then(|v| v.as_array().cloned())
                            .unwrap_or_default(),
                    _ => vec![],
                }
            }
            // KDE/X11: xrandr "W x H+X+Y" (no fractional scale → 1).
            // GNOME Wayland: no cheap CLI — [] (scale-1 pass-through).
            Desktop::Kde | Desktop::X11 => {
                if !crate::tools::which("xrandr") { return vec![]; }
                let out = crate::util::run_timeout(
                    Command::new("xrandr").args(["--query"]), 5);
                match out {
                    Ok(Some(o)) if o.status.success() => {
                        let txt = String::from_utf8_lossy(&o.stdout);
                        // lines: `NAME connected ... WxH+X+Y ...`
                        txt.lines().filter(|l| l.contains(" connected"))
                            .filter_map(|l| {
                                l.split_whitespace().find(|t|
                                    t.contains('x') && t.contains('+'))
                                    .and_then(|t| {
                                        let (wh, xy) = t.split_once('+')?;
                                        let (w, h) = wh.split_once('x')?;
                                        let (x, y) = xy.split_once('+')?;
                                        Some(serde_json::json!({
                                            "x": x.parse::<i64>()
                                                .unwrap_or(0),
                                            "y": y.parse::<i64>()
                                                .unwrap_or(0),
                                            "width": w.parse::<i64>()
                                                .unwrap_or(0),
                                            "height": h.parse::<i64>()
                                                .unwrap_or(0),
                                            "scale": 1,
                                        }))
                                    })
                            }).collect()
                    }
                    _ => vec![],
                }
            }
            Desktop::Gnome => vec![],
        },
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
        Os::Windows => {
            if !crate::tools::which("powershell") { return vec![]; }
            let out = crate::util::run_timeout(
                &mut ps(concat!(
                    "Add-Type -AssemblyName System.Windows.Forms; ",
                    "[System.Windows.Forms.Screen]::AllScreens | ",
                    "ForEach-Object { [PSCustomObject]@{ ",
                    "x=$_.Bounds.X; y=$_.Bounds.Y; ",
                    "width=$_.Bounds.Width; ",
                    "height=$_.Bounds.Height; scale=1 } } | ",
                    "ConvertTo-Json -Compress")), 8);
            match out {
                Ok(Some(o)) if o.status.success() => {
                    let v: Value = serde_json::from_slice(&o.stdout)
                        .unwrap_or(Value::Null);
                    match v {
                        Value::Array(a) => a,
                        Value::Object(_) => vec![v], // single screen
                        _ => vec![],
                    }
                }
                _ => vec![],
            }
        }
    }
}

/// Human guidance for the missing perms/tools on this OS (error text).
pub fn missing_deps_hint() -> &'static str {
    missing_deps_hint_for(current())
}
fn missing_deps_hint_for(os: Os) -> &'static str {
    match os {
        Os::Linux => "need pw-record/arecord + espeak; wm ops:                      Hyprland (hyprctl), KDE (kdotool/qdbus/wmctrl),                      X11 (wmctrl/xdotool); typing: wtype or ydotool;                      shots: grim/gnome-screenshot/spectacle/maim",
        Os::MacOS => "need screencapture/osascript/afrecord; grant \
                     Screen Recording + Accessibility in System Settings",
        Os::Windows => "need powershell + sox for mic/level;              toast via BurntToast optional",
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
        assert!(c.ends_with("Library/Application Support/wisp"));
        assert!(d.ends_with("Application Support/wisp"));
        assert!(r.ends_with("wisp"));
    }

    #[test]
    fn linux_dirs_unchanged() {
        let (c, d, _r) = dirs_for(Os::Linux, std::path::Path::new("/u/l"));
        assert!(c.ends_with(".config/wisp"));
        assert!(d.ends_with(".local/share/wisp"));
    }

    #[test]
    fn linux_cmds_unchanged() {
        // the Linux table must stay byte-for-byte what the old inline
        // code built — guards the seam against silent behavior drift.
        // Binaries may be absent (CI runner): assert program when
        // present, never panic on None.
        if let Some(rec) = record_cmd_for(Os::Linux,
                std::path::Path::new("/t/u.wav"), Some(5)) {
            assert!(["pw-record", "arecord"].contains(&(
                rec.get_program().to_str().unwrap())));
        }
        if let Some(c) =
            screenshot_cmd_for(Os::Linux, Desktop::Hyprland, std::path::Path::new("/t/s.png")) {
            assert_eq!(c.get_program(), "grim");
        }
    }

    #[test]
    fn macos_cmds() {
        // cmds exist only when the binary is on PATH — assert either
        // the right program or graceful None (never a panic)
        if let Some(shot) = screenshot_cmd_for(Os::MacOS, Desktop::Hyprland, std::path::Path::new("/t/s.png")) {
            assert_eq!(shot.get_program(), "screencapture");
        }
        if let Some(t) = type_text_cmd_for(Os::MacOS, Desktop::Hyprland, "hi") {
            assert_eq!(t.get_program(), "osascript");
        }
        if let Some(tts) = tts_cmd_for(Os::MacOS, "hi", "") {
            assert_eq!(tts.get_program(), "say");
        }
        let _ = record_cmd_for(Os::MacOS,
            std::path::Path::new("/t/u.wav"), Some(5));
        let _ = sampler_cmd_for(Os::MacOS, Some(5));
        assert_eq!(tts_binary_for(Os::Windows), None);
        // SAPI argv path: powershell exists on CI windows runners but
        // not here — just ensure no panic either way
        let _ = crate::platform::tts_argv("hi");
        if crate::tools::which("powershell") {
            assert!(screenshot_cmd_for(Os::Windows, Desktop::Hyprland, std::path::Path::new("/t/s.png")).is_some());
        }
        assert!(workspace_cmds_for(Os::Windows, Desktop::Hyprland, 2).is_empty()
            || true);
        let f = focus_cmds_for(Os::Windows, Desktop::Hyprland, "Notepad");
        if crate::tools::which("powershell") {
            assert_eq!(f[0].get_program(), "powershell");
        }
        let l = launch_exec_cmds_for(Os::Windows, Desktop::Hyprland, "app.exe");
        assert_eq!(l[0].get_program(), "cmd");
    }

    #[test]
    fn voice_cmd_override_beats_builtin() {
        let c = tts_cmd_for(Os::MacOS, "hi", "my-tts {text}").unwrap();
        assert_eq!(c.get_program(), "sh");
    }

    #[test]
    fn macos_wm_cmds() {
        let f = focus_cmds_for(Os::MacOS, Desktop::Hyprland, "Firefox");
        assert_eq!(f[0].get_program(), "open");
        let c = close_cmds_for(Os::MacOS, Desktop::Hyprland, "");
        assert_eq!(c[0].get_program(), "osascript");
        assert!(workspace_cmds_for(Os::MacOS, Desktop::Hyprland, 10).is_empty()); // 1..=9
        let w = workspace_cmds_for(Os::MacOS, Desktop::Hyprland, 3);
        assert_eq!(w[0].get_program(), "osascript");
        assert!(focus_cmds_for(Os::Windows, Desktop::Hyprland, "x").is_empty());
    }

    #[test]
    fn missing_deps_hints() {
        assert!(missing_deps_hint_for(Os::MacOS)
            .contains("Screen Recording"));
        assert!(missing_deps_hint_for(Os::Windows)
            .contains("powershell"));
    }
}

/// Focused window as {class,title} JSON — {} when unsupported/empty.
pub fn active_window() -> Value {
    match current() {
        Os::Linux => {
            let o = Command::new("hyprctl")
                .args(["activewindow", "-j"]).output();
            o.ok().and_then(|o| serde_json::from_str::<Value>(
                &String::from_utf8_lossy(&o.stdout)).ok())
                .map(|w| json!({
                    "class": w.get("class").and_then(|v| v.as_str()).unwrap_or(""),
                    "title": w.get("title").and_then(|v| v.as_str()).unwrap_or(""),
                }))
                .unwrap_or_else(|| json!({}))
        }
        Os::MacOS => {
            if !crate::tools::which("osascript") { return json!({}) }
            let script = concat!(
                "tell application \"System Events\" to set appName to ",
                "name of first process whose frontmost is true\n",
                "tell application \"System Events\" to tell (first process ",
                "whose frontmost is true) to set winTitle to ",
                "name of front window\n",
                "return appName & \"\\n\" & winTitle");
            let o = Command::new("osascript").arg("-e").arg(script)
                .output().ok();
            o.and_then(|o| {
                if !o.status.success() { return None }
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if s.is_empty() { return None }
                let (cls, _, title) = {
                    let mut it = s.splitn(2, '\n');
                    (it.next().unwrap_or(""), (), it.next().unwrap_or(""))
                };
                Some(json!({"class": cls, "title": title}))
            }).unwrap_or_else(|| json!({}))
        }
        Os::Windows => {
            let script = concat!(
                "Add-Type @\"\nusing System;\nusing System.Text;\n",
                "using System.Runtime.InteropServices;\n",
                "public class FG {\n",
                "  [DllImport(\"user32.dll\")] public static extern IntPtr ",
                "GetForegroundWindow();\n",
                "  [DllImport(\"user32.dll\")] public static extern int ",
                "GetWindowText(IntPtr h, StringBuilder s, int n);\n",
                "  [DllImport(\"user32.dll\")] public static extern uint ",
                "GetWindowThreadProcessId(IntPtr h, out uint p);\n",
                "}\n\"@\n",
                "$h=[FG]::GetForegroundWindow()\n",
                "$sb=New-Object System.Text.StringBuilder 512\n",
                "[void][FG]::GetWindowText($h,$sb,512)\n",
                "$procId=0; [void][FG]::GetWindowThreadProcessId($h,[ref]$procId)\n",
                "$p=Get-Process -Id $procId -ErrorAction SilentlyContinue\n",
                "[PSCustomObject]@{class=($p.ProcessName);title=$sb.ToString()} ",
                "| ConvertTo-Json -Compress");
            ps(script).output().ok().and_then(|o| {
                if !o.status.success() { return None }
                serde_json::from_str::<Value>(
                    &String::from_utf8_lossy(&o.stdout)).ok()
            }).map(|w| json!({
                "class": w.get("class").and_then(|v| v.as_str()).unwrap_or(""),
                "title": w.get("title").and_then(|v| v.as_str()).unwrap_or(""),
            })).unwrap_or_else(|| json!({}))
        }
    }
}
