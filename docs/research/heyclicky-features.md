# HeyClicky — what it actually does

Product reference, not architecture. Sources: heyclicky.com (FAQ, pricing,
changelog v1.0.10–v1.0.53), `farzaa/clicky` OSS README/CLAUDE.md,
isaacflath.com's point-and-talk teardown. Compiled 2026-10-13.

## What it is

A resident AI companion in the Mac's notch area (no dock icon, no windows by
default). You hold a hotkey, talk, and it answers — out loud — while looking at
whatever was on your screen when you pressed. The defining interaction: it
**points at things** instead of describing where they are. A little triangle
companion flies across your screen, lands beside the button it means, and talks
you through it. Everything else — agents, dictation, connectors — hangs off
that gesture.

It is not always-listening and never screenshots anything until you press the
key. That is the whole privacy story they lean on.

## Talk — the default mode

- **Push-to-talk:** hold Control+Option, speak, release. It grabs your
  screenshot(s) at that instant, transcribes, answers by voice. Most utterances
  end here — a question, a spoken answer, a point at the thing.
- **Screen-aware answers:** it sees all your monitors at press time. "What does
  this error mean", "where is export in DaVinci", "what did billing say" — it
  reads the screen and answers, pointing at the relevant element.
- **Follow-ups:** it remembers the last ~40 messages and what it just looked
  at — "what about the other one", "and then?" work. It also remembers the
  page you just left when you navigate mid-conversation.
- **Drawing:** it can draw on your screen — circles, arrows, highlights —
  hand-drawn-looking, Excalidraw-style. Highlights fade in ~2s; drawings stay
  while it's explaining and clear when it stops talking. Nothing stays.
- **Spatial context (draw for it):** you can also draw — scribble a circle
  around the thing you mean and ask about it. Useful for dense apps.
- **Interruption:** talk over it / press to barge in — it stops mid-sentence.
- **Text mode:** double-tap Control opens a typed composer; typed replies
  stream and get read aloud.
- **Speed control:** voice rate 0.5x–1.5x in settings.
- **Languages:** 70+.

## Walkthroughs — the teaching feature

This is what made it blow up. Ask "how do I do X in this app" and it becomes a
step-by-step tutor on your real screen:

- It tells you the step out loud, **draws/points at the exact element** to
  press next, and waits for you to do it.
- It **detects when you actually clicked** where it said and advances —
  up to 15 steps, with a running log of what you've done so it doesn't loop
  you back to finished steps.
- It waits for slow pages to load before looking again, asks what you already
  have instead of assuming a from-scratch setup, and won't repeat a step that
  just failed.
- App knowledge comes from injected skill files — it claims teaching coverage
  for ~89 apps with browser-site matching.

## Agents — "heyclicky agent …"

The other mode, and the paid differentiator. Say the wake phrase (or route it
from a Clicky's chat) and it becomes a computer-use loop that goes and does
the thing while you keep working.

- **Background delivery:** clicks and typing land inside the target app
  without moving your real cursor or stealing focus. You keep typing; it works
  in its lane. (Their native driver; real-cursor input is a deliberate
  escalation, not the default.)
- **Structured-first:** if a connected app (Gmail, Calendar, Notion…) can do
  it via API, it does that; pixel-level computer use is the last-mile
  fallback. Their honest changelog note: "not good at controlling your
  computer yet, very good when you authenticate with your tools directly."
- **Agent cards:** a live card sits top-right while it works — progress, files
  it produced (as thumbnails you can open/drag out), stop/retry buttons.
  **Voice follow-up:** hover the card, hold your voice keys, talk, release to
  send — you answer a finished agent without opening anything.
- **Permission model:** before first computer use in a conversation it asks —
  "Allow once / Always allow / Not now", answerable by voice. It batches:
  approval is per conversation, not per click, and stops before
  purchases/sends/deletes/irreversible actions regardless. "Always approve"
  exists for long tasks. Answering a card doesn't spend an agent message.
- **Ask instead of guess:** when your input would materially change the work,
  it does what it can, then asks one short question — rather than inventing
  details or giving up. Told "wait", it holds.
- **Budget awareness:** agents pause at your plan's message cap with an
  approval card; one stopped within 10 seconds doesn't count against you.
- **Self-healing:** if its helper process dies mid-task it restarts and
  retries instead of dying silently.
- **Browser scope:** web tasks can run in a separate browser window using your
  signed-in profile — one window per task, not a new window per page.

## Clickys — named agent personas

The retention layer: persistent named workers instead of one-off tasks.

- Each **Clicky** has a name, a face (customizable character packs — faces
  react while listening/thinking, doze when stopped), its own memory, its own
  chat, and its own folder for produced files.
- **Jobs:** you found one through conversation — "I need help with X" → it
  asks a couple of useful questions and spins up a Clicky for that job.
- **Home:** the notch opens a full chat UI — sidebar of Clickys, pins, search,
  archive, unread badges. Resizable, pops out into a window, remembers size.
- **Ambient routing:** from anywhere you can say "tell Launch Scout I like
  this too" or "what's running right now" and it routes to the right Clicky —
  or founds a new one.
- **Done announcements:** says it's finished out loud + beside your cursor —
  except on calls, screen shares, or DND.

## Routines — scheduled agents

- "Check this every few hours", "daily briefing" → a **routine** that runs on
  the Mac while the app is open.
- Results land in the Clicky's chat with an unread dot — quiet, no spoken
  interruption. Missed runs (asleep/offline/limit-hit) wait quietly rather
  than pile up or nag.
- First suggested routine explicitly asks "yes, keep it going" — you opt into
  recurrence consciously.

## Suggestions — proactive ideas

- Clickys mine recent work in your connected apps + web research and propose
  concrete tasks — one card at a time, in a Suggestions sidebar.
- "Do it" / "next one" / **Adjust** (talk through a change to the proposal).
- They remember what you saw, approved, or declined — and why — so tomorrow's
  batch shifts.
- Morning greeting: Clickys peek out of the notch with a "Show me" — but hold
  if you're on a call, screen sharing, or in Focus.
- If you ignore three days of suggestions it backs off automatically.
- History note: true *proactive* agents (local activity tracking) shipped and
  were later **removed over privacy concerns** — suggestions are now driven
  by connected-app data, not watching your screen.

## Dictation

Shipped as a full Wispr-Flow-class feature, not an afterthought:

- **Hold Fn+Control → text streams into the focused app ~450ms.** Double-tap
  for hands-free. Any held combo bindable.
- **Cleanup model:** grammar, spelling, punctuation fixed as it streams; it
  does not add words you didn't say.
- **Learns your dictionary:** fix a word within ~20s and the correction is
  saved to a personal dictionary (editable in settings).
- **Screen-aware compose — the headline:** open an email, hold the talk key,
  ramble "reply to this person, tell them Thursday works" → it screenshots the
  thread, reads your memories of how you write, and **types the finished draft
  in your voice**. Skills like "Write Like Farza" style it further.
- **Terminal safety:** dictated newlines are collapsed — a ramble into a
  terminal can never execute as a command.
- **Insertion:** prefers typing into the field over clipboard paste; respects
  non-QWERTY layouts; restores your clipboard afterward; long/interrupted
  sessions never lose what you already said.
- Auto-detects language, 50+ supported.

## Connectors & tools

- Built-in app catalog — Gmail, Calendar, Notion, Stripe, Supabase, Meta Ads,
  and others (they prune ones that don't work: Reddit/Monday paused).
- **Multi-account:** two Gmails labeled Work/Personal; it reads across both,
  says which each result came from, and asks once when an outbound action's
  account is ambiguous.
- **Custom MCP servers:** paste a server URL or local command; browser sign-in
  or API key auth. It reads the connector's capability list so the voice knows
  when to use it.
- Whole-document understanding: ask about a PDF/page/file and it reads the
  whole thing, not just the visible screen.

## Memory

- Two persisted docs: **PROFILE.md** (name, language, preferences — "how you
  like CSVs named") and **VOLATILE.md** (the project you're mid-flight on).
  Both inject into voice and agents.
- It knows its own settings: "talk slower", "stop announcing yourself",
  "how much of my plan have I used" all work by voice.
- Account deletion actually deletes — cloud data, local Clickys, files to
  Trash, analytics included.

## Surfaces

- **The notch:** the whole product lives in the MacBook notch area — hover
  peeks Clickys/suggestions/files; Home expands from it; it's the only
  presence (menu-bar icon removed).
- **The floating cursor:** a drawn companion triangle that flies in an arc to
  targets, spring-animated. (As of 1.0.52 the *agent* floating cursor was
  pulled for working in true background; the talk-time pointer remains.)
- **Agent HUD/card:** top-right live card per running task.
- **Drag-and-drop:** files into chats; produced files drag out of the notch
  into other apps.

## Pricing shape (the interesting bit)

- **Talk and dictation are unlimited on paid** — free tier gets 25 talk + 25
  agent messages/month.
- **Agent messages are the metered currency**: Pro $20 → 150/mo, Max $100 →
  1000/mo. Approvals and follow-ups on live cards are free.
- Teams: shared skill library, seat dashboard (early, hand-onboarded).
- Referral: 25% recurring for 12 months, cash.

## What it refuses to do

- No screen watching between presses; no stored screenshots (text summaries
  only).
- Confirms before money/sends/deletes; holds when told "wait".
- Suggestions never auto-run — every card waits for your go-ahead.
- macOS only (Sonoma 14.2+). Windows is a waitlist.

## Under the hood (as far as they've said)

Claude-family brains (Sonnet default, deeper model for complex asks; more
recently a "GPT-6 Luna/Sol" pair — user prohibited for wisp), gpt-realtime
voice, AssemblyAI streaming STT, ElevenLabs TTS, Cloudflare Worker proxy so
keys never ship in the binary. Codex bundled inside for agent runs (yes,
really — their changelog says "the Codex we bundle").
