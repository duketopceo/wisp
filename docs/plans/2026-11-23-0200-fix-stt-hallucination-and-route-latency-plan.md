---
title: Fix STT trailing hallucinations and route latency
type: fix
date: 2026-11-23
artifact_contract: ce-unified-plan/v1
execution: code
status: implemented
---

# Fix STT trailing hallucinations and route latency

Shipped in the companion PR: tail PCM trim, whisper/Groq anti-hallucination
settings, quiet-tail phrase filter with tests, parallel context gathering,
400 ms route deadline cap for ambiguity routing, TLS preconnect warm-up, and
100 ms busy barge-in debounce in `wispd`.