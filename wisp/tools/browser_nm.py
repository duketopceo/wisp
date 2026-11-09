"""Native messaging for the browser lane.

Chrome starts `wispd nmhost` when the Wisp extension connects (the host
manifest names the extension's id in `allowed_origins`, so Chrome itself
refuses any other extension). The host is a plain relay between Chrome's
stdio and a Unix socket that `wispd` serves, so the only door into the lane
is a socket mode 0600 whose peer must be the same user.

Framing, both on stdio and on the socket: a 32-bit length in native byte
order, then that many bytes of UTF-8 JSON. Chrome caps a message to the
browser at 1 MB, so commands stay small; screenshots travel the other way
(browser to host, up to 64 MiB in Chrome, MAX_FROM_BROWSER here).

Messages carry a `t` (type):
  browser -> wisp: hello {v, ext}, result {id, ok, results|error},
                   stop, ping, bye
  wisp -> browser: hello_ok {v}, cmd {cmd}, pong, error {code, message}
"""
import base64
import hashlib
import json
import os
import pathlib
import shlex
import socket
import stat
import struct
import sys
import threading

HOST_NAME = "com.wisp.browser"
PROTOCOL = 1
SOCKET_NAME = "browser.sock"
MAX_TO_BROWSER = 1024 * 1024         # Chrome's cap for host -> browser
MAX_FROM_BROWSER = 16 * 1024 * 1024  # ours; Chrome allows 64 MiB
HELLO_TIMEOUT_S = 10.0
WRITER_TICK_S = 0.25
_LEN = struct.Struct("=I")

# The development extension id: the id Chrome derives from the public key
# pinned in browser-extension/wxt.config.ts, so an unpacked build keeps one
# id. Only used when the user asks for it (`--dev`).
DEV_EXTENSION_ID = "cbbeeaamnkogifjkglfcklifijjnjpma"

# user-level manifest directories under $HOME. `documented` is true for the
# locations the Chrome docs list; the others follow each browser's own
# config directory and are checked by `wispd browser status`.
BROWSERS = {
    "chrome": (".config/google-chrome/NativeMessagingHosts", True),
    "chromium": (".config/chromium/NativeMessagingHosts", True),
    "brave": (".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
              False),
    "edge": (".config/microsoft-edge/NativeMessagingHosts", False),
}


class FrameError(ValueError):
    """A frame that is too long, truncated or not a JSON object."""


def extension_id_from_key(key_b64: str) -> str:
    """The id Chrome assigns an extension whose manifest has this `key`."""
    digest = hashlib.sha256(base64.b64decode(key_b64)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


# -- framing ----------------------------------------------------------------

def encode_frame(obj: dict, limit: int = MAX_TO_BROWSER) -> bytes:
    body = json.dumps(obj, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    if len(body) > limit:
        raise FrameError(f"message is {len(body)} bytes; the most is {limit}")
    return _LEN.pack(len(body)) + body


def _read_exact(read, n: int) -> bytes:
    chunks, got = [], 0
    while got < n:
        b = read(n - got)
        if not b:
            raise EOFError("stream closed")
        chunks.append(b)
        got += len(b)
    return b"".join(chunks)


def read_frame(read, limit: int = MAX_FROM_BROWSER) -> dict:
    """The next message. `read(n)` returns up to n bytes, b'' at EOF.
    Raises EOFError at a clean end and FrameError for a bad frame."""
    head = read(_LEN.size)
    if not head:
        raise EOFError("stream closed")
    if len(head) < _LEN.size:
        head += _read_exact(read, _LEN.size - len(head))
    (n,) = _LEN.unpack(head)
    if n > limit:
        raise FrameError(f"message is {n} bytes; the most is {limit}")
    try:
        raw = _read_exact(read, n)
    except EOFError as e:
        raise FrameError("message cut short") from e
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise FrameError("message is not valid JSON") from e
    if not isinstance(obj, dict):
        raise FrameError("message is not a JSON object")
    return obj


# -- the server inside wispd ----------------------------------------------------

def _peer_uid(conn: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                            struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


class NativeServer:
    """Accepts the relay on a private Unix socket and feeds the Lane."""

    def __init__(self, lane, path, *, uid_of=_peer_uid):
        self.lane = lane
        self.path = pathlib.Path(path)
        self._uid_of = uid_of
        self._sock = None
        self._conns: set = set()
        self._lock = threading.Lock()
        self._closed = threading.Event()

    def start(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.stat().st_uid == os.getuid():
            os.chmod(self.path.parent, 0o700)
        self._clear_stale()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(str(self.path))
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        s.listen(4)
        self._sock = s
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _clear_stale(self) -> None:
        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(mode):
            raise OSError(f"{self.path} exists and is not a socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(str(self.path))
        except OSError:
            self.path.unlink()          # nobody listens: a leftover
            return
        finally:
            probe.close()
        raise OSError(f"another wispd already serves {self.path}")

    def close(self) -> None:
        self._closed.set()
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            _shutdown(c)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except (OSError, AttributeError):
                return
            threading.Thread(target=self._serve, args=(conn,),
                             daemon=True).start()

    def _send(self, conn, wlock, obj: dict) -> None:
        data = encode_frame(obj)
        with wlock:
            conn.sendall(data)

    def _serve(self, conn: socket.socket) -> None:
        wlock = threading.Lock()
        token = object()
        attached = False
        try:
            uid = self._uid_of(conn)
            if uid is not None and uid != os.getuid():
                return
            conn.settimeout(HELLO_TIMEOUT_S)
            hello = read_frame(conn.recv)
            if hello.get("t") != "hello" or hello.get("v") != PROTOCOL:
                self._send(conn, wlock, {
                    "t": "error", "code": "bad_hello",
                    "message": f"expected hello with v={PROTOCOL}"})
                return
            conn.settimeout(None)
            with self._lock:
                older = list(self._conns)
                self._conns.add(conn)
            for c in older:          # one browser at a time: the newest wins
                _shutdown(c)
            self.lane.native_attach(token)
            attached = True
            self._send(conn, wlock, {"t": "hello_ok", "v": PROTOCOL})
            threading.Thread(target=self._write_loop,
                             args=(conn, wlock), daemon=True).start()
            self._read_loop(conn, wlock)
        except (OSError, EOFError, FrameError):
            pass
        finally:
            if attached:
                self.lane.native_detach(token)
            with self._lock:
                self._conns.discard(conn)
            _shutdown(conn)

    def _read_loop(self, conn, wlock) -> None:
        while True:
            msg = read_frame(conn.recv)
            kind = msg.get("t")
            if kind == "result":
                self.lane.deliver(msg)
            elif kind == "stop":
                self.lane.stop()
            elif kind == "ping":
                self._send(conn, wlock, {"t": "pong"})
            elif kind == "bye":
                return
            else:
                self._send(conn, wlock, {
                    "t": "error", "code": "unknown_message",
                    "message": f"unknown message type {str(kind)[:40]!r}"})

    def _write_loop(self, conn, wlock) -> None:
        while not self._closed.is_set():
            with self._lock:
                if conn not in self._conns:
                    return
            cmd = self.lane.next_command(WRITER_TICK_S)
            if not cmd:
                continue
            try:
                self._send(conn, wlock, {"t": "cmd", "cmd": cmd})
            except FrameError:
                self.lane.deliver({"id": cmd.get("id"), "ok": False,
                                   "error": "the command is too large to send"})
            except OSError:
                self.lane.requeue(cmd)
                return


def _shutdown(conn) -> None:
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except OSError:
        pass


# -- the relay Chrome starts (`wispd nmhost`) -------------------------------

def relay(stdin, stdout, sock_path, *, connect_timeout: float = 5.0) -> int:
    """Pipe Chrome's frames to the socket and back until either side ends.
    `stdin` and `stdout` are binary streams. Returns an exit code."""
    def say(obj):
        stdout.write(encode_frame(obj))
        stdout.flush()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(connect_timeout)
    try:
        s.connect(str(sock_path))
    except OSError:
        s.close()
        say({"t": "error", "code": "wisp_unavailable",
             "message": "Wisp is not running, or its browser lane is off."})
        return 0
    s.settimeout(None)

    def up() -> None:             # Chrome -> wispd
        try:
            while True:
                msg = read_frame(stdin.read)
                s.sendall(encode_frame(msg, MAX_FROM_BROWSER))
        except (EOFError, FrameError, OSError):
            pass
        finally:
            _shutdown(s)

    t = threading.Thread(target=up, daemon=True)
    t.start()
    try:
        while True:
            say(read_frame(s.recv, MAX_TO_BROWSER))
    except (EOFError, FrameError, OSError):
        pass
    finally:
        _shutdown(s)
    return 0


def main(argv: list[str]) -> int:
    """`wispd nmhost [origin]`: Chrome passes the caller's origin."""
    from .. import config
    return relay(sys.stdin.buffer, sys.stdout.buffer,
                 config.RUN_DIR / SOCKET_NAME)


# -- installing the host manifest -------------------------------------------

def launcher_path(data_dir: pathlib.Path) -> pathlib.Path:
    return data_dir / "native-host" / "wisp-nmhost"


def _write_private(path: pathlib.Path, text: str, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    tmp.replace(path)


def host_manifest(launcher: pathlib.Path, ext_ids: list[str]) -> dict:
    return {"name": HOST_NAME,
            "description": "Wisp browser lane",
            "path": str(launcher),
            "type": "stdio",
            "allowed_origins": [f"chrome-extension://{i}/" for i in ext_ids]}


def _valid_id(i: str) -> bool:
    return len(i) == 32 and all("a" <= c <= "p" for c in i)


def plan_install(home: pathlib.Path, data_dir: pathlib.Path,
                 ext_ids: list[str], browsers: list[str] | None = None):
    """(launcher, [(browser, manifest path)], error). Without `browsers`,
    every browser whose config directory exists under `home`."""
    bad = [i for i in ext_ids if not _valid_id(i)]
    if bad:
        return None, [], f"not an extension id: {bad[0]!r}"
    if not ext_ids:
        return None, [], "no extension id (pass --extension-id or --dev)"
    names = browsers or [
        b for b, (rel, _) in BROWSERS.items()
        if (home / pathlib.Path(rel).parent).is_dir()]
    unknown = [b for b in names if b not in BROWSERS]
    if unknown:
        return None, [], f"unknown browser {unknown[0]!r}"
    if not names:
        return None, [], "no supported browser found under " + str(home)
    targets = [(b, home / BROWSERS[b][0] / f"{HOST_NAME}.json")
               for b in names]
    return launcher_path(data_dir), targets, ""


def install_host(home: pathlib.Path, data_dir: pathlib.Path,
                 python: str, wispd: str, ext_ids: list[str],
                 browsers: list[str] | None = None) -> dict:
    """Write the launcher and one host manifest per browser. Returns
    {"launcher", "manifests": [{browser, path, documented}]}; raises
    ValueError with a sentence when the request cannot be met."""
    launcher, targets, err = plan_install(home, data_dir, ext_ids, browsers)
    if err:
        raise ValueError(err)
    _write_private(launcher,
                   "#!/bin/sh\nexec " + shlex.join([python, wispd, "nmhost"])
                   + ' "$@"\n', 0o700)
    written = []
    for browser, path in targets:
        _write_private(path, json.dumps(host_manifest(launcher, ext_ids),
                                        indent=2) + "\n", 0o600)
        written.append({"browser": browser, "path": str(path),
                        "documented": BROWSERS[browser][1]})
    record = {"launcher": str(launcher),
              "manifests": [w["path"] for w in written]}
    _write_private(data_dir / "browser" / "host-install.json",
                   json.dumps(record, indent=2) + "\n", 0o600)
    return {"launcher": str(launcher), "manifests": written}


def uninstall_host(data_dir: pathlib.Path) -> list[str]:
    """Remove exactly the files `install_host` recorded, and only if a
    manifest still names this host. Returns what was removed."""
    rec_path = data_dir / "browser" / "host-install.json"
    try:
        rec = json.loads(rec_path.read_text())
    except (OSError, ValueError):
        return []
    removed = []
    for p in rec.get("manifests", []):
        path = pathlib.Path(p)
        try:
            if json.loads(path.read_text()).get("name") != HOST_NAME:
                continue
            path.unlink()
            removed.append(str(path))
        except (OSError, ValueError):
            continue
    launcher = pathlib.Path(rec.get("launcher", ""))
    if launcher == launcher_path(data_dir) and launcher.is_file():
        launcher.unlink()
        removed.append(str(launcher))
    rec_path.unlink(missing_ok=True)
    return removed


def status(home: pathlib.Path, data_dir: pathlib.Path,
           sock_path: pathlib.Path) -> dict:
    """What is installed and whether wispd is serving the socket."""
    rows = []
    for browser, (rel, documented) in BROWSERS.items():
        path = home / rel / f"{HOST_NAME}.json"
        row = {"browser": browser, "path": str(path),
               "documented": documented, "installed": path.is_file(),
               "origins": []}
        if row["installed"]:
            try:
                row["origins"] = json.loads(
                    path.read_text()).get("allowed_origins", [])
            except (OSError, ValueError):
                row["installed"] = False
        rows.append(row)
    launcher = launcher_path(data_dir)
    live = False
    mode = ""
    if sock_path.exists():
        mode = oct(stat.S_IMODE(sock_path.stat().st_mode))
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(str(sock_path))
            live = True
        except OSError:
            live = False
        finally:
            probe.close()
    return {"browsers": rows, "launcher": str(launcher),
            "launcher_ok": launcher.is_file() and os.access(launcher, os.X_OK),
            "socket": str(sock_path), "socket_mode": mode,
            "socket_live": live}
