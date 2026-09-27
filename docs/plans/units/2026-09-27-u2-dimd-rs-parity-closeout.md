---
plan: dim-u2-dimd-rs-parity-closeout
created: 2026-09-27
status: ready
origin: docs/plans/2026-09-26-001-feat-dim-companion-crossplatform-plan.md#U2
issue: https://github.com/duketopceo/dim-agent/issues/6
wave: 1
---

# U2 close-out — dimd-rs Linux parity core

## Scope

The parity core exists and its contract tests pass. This unit covers the
remainder before dimd-rs can replace the Python daemon as the default on
<host>.

## Steps

1. **Strict observable-parity sweep** — diff every reply/error string and
   `state.json` field emitted by both cores for the full fixture set;
   align or record intentional divergence in `docs/IPC_CONTRACT.md`.
   Known remaining: a few error-string texts, `agents.model` unused.
2. **Confirm-flow reconciliation** — Python act loop blocks on the socket
   mid-step; Rust asks the choice IPC instead. Decide which semantics the
   contract blesses (recommend: Rust's IPC-confirm, it's non-blocking)
   and port the loser.
3. **Dual-daemon soak** — run `dimd-rs daemon` on <host> as the
   systemd unit for a day; compare `decisions.jsonl`/`session.jsonl`
   shapes byte-for-byte against Python output.
4. **Gate** — `dimd-rs` serves real `listen→done` (record → whisper →
   Jev → execute) with the shell plugin completely unchanged.

## Tests

- `rs/dimd/tests/parity.rs` fixture replay (already live) extended to
  assert reply *content* for deterministic commands (`status` field set,
  `config` round-trip), not just envelope.
- Fixture-driven diff harness: same inputs → normalized JSON outputs
  compared between cores.

## Risks

- Mic-level sampling on arecord is best-effort; Wayland/PipeWire audio
  edge cases may need the sampler reworked.
- Python remains the reference until the gate passes — do not flip
  `~/.local/bin/dimd` early.

## Done when

dimd-rs runs the daemon role on <host> for 24h with zero contract
violations and the plugin needs no changes.
