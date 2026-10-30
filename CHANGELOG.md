# Changelog

What changed for you, newest first. One line per change, written for the
person using Wisp, not for the person who wrote it.

How this file is kept:

- The first three lines under a version are its headline: `wispd whatsnew`
  and the Panel's one-time card show exactly those.
- A reporter is credited with `(thanks @handle)` at the end of a line, only
  when they said they want it.
- A number about users, downloads, installs or stars is written only with
  its source, as `(source: https://...)`. `tests/test_whatsnew.py` fails on
  one without.
- `Unreleased` is what the code on `master` does that the last release did
  not. A version heading is `## v1.2.3 - YYYY-MM-DD`.

## Unreleased

- Background agents are live: "agent, fix the tests" starts an OpenCode session that reports progress, asks you out loud for answers and for permission on risky steps, takes follow-ups and can be cancelled. Onboarding (or `wispd install --agents`) downloads the pinned ori and OpenCode for you, and the agent can read your memory unless you set `[agents] mcp_memory = false`.
- Draw on your screen and ask about it: Wisp draws rings, arrows and highlights, and you can scribble on the screen to point at what you mean.
- Walkthroughs: Wisp can teach you a task step by step, spoken and pointed, and you can save a lesson, replay it and resume one you paused.
- Answers start sooner: the first clause is spoken as soon as it is ready, speech is transcribed while you still hold the key, and pressing the key while Wisp thinks cancels that turn and starts a new one.
- Ask chips: a quick tap of the talk key shows up to three things you can ask in the app you are in, for your first seven days.
- Selected text, a copied image or a file you pointed at can ride along with a question that says "this" or "that". Nothing is read between key presses.
- What you type into an answer card, a rating note or a 3D-part question no longer appears in a command line another account on the machine could read; the panel hands it to `wispd` on stdin (`wispd choice --stdin`, `wispd ask --stdin`, `wispd label set --stdin`).
- Wisp speaks and understands other languages: it answers in the language you spoke, picks a matching voice when one is installed, and says so once when it has none.
- Dictation keeps what you said: a failed insert loses nothing (`wispd dictate history`, `retry`, `copy`), a killed session is recovered on the next start, and the cleanup pass cannot change your words.
- Your transcripts, replies and traces are private to your account: files are readable only by you, and older ones are tightened when the daemon starts.
- Pressing the talk key before the daemon is running now records privately too: the recording is readable only by you, same as when the daemon runs.
- `wispd update` checks a release against its published SHA-256, installs only when you say yes, and refuses a release that is not newer than what you have.
- Blank windows: Wisp paints over password managers and other sensitive windows in every screenshot, and takes none while one has focus.
- Helpers: name a background helper, give it a folder and notes, and ask for it by name. Routines wait for the network instead of counting an offline miss as a failure.
- The Omarchy tutor answers "how do I do this in Omarchy" from your own machine's bindings and config.
- Answer cards can show one picture from an allow-listed host.
- `docs/TRUST.md` lists every outside host Wisp can contact, what it gets, who holds the key and what you control, and a test keeps it true.
- Voice speed goes from 0.5 to 1.5 times, and you can say "talk slower" or "talk faster".
- Linux only: the macOS and Windows code paths are removed.
- Voice polish: a captions toggle (say "turn off captions"), a fallback to your default mic when the one you picked is gone, the answer on your clipboard when the speaker is muted, and no announcements while you are on a call or sharing your screen.
- Browser lane (off by default): a small extension lets Wisp work in a tab group in your own browser. You pair it with a code, watch it work and press Stop to end it; it never fills password, one-time-code or card fields.
- 3D parts (off unless a model host is allowed): an answer can show one small glTF model from an allow-listed host that you can turn; click a part and Wisp asks one question naming it. It needs no GPU and gives the pointer back when the answer goes.

## v0.9.0 - 2026-09-30

- Hold the talk key and speak, or tap it once to start open capture and again to stop; the `[audio] seconds` limit is the safety ceiling.
- Wisp shows an orb with working states and a popup panel from the Omarchy bar, and answers, choices and errors surface on their own.
- Computer use goes through the same act loop as everything else, so "open the terminal and..." is one turn.
- You can mark a turn good or wrong from the orb, and a soak report shows how routing did.
- Opening an app by name falls back to your default terminal launcher when your configured terminal is missing.

## v0.1.0-rc1 - 2026-09-29

- First release candidate: Super+D push-to-talk, routing each request to launch, tool, agent or answer, a risk-tiered toolbelt, answers with a screenshot when you ask about the screen, and memory of your recent turns.
