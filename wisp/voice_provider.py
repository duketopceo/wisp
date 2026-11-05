"""Provider-agnostic seam for speech in (STT) and speech out (TTS).

Off by default. The shipped providers (Groq Whisper for STT, Groq Orpheus
for TTS) stay the only active ones: nothing in this module is called from
the speak or capture paths, and no second provider is registered in the
tree. A follow-up PR can register one behind `[voice] alt_provider` once
the owner approves (docs/research/2026-11-05-voice-provider-evaluation.md).

    select(cfg, "tts") -> (Provider, reason)   # never raises

Selection falls back to the default (Groq) when `alt_provider` is unset,
unknown, lacks the direction, or its key does not resolve. Resolving a
key can shell out to omaseal, so `select` is for setup and the harness,
not per sentence.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Protocol

from . import config

DEFAULT = "groq"
DIRECTIONS = ("stt", "tts")


@dataclasses.dataclass(frozen=True)
class Capabilities:
    stt: bool = False
    tts: bool = False

    def has(self, direction: str) -> bool:
        return direction in DIRECTIONS and bool(getattr(self, direction))


class Provider(Protocol):
    name: str
    key_ref: str                 # config.load_env_key reference, "" = none
    caps: Capabilities

    def transcribe(self, wav: bytes) -> str: ...
    def synth(self, text: str) -> bytes: ...


_REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> None:
    _REGISTRY[provider.name] = provider


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


class GroqProvider:
    """The current default. Thin: delegates to the existing code paths, so
    it adds no behavior. A live call happens only when a caller invokes
    transcribe or synth, never at import or select time."""
    name = DEFAULT
    caps = Capabilities(stt=True, tts=True)

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    @property
    def key_ref(self) -> str:
        return str(config.stt_settings(self.cfg)["key_env"])

    def transcribe(self, wav: bytes) -> str:
        import pathlib
        import tempfile
        from . import stage_capture
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "in.wav"
            p.write_bytes(wav)
            return str(stage_capture.transcribe(p, self.cfg))

    def synth(self, text: str) -> bytes:
        from . import tts_groq
        return tts_groq.Fetcher(self.cfg).synth(text).data


def alt_name(cfg: dict | None) -> str:
    """[voice] alt_provider, "" (off) by default."""
    return str(((cfg or {}).get("voice") or {}).get("alt_provider", "")
               ).strip().lower()


def select(cfg: dict | None, direction: str,
           resolve_key: Callable[[str], str] | None = None
           ) -> tuple[Provider, str]:
    """(provider, reason). The alternative only when it is named, known,
    has `direction`, and its key resolves; otherwise the default, with the
    reason it fell back."""
    resolve = resolve_key or config.load_env_key
    want = alt_name(cfg)
    default = GroqProvider(cfg)
    if not want or want == DEFAULT:
        return default, "default"
    alt = _REGISTRY.get(want)
    if alt is None:
        return default, f"fallback: {want} not registered"
    if not alt.caps.has(direction):
        return default, f"fallback: {want} has no {direction}"
    if alt.key_ref and not resolve(alt.key_ref):
        return default, f"fallback: no key for {want}"
    return alt, f"alt: {want}"
