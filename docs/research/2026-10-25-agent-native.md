## Agent-Native Planning Assessment

### Applicability

**Verdict: yes, agents must be planned as first-class users — but the deciding fact is not the new features; it is that wisp already grants them the access and the plan would widen it without closing the trust gaps.**

Evidence that the surface is already agent-facing:

- `wispd` IPC (`wispd:52-370`) is an unauthenticated same-uid command socket. `SO_PEERCRED` is captured (`ipc.py:45-58`) but used **only for logging** (`wispd:60-63`) — `_dispatch` never sees `peer`. Any process the user spawns — including every background agent wisp launches — can already send `config set` (live-reload, `wispd:329-342`), `agent` (recursive spawn, `wispd:281-284`), `choice` (answer its own confirm cards, `wispd:206-270`), `stop`, `interrupt`. A spawned agent that tails `state.json` can observe a pending `prompt_id` and approve itself.
- The act loop's own toolbelt already treats agents as callable primitives: `agent_spawn` (T1), `task_status` (T0), `task_cancel` (T2) in `wisp/tools/__init__.py:132-140`, dispatched through `policy.gate`.
- `wisp/skills.py` is already the clacky/hermes shape: `~/.local/share/wisp/skills/*/SKILL.md` with `tool:`+`tier:` frontmatter, `skill_manage`/`skill_view` tools, app-keyed matching by `url_hosts`/`app_classes`. The foreground/background split the plan describes is the missing half — spawned runtimes (`ori opencode run`, `codex exec`, `claude -p`, `devin run` — `agents.py:272-281`) today get nothing from `SKILLS_DIR`.
- `wisp/routines.py` (489 lines: `RoutineStore`, `generate_systemd_units`, opt-in gate, `record_routine_outcome`) is **shipped dead code** — zero production imports (`rg "import routines"` -> tests only), and its generated units exec `wispd agents run <id>`, a command that **does not exist** (`agents` is no GROUPS key; only `task run`, `wisp/cli/agents.py:62`; `test_heyclicky_delta.py:611` asserts only the unit text). `Ctx.send` raises `E_DAEMON_DOWN` when wispd is down (`cli/registry.py:305-315`), so a `Persistent=true` timer firing while the daemon is off produces nothing at all — no spawn, no outcome record.
- Completion handling today is one toast: `_agent_done` (`wispd:708-713`) sends `notify_tool("wisp agent '<name>' <status> — <last log line>")`. No exit code is recorded, no declared deliverable is checked — "she opens what she delivers, never claims a delivery she didn't make" (clacky's contract) has no analogue.
- No `organize`/undo anywhere (`rg -i organize` -> 0 hits).

So the agent-native lens changes this plan from "port features" to "finish the half-landed agent substrate, then extend it." The clacky mechanics map onto existing-but-incomplete machinery; each has a parity question (callable by voice AND by agents/scripts over IPC) and a trust question (what a same-uid agent may do).

### Planning Changes

**Requirements**

- R-parity: every new capability lands on both faces — voice path and programmatic path — or names why not. Concretely: routine create/list/pause/resume/delete need IPC cmds (today there are none); `organize` needs a tool + CLI verb; skill export to background runtimes needs a declared mechanism.
- R-delivery: `agent_spawn` gains an optional declared-deliverables list and a per-task output-dir convention (e.g. `TASK_LOGS/<name>/out/` passed as `cwd`/env); the reaper's `task_finished` verifies existence/size/mtime-within-run and publishes an honest verdict (`delivered|missing`), never echoing the model's claim.
- R-exit: terminal task status becomes exit-aware — process reaping records exit status so `done` vs `failed` is truth, not "exited" ambiguity (`agents.py:128-137` `_state_of` currently can't tell crash from success).
- R-routines: wire `routines.py` end-to-end — real `agents run <id>` CLI path (add the group or fix the unit to `task run --routine <id>`), direct-spawn fallback when the daemon is down (precedent: `label set`'s local fallback, `cli/agents.py:125-138`; the file registry reconciles on next daemon start), `task_finished` with `routine_id` provenance -> `record_routine_outcome` -> unread dot + 3-failure auto-pause + one notification.
- R-ipc-authz: split IPC commands into read (`status`, `task_status`, `context`, `subscribe`, `captures`, `suggestions`) vs mutating (`agent`, `task_cancel`, `choice`, `config`, `memory`, `stop`, `interrupt`, `listen`). Mutating commands refuse peers marked as agent-spawned (env marker e.g. `WISP_TASK_ID` on the spawn + SO_PEERCRED ancestry walk — the credential capture already exists at `ipc.py:45-58`; `_dispatch` just has to receive it). `config set` keys that lower safety (`agent.allow_shell`, `agent.autonomy`, `cua.*`, `spend` caps) refuse regardless of mark when the peer is not the daemon's own UI — or at minimum refuse for marked peers.
- R-organize: clacky's organize is a **composite, journal-first tool**, never decomposed into raw move primitives the model could run unjournaled. Shape: `organize <dir> [policy]` -> plan/dry-run (T0, pure) -> manifest rendered in the confirm card's `detail` field (the field exists, IPC_CONTRACT "Confirm card") -> apply as move-only + journaled -> `organize undo` reverses. Protected paths refuse outright.
- R-grants: spawned agents get no wisp credentials and no wisp-side `mcp_call` — their connector access is whatever the *runtime's own* MCP config grants; the plan must state that explicitly, because clacky's "any MCP server you connect" auto-carries is the risky version.

**Key Technical Decisions**

- KTD-agent-lifecycle: keep `agents.py`'s file-registry + detached-process model (it already reconciles across daemon restarts via pstart pinning — `agents.py:64-100`); extend records with `exit_code`, `delivers`, `routine_id`, `spawned_by`, `depth`. Do not build a supervisor daemon; the 5 s reaper + `on_finished` hook (`agents.py:437-462`, `wispd:708`) is the right seam — delivery verification and routine outcome-recording both hang there.
- KTD-composite-not-primitives: background-agent delegation stays ONE composite tool (`agent_spawn`) for the voice loop; the IPC/CLI exposes the primitives (`task run|status|cancel|list`) it composes. Rationale: a voice turn needs one call; a script needs the pieces. Do not add a second delegation surface — the current split is already correct, just incomplete (`task output`/`agent_artifacts` reads are missing).
- KTD-organize-boundary: organize is move-only, same-filesystem, journaled per file, crash-resumable, with an allowlisted root set (`~/Desktop`, `~/Downloads`, explicit args) — never `.git`, `.config`, `.local`, system paths, never cross-device (copy+delete breaks the crash-safe undo invariant).
- KTD-skills-share: one store (`SKILLS_DIR`), exported read-only into spawned runtimes by whatever mechanism each runtime honors (`--add-dir`-style flags, env, or a generated index in the task's `cwd`). Never copy/mutate a second store — `skills.import_dir` already demonstrates the snapshot-not-symlink convention (`skills.py:488-522`).
- KTD-mcp-tiers-for-agents: if the plan shares connectors into background runtimes, default to read-verbs only; write-capable servers must be named in the spawn-time confirmation text. Auto-approving a Composio-style 1000-app connector bundle into an unattended agent is the specific anti-pattern to forbid.
- KTD-proportional-gates: reuse the T0-T3 + batched-checkpoint + `HARD_STOP_KINDS` machinery (`policy.py`, `conversation_grants.py:16-24`) unchanged for new capabilities — organize-apply T2, organize-plan T0, routine-create T2 + first-run opt-in (`routines.py:371-417`), routine edits/pause T2, skill authoring T2 (already), agent_spawn T1 with undo_ref `task_cancel` (already, `policy.py:170`).

**Implementation Units** (suggested partition the plan can adopt/merge)

- U-lifecycle: exit-code capture at reap; `delivers` verification on `task_finished`; `task output`/`artifacts` IPC reads; `spawned_by`/`depth` fields; honest `done|failed` in `tasks` state.
- U-ipc-authz: peer marking on spawn + mutating-command refusal + safety-key config gating. (Blocks/clarifies the whole connector-sharing story; cheap — the credential plumbing exists.)
- U-routines-wire: `agents run`/`task run --routine` real path + daemon-down fallback + outcome recording + notification + AgentsTab unread dot. This is finishing H5, not new scope.
- U-organize: composite tool with plan->confirm(detail=manifest)->apply->journal->undo.
- U-skills-export: runtime-appropriate export of the skill index/dirs into spawned tasks.
- U-voice-routine: "save this as my <name> routine" teach path -> RoutineStore.create with `confirm_fn` wired to the existing broker.

**System-Wide Impact**

- `tasks.jsonl` record + `tasks` state field + `task_finished` event all grow fields — additive under the contract's rules, but `docs/IPC_CONTRACT.md` must be bumped and `rs/wispd` (agents.rs/ipc.rs + `parity.rs`) lands the same change; every IPC/agent change is a two-implementation cost.
- `wispd` handler signature change (`peer` into `_dispatch`) touches the hot dispatch — keep it additive.
- Notifications gain actions (`open <file>`) — `notify.py` already supports `actions` where the server advertises them.
- New `[routines]`/`[agents]` config keys need `settings_schema.py` + `docs/CONFIG.md` entries; the existing `[agent]` (Jev/session) vs `[agents]` (act-loop bounds) vs `cfg["agent"]["max_concurrent"]` (background tasks, `agents.py:219`) split is already confusing — name ownership in CONFIG.md while there.

**Verification** (agent-native scenarios worth naming in the plan)

- Marked-peer refusals: a spawned agent's subtree sending `config set agent.allow_shell=true`, `{"cmd":"agent"}` (recursive spawn), `{"cmd":"choice"}`, `stop` -> refused; `status`/`context`/`task_status`/`captures` -> allowed.
- Delivery honesty: task declares `delivers: [out/report.md]`; file absent at finish -> `task_finished{delivered:false}` + notification says "claims report.md — not on disk"; present -> unread dot + open action.
- Exit truth: child killed by SIGKILL / exits 1 -> status `failed` (not `exited`-ambiguous); pid-reuse test stays green (existing `test_agents_reaper.py` pattern).
- Routine loop: timer fires `agents run` -> command resolves (today it cannot) -> outcome lands in `routines.json` (`unread=True`); 3 consecutive fails -> paused + exactly one notification; daemon-down timer still spawns and reconciles on next daemon start.
- Organize: dry-run writes nothing; confirm card shows the manifest via `detail`; journal records every move; `undo` restores incl. rename collisions; kill mid-apply -> resume or clean rollback; protected-root args refuse.
- Skill parity: `skill_manage create` -> spawned runtime's context sees it via the export path; `tool:` skill still floors at `mutating` (`skills.py:215-226`).
- Concurrency/depth: spawn at `max_concurrent` -> legible SKIP; agent-spawned-agent hits the same cap; `depth` increments and is bounded.
- Regression anchor: `tasks` snapshot shape stays additive for `wispd-rs` parity + shells.

**Scope Boundaries**

- No mid-run message/question channel into a spawned agent (stdin is DEVNULL, `agents.py:246`) — Now: it ends by notifying; Later: notification-action reply or a wisp-owned MCP shim.
- No checkpoint/resume inside a run — bound scope under `task_timeout_s`, split work into subtasks; runtime session-resume flags are a Later.
- `wispd connect` OAuth stays human-gated (browser sign-in in a personal browser — `mcpauth.py:165-226`); agents may *use* granted connectors, never *grant* them.
- No agent-side edits to its own schedule/timer; routine mutation goes through the same T2 confirm a human would.
- Never export wisp-held keys/tokens (openrouter key, omaseal refs) into a spawned agent's env; the runtime uses the user's own ambient config only.
- Routines stay systemd-user-timer on Linux; a macOS launchd path is explicitly Later (or scope the feature Linux-only).

**Now / Later / Never per capability**

| Capability | Class | Note |
|---|---|---|
| `agents run` CLI + routine outcome wiring | Now | shipped dead code today |
| Exit-aware status + deliverable verification | Now | cheap, unblocks honest notifications |
| IPC read/mutate split + marked-peer refusal | Now | gates everything below safely |
| organize plan/apply/undo (composite tool) | Now | the marquee clacky mechanic; journal-first |
| Voice-taught routine creation (opt-in gate) | Now | machinery exists; needs the route + confirm wiring |
| Skill export into spawned runtimes | Now | read-only export, single store |
| `task output`/`artifacts` IPC + AgentsTab surfacing | Now | completes action parity |
| Connectors inside background agents | Later | only after U-ipc-authz; read-tier servers first |
| Mid-run ask channel / message a running agent | Later | notification-action reply is the cheap interim |
| Checkpoint/resume via runtime session ids | Later | per-runtime flags; task text + prior-log summary is the interim |
| Composio-style bulk connector auto-grant | Never | per-server, read-first only |
| Agent-driven safety-lowering config (`allow_shell`, autonomy, cua.*) | Never | refuse for marked peers regardless of `config set` |
| Auto-unpause routines / self-extending schedules | Never | pause is a human decision |
| Agent granting OAuth (`connect` from an agent path) | Never | browser sign-in is the trust ceremony |

### Open Questions

1. Is hermes-agent itself a new `_RUNTIMES` entry (`agents.py:272`), or is the plan absorbing only its mechanics (skills format, routines, organize)? This decision splits U-skills-export and the connector story completely differently.
2. Do spawned agents need a question channel at all? If yes, the proportionate Now answer is "finish -> notify -> user follows up with a new spawn," not a bidirectional channel.
3. Is `wispd-rs` still parity-tracking? If yes, every unit above doubles; if it's frozen, the plan should say so explicitly.
4. Does `agent_spawn` need a Jev risk pre-score for tasks whose text implies external mutation ("post this", "email that") — i.e. should some spawns be T2 instead of flat T1?
5. Routine units when the daemon is down: direct-spawn fallback (recommended — registry reconciles) vs `Requires=wispd.service`? The answer changes whether `task run` needs a `--local` mode.
6. Organize undo scope: single-level undo (clacky's `clacky undo` = reverse last run) or a journal stack (undo N runs)? The former is the Now answer; the latter is a design choice worth pinning before the journal format is fixed.
7. Where do task workspaces live — `TASK_LOGS/<name>/out/` (inside DATA_DIR, auto-cleaned with logs) vs `~/wisp-out/` (user-visible)? Deliverable verification works either way; the difference is UX and retention policy.
