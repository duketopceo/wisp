"""Fast talk lane vs deep agent lane on OpenRouter (H9).

Splits model execution into two latency/capability lanes:
  - `talk`: 1500 ms first-token budget on a fast streaming vision model for
    low-latency spoken answers and walkthrough step verification.
  - `deep`: full reasoning + tool-calling model for multi-step agent turns.

Also provides `LaneLedger` for per-lane spend and latency tracking and
`BargeInController` to cancel both TTS playback and the in-flight token stream
on user barge-in.
"""
from __future__ import annotations

import dataclasses
from typing import Callable

from . import cancel

TALK_LANE = "talk"
DEEP_LANE = "deep"

TALK_FIRST_TOKEN_BUDGET_MS = 1500
DEEP_FIRST_TOKEN_BUDGET_MS = 5000

DEFAULT_TALK_MODEL = "google/gemini-2.5-flash-lite"
DEFAULT_DEEP_MODEL = "meta-llama/llama-4-maverick"

_DEEP_MODES = frozenset(
    {"act", "deep", "agent", "agents", "tool", "tools", "execute", "plan", "routine"}
)
_TALK_MODES = frozenset(
    {"talk", "ask", "point", "guide", "walkthrough", "verify", "chat", "quick", ""}
)


@dataclasses.dataclass
class LaneConfig:
    """Configuration for a model lane (`talk` vs `deep`).

    Supports equality against lane name strings (`lane == "talk"`) as well as
    attribute and dict-key access (`lane.first_token_budget_ms`,
    `lane["model"]`).
    """

    name: str = TALK_LANE
    model: str = DEFAULT_TALK_MODEL
    provider: str = "openrouter"
    first_token_budget_ms: int = TALK_FIRST_TOKEN_BUDGET_MS
    streaming: bool = True
    vision: bool = True
    supports_tools: bool = False
    max_tokens: int = 400

    @property
    def lane(self) -> str:
        return self.name

    @property
    def first_token_s(self) -> float:
        return self.first_token_budget_ms / 1000.0

    @classmethod
    def talk(
        cls,
        model: str = DEFAULT_TALK_MODEL,
        first_token_budget_ms: int = TALK_FIRST_TOKEN_BUDGET_MS,
    ) -> "LaneConfig":
        return cls(
            name=TALK_LANE,
            model=model or DEFAULT_TALK_MODEL,
            provider="openrouter",
            first_token_budget_ms=int(first_token_budget_ms),
            streaming=True,
            vision=True,
            supports_tools=False,
            max_tokens=400,
        )

    @classmethod
    def deep(
        cls,
        model: str = DEFAULT_DEEP_MODEL,
        first_token_budget_ms: int = DEEP_FIRST_TOKEN_BUDGET_MS,
    ) -> "LaneConfig":
        return cls(
            name=DEEP_LANE,
            model=model or DEFAULT_DEEP_MODEL,
            provider="openrouter",
            first_token_budget_ms=int(first_token_budget_ms),
            streaming=True,
            vision=True,
            supports_tools=True,
            max_tokens=1200,
        )

    def to_dict(self) -> dict:
        return {
            **dataclasses.asdict(self),
            "first_token_s": self.first_token_s,
        }

    def __getitem__(self, key: str):
        if key == "lane":
            return self.name
        if key == "first_token_s":
            return self.first_token_s
        return getattr(self, key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.name == other
        if isinstance(other, LaneConfig):
            return (
                self.name == other.name
                and self.model == other.model
                and self.provider == other.provider
                and self.first_token_budget_ms == other.first_token_budget_ms
                and self.streaming == other.streaming
                and self.vision == other.vision
                and self.supports_tools == other.supports_tools
            )
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)


TALK_CONFIG = LaneConfig.talk()
DEEP_CONFIG = LaneConfig.deep()


def select_lane(
    mode: str = "talk",
    needs_tools: bool = False,
    is_walkthrough_verify: bool = False,
    cfg: dict | None = None,
) -> LaneConfig:
    """Select the model lane for a turn.

    - Walkthrough step verification (`is_walkthrough_verify=True` and not
      `needs_tools`) always uses the fast `talk` lane (1500 ms budget).
    - Turns requiring tool calls (`needs_tools=True`) or agent/act modes use
      the `deep` lane.
    - Pure spoken/pointing/guide turns use the `talk` lane.
    """
    brain_cfg = (cfg or {}).get("brain", {}) if isinstance(cfg, dict) else {}
    agent_cfg = (cfg or {}).get("agent", {}) if isinstance(cfg, dict) else {}
    talk_model = (
        brain_cfg.get("talk_model")
        or agent_cfg.get("talk_model")
        or DEFAULT_TALK_MODEL
    )
    deep_model = (
        brain_cfg.get("deep_model")
        or agent_cfg.get("act_model")
        or agent_cfg.get("answer_model")
        or DEFAULT_DEEP_MODEL
    )

    if needs_tools:
        return LaneConfig.deep(model=deep_model)
    if is_walkthrough_verify:
        return LaneConfig.talk(model=talk_model)

    m = (mode or "").strip().lower()
    if m in _DEEP_MODES:
        return LaneConfig.deep(model=deep_model)
    return LaneConfig.talk(model=talk_model)


def _percentile(samples: list[float], q: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    idx = int(round((len(ordered) - 1) * q))
    idx = max(0, min(len(ordered) - 1, idx))
    return float(ordered[idx])


class LaneLedger:
    """Records per-lane spend (USD, tokens, calls) and first-token latency
    samples in milliseconds."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {
            TALK_LANE: {
                "calls": 0,
                "usd": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "latencies_ms": [],
                "models": {},
            },
            DEEP_LANE: {
                "calls": 0,
                "usd": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "latencies_ms": [],
                "models": {},
            },
        }
        self.entries: list[dict] = []

    @staticmethod
    def _lane_key(lane: str | LaneConfig) -> str:
        name = lane.name if isinstance(lane, LaneConfig) else str(lane or TALK_LANE)
        name = name.strip().lower()
        return DEEP_LANE if name == DEEP_LANE else TALK_LANE

    def record(
        self,
        lane: str | LaneConfig,
        usd: float = 0.0,
        latency_ms: float | None = None,
        *,
        cost_usd: float | None = None,
        first_token_ms: float | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model: str = "",
    ) -> dict:
        """Record one turn's spend and optional first-token latency on `lane`."""
        key = self._lane_key(lane)
        bucket = self._data.setdefault(
            key,
            {
                "calls": 0,
                "usd": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "latencies_ms": [],
                "models": {},
            },
        )
        actual_usd = float(cost_usd if cost_usd is not None else usd or 0.0)
        actual_lat = first_token_ms if first_token_ms is not None else latency_ms
        model_name = model or (lane.model if isinstance(lane, LaneConfig) else "")

        bucket["calls"] += 1
        bucket["usd"] = round(bucket["usd"] + actual_usd, 8)
        bucket["tokens_in"] += int(tokens_in or 0)
        bucket["tokens_out"] += int(tokens_out or 0)
        if actual_lat is not None:
            bucket["latencies_ms"].append(float(actual_lat))
        if model_name:
            bucket["models"][model_name] = bucket["models"].get(model_name, 0) + 1

        entry = {
            "lane": key,
            "model": model_name,
            "usd": round(actual_usd, 8),
            "latency_ms": float(actual_lat) if actual_lat is not None else None,
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
        }
        self.entries.append(entry)
        return entry

    note = record

    def lane_stats(self, lane: str | LaneConfig) -> dict:
        key = self._lane_key(lane)
        b = self._data[key]
        lats = list(b["latencies_ms"])
        budget_ms = (
            TALK_FIRST_TOKEN_BUDGET_MS
            if key == TALK_LANE
            else DEEP_FIRST_TOKEN_BUDGET_MS
        )
        within = sum(1 for x in lats if x <= budget_ms)
        return {
            "lane": key,
            "calls": b["calls"],
            "usd": round(b["usd"], 6),
            "spend_usd": round(b["usd"], 6),
            "tokens_in": b["tokens_in"],
            "tokens_out": b["tokens_out"],
            "latencies_ms": lats,
            "latency_samples_ms": lats,
            "p50_ms": _percentile(lats, 0.50),
            "p95_ms": _percentile(lats, 0.95),
            "within_budget_count": within,
            "models": dict(b["models"]),
        }

    def summary(self) -> dict:
        talk = self.lane_stats(TALK_LANE)
        deep = self.lane_stats(DEEP_LANE)
        return {
            TALK_LANE: talk,
            DEEP_LANE: deep,
            "total_usd": round(talk["usd"] + deep["usd"], 6),
            "total_calls": talk["calls"] + deep["calls"],
        }

    def spend_for(self, lane: str | LaneConfig) -> float:
        return self.lane_stats(lane)["usd"]

    def latencies_for(self, lane: str | LaneConfig) -> list[float]:
        return self.lane_stats(lane)["latencies_ms"]

    def p50_latency_ms(self, lane: str | LaneConfig) -> float | None:
        return self.lane_stats(lane)["p50_ms"]


class BargeInController:
    """Coordinates local barge-in cancellation across both TTS playback and the
    in-flight OpenRouter token stream."""

    def __init__(
        self,
        stream_token: cancel.CancelToken | None = None,
        tts_stop: Callable[[], None] | None = None,
        speaker: object | None = None,
        stream_close: Callable[[], None] | None = None,
    ) -> None:
        self.stream_token: cancel.CancelToken = stream_token or cancel.CancelToken()
        self.tts_token: cancel.CancelToken = cancel.CancelToken()
        self._tts_stop = tts_stop
        self._speaker = speaker
        self._stream_close = stream_close
        self.tts_cancelled: bool = False
        self.stream_cancelled: bool = False
        self.barge_in_count: int = 0
        self.last_reason: str = ""

    def attach_tts(
        self,
        speaker_or_fn: object | Callable[[], None],
    ) -> None:
        if callable(speaker_or_fn) and not hasattr(speaker_or_fn, "stop"):
            self._tts_stop = speaker_or_fn
        else:
            self._speaker = speaker_or_fn

    def attach_stream(
        self,
        token: cancel.CancelToken | None = None,
        close_fn: Callable[[], None] | None = None,
    ) -> None:
        if token is not None:
            self.stream_token = token
        if close_fn is not None:
            self._stream_close = close_fn

    def barge_in(self, reason: str = "user_speech") -> dict:
        """Cancel both TTS output and the in-flight LLM stream immediately."""
        self.stream_token.cancel()
        if self._stream_close is not None:
            try:
                self._stream_close()
            except Exception:
                pass
        self.stream_cancelled = True

        self.tts_token.cancel()
        if self._tts_stop is not None:
            try:
                self._tts_stop()
            except Exception:
                pass
        if self._speaker is not None:
            for attr in ("stop", "cancel", "terminate", "kill"):
                fn = getattr(self._speaker, attr, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
        self.tts_cancelled = True

        self.barge_in_count += 1
        self.last_reason = reason
        return {
            "cancelled": True,
            "tts_cancelled": self.tts_cancelled,
            "stream_cancelled": self.stream_cancelled,
            "reason": reason,
            "barge_in_count": self.barge_in_count,
        }

    cancel = barge_in
    trigger = barge_in

    @property
    def is_cancelled(self) -> bool:
        return bool(
            (self.tts_cancelled and self.stream_cancelled)
            or self.stream_token.cancelled
        )

    def reset(self) -> None:
        self.stream_token = cancel.CancelToken()
        self.tts_token = cancel.CancelToken()
        self.tts_cancelled = False
        self.stream_cancelled = False
        self.last_reason = ""
