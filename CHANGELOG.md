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

- `wispd update` saves a backup of the Wisp files it replaces and checks them against the release afterwards; `wispd update --rollback` restores them, and `--restart` checks the daemon answers. Install, update and `wispd doctor` show a preflight and stop before writing when something blocks.
- Background agents are live: "agent, fix the tests" starts an OpenCode session that reports progress, asks you out loud for answers and for permission on risky steps, takes follow-ups and can be cancelled. Onboarding (or `wispd install --agents`) downloads the pinned ori and OpenCode for you, and the agent can read your memory unless you set `[agents] mcp_memory = false`.
- Draw on your screen and ask about it: Wisp draws rings, arrows and highlights, and you can scribble on the screen to point at what you mean.
- Your agent tasks and short dictations no longer appear in a command line another account on the machine could read: Wisp hands them to the agent runtime and to the typer on stdin.
- "Show me how to rebase", "teach me vim macros" and "I want to learn layers" now start a walkthrough, and every step says why it matters, not only what to click. `[teach] auto = "false"` turns the new routing off.
- Walkthroughs: Wisp can teach you a task step by step, spoken and pointed, and you can save a lesson, replay it and resume one you paused.
- Answers start sooner: the first clause is spoken as soon as it is ready, speech is transcribed while you still hold the key, and pressing the key while Wisp thinks cancels that turn and starts a new one.
- Ask chips: a quick tap of the talk key shows up to three things you can ask in the app you are in, for your first seven days.
- Selected text, a copied image or a file you pointed at can ride along with a question that says "this" or "that". Nothing is read between key presses.
- What you type into an answer card, a rating note or a 3D-part question no longer appears in a command line another account on the machine could read; the panel hands it to `wispd` on stdin (`wispd choice --stdin`, `wispd ask --stdin`, `wispd label set --stdin`).
- Wisp speaks and understands other languages: it answers in the language you spoke, picks a matching voice when one is installed, and says so once when it has none.
- Dictation keeps what you said: a failed insert loses nothing (`wispd dictate history`, `retry`, `copy`), a killed session is recovered on the next start, and the cleanup pass cannot change your words.
- Your transcripts, replies and traces are private to your account: files are readable only by you, and older ones are tightened when the daemon starts.
- Pressing the talk key before the daemon is running now records privately too: the recording is readable only by you, same as when the daemon runs.
- Spoken replies no longer appear in the speech program's command line: the text is passed on stdin, so another account on the machine cannot read it while it is spoken. A custom `[voice] cmd` now reads the text from stdin, and `{text}` is ignored.
- `wispd update` checks a release against its published SHA-256, installs only when you say yes, and refuses a release that is not newer than what you have.
- Blank windows: Wisp paints over password managers and other sensitive windows in every screenshot, and takes none while one has focus.
- Helpers: name a background helper, give it a folder and notes, and ask for it by name. Routines wait for the network instead of counting an offline miss as a failure.
- The Omarchy tutor answers "how do I do this in Omarchy" from your own machine's bindings and config.
- Answer cards can show one picture from an allow-listed host.
- Answers and other text in the panel are shown as plain text, so an answer that contains an HTML image tag no longer makes your machine request that address.
- `docs/TRUST.md` lists every outside host Wisp can contact, what it gets, who holds the key and what you control, and a test keeps it true.
- Voice speed goes from 0.5 to 1.5 times, and you can say "talk slower" or "talk faster".
- Linux only: the macOS and Windows code paths are removed.
- Voice polish: a captions toggle (say "turn off captions"), a fallback to your default mic when the one you picked is gone, the answer on your clipboard when the speaker is muted, and no announcements while you are on a call or sharing your screen.
- Browser lane (off by default): a small extension lets Wisp work in a tab group in your own browser. You pair it with a code, watch it work and press Stop to end it; it never fills password, one-time-code or card fields.
- 3D parts (off unless a model host is allowed): an answer can show one small glTF model from an allow-listed host that you can turn; click a part and Wisp asks one question naming it. It needs no GPU and gives the pointer back when the answer goes.
- `wispd config keys` now groups every setting by page (voice, pointer, agents, models, budget, connectors, advanced) and lists the push-to-talk key and the answer model keys; `wispd config set` checks them for a valid form before writing.

Merged since `v1.0.0-rc.2` (#261-#305), grouped by kind:

- feat: the gauntlet, a battery of live cases for `wispd dev` (#291), and an isolated Hyprland session so test runs leave your desktop alone (#295).
- feat: the default brain is `google/gemini-2.5-flash` (#299). Hosted models stay the default and local servers stay off.
- feat: the first step of the settings window, a type scale and settings metadata (#288).
- feat: terminal output is shared and width-aware: `wispd doctor` leads with the verdict (#276, #277), onboarding is a checklist (#278), and the installer shows its steps (#279).
- feat: the site gets a playable desktop with drawings (#273) and a `/light/` preview with a real-time orb (#274, #285). The Wisp flame 3D asset is added (#293).
- fix: clicks land where aimed on mixed-scale layouts, and fractional or loosely labelled point replies are accepted (#292, #298).
- fix: a non-English turn on the default router gets a reply in that language (#286).
- fix: the Jev router is fully removed (#284), after replay fixtures moved to the act router (#261).
- fix: release and install checks: attestation sidecars in checksums (#262), first-run readiness (#264), and review findings on the safety gate, RC updates and CI (#281).
- fix: the agent asks before running tests after it wrote executable files (#265). Gauntlet runs no longer trip wisp's own policy blocks or overlay (#302, #303).
- test: the suite is hermetic and no longer reads your desktop or environment (#296, #304), and gauntlet results and driver fixes are recorded (#297, #300, #301).
- docs: the roadmap and plans are synced with what merged (#275, #289), plus the gauntlet, UI overhaul, grounding post-training and light orb plans (#283, #287, #290, #294), multi-OS prep notes (#282), a next-tasks handoff (#280) and the gauntlet reruns (#305).

## v0.9.0 - 2026-09-30

- Hold the talk key and speak, or tap it once to start open capture and again to stop; the `[audio] seconds` limit is the safety ceiling.
- Wisp shows an orb with working states and a popup panel from the Omarchy bar, and answers, choices and errors surface on their own.
- Computer use goes through the same act loop as everything else, so "open the terminal and..." is one turn.
- You can mark a turn good or wrong from the orb, and a soak report shows how routing did.
- Opening an app by name falls back to your default terminal launcher when your configured terminal is missing.

## v0.1.0-rc1 - 2026-09-29

- First release candidate: Super+D push-to-talk, routing each request to launch, tool, agent or answer, a risk-tiered toolbelt, answers with a screenshot when you ask about the screen, and memory of your recent turns.
