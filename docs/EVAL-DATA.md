# Eval data to record

The v1 gate (`[eval] gate_rate` over `gate_min_turns`, 50 by default) is
scored from your own labelled turns. On 2026-10-26 there were 19 labelled
turns and 6 were right first time (32%). The plan recommends
`gate_rate = "60%"`, so the target is at least 50 labelled turns with 30
or more right first time, recorded against the deployed `master`.

## Before recording

1. Install current `master` on the desktop and restart the daemon
   (`wispd install --ref master`), so the labels measure current code.
2. Check the starting point with `wispd eval`.

## What to record

Use the push-to-talk key and speak normally. After each turn, label it
with `wispd label set correct` or `wispd label set incorrect` (or the
`good` and `wrong` buttons). Label every turn, including the ones that
worked: the rate needs both sides. A turn you retry after a miss gets
`corrected-by-retry` from the retry flow and counts as not right first
time.

Aim for these mixes. Act is the weakest kind and has the most turns, so
it gets the most.

| Kind | Turns | Examples to speak |
|---|---|---|
| act | 25 | "open my email", "open my calendar", "go to github.com", "open firefox then search for linux rice", "scroll down", "click the settings button" |
| answer | 10 | "what is on my screen", "what does this error mean", "how do I undo this", "where is the save button" |
| launch | 8 | "open firefox", "open the terminal", "open the file manager", "open files" |
| dictate | 4 | dictate a sentence into a text field |
| agent | 3 | "start an agent to ..." for a small task |

Cover the three known act failure patterns on purpose, five turns each:

- default-app resolution ("open my email" focusing the wrong app)
- wrong-coordinate clicks ("click the X button" on a busy window)
- launch instead of navigate ("go to <site>" opening a new app)

Record some turns in each of these app states, since each stresses a
different path: a browser focused, a terminal focused, an empty desktop,
and two windows side by side.

## After recording

- `wispd eval` shows the rate per kind and the gate state.
- `wispd eval --unlabelled` lists recent turns you have not labelled.
- `wispd eval --misses` groups the turns that were not right first time
  by kind and result pattern, biggest first. The top group is the next
  Phase 9 fix.
