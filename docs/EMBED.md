# Embedding Wisp in another shell

Any shell (a bar, a panel, a launcher, a script) can show Wisp live and act
on it through the `wispd` CLI. Wisp's own QML components need its service,
theme tokens and kit, which other shells do not host, so the contract is the
CLI, not the QML. Everything here is pinned by `tests/test_embed_contract.py`.

The rule for hosts: **never copy Wisp's status words.** Read them from the
CLI, so your shell says exactly what the Wisp bar, Panel and overlay say.

## Presence and version

| Check | How | Meaning |
|---|---|---|
| Installed | `wispd` is on `PATH` | Wisp is installed for this user |
| Running | `wispd status --json` exit 0 | the daemon answered |
| Down | `wispd status --json` exit 3 | installed, daemon not running |
| Embed version | `data.embed_version` from `wispd status --table --json` | `1` today |
| No embed contract | `wispd status --table --json` exit 2 | an older `wispd`; fall back to "installed" only |
| Stream version | `contract_version` on the watch `hello` line | the IPC contract version (`docs/IPC_CONTRACT.md`) |

`embed_version` rises only when a field below changes meaning or goes away.
New fields are added without a bump, so ignore fields you do not know.

## Read path

```
wispd watch state tasks
wispd status --json
wispd status --table --json
```

### `wispd watch state tasks`

NDJSON, one object per line, reconnecting forever. The lines are the
daemon's subscribe stream, defined in `docs/IPC_CONTRACT.md`: `hello`,
`snapshot`, then `state` diffs, named `event`s and `ping`s. The CLI adds one
thing: every `snapshot` and `state` line carries

```json
"view": {"word": "working", "tone": "ember"}
```

computed from the state merged so far (the snapshot plus every diff since).
Show `view.word` with `view.tone`; do not map `state.status` yourself. A
fresh `snapshot` (sent on every reconnect) replaces the merged state.

Two things the stream cannot tell you on its own:

- **Stale.** A busy turn (`transcribing`, `deciding`, `acting`) refreshes
  `heartbeat_at` every 15 s. If a busy turn sees no `state` line for 20 s,
  show the `stale` row from the table ("reconnecting", `muted`) instead of
  `view`. Pings do not count as change.
- **Offline.** `wispd watch` reconnects silently, so while the daemon is down
  it prints nothing. After 45 s with no line at all (not even a `ping`), run
  `wispd status --json`; on exit 3 show its offline word.

### `wispd status --json`

One-shot state. The output is the CLI envelope:

```json
{"ok": true, "command": "status",
 "data": {"state": {"status": "acting", "...": "..."}, "deploy": {"commit": "..."},
          "word": "working", "tone": "ember"}}
```

`data.word` and `data.tone` follow the same precedence as every Wisp
surface: an `error` with an `error_code` reads that code's message, a `done`
whose `result` starts with `BLOCKED` reads "blocked", anything else reads its
status word. `data.state` is the daemon's state as `docs/IPC_CONTRACT.md`
describes it.

With the daemon down it exits 3 with the error envelope, and `data` still
carries the offline word, so a host never hardcodes it:

```json
{"ok": false, "command": "status",
 "error": {"code": "E_DAEMON_DOWN", "message": "...", "try": "..."},
 "data": {"status": "offline", "word": "offline", "tone": "muted"}}
```

### `wispd status --table --json`

The whole status table resolved to text. It never contacts the daemon, so it
works when Wisp is down and is cheap to call once at startup. Use it for
states your shell computes itself (stale, offline) and for a short word when
space is tight.

```json
{"ok": true, "command": "status",
 "data": {"embed_version": 1,
          "rows": [{"key": "transcribing", "derived": false,
                    "word": "hearing you", "short": "hearing", "tone": "ember"}],
          "causes": {"jev_down": "model", "stt_down": "speech"}}}
```

- `data.rows` lists every daemon status, then the derived states `confirm`
  (a pending confirmation), `blocked` (a done turn that was blocked) and
  `stale` (a busy turn that stopped updating). `offline` is a daemon status.
- `short` is the main word or a prefix of it, for narrow surfaces.
- `data.causes` maps an `error_code` to one short cause word, for a
  secondary line next to the error word.

## Tones

`tone` is one of a closed set. Map each to your own theme:

| Tone | Means |
|---|---|
| `muted` | idle, offline, reconnecting: nothing to look at |
| `ember` | Wisp is working or listening |
| `needsYou` | Wisp is waiting on the user |
| `ok` | the turn finished |
| `fail` | the turn failed |

A new tone would be a contract change and bump `embed_version`.

## Actions

```
wispd trigger start
wispd trigger stop
wispd trigger
wispd interrupt
wispd choice <pick> --prompt-id <id>
wispd settings
wispd settings --category budget
```

| Verb | Does |
|---|---|
| `trigger start` / `trigger stop` | hold-to-talk: start or stop listening |
| `trigger` | toggle listening |
| `interrupt` | cancel the turn in flight; the daemon keeps running |
| `choice <pick> --prompt-id <id>` | answer a pending prompt; pass the `prompt_id` from the state so a late click cannot answer a newer prompt |
| `settings [--category <category>]` | open the Wisp settings window, optionally on one page |

Every verb accepts `--json` and then prints the envelope above. Exit codes:
0 ok, 1 failure, exit 2 usage (an unknown verb or flag), exit 3 daemon not
running, 4 unhealthy dependency. Under `--json` an error prints
`{"ok": false, "error": {"code", "message", "try"}}`.

## Worked example

A minimal host in Python that keeps one line of text current. A QML or
JavaScript host does the same with its process API.

```python
import json
import subprocess
import time

STALE_S, SILENT_S = 20, 45
BUSY = {"transcribing", "deciding", "acting"}


def table():
    out = subprocess.run(["wispd", "status", "--table", "--json"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None  # older wispd: no embed contract
    return {r["key"]: r for r in json.loads(out.stdout)["data"]["rows"]}


def offline_word():
    out = subprocess.run(["wispd", "status", "--json"],
                         capture_output=True, text=True)
    if out.returncode == 3:
        return json.loads(out.stdout)["data"]["word"]
    return None


def show(word, tone):
    print(f"[{tone}] {word}", flush=True)


rows = table()
proc = subprocess.Popen(["wispd", "watch", "state", "tasks"],
                        stdout=subprocess.PIPE, text=True)
status, changed = "offline", time.monotonic()
for line in proc.stdout:
    ev = json.loads(line)
    now = time.monotonic()
    if ev.get("type") == "snapshot":
        status = ev["state"].get("status", "offline")
    elif ev.get("type") == "state":
        status = ev["diff"].get("status", status)
    if "view" in ev:
        changed = now
        show(ev["view"]["word"], ev["view"]["tone"])
    elif rows and status in BUSY and now - changed > STALE_S:
        stale = rows["stale"]
        show(stale["word"], stale["tone"])
```

The loop above only wakes when a line arrives. A real host also runs a timer
that applies the stale rule between lines and, after `SILENT_S` seconds with
no line at all, calls `offline_word()` and shows that word when it returns one.
