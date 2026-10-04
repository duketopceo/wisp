"""Newline-delimited JSON IPC: daemon server + client.

The daemon accepts one JSON object per connection and replies with one
JSON object. Commands: listen, status, choice, stop, task_status,
task_cancel. Widgets and the trigger shim are plain clients.

Exception: `{"cmd":"subscribe"}` turns the connection into a push
stream of newline-delimited JSON (see docs/IPC_CONTRACT.md, "Push
stream"): hello, snapshot, then StateBus events until either side
closes. Each subscriber has a bounded queue; one that cannot keep up is
sent a final `overflow` event and dropped, never blocking the bus.

Transport per OS (mirrors rs/wispd/src/ipc.rs):
  linux/macos → AF_UNIX socket at SOCK_FILE
  windows     → 127.0.0.1 TCP; the ephemeral port is written to
                SOCK_FILE (a plain file) for client discovery. Same
                protocol — fixture replay is identical.
"""
import json
import socket
import threading
import time

from . import config
from . import platform as _plat
from . import state as _state

_TIMEOUT = 10
_TCP = _plat.current() == "windows"


def _use_tcp() -> bool:
    """TCP loopback on Windows, AF_UNIX elsewhere. Read dynamically
    (not just at import) so WISP_OS overrides and tests take effect,
    while the patched `ipc._TCP` module flag still forces TCP on."""
    if _TCP:
        return True
    try:
        return _plat.current() == "windows"
    except Exception:
        return False


class Daemon:
    """IPC server. `handler(cmd_dict) -> dict` supplies the responses.

    `bus` (a StateBus) enables `subscribe`. `sub_queue` bounds each
    subscriber's queue, `ping_s` is the idle keep-alive interval (also
    how a vanished client is noticed), `send_timeout` drops a client
    whose socket stays unwritable that long."""

    def __init__(self, handler, sock_file=config.SOCK_FILE, bus=None,
                 sub_queue: int = 256, ping_s: float = 15.0,
                 send_timeout: float = 5.0):
        self._handler = handler
        self._bus = bus
        self._sub_queue = sub_queue
        self._ping_s = ping_s
        self._send_timeout = send_timeout
        self._sock_file = sock_file
        self._server = None
        self._thread = None
        self._running = False

    def start(self) -> None:
        self._sock_file.parent.mkdir(parents=True, exist_ok=True)
        if self._sock_file.exists():
            self._sock_file.unlink()
        if _use_tcp():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            srv.listen(8)
            srv.settimeout(0.5)
            self._sock_file.write_text(str(srv.getsockname()[1]))
        else:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(self._sock_file))
            srv.listen(8)
            srv.settimeout(0.5)
        self._server = srv
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def healthy(self) -> bool:
        """Accept loop is running (watchdog liveness, W29)."""
        t = self._thread
        return bool(self._running and t is not None and t.is_alive())

    def stop(self) -> None:
        self._running = False
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        try:
            self._sock_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(_TIMEOUT)
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            try:
                cmd = json.loads(data.decode().strip() or "{}")
            except json.JSONDecodeError:
                resp = {"ok": False, "error": "malformed json"}
            else:
                if isinstance(cmd, dict) and cmd.get("cmd") == "subscribe":
                    self._stream(conn, cmd)
                    return
                try:
                    resp = self._handler(cmd)
                except Exception as e:
                    resp = {"ok": False, "error": str(e)}
            conn.sendall(json.dumps(resp).encode() + b"\n")
        except (OSError, socket.timeout):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


    def _stream(self, conn: socket.socket, cmd: dict) -> None:
        """Serve one subscriber until it disconnects, overflows or the
        daemon stops. Runs on the connection's own thread."""
        def put(obj) -> None:
            conn.sendall(json.dumps(obj).encode() + b"\n")

        topics = cmd.get("topics")
        if topics is not None and (
                not isinstance(topics, list)
                or not set(topics) <= _state.TOPICS):
            put({"type": "hello", "ok": False,
                 "error": "unknown topic (valid: "
                          + ", ".join(sorted(_state.TOPICS)) + ")"})
            return
        if self._bus is None:
            put({"type": "hello", "ok": False,
                 "error": "subscribe unavailable: no state bus"})
            return
        conn.settimeout(self._send_timeout)
        sub = self._bus.subscribe(self._sub_queue, topics)
        try:
            snap = sub.snapshot
            put({"type": "hello", "ok": True,
                 "contract_version": _state.CONTRACT_VERSION,
                 "topics": sorted(topics if topics is not None
                                  else _state.TOPICS)})
            put({"type": "snapshot", "seq": snap.get("seq"),
                 "state": snap})
            while self._running:
                ev = sub.get(self._ping_s)
                if ev is None:
                    if sub.closed:
                        break
                    put({"type": "ping"})
                    continue
                put(ev)
        except (OSError, socket.timeout):
            pass
        finally:
            self._bus.unsubscribe(sub)


def _connect(sock_file, timeout: float) -> socket.socket:
    if _TCP:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            port = int(sock_file.read_text().strip())
            s.connect(("127.0.0.1", port))
        except Exception:
            s.close()
            raise ConnectionError("no daemon (port file absent)")
        return s
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_file))
    except OSError:
        s.close()
        raise
    return s


def subscribe(topics=None, sock_file=config.SOCK_FILE,
              timeout: float = 60.0):
    """Generator over one subscription: yields hello, snapshot, then
    events/pings as dicts. Ends when the daemon closes the stream (an
    `overflow` event is the last item after a drop). `timeout` is the
    max silence tolerated (the daemon pings every 15 s). Raises
    ConnectionError when the daemon is absent or refuses."""
    s = _connect(sock_file, timeout)
    f = None
    try:
        msg = {"cmd": "subscribe"}
        if topics is not None:
            msg["topics"] = list(topics)
        s.sendall(json.dumps(msg).encode() + b"\n")
        f = s.makefile("rb")
        first = True
        while True:
            try:
                raw = f.readline()
            except socket.timeout:
                raise ConnectionError("subscription went silent")
            if not raw:
                if first:
                    raise ConnectionError("daemon closed without a reply")
                return
            ev = json.loads(raw.decode())
            if first and ev.get("ok") is False:
                raise ConnectionError(ev.get("error", "refused"))
            first = False
            yield ev
    finally:
        if f is not None:
            f.close()  # the makefile holds the fd open past s.close()
        s.close()


def watch(topics=None, sock_file=config.SOCK_FILE, retry_s: float = 1.0,
          stop: threading.Event | None = None, timeout: float = 60.0):
    """Like `subscribe` but reconnects forever (until `stop` is set).
    Every reconnect begins with a fresh `snapshot`, so a consumer never
    has to reason about the gap."""
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            for ev in subscribe(topics, sock_file, timeout):
                yield ev
                if stop.is_set():
                    return
        except (OSError, ConnectionError, ValueError):
            pass
        stop.wait(retry_s)


def send(cmd: dict, sock_file=config.SOCK_FILE, timeout: float = _TIMEOUT) -> dict:
    """Send one command to the daemon; returns its reply dict.

    Raises ConnectionError when the socket is absent/refused."""
    tcp = _use_tcp()
    if tcp:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            port = int(sock_file.read_text().strip())
            s.connect(("127.0.0.1", port))
        except Exception:
            s.close()
            raise ConnectionError("no daemon (port file absent)")
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
    try:
        if not tcp:
            s.connect(str(sock_file))
        s.sendall(json.dumps(cmd).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    if not data:
        raise ConnectionError("daemon closed connection without a reply")
    return json.loads(data.decode())


def alive(sock_file=config.SOCK_FILE) -> bool:
    try:
        send({"cmd": "status"}, sock_file=sock_file, timeout=2)
        return True
    except (OSError, ConnectionError):
        return False
