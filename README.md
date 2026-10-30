# Wisp

Wisp is a resident voice companion for Omarchy (Hyprland). Hold `Super+D`,
speak, and Wisp hears you, decides what you meant, and acts: it answers
with your screen as context, drives the desktop one step at a time, points
at the thing it means, or hands a long job to a background coding agent.
It keeps the conversation open across utterances, so "check the build",
"open it" and "scroll to the failure" are one task.

Pipeline: push-to-talk, PipeWire capture, whisper.cpp, Jev routing, then
one of launch, tool, agent, act, dictate, answer or clarify. The result
shows up as the bar mark and live pill, a cursor bubble, a bottom-center
listening pill on the overlay, and the Panel.

Status: v0.9 shipped; v1.0 is a verification milestone (a labelled soak,
a fresh-box install and the learning loop; see `ROADMAP.md`). Linux
(Omarchy/Hyprland) is the only supported platform.

## What it looks like

These images are real renders. They are composed from the offscreen
snapshot goldens in `tests/qml/snapshots` (the shipped QML components run
through the real state reducer, with no compositor and no mock-ups) by
`scripts/ui/readme_media.py`. Live screen recordings are made by a
repeatable harness (`scripts/demo/record.py`) and none is published yet; see
[Media](#media) and [docs/MEDIA.md](docs/MEDIA.md).

<!-- hero:start -->
<!-- hero:end -->

![Companion overlay: listening pill, answer bubble, confirm card, cursor buddy (goldens predate the in-bar live pill — see Surfaces)](assets/readme/companion.png)

![The panel: Now, Agents, Memory and Settings tabs](assets/readme/panel.png)

![The bar mark, one glyph per state](assets/readme/bar-mark.png)

![The first-run card](assets/readme/first-run.png)

![The management app: Health, Spend, Audit and Binds](assets/readme/manage.png)

## Install

On Omarchy you can paste one prompt into your coding agent and let it do the
install with you; see [Let your coding agent do it](docs/INSTALL.md#let-your-coding-agent-do-it).

```sh
git clone https://github.com/duketopceo/wisp
cd wisp
python3 wispd install          # files, shell plugin, unit, desktop entry, bind
systemctl --user enable --now wispd
wispd onboard                  # guided first run, every step skippable
```

- `wispd install --units` installs only the systemd units for the local
  model services and the daemon (oomd-safe, see `docs/LINUX.md`). Add
  `--dry-run` to preview. It never enables or starts anything.
- `wispd install --cua` installs the pinned `cua-driver` (checksum
  verified, user scope, no sudo). `--dry-run` previews it.
- `wispd onboard` checks the microphone, the local models, the cua driver,
  notifications and the keyboard submap. The Panel shows the same
  checklist as a card until you finish. Nothing in it edits your config.
- Some questions are answered from this machine with no model call: "what
  model are you", "what did I spend today" (or "this week"), "what version
  is this", "say that again", "copy that" (puts the last answer on the
  clipboard) and "what went wrong". They match only as the whole
  sentence, so "explain what version control is" still goes to the model.
- `wispd doctor` checks every dependency and prints the fix for each
  missing one.
- `wispd whatsnew` shows what changed in the version you have (the Panel
  shows it once after an update), and `wispd bugreport` writes one
  markdown file for a bug report: version, health, recent error codes,
  trace counts and a masked config, never what you said or saw. Nothing
  is sent; you open the issue yourself.
- `wispd export lesson NAME` (or `skill`, or `helper`) writes one file you
  can share (no keys, home paths, memory or scripts), and `wispd import FILE|URL`
  shows its full text and what it asks for, and imports it only on your
  yes. Imported helper routines arrive paused (`wispd routine list`,
  `wispd routine resume ID`).

Prerequisites: `pw-record` (or `arecord`), whisper.cpp at
`~/src/whisper.cpp` with `models/ggml-small.en.bin`, `hyprctl`,
`notify-send`. Optional: `grim`, `wtype`, `espeak-ng`, `ori` (agent
spawning). Secrets go in `~/.config/wisp/.env` (`OPENROUTER_API_KEY=...`)
or an `omaseal` reference; nothing is committed. Full steps and per-OS
notes are in `docs/INSTALL.md`; every config key is in `docs/CONFIG.md`.

## Surfaces

- **Bar mark and live pill**: one glyph in the Omarchy bar for state at a
  glance, plus an in-bar pill that grows while Wisp works — status word,
  mic-level meter while listening, and the same vocabulary as the overlay.
  Click toggles talk, middle-click stops the turn, right-click opens the
  Panel. The pill names the state (listening, thinking, speaking, acting,
  needs you, error) and, after a finished turn, shows thumbs for eight
  seconds so you can rate it in one tap.
- **Companion overlay**: transient surfaces only (no corner orb): a
  bottom-center pill while you speak, answers in a bubble next to your
  cursor (with thumbs-up and thumbs-down rating buttons; `Super+Alt+D` rates the last turn wrong and opens a one-line note), confirm/choice chips on
  the pill, and a cursor buddy beside the pointer that flies to act targets. Step detail lives in the
  Panel Now tab, not a separate console window.
- **Panel**: opened from the bar. Four tabs (five with the Dev tab): Now (the current turn and
  steps), Agents (background tasks), Memory (skills and recent
  decisions) and Settings (health, spend caps, pointer and cua safety,
  connectors). A first-run card sits on top until setup is finished.
  With `[dev] panel = true` a fifth tab, Dev, shows the v1 gate tally,
  recent turns with per-stage time and the top misses (local only; the
  same data as `wispd dev turns`).
- **Desktop entry**: "Wisp" in the app menu, with Listen, Stop and Panel
  actions. No tray icon is shipped (see `docs/INSTALL.md`).
- **Management app and TUI**: Health, Spend, Audit and Binds views over
  the same data. `wispd tui` is the terminal version.

Every surface reads one state stream from the daemon
(`docs/IPC_CONTRACT.md`), so they never disagree.

## Using it

| Keys | What happens |
|---|---|
| `Super+D` (hold) | listen; release to send. `wispd trigger start` / `stop` does the same; bare `wispd trigger` toggles |
| `Super+D` (hold) while a choice/confirm waits or a turn runs | speak your pick ("yes", "the second one", an option label) or say stop / wait / never mind to interrupt — same IPC path as `wispd choice` / `interrupt` |
| `Esc` while Wisp acts or waits | stop the turn |
| `Enter` on a confirm card | pick option 1 (the yes) |
| `1` to `9` on a choice | pick that option |

The `Esc`, `Enter` and number keys exist only while a turn is acting or
waiting, through a Hyprland submap named `wisp`, so they never shadow
typing. `[keys] submap = "false"` turns the submap off. Nothing is written
to your Hyprland config.

What a turn can do:

- **Answer**: with the screenshot taken when you pressed the key, so it
  already knows the focused app. `[POINT]` replies fly the cursor buddy to the point.
  Set `[agent] screenshots = "false"` to keep images local.
- **Act**: a bounded loop that re-screenshots before every pointer action.
  No blind clicks. See [Computer use](#computer-use).
- **Agent**: "Wisp, agent, fix the tests in wisp" starts a named task on
  your runtime (`opencode`, `codex`, `claude` or `devin`; `auto` probes
  `PATH`). `wispd task list` shows status and a live log tail.
  **Named helpers**: "make me a research helper called Scout" gives it a
  folder in the data dir (`agents/scout/`: `AGENTS.md` identity, dated
  `notes/`, `output/`, `tmp/`). "Tell Scout to ..." starts a run that reads
  its identity and notes (a busy helper gets the message in its inbox
  instead), and "what's running" lists the live ones. A helper asks once with
  bundled questions, prints `PROGRESS:` lines, and the first sentence of its
  result is what Wisp speaks.
- **Tools**: launch, focus and close apps, switch workspace, notify,
  screenshot, pointer, typing, a guarded shell, file search, DOM-mode
  `fill` and click-by-id, X compose helpers (`post` / `post_send`), and
  `mcp_call` to any configured MCP server. `wispd connect <service>`
  connects OAuth services through the local BrowserOS gateway.
- **Goal memory**: utterances that share the focused app or the running
  goal join one goal (`[agent] goal_ttl_s`, 10 minutes). Questions from
  the agent come back through the voice backchannel without ending it.

Spoken settings: "talk slower", "talk faster" and "talk at normal speed"
change `[voice] speed` (0.5 to 1.5) and are logged with the guarded calls
(`wispd cua log --audit`).

Spoken answers use Groq Orpheus when a Groq key resolves (the same key as
speech-to-text), and fall back to espeak for the turn if Groq is slow or
refuses. `[voice] enabled` is `auto` by default: on only with a Groq key.
`wispd doctor` shows which voice is in use and the last Groq error.

## Computer use

Wisp can click, scroll, type and press keys for you. Pointer backends,
in auto order: `cua` (background virtual pointer, no focus steal),
`hyprcursor`, `ydotool`, `wlrctl`, then `guide`, where Wisp only shows
the target and you click. `[pointer] mode` is `guide` by default (safe),
`drive` to inject input, or `auto`.

Safety is on by default and sits between the act loop and the backend:

- a kill switch (`wispd cua kill`, `wispd cua resume`) that refuses all
  input at once, and a dry run mode that plans and logs without acting;
- a built-in deny list (password managers, polkit and pinentry prompts,
  keyrings, terminals showing `sudo`) plus your own `[cua] deny` and
  `[cua] allow` lists;
- rate caps per minute and per turn, and a confirm card for risky steps
  (one yes covers a tool in one app for the session);
- an audit line for every call in `~/.local/state/wisp/cua.jsonl`. Typed
  text, target names and screenshots are never written.

Targets are grounded from names to screen points through a chain: the
window's accessibility tree, then local UI-TARS, then the vision
fallback. A low-confidence point is re-observed once and then refused,
never clicked. How all of this fits together, with config keys and
troubleshooting, is in [`docs/CUA.md`](docs/CUA.md).

## Spend

Paid-model spend is recorded in one ledger (`wispd spend`). Caps are USD
and reset by local date:

- `[budget] daily_usd` (default 8.00) and `[budget] monthly_usd`
  (default 160.00). `[brain] daily_cap_usd` still works as an alias for
  the daily cap.
- At a cap, paid fallback models stop. The primary brain keeps running so
  Wisp does not go dumb mid-task, unless `[budget] gate_primary = "true"`,
  which stops the primary too.
- Local models are recorded at zero cost and never gated.

## Local models

Wisp runs on local OpenAI-compatible servers when you want zero marginal
cost. Any `llama.cpp`, Ollama or LM Studio endpoint works as a
`[brain.<name>]` provider.

| Endpoint | Port | Role |
|---|---|---|
| Ornith (llama-server, GPU) | `:8080` | answer and act brain |
| Jev (llama-jev) behind jev-shim | `:8091`, `:8931` | decisions router |
| UI-TARS-7B (llama-server) | `:8081` | GUI grounding, emits `Action: click(x,y)` text |
| Ollama | `:11434` | CPU or GPU brain, native `/api/chat` |

`wispd health` probes these over loopback only. `wispd health start`
prints the command that starts a down endpoint (`--run` executes it).
Jev is an accelerator, not a gate: past `[jev] deadline_ms` a heuristic
router decides and the turn goes on. Provider sections and flags are in
`docs/CONFIG.md`.

## Learning

Every run can be labelled (`wispd label set correct|incorrect`, or the
`good` and `wrong` buttons). `wispd eval` scores the labels
by turn kind (answer, act, launch, dictate, agent) and checks the
`[eval]` gate. `wispd eval --misses` groups the turns that were not
right first time, and `wispd eval --unlabelled` lists the turns still
waiting for a label. `wispd learn fails` lists logged failures.

## Walkthroughs

Say "walk me through <task>" (also "guide me through", "take me through",
"teach me how to"). Wisp plans up to 15 steps, speaks each one and points
at its control, then waits for you to do it: the focused window or its
title changing counts as done. After 20 s of no change it asks "done, or
stuck?". Pointing is label-first: the control's on-screen label is looked
up through the app's control channel and the accessibility tree before the
model's own coordinates are used. Wisp never clicks or types during a
walkthrough, and Esc stops it.

Say "demonstrate <task>" (or "demo me <task>") and Wisp narrates and points
at every step in one go without waiting for you. When the focused app has a
skill (`app_classes` in its frontmatter), its notes go into the plan.

Wisp first asks whether you have already started or are starting fresh, and
plans around the answer. If a walkthrough stops (you press the key, or you
don't answer "done, or stuck?"), it is kept for six hours: do the step
yourself, then say "continue" (or "next step", "I did that") and Wisp picks
up with the same goal and the steps already done, without repeating them.

When a walkthrough finishes, say "save that as a lesson called <name>" (or
just "save that lesson"). "Replay that lesson" (or "replay the lesson about
<topic>") speaks and points at the saved steps again without asking a model
anything.

## First minute

`wispd onboard --tour` runs five spoken steps that show Wisp working: hello,
draw, circle, ask about your screen, dictation. Each step waits for you to do
what it asked and records a pass; a step you skip is offered again next run.
`wispd onboard --tour circle` replays one step.

## Privacy

- Wisp hears you only while you hold the key, unless you opt in to
  hands-free (double-tap) or a local wake word. Both are off by default,
  tell you what they listen to when you turn them on, and are described in
  [docs/PRIVACY.md](docs/PRIVACY.md).
- Every outside host, what it gets, who holds the key and what you
  control is listed in [docs/TRUST.md](docs/TRUST.md), a page generated
  from the code (a test fails when a new host appears without an entry).
- Audio goes to your speech provider (Groq by default) unless you set
  `[stt] provider = "local"`, which transcribes on this machine with
  whisper.cpp.
- Screenshots ride into the model only for the turn that needs them, and
  stay on the machine when `screenshots = "false"` or the brain is local.
- Error reporting is off. If you set `[report] dsn` (a GlitchTip DSN or
  an `omaseal://` reference), only typed error codes and a scrubbed
  context are sent: never transcripts, screenshots, typed text, keys,
  environment values or paths with your username.
- Asking about "this document" reads the focused PDF, DOCX, XLSX or
  text file on your machine and sends only the pages that matter to the
  answer. Keys, config, keyrings, browser profiles and system folders
  are never read, and `[docs] enabled = "false"` turns it off.
- Asking about "this" or "that" can use the text you selected, the
  image you copied or the file path you highlighted. The selection is
  read when you press the key, the clipboard only when the question says
  "this", "that", "copied" or "selected", nothing between presses. It
  goes to the answer only, as quoted data, and
  `[selection] enabled = "false"` turns it off.
- Transcripts, replies and traces stay in `~/.local/share/wisp`, a 0700
  folder of 0600 files (the daemon runs with umask 077 and starts by
  tightening anything an older version wrote); settings and keys in
  `~/.config/wisp` are private the same way.
- The cua audit log keeps the length and a salted hash of typed text,
  not the text.

## Commands

Run `wispd --help` for the grouped list and `wispd <command> --help` for
verbs and examples. Add `--json` for machine-readable output.

| Command | What it does |
|---|---|
| `wispd daemon run` | run the daemon in the foreground (what the unit starts) |
| `wispd install` | install files, plugin, unit, desktop entry and bind |
| `wispd status` / `wispd stop` | show the daemon state, or stop the daemon |
| `wispd trigger` | push-to-talk toggle, what the bind runs |
| `wispd interrupt` | cancel the turn in flight, keep the daemon |
| `wispd choice <pick>` | answer a pending prompt |
| `wispd watch` | follow the push stream as NDJSON |
| `wispd tui` | terminal dashboard |
| `wispd note` | show or follow the live paper (`note.md`) |
| `wispd scribble set\|clear` | the strokes drawn on screen while holding the talk key (the overlay calls this; they reach the next screenshot only) |
| `wispd doctor` | check every dependency |
| `wispd health` | local model endpoint health |
| `wispd latency` | p50 and p90 per budget path |
| `wispd spend` | usage today and the caps |
| `wispd binds` | the hotkey and its Hyprland binds |
| `wispd onboard` | guided first run |
| `wispd trace show` / `trace digest` | turn trace and local digest |
| `wispd captures [turn] [--full]` | capture-pack list or one pack's manifest |
| `wispd cua status` | whether the cua pointer backend is usable |
| `wispd cua kill` / `wispd cua resume` | arm or clear the kill switch |
| `wispd cua log` | the driver journal, or the audit log |
| `wispd notify test` | send one test notification |
| `wispd task list` | background agents |
| `wispd memory edit` | edit the MEMORY and USER notes |
| `wispd dictate correct` / `wispd dictate list` | teach a heard->meant dictation correction, or show them |
| `wispd suggest list` | suggestions mined from your activity |
| `wispd label set` / `wispd eval` | label a run, or score your labels by turn kind |
| `wispd dev turns` | the last turns with per-stage time, labels, the v1 gate and top misses (read-only) |
| `wispd context` | what the daemon sees right now |
| `wispd ask TEXT` | ask one typed question as a normal turn (a click on a 3D part sends this) |
| `wispd learn fails` | logged failures |
| `wispd skills list` | installed skills |
| `wispd config show` / `wispd config set` | read or change config live |
| `wispd theme` | pick the theme or audit contrast |
| `wispd connect <service>` | connect an outside service |
| `wispd sync` | refresh the MEMORY block and import skills |
| `wispd inventory` | scan apps, CLI tools and MCP servers |
| `wispd completion bash` | print a shell completion script |

Exit codes: 0 ok, 1 failure, 2 usage, 3 daemon not running, 4 unhealthy
dependency.

## Data files

Local, never committed:

- `~/.local/share/wisp/`: `session.jsonl`, `decisions.jsonl`,
  `labels.jsonl`, `trajectories.jsonl`, `usage.jsonl` (the spend
  ledger), `inventory.json`, `corrections.jsonl`, `dictation.json`
  (dictate corrections + per-app counts), `tasks.jsonl`,
  `onboard.json`,
  `packs/<turn>/` (durable capture packs — `wispd captures`),
  `rec/<turn>/` (transient in-flight recording), `pack.salt`
- `~/.local/state/wisp/cua.jsonl`: the cua audit log
- `~/.config/wisp/`: `config.toml`, `.env`, `mcp.json`
- `$XDG_RUNTIME_DIR/wisp/`: `state.json` and the `wispd.sock` socket

## Media

The images above are deterministic and re-made with
`python3 scripts/ui/readme_media.py` after `python3 scripts/ui/snap.py
update`. A test (`tests/test_readme_media.py`) keeps every README image
present and under 250 KB.

Live recordings come from real turns, recorded the same way every time
by `python3 scripts/demo/record.py <script>` (five 30 to 60 second scripts in
`scripts/demo/scripts/`; `--dry-run` prints the plan and records nothing).
A clip is kept only if the turn it shows really happened (the script's
`proof:` line is checked against the decision log), sensitive windows are
blanked in the video, and paths and tokens are scrubbed from every text
artefact. Details, the size caps and the caption files are in
[docs/MEDIA.md](docs/MEDIA.md). The harness writes files and posts nothing.

## Development

```sh
python3 -m unittest discover -s tests          # host-independent
python3 -m py_compile wispd wisp/*.py wisp/tools/*.py
python3 scripts/ui/snap.py check               # QML snapshot goldens
python3 scripts/assets/gen_copy.py --check     # copy table up to date
python3 scripts/assets/gen_settings.py --check # settings table up to date
```

Layout: `wispd` (entry), `wisp/` (config, ipc, state,
`pipeline.py` orchestrator + `stage_{capture,route,execute,speak}.py`,
routing, act, cua, grounding, ledger, learn, voicepick, tools),
`shell-plugin/` (the
quickshell plugin: components, lib, Panel, Companion), `shells/` (the
management app), `scripts/` (harness, snapshot and asset tools), `docs/`
(install, config, IPC contract, CUA, plans). The plan of record is
`docs/plans/2026-10-04-0100-feat-wisp-unified-plan.md`.

## License

AGPL-3.0. Free to use and modify, including privately. If you host or distribute a modified version, you must publish your source under the same license. See [`LICENSE`](LICENSE).

Releases up to and including v0.9.0 were published under the MIT License and remain available under MIT. Icons and artwork in `assets/` stay CC0 (see `assets/LICENSE`), and the bundled test fonts keep their own license (`tests/qml/fonts/LICENSE-Liberation`).
