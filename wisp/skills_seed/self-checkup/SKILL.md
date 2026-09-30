---
name: self-checkup
description: Wisp self-diagnostic — read daemon log, trace, decisions, and soak labels to report health and recurring failures
---
# self-checkup

Produce a health digest for Wisp itself. Use when asked "how are you
doing", "what's failing", "check yourself", or during debug sessions.

Read, in order:
- `~/.local/share/wisp/wispd.log` — human-readable daemon log (IPC
  calls, turn outcomes, errors). Tail ~100 lines.
- `~/.local/share/wisp/decisions.jsonl` — every routed turn with Jev
  answers, risk, and result. Look for repeating BLOCKED/SKIP/CANCELLED.
- `~/.local/share/wisp/labels.jsonl` — user intent-match labels from
  the soak; compare against decisions to find misroutes.
- `~/.local/share/wisp/trace.jsonl` — per-stage timing events
  (`wispd trace` pretty-prints it).
- `~/.local/share/wisp/activity.jsonl` — passive sense records when
  `[sense]` is enabled.

Report: current status, turns today, failure clusters, top misrouted
patterns, whether intent-match is above the 85% soak gate, and the one
thing most worth fixing. Short and specific — name the failing route
or tool, not "there were some errors".
