"""A scripted speech provider for the U13 harness and seam tests. It
makes no network call: latency is a fake clock that advances by the
scripted amount, so reports are deterministic."""
from wisp.voice_provider import Capabilities


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeProvider:
    def __init__(self, name="fake", stt_ms=120, tts_ms=300, clock=None,
                 caps=Capabilities(stt=True, tts=True), key_ref="",
                 fail=False):
        self.name, self.key_ref, self.caps = name, key_ref, caps
        self.stt_ms, self.tts_ms, self.fail = stt_ms, tts_ms, fail
        self.clock = clock
        self.calls = []

    def _tick(self, ms):
        if self.clock is not None:
            self.clock.t += ms / 1000

    def transcribe(self, wav: bytes) -> str:
        self.calls.append(("stt", len(wav)))
        if self.fail:
            raise RuntimeError("scripted failure")
        self._tick(self.stt_ms)
        return "hello"

    def synth(self, text: str) -> bytes:
        self.calls.append(("tts", text))
        if self.fail:
            raise RuntimeError("scripted failure")
        self._tick(self.tts_ms)
        return b"RIFF" + bytes(40)
