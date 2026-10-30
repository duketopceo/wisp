# When Wisp listens

By default Wisp hears you only while you hold the talk key. Two opt-in
modes change that. Both are off in a fresh install, both say what they do
before they turn on, and neither changes hold-to-talk: with both off, the key
works byte for byte as it did.

For where audio and screenshots go once a turn starts, see
[TRUST.md](TRUST.md).

## What a background agent can see

A background OpenCode agent runs locally and works in its own folder. Its
one connection back into Wisp is a read-only tool list served by the hidden
agent-mcp subcommand: `recall`, `memory_read`, `skill_list`, `skill_view`,
`task_status`, `task_output`, `task_artifacts` and `ask_user`. Nothing else
on the daemon's socket is open to it. The agent's model calls go through ori
to OpenRouter, so memory it reads goes to OpenRouter-routed models.

`wispd config set agents.mcp_memory false` removes `recall` and `memory_read`
from the list. The OpenRouter key lives in your desktop keyring
(`keyring://wisp/openrouter`); Wisp passes it to ori and never writes it into
the agent's config files. What the agent may do on your machine is decided
by Wisp's permission policy; see [TRUST.md](TRUST.md#background-agents).

## Hands-free by double-tap (off)

`wispd config set handsfree.enabled true`

Tap the key twice quickly and the second tap keeps listening after you let
go. The next tap sends it. Esc interrupt ends it, and a latched mic closes by
itself after two minutes. Nothing listens between taps. Holding the key still
means hold to talk, release to send.

## Local wake word (off)

`wispd config set wakeword.enabled true` (the phrase is `[wakeword] phrase`,
default "hey wisp")

While this is on, Wisp reads your microphone all the time.

- Audio is processed on this machine. Stretches that sound like speech are
  checked by the local whisper.cpp model, never by the speech provider under
  `[stt]`, and dropped right after. Nothing is saved or logged.
- Until the phrase is heard nothing is sent anywhere, and no screenshot is
  taken. The screenshot belongs to the turn the phrase starts.
- After the phrase the turn works like a held key: your words go to the
  speech provider you chose, as in TRUST.md.
- The bar shows an open-mic mark for as long as the listener runs.
- Turn it off with `wispd config set wakeword.enabled false`; it stops within
  a second, no restart.
- It refuses to turn on over open speakers, because Wisp would hear itself.
  Use headphones, or run `wispd install --echo-cancel` (shows the one
  PipeWire file it adds, asks first, never restarts PipeWire).
- It is deaf while Wisp speaks and for 1.5 s after.
