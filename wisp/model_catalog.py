"""Curated model catalog for user-facing selection.

Rules (from the 2026-10-31 matrix, reports/wisp-model-matrix.md):
- At most 3 options per lane when the user is asked to pick.
- Every lane lists at least one OpenRouter option — a user with only an
  OpenRouter key is never stranded on a local-only lane.
- Local entries carry an ollama tag; `detected()` probes the local
  daemon and hides entries whose weights are not pulled, so the picker
  only shows what actually runs on this machine.

Scores are matrix outcomes, ordered success -> latency -> cost.
"""

from __future__ import annotations

import json
import urllib.request

OLLAMA_TAGS = "http://localhost:11434/api/tags"

# lane -> ordered options (best first). provider: openrouter | ollama | groq | local
CATALOG: dict[str, list[dict]] = {
    "brain": [
        {"id": "google/gemini-2.5-flash", "provider": "openrouter", "note": "matrix winner — 89.5% first-time-correct, 448 ms p50"},
        {"id": "mistralai/mistral-small-3.2-24b-instruct", "provider": "openrouter", "note": "84% FTC, cheapest hosted, 210 ms TTFT"},
        {"id": "google/gemini-3-flash-preview", "provider": "openrouter", "note": "84% FTC, newer family, 812 ms"},
    ],
    "agent": [
        {"id": "particle-ai/particle-1", "provider": "openrouter", "note": "6/6 tasks, cheapest per run ($0.003), 10.7 s"},
        {"id": "deepseek/deepseek-v4.1-flash", "provider": "openrouter", "note": "6/6 tasks, $0.012, 37 s"},
        {"id": "qwen/qwen3-coder", "provider": "openrouter", "note": "5/6 tasks, coding-focused, $0.017"},
    ],
    "routing": [
        {"id": "typesafe/jev-latest", "provider": "openrouter", "note": "93% on wisp criteria, 183 ms — baseline engine"},
        {"id": "perplexity/pplx-decider-v1.2", "provider": "openrouter", "note": "90% on app-choice, 271 ms"},
        {"id": "wisp/heuristic-local", "provider": "local", "note": "free, 0 ms — handles the common routes"},
    ],
    "speech": [
        {"id": "groq/whisper-large-v3-turbo", "provider": "groq", "note": "WER 0.159, 217 ms — noise-robust winner"},
        {"id": "local/whisper-small", "provider": "local", "note": "clean-audio WER 0.096, free, 1.3 s — quiet dictation only"},
        {"id": "google/gemini-2.5-flash", "provider": "openrouter", "note": "audio-input capable via chat completions — hosted fallback"},
    ],
    "embeddings": [
        {"id": "google/gemini-embedding-001", "provider": "openrouter", "note": "recall@1 0.958 — best hosted"},
        {"id": "openai/text-embedding-3-small", "provider": "openrouter", "note": "recall@1 0.875 — current baseline"},
        {"id": "nomic-embed-text", "provider": "ollama", "ollama": "nomic-embed-text:latest", "note": "recall@1 0.917, free local — beats the hosted baseline"},
    ],
    "eyes": [
        {"id": "lfm2.5-vl-1.6b", "provider": "ollama", "ollama": "hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF:Q8_0", "note": "all probes pass, 1.8 s p50, 1.7 GB"},
        {"id": "smolvlm2-2.2b", "provider": "ollama", "ollama": "hf.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF:Q8_0", "note": "all pass, 2.7 s p50"},
        {"id": "google/gemini-2.5-flash", "provider": "openrouter", "note": "hosted vision fallback when no local weights"},
    ],
    "assist": [
        {"id": "smollm3-3b", "provider": "ollama", "ollama": "hf.co/ggml-org/SmolLM3-3B-GGUF:Q8_0", "note": "90% pass on helper tasks"},
        {"id": "qwen3-1.7b", "provider": "ollama", "ollama": "qwen3:1.7b-q8_0", "note": "78% pass at 988 ms — speed-balanced"},
        {"id": "google/gemini-2.5-flash-lite", "provider": "openrouter", "note": "hosted helper fallback, 271 ms"},
    ],
}

MAX_OPTIONS = 3


def ollama_tags(timeout: float = 0.8) -> set[str]:
    """Pulled model names on the local ollama daemon; empty set when down."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=timeout) as r:
            data = json.loads(r.read())
        return {m.get("name", "") for m in data.get("models", [])} | {
            m.get("model", "") for m in data.get("models", [])
        }
    except Exception:
        return set()


def detected(lane: str, *, local: bool = True, tags: set[str] | None = None) -> list[dict]:
    """Options for `lane`, capped at MAX_OPTIONS, local entries filtered to
    weights actually pulled. An OpenRouter option is always included:
    if the catalog's first three are all local, the first local entry
    beyond the cap is dropped for the best hosted option."""
    if not lane in CATALOG:
        return []
    have = tags if tags is not None else ollama_tags()
    out = []
    for opt in CATALOG[lane]:
        if opt["provider"] == "ollama":
            if not local or opt.get("ollama") not in have:
                continue
        if opt["provider"] == "local" and not local:
            continue
        out.append(dict(opt))
    hosted = [o for o in out if o["provider"] == "openrouter"] or [
        o for o in CATALOG[lane] if o["provider"] == "openrouter"
    ]
    picks = out[:MAX_OPTIONS]
    if hosted and not any(o["provider"] == "openrouter" for o in picks):
        picks = picks[: MAX_OPTIONS - 1] + [hosted[0]]
    return picks


def select_label(opt: dict) -> str:
    """One-line picker label: provider tag + slug + the matrix note."""
    return f"[{opt['provider']}] {opt['id']} — {opt.get('note', '')}".rstrip(" —")
