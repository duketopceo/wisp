//! Newline-delimited JSON over a unix socket — contract v1.
//! One JSON object per connection; {"ok":bool,...} reply envelope.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

pub fn serve(sock: PathBuf, handler: Arc<dyn Fn(Value) -> Value + Send + Sync>,
             running: Arc<AtomicBool>) -> std::io::Result<()> {
    if let Some(p) = sock.parent() {
        std::fs::create_dir_all(p)?;
    }
    let _ = std::fs::remove_file(&sock);
    let listener = UnixListener::bind(&sock)?;
    listener.set_nonblocking(true)?;
    while running.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((conn, _)) => {
                let h = handler.clone();
                std::thread::spawn(move || {
                    let _ = conn.set_read_timeout(Some(Duration::from_secs(10)));
                    let mut line = String::new();
                    let mut r = BufReader::new(&conn);
                    let resp = match r.read_line(&mut line) {
                        Ok(_) => match serde_json::from_str::<Value>(line.trim()) {
                            Ok(cmd) => h(cmd),
                            Err(_) => json!({"ok": false, "error": "malformed json"}),
                        },
                        Err(e) => json!({"ok": false, "error": e.to_string()}),
                    };
                    let mut c = conn;
                    let _ = c.write_all(
                        (serde_json::to_string(&resp).unwrap() + "\n").as_bytes(),
                    );
                });
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                // transient accept errors (EMFILE/EINTR) must not kill
                // the daemon — Python's accept loop continues too
                eprintln!("accept: {e}");
                std::thread::sleep(Duration::from_millis(50));
            }
        }
    }
    let _ = std::fs::remove_file(&sock);
    Ok(())
}

pub fn send(sock: &PathBuf, cmd: &Value) -> Result<Value, String> {
    let mut c = UnixStream::connect(sock).map_err(|e| e.to_string())?;
    c.set_read_timeout(Some(Duration::from_secs(10))).ok();
    c.write_all((serde_json::to_string(cmd).unwrap() + "\n").as_bytes())
        .map_err(|e| e.to_string())?;
    let mut buf = String::new();
    c.read_to_string(&mut buf).map_err(|e| e.to_string())?;
    serde_json::from_str(buf.trim()).map_err(|e| e.to_string())
}

pub fn alive(sock: &PathBuf) -> bool {
    send(sock, &json!({"cmd": "status"})).is_ok()
}
