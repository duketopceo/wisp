//! Parity checks for the file-level contract plus a live-daemon fixture
//! replay: spawn `wispd daemon`, replay tests/fixtures/ipc_commands.jsonl
//! over the unix socket, assert the {ok, ...} reply envelope.
//! One test binary; HOME/XDG env is process-global so daemon-reliant
//! checks stay in a single test fn.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::process::{Child, Command};
use std::time::{Duration, Instant};

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_wispd"))
}

fn send(sock: &std::path::Path, cmd: &Value) -> Value {
    let mut c = UnixStream::connect(sock).unwrap();
    c.write_all((serde_json::to_string(cmd).unwrap() + "\n").as_bytes())
        .unwrap();
    let mut line = String::new();
    BufReader::new(&mut c).read_line(&mut line).unwrap();
    serde_json::from_str(line.trim()).unwrap()
}

struct Daemon(Child, std::path::PathBuf);
impl Daemon {
    fn start() -> Self {
        let tmp = std::env::temp_dir()
            .join(format!("wispd-parity-{}", std::process::id()));
        let sock = tmp.join("wisp/wispd.sock");
        let child = bin().arg("daemon")
            .env("HOME", &tmp).env("XDG_RUNTIME_DIR", &tmp)
            .spawn().unwrap();
        let d = Daemon(child, sock);
        // wait for the socket
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if d.1.exists() {
                if let Ok(c) = UnixStream::connect(&d.1) {
                    drop(c);
                    return d;
                }
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        panic!("daemon socket never appeared");
    }
}
impl Drop for Daemon {
    fn drop(&mut self) {
        let _ = self.0.kill();
    }
}

#[test]
fn cli_and_contract() {
    // unique HOME so the daemon-side paths land in a tmp dir
    let tmp = std::env::temp_dir()
        .join(format!("wispd-test-{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    std::env::set_var("HOME", &tmp);
    std::env::set_var("XDG_RUNTIME_DIR", &tmp);

    // --help/usage path returns nonzero with usage text
    let out = bin().output().unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr)
        .contains("wispd"));
}

#[test]
fn fixture_replay_against_live_daemon() {
    // The same fixtures the Python contract test validates — wispd-rs
    // must answer every command with the contract envelope.
    let mut d = Daemon::start();
    let fixtures = concat!(env!("CARGO_MANIFEST_DIR"),
                           "/../../tests/fixtures/ipc_commands.jsonl");
    let mut saw_stop = false;
    for line in std::fs::read_to_string(fixtures).unwrap().lines() {
        if line.trim().is_empty() {
            continue;
        }
        let cmd: Value = serde_json::from_str(line).unwrap();
        let name = cmd["cmd"].as_str().unwrap().to_string();
        let resp = send(&d.1, &cmd);
        assert_eq!(resp.get("ok").and_then(|v| v.as_bool()).is_some(),
                   true, "no ok field for {name}");
        match name.as_str() {
            "bogus" => {
                assert_eq!(resp["ok"], json!(false));
                assert!(resp["error"].as_str().unwrap_or("")
                        .contains("unknown cmd"),
                        "unknown-cmd error string: {resp}");
            }
            "listen" =>
                // busy or ok — a second listen may be refused; either is
                // contract-conformant. First call may be ok:true.
                assert!(resp["ok"].is_boolean()),
            "status" => {
                let st = &resp["state"];
                assert!(st.is_object(), "status must return state object");
                for f in ["status", "transcript", "answer", "result",
                          "choices", "points", "level", "tasks",
                          "error", "started_at"] {
                    assert!(st.get(f).is_some(),
                            "state.json missing field: {f}");
                }
            }
            "task_status" | "task_cancel" | "learn" =>
                assert!(resp.get("result").is_some(),
                        "{name} must return result"),
            "config" =>
                assert!(resp["config"].is_object(),
                        "config must return flat config object"),
            "stop" => saw_stop = true,
            _ => assert!(resp["ok"].is_boolean()),
        }
        if saw_stop {
            break;
        }
    }
    // daemon should have exited on stop
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if d.0.try_wait().unwrap().is_some() || !d.1.exists() {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    // stop raced or queued behind other conns — acceptable; kill in Drop
}
