"""Stream endpoints for fakes on hosts without AF_UNIX (Windows).

``bind_stream`` returns AF_UNIX where it exists; otherwise a TCP
loopback listener whose port is written into `path` — the file still
exists for presence checks, and fakes-side clients read the port back
out with ``connect_stream``.
"""
import pathlib
import socket


def bind_stream(path):
    """Bind a stream listener for `path`; returns the bound socket."""
    path = pathlib.Path(path)
    if hasattr(socket, "AF_UNIX"):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        return s
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(s.getsockname()[1]))
    return s


def connect_stream(path, timeout=None):
    """Connect to an endpoint bound by ``bind_stream``; returns the
    connected socket."""
    if hasattr(socket, "AF_UNIX"):
        s = socket.socket(socket.AF_UNIX)
        if timeout is not None:
            s.settimeout(timeout)
        s.connect(str(path))
        return s
    port = int(pathlib.Path(path).read_text().strip())
    return socket.create_connection(("127.0.0.1", port), timeout)
