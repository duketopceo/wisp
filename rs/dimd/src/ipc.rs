//! Newline-delimited JSON IPC — contract v1.
//! One JSON object per connection; {"ok":bool,...} reply envelope.
//!
//! Transport per OS:
//!   linux/macos → unix socket at `sock` path (AF_UNIX on Windows is
//!                 avoided — Python parity uses the same TCP path)
//!   windows     → 127.0.0.1 TCP; the chosen ephemeral port is written
//!                 to `sock` (a plain file) so clients discover it.
//!                 Same protocol, so fixture replay is identical.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

fn serve_conn<C>(conn: C, handler: Arc<dyn Fn(Value) -> Value + Send + Sync>)
where C: Read + Write + Send + 'static + CloneStream {
    std::thread::spawn(move || {
        let mut line = String::new();
        let mut r = BufReader::new(conn.clone_stream());
        let resp = match r.read_line(&mut line) {
            Ok(_) => match serde_json::from_str::<Value>(line.trim()) {
                Ok(cmd) => handler(cmd),
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

/// Minimal trait so unix `UnixStream`/`UnixStream` clone and
/// `TcpStream::try_clone` share `serve_conn`.
pub trait CloneStream {
    fn clone_stream(&self) -> Self;
}

#[cfg(unix)]
mod imp {
    use super::*;
    use std::os::unix::net::{UnixListener, UnixStream};

    impl CloneStream for UnixStream {
        fn clone_stream(&self) -> Self {
            // BufReader needs its own handle; UnixStream::try_clone
            // gives an independent fd.
            self.try_clone().expect("unix stream clone")
        }
    }

    pub fn serve(sock: PathBuf,
                 handler: Arc<dyn Fn(Value) -> Value + Send + Sync>,
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
                    let _ = conn.set_read_timeout(
                        Some(Duration::from_secs(10)));
                    serve_conn(conn, handler.clone());
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(50));
                }
                Err(e) => {
                    // transient accept errors (EMFILE/EINTR) must not
                    // kill the daemon — Python's accept loop continues
                    eprintln!("accept: {e}");
                    std::thread::sleep(Duration::from_millis(50));
                }
            }
        }
        let _ = std::fs::remove_file(&sock);
        Ok(())
    }

    pub fn send(sock: &PathBuf, cmd: &Value) -> Result<Value, String> {
        let mut c =
            UnixStream::connect(sock).map_err(|e| e.to_string())?;
        c.set_read_timeout(Some(Duration::from_secs(10))).ok();
        c.write_all(
            (serde_json::to_string(cmd).unwrap() + "\n").as_bytes())
            .map_err(|e| e.to_string())?;
        let mut buf = String::new();
        c.read_to_string(&mut buf).map_err(|e| e.to_string())?;
        serde_json::from_str(buf.trim()).map_err(|e| e.to_string())
    }
}

/// TCP loopback + port-file transport — used on Windows, and the code
/// path is exercised on Linux by `tcp_roundtrip` below.
mod tcp {
    use super::*;
    use std::net::{TcpListener, TcpStream};

    impl CloneStream for TcpStream {
        fn clone_stream(&self) -> Self {
            self.try_clone().expect("tcp stream clone")
        }
    }

    pub fn serve(sock: PathBuf,
                 handler: Arc<dyn Fn(Value) -> Value + Send + Sync>,
                 running: Arc<AtomicBool>) -> std::io::Result<()> {
        if let Some(p) = sock.parent() {
            std::fs::create_dir_all(p)?;
        }
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let port = listener.local_addr()?.port();
        std::fs::write(&sock, port.to_string())?;
        listener.set_nonblocking(true)?;
        while running.load(Ordering::Relaxed) {
            match listener.accept() {
                Ok((conn, _)) => {
                    let _ = conn.set_read_timeout(
                        Some(Duration::from_secs(10)));
                    serve_conn(conn, handler.clone());
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(50));
                }
                Err(e) => {
                    eprintln!("accept: {e}");
                    std::thread::sleep(Duration::from_millis(50));
                }
            }
        }
        let _ = std::fs::remove_file(&sock);
        Ok(())
    }

    pub fn send(sock: &PathBuf, cmd: &Value) -> Result<Value, String> {
        let port: u16 = std::fs::read_to_string(sock)
            .map_err(|e| e.to_string())?
            .trim().parse().map_err(|e: std::num::ParseIntError|
                e.to_string())?;
        let mut c = TcpStream::connect(("127.0.0.1", port))
            .map_err(|e| e.to_string())?;
        c.set_read_timeout(Some(Duration::from_secs(10))).ok();
        c.write_all(
            (serde_json::to_string(cmd).unwrap() + "\n").as_bytes())
            .map_err(|e| e.to_string())?;
        // signal end-of-request so read_to_string terminates
        c.shutdown(std::net::Shutdown::Write).ok();
        let mut buf = String::new();
        c.read_to_string(&mut buf).map_err(|e| e.to_string())?;
        serde_json::from_str(buf.trim()).map_err(|e| e.to_string())
    }
}

#[cfg(unix)]
pub use imp::{send, serve};
#[cfg(not(unix))]
pub use tcp::{send, serve};

pub fn alive(sock: &PathBuf) -> bool {
    send(sock, &json!({"cmd": "status"})).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicBool;

    /// The Windows transport path — exercised on Linux so fixture
    /// replay semantics are proven on the exact code that ships.
    #[test]
    fn tcp_roundtrip() {
        let dir = std::env::temp_dir()
            .join(format!("dimd-tcp-{}", std::process::id()));
        let sock = dir.join("dimd.sock");
        let running = Arc::new(AtomicBool::new(true));
        let r2 = running.clone();
        let s = sock.clone();
        let h = std::thread::spawn(move ||
            tcp::serve(s, Arc::new(|cmd| json!({
                "ok": true, "echo": cmd.get("cmd")
            })), r2));
        for _ in 0..40 {
            if sock.exists() { break; }
            std::thread::sleep(Duration::from_millis(25));
        }
        let r = tcp::send(&sock, &json!({"cmd": "status"})).unwrap();
        assert_eq!(r["ok"], true);
        assert_eq!(r["echo"], "status");
        running.store(false, Ordering::Relaxed);
        let _ = h.join();
    }
}
