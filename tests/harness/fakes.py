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

FakeJev      tripwire for the retired decision endpoint: nothing routes
             through it, so any call it records is a stray hop (the
             runner fails the fixture). script["answers"] is only the
             canned reply for a fixture that proves it is never called.
FakeBrain    script["responses"][i]       -> one entry per call (last
             repeats); entry keys: content, chunks, tool_calls
             [{name,arg}], latency_ms, chunk_delay_ms. Streams SSE when
             the request carries ``"stream": true``. Also serves GET
             /models and /v1/models (the daemon's reachability probe).
FakeWhisper  script["transcript"]         -> {"text": ...} on both
             /audio/transcriptions (OpenAI shape) and /inference
             (whisper-server shape)
FakeUiTars   FakeBrain with a grounding-style default response
FakeGroqTts  script["wav_ms"]             -> a silent WAV per /audio/speech
             call (U6; a fixture that declares it speaks with Groq)

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

    def handle(self):
        try:
            super().handle()
        except ConnectionError:
            pass  # a cancelled caller hanging up is not an error

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
        self.peer_closed = False   # a client hung up before we replied
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
        self._sleep_watch(h, self.script.get("latency_ms", 0))
        if self.client_gone(h):
            return  # the caller cancelled: nobody to answer
        if n in self.script.get("fail_on_calls", ()):
            st = self.script.get("fail_status", 500)
            return self.respond(h, st, {"error": f"scripted failure #{n}"})
        status = self.script.get("status", 200)
        if status != 200:
            return self.respond(h, status, {"error": self.script.get(
                "error_body", "scripted status")})
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
    def client_gone(self, h) -> bool:
        """True (and remembered in ``peer_closed``) when the client has
        closed its end of the connection."""
        import socket as _s
        import select
        try:
            # MSG_DONTWAIT does not exist on Windows — readiness via
            # select() is the portable non-blocking probe.
            if not select.select([h.connection], [], [], 0)[0]:
                return False
            data = h.connection.recv(1, _s.MSG_PEEK)
            gone = data == b""
        except BlockingIOError:
            gone = False
        except OSError:
            gone = True
        if gone:
            self.peer_closed = True
        return gone

    def _sleep_watch(self, h, ms) -> None:
        """Sleep `ms`, waking early once the client hangs up."""
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            if self.client_gone(h):
                return
            time.sleep(min(0.01, max(0.0, end - time.monotonic())))

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
        try:
            h.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the caller cancelled before the reply


class FakeJev(FakeServer):
    """Tripwire for `JEV_ENDPOINT` (still read by the grounding `jev` provider and the
    health probe; Q3 is open). The
    router that used it is gone; the runner reports any recorded call."""

    def serve(self, h, method, body, n):
        self.respond(h, 200, {"answers": self.script.get("answers", {}),
                              "latency_ms": self.script.get(
                                  "latency_ms", 0)})


class FakeWhisper(FakeServer):
    def serve(self, h, method, body, n):
        out = {"text": self.script.get("transcript", "")}
        if self.script.get("language"):
            out["language"] = self.script["language"]    # verbose_json
        self.respond(h, 200, out)


class FakeBrain(FakeServer):
    """OpenAI-compatible chat server with optional SSE streaming.
    ``sent`` records (monotonic time, text) for every streamed chunk."""

    def __init__(self, script: dict | None = None):
        super().__init__(script)
        self.sent: list = []

    def counts(self, path: str) -> bool:
        return path.rstrip("/").endswith("/chat/completions")

    def probe_body(self, path: str):
        return {"object": "list", "data": [{"id": "fake-model"}]}

    def _entry(self, n: int) -> dict:
        rs = self.script.get("responses") or [{"content": ""}]
        return rs[min(n, len(rs)) - 1]

    def serve(self, h, method, body, n):
        entry = self._entry(n)
        # A scripted follow-up can depend on the actual broker reply,
        # rather than unconditionally launching even after NO_ANSWER.
        required = entry.get("requires_tool_result")
        if required and not any(
                m.get("role") == "tool" and m.get("content") == required
                for m in (body or {}).get("messages", [])):
            entry = entry.get("otherwise", {"content": ""})
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
            out = {"choices": [{"index": 0, "message": msg,
                                "finish_reason": "tool_calls" if tcs
                                else "stop"}]}
            if entry.get("usage"):
                out["usage"] = entry["usage"]
            return self.respond(h, 200, out)
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
                if self.client_gone(h):
                    return  # client cancelled mid-stream
                chunk = {"choices": [{"index": 0,
                                      "delta": {"content": p}}]}
                h.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                h.wfile.flush()
                with self._lock:
                    self.sent.append((time.monotonic(), p))
                self._sleep(entry.get("chunk_delay_ms", 0))
            if entry.get("usage"):
                u = {"choices": [], "usage": entry["usage"]}
                h.wfile.write(f"data: {json.dumps(u)}\n\n".encode())
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


class FakeGroqTts(FakeServer):
    """Groq `/audio/speech`: one silent mono 16-bit WAV per call, its
    length from script["wav_ms"][call - 1] (the last repeats, default
    300 ms). `calls` records each request body."""

    RATE = 24000

    def counts(self, path: str) -> bool:
        return path.rstrip("/").endswith("/audio/speech")

    def serve(self, h, method, body, n):
        import io
        import wave
        lens = self.script.get("wav_ms") or [300]
        ms = lens[min(n, len(lens)) - 1]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(b"\0\0" * (self.RATE * ms // 1000))
        data = buf.getvalue()
        h.send_response(200)
        h.send_header("Content-Type", "audio/wav")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        try:
            h.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


KINDS = {"jev": FakeJev, "brain": FakeBrain, "brain2": FakeBrain,
         "whisper": FakeWhisper,
         "uitars": FakeUiTars, "groq_tts": FakeGroqTts}
