"""Scripted fake model servers for the turn-replay harness (backend U14).

Every fake is a stdlib ``http.server`` bound to ``127.0.0.1`` on an
ephemeral port (never a fixed port, so it cannot collide with the live
llama/ollama services). Behaviour is data, set per fixture:

Common script keys (any fake):
  latency_ms      sleep before responding (default 0)
  status          HTTP status for successful calls (default 200)
  fail_on_calls   1-based call numbers that fail instead
  fail_status     status used for those failures (default 500)
  drop_on_calls   1-based call numbers where the socket is closed
                  without any response (connection reset)

FakeJev      script["answers"]            -> {"answers": ...}
FakeBrain    script["responses"][i]       -> one entry per call (last
             repeats); entry keys: content, chunks, tool_calls
             [{name,arg}], latency_ms, chunk_delay_ms. Streams SSE when
             the request carries ``"stream": true``. Also serves GET
             /models and /v1/models (the daemon's reachability probe).
FakeWhisper  script["transcript"]         -> {"text": ...} on both
             /audio/transcriptions (OpenAI shape) and /inference
             (whisper-server shape)
FakeUiTars   FakeBrain with a grounding-style default response
FakeBatch    provisional OpenRouter-batch shape (U11 reconciles it):
             POST /batches -> {"id"}; GET /batches/<id> walks
             script["statuses"], then returns script["results"]

``calls`` records every request (path, method, parsed body, monotonic
arrival time) so tests can assert on what the pipeline sent.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _dispatch(self, method):
        raw = self._body()
        self.server.fake.handle(self, method, raw)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


class FakeServer:
    """Base fake: owns the server thread, the script and the call log."""

    def __init__(self, script: dict | None = None):
        self.script = script or {}
        self.calls: list = []
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.fake = self
        self._thread = None

    # -- lifecycle -------------------------------------------------
    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(
                target=self.server.serve_forever,
                kwargs={"poll_interval": 0.02}, daemon=True)
            self._thread.start()
        return self

    def stop(self):
        if self._thread is not None:
            self.server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self.server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- request handling -----------------------------------------
    def handle(self, h, method: str, raw: bytes) -> None:
        try:
            parsed = json.loads(raw) if raw[:1] in (b"{", b"[") else None
        except ValueError:
            parsed = None
        with self._lock:
            self.calls.append({"path": h.path, "method": method,
                               "body": parsed, "bytes": len(raw),
                               "t": time.monotonic()})
            n = sum(1 for c in self.calls if self.counts(c["path"]))
        if not self.counts(h.path):
            return self.respond(h, 200, self.probe_body(h.path))
        if n in self.script.get("drop_on_calls", ()):
            h.close_connection = True
            h.connection.close()
            return
        self._sleep(self.script.get("latency_ms", 0))
        if n in self.script.get("fail_on_calls", ()):
            st = self.script.get("fail_status", 500)
            return self.respond(h, st, {"error": f"scripted failure #{n}"})
        status = self.script.get("status", 200)
        if status != 200:
            return self.respond(h, status, {"error": "scripted status"})
        self.serve(h, method, parsed, n)

    # hooks -------------------------------------------------------
    def counts(self, path: str) -> bool:
        """Does this path count as a 'real' call (vs a probe)?"""
        return True

    def probe_body(self, path: str):
        return {}

    def serve(self, h, method, body, n):
        self.respond(h, 200, {})

    # helpers -----------------------------------------------------
    @staticmethod
    def _sleep(ms) -> None:
        if ms:
            time.sleep(ms / 1000.0)

    @staticmethod
    def respond(h, status: int, obj) -> None:
        data = json.dumps(obj).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)


class FakeJev(FakeServer):
    """Jev decisions endpoint: returns scripted typed answers."""

    def serve(self, h, method, body, n):
        self.respond(h, 200, {"answers": self.script.get("answers", {}),
                              "latency_ms": self.script.get(
                                  "latency_ms", 0)})


class FakeWhisper(FakeServer):
    def serve(self, h, method, body, n):
        self.respond(h, 200, {"text": self.script.get("transcript", "")})


class FakeBrain(FakeServer):
    """OpenAI-compatible chat server with optional SSE streaming."""

    def counts(self, path: str) -> bool:
        return path.rstrip("/").endswith("/chat/completions")

    def probe_body(self, path: str):
        return {"object": "list", "data": [{"id": "fake-model"}]}

    def _entry(self, n: int) -> dict:
        rs = self.script.get("responses") or [{"content": ""}]
        return rs[min(n, len(rs)) - 1]

    def serve(self, h, method, body, n):
        entry = self._entry(n)
        self._sleep(entry.get("latency_ms", 0))
        stream = bool(body and body.get("stream"))
        calls = entry.get("tool_calls") or []
        tcs = [{"id": f"call_{n}_{i}", "type": "function",
                "function": {"name": c["name"],
                             "arguments": json.dumps(
                                 {"arg": c.get("arg", "")})}}
               for i, c in enumerate(calls)]
        content = entry.get("content", "")
        if not stream:
            msg = {"role": "assistant", "content": content}
            if tcs:
                msg["tool_calls"] = tcs
            return self.respond(h, 200, {
                "choices": [{"index": 0, "message": msg,
                             "finish_reason": "tool_calls" if tcs
                             else "stop"}]})
        pieces = entry.get("chunks")
        if pieces is None:
            pieces = [w + " " for w in content.split()]
            if pieces:
                pieces[-1] = pieces[-1].rstrip()
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "close")
        h.end_headers()
        h.close_connection = True
        try:
            for p in pieces:
                chunk = {"choices": [{"index": 0,
                                      "delta": {"content": p}}]}
                h.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                h.wfile.flush()
                self._sleep(entry.get("chunk_delay_ms", 0))
            h.wfile.write(b"data: [DONE]\n\n")
            h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client cancelled mid-stream


class FakeUiTars(FakeBrain):
    """UI-TARS GUI grounding (OpenAI-compatible)."""

    def __init__(self, script: dict | None = None):
        script = dict(script or {})
        script.setdefault("responses",
                          [{"content": "click(start_box='(100,200)')"}])
        super().__init__(script)


class FakeBatch(FakeServer):
    """Provisional OpenRouter Batch API (shape reconciled in U11)."""

    def __init__(self, script: dict | None = None):
        super().__init__(script)
        self._polls: dict = {}

    def serve(self, h, method, body, n):
        path = h.path.split("?")[0].rstrip("/")
        if method == "POST" and path.endswith("/batches"):
            bid = f"batch_{len(self._polls) + 1}"
            self._polls[bid] = 0
            return self.respond(h, 200, {"id": bid,
                                         "status": "validating"})
        bid = path.rsplit("/", 1)[-1]
        sts = self.script.get("statuses") or ["completed"]
        i = self._polls.get(bid, 0)
        self._polls[bid] = i + 1
        st = sts[min(i, len(sts) - 1)]
        out = {"id": bid, "status": st}
        if st == "completed":
            out["results"] = self.script.get("results", [])
        self.respond(h, 200, out)


KINDS = {"jev": FakeJev, "brain": FakeBrain, "whisper": FakeWhisper,
         "uitars": FakeUiTars, "openrouter_batch": FakeBatch}
