# Research: trycua cua-bench as a Wisp training arena

Agent: R5 · Date: 2026-10-13 · Repo studied: `trycua/cua` (monorepo, ~28k stars, MIT)

Question: can `cua-bench` serve as (or feed) a desktop-surface training arena for
Wisp's computer-use loop, given an aarch64 Asahi host and local CubeSandbox?

## VERDICT: adopt-as-arena (selectively) + mine-for-tasks

Adopt `cb` as a **second arena for screen-level tasks**: `cua-bench-basic` and
the `bench-web` adapter suites run natively on this host (arm64 container
images, plain Docker/runc), give Wisp pixel-level observe→act→verify episodes
with programmatic rewards, and emit ATIF trajectories with ready-made training
exports (aguvis-stage-1, gui-r1). Keep clicklab for cheap DOM-side iteration.
Skip OSWorld-Verified and the Windows/macOS surfaces (amd64-only or
macOS-only). Separately, mine `libs/cua-s1` + `libs/cua-bench-rl` as reference
implementations — they are a worked SFT→RL pipeline for a small CUA model on
exactly this task format.

## Where it lives

- Package: `cua-bench` on PyPI (`cb` CLI), source at
  `libs/cua-bench/` in `github.com/trycua/cua`. Version 0.3.0. MIT.
- Companions: `libs/cua-bench-rl` (RL workers/dataloader/GRPO trainer),
  `libs/cua-s1` + `libs/cua-bench-s1` (their S1 specialist-model research),
  `libs/python/agent` (`cua-agent` framework), `libs/cua-spacesd` (in-sandbox
  daemon, gRPC :3211).
- Registry: `cua.ai/cuabench/registry`; taskset names pin to git commits,
  fetched into `~/.cua/cbregistry`. `CUA_BENCH_REGISTRY` allows a private index.

## Environment inventory

Registry tasksets (all run on a real desktop sandbox; agent sees the screen,
drives mouse/keyboard — never a DOM):

| Taskset | Tasks (variants) | Surface | Verifier |
|---|---|---|---|
| `cua-bench-basic` | 13 (68) | `bench-web` image: Linux desktop + bench-ui (pywebview) | JS state inside the window (`execute_javascript`), e.g. `window.__submitted` |
| `cua-bench-kicad` | 25 | `ghcr.io/trycua/linux` desktop | KiCad netlist comparison (PySpice) |
| `cua-bench-workflows` | 2 (52) | same | Multi-step OpenShot/Unity; no oracle |

`cua-bench-basic` task list is almost a superset of clicklab's widget
vocabulary: click-button, click-icon, color-picker, date-picker, drag-drop,
drag-slider, fill-form, right-click-menu, select-dropdown, spreadsheet-cell,
toggle-switch, typing-input, video-player.

Adapter benchmarks (`libs/cua-bench/tasks/`), run with the same `cb run`:

| Adapter | Items | Image / arch | Reward |
|---|---|---|---|
| OSWorld-Verified | 369 | `bench-osworld:verified` — **amd64 only**, KVM for VMs | OSWorld's own evaluators via guest control server :5000 |
| MiniWoB++ | 130 | `bench-web:1.0` — amd64+arm64 | Page's own reward fn |
| WebVoyager | 643 | `bench-web:1.0` | LLM judge (`auto_eval`), needs `OPENAI_API_KEY` + net |
| Online-Mind2Web | 300 | `bench-web:1.0` | WebJudge LLM, gated HF dataset |
| WebGym | 1,167 | `bench-web:1.0` | LLM judge |
| OSWorld-G | 564 | none (screenshots) | Click-in-box/polygon; refusal items |
| ScreenSpot-Pro | ~1,581 | none (screenshots) | Point-in-box grounding |

Also `winarena_adapter` (Windows Agent Arena) and a `wordpad_env`.

## Task format (the part worth stealing even if we never run `cb`)

One directory per task, one `main.py`, four decorated functions:

```python
@cb.tasks_config(split="train")   # load() -> list[cb.Task]: the VARIANTS
@cb.setup_task(split="train")     # async(task_cfg, session): prepare env
@cb.solve_task(split="train")     # optional oracle; proves the task is solvable
@cb.evaluate_task(split="train")  # async -> list[float]: reward from final state
```

- `cb.Task`: `description` (prompt), `metadata` (variant params), `computer`
  (`provider:"native"` + `setup_config{os_type, image, kind, width, height}`).
- `cb.DesktopSession` ops: `run_command`, `read_file`/`write_file`/
  `file_exists`, `launch_window(html=...)` (bench-ui pywebview → window id),
  `execute_javascript(pid, js)`, `click_element(pid, sel)` (oracle only),
  `execute_action`, `screenshot()`.
- Reward model: deterministic programmatic state checks returning floats —
  JS-in-window state, file contents, shell output, netlist diff, OSWorld
  evaluator, or LLM judge. No learned reward needed.
- Oracle semantics: `--oracle` runs `solve_task` through the evaluator
  (expect reward=1) — a self-test that a task is not broken. `--noop` scores
  an untouched env (reward floor). `--attempts N` gives pass@k.

## Runner / agent loop

```bash
uv tool install cua-bench          # or pip install cua-bench
cb run cua-bench-basic --task-filter 'click-*'          # oracle smoke
cb run cua-bench-basic --agent cua-agent --model anthropic/... -j 4
cb run my_task --agent-import-path my.module:Agent      # custom agent in-process
cb run ... --agent harness                               # Claude Code/Codex inside the sandbox via MCP
cb interact my_task --variant-id 0                       # manual drive + eval
cb dataset build <run dir>                               # export trajectories
```

- Local runtimes: `gvisor` (default) or `runc` for Linux containers; `qemu`,
  `lume` for VMs. Cloud: gVisor containers / KubeVirt VMs on Cua Fleet.
- Agents are loaded in-process; the loop is screenshot → action calls into the
  sandbox. Results land in `~/.local/share/cua-bench/runs/<id>/`:
  `trajectory.json` is **ATIF-v1.8** (Harbor format) with per-step screenshots;
  `result.json` records image digest, arch, verifier rewards, timing;
  `summary.json` has pass@k + per-target breakdown.
- Training exports: `cb dataset build` emits aguvis-stage-1 and gui-r1.

## Requirements / aarch64 feasibility (omarchy-max)

- Python `>=3.12,<3.14`; MIT; deps modest (cua-sandbox, cua-agent, aiohttp,
  rich, datasets, pillow…). `pipx`/`uv tool` install is clean.
- **arm64 works for the surfaces we care about.** `ghcr.io/trycua/linux:24.04`
  and `ghcr.io/trycua/bench-web:1.0` are multi-arch (the image-software doc is
  literally generated from the arm64 child; PR #3257 added + validated local
  Linux-on-ARM64 on Apple Silicon). There is even `ghcr.io/trycua/omarchy:edge`.
- Local containers need Docker (`runc`) or gVisor — Docker already runs on this
  host; `--runtime runc` is the fallback for anything gVisor can't do
  (kicad/workflows `apt install` need it anyway).
- **Does NOT run here:** OSWorld-Verified image is amd64-only (and would need
  KVM x86 emulation — no). Windows/macOS guests are amd64/lume(macOS)-only.
  Android is local-only via a path that needs VM support.
- CubeVM integration: plausible but not first-class. `cb` provisions its own
  sandboxes via the cua SDK; `RemoteDesktopSession` can attach
  `direct:<host:port>` to a cua-spacesd, so a CubeVM running spacesd could be
  driven by cb's task lifecycle — custom glue required. Simpler: run `cb`
  containers on the host's Docker; use CubeVM only if we want stronger
  isolation than gVisor/runc.

## Model weights / trainer

- trycua ships their **own** weights under `cua-ai/*` on HF:
  `cua-s1-4b-0.1/0.2` (LoRA r16 on frozen Qwen3.5-4B, Apache-2.0, text +
  multimodal adapters, SFT→RL against live GUI envs), `cua-s1-nano-0.1`
  (855K-param option-attention classifier, Apache-2.0), `cua-s1-forms`
  (706K tinyx checkpoint, MIT). Methodology + eval code in `libs/cua-s1`,
  `libs/cua-bench-s1` — directly relevant as a worked small-CUA-model recipe.
- Trainer: `cua-bench-rl` — per-env FastAPI worker server + manager,
  MultiTurnDataloader, ReplayBuffer, and a **Tinker** GRPO trainer (Thinking
  Machines' hosted API — usable but it's an external dependency; the worker/
  buffer design is the reusable part).
- `cua-agent` loops: Anthropic/OpenAI/Gemini native CUA, plus UI-TARS
  (`uitars-hf`, `uitars-mlx`), GLM-4.5V, InternVL, Qwen-VL, and OmniParser+any-
  VLM composed loops. UI-TARS-compatible in the sense that UI-TARS checkpoints
  plug in as agent adapters; they do not ship a UI-TARS finetune themselves.
- Note: Wisp already ships trycua code — `cua-driver` is our pointer backend
  (`scripts/cua/PIN`). Same org, same license, already vetted.

## Fit vs. clicklab

| | clicklab (current) | cua-bench-basic |
|---|---|---|
| Surface | Browser page, DOM-driven | Real desktop sandbox, pixels only |
| Action space | DOM events | Mouse/keyboard through screen |
| Variants | suites.json | `tasks_config` list |
| Reward | scripted page state | `evaluate_task` → float list |
| Trajectory | wisp train logs | ATIF + exported SFT formats |
| Cost | ~free, no container | Docker desktop per episode |

They are complementary: clicklab stays the fast DOM harness; cua-bench gives
the screen-level episodes Wisp's grounding/actuation actually trains on.

## Suggested path

1. `uv tool install cua-bench` → `cb run cua-bench-basic --task-filter
   'click-*' --runtime runc` to verify arm64 images pull and oracle=1.
2. Write one `--agent-import-path` adapter that maps Wisp's observe→act loop
   onto the cb agent interface (screenshot in, action out).
3. Convert the clicklab task generator to emit cb task dirs — same
   HTML/`evaluate_task`-JS pattern — so both arenas share task sources.
4. Later: `libs/cua-bench-rl` worker model + `libs/cua-s1` recipe as the
   template for Wisp's own SFT→RL stage; OSWorld only via their cloud or an
   x86 machine.

## Sources

- `libs/cua-bench/README.md`, `pyproject.toml`, `example_tasks/`,
  `datasets/cua-bench-basic/*/main.py`, `tasks/` — github.com/trycua/cua
- Docs: cua.ai/docs — cua-bench introduction, write-a-task, benchmarks,
  adapter-benchmarks, sandbox-images, image-software
- `libs/cua-bench-rl`, `libs/cua-s1`, `libs/cua-bench-s1` READMEs;
  HF `cua-ai/cua-s1-4b-0.2` model card; PR #3257 (arm64 local Linux)
