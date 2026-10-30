# Dev mode

Dev mode is a short tuning session. You give wisp a list of tasks, it runs
them on your live desktop one after another, a judge model grades each one
from the screen, and you get a report: accuracy, the outcome mix, drift,
cost and time per stage. Use it to find what wisp gets wrong, and to
compare two settings side by side.

While a session is on, the bar shows a small "dev" badge and the panel gains
a Dev tab ("DEV · N runs left"). Tracing is on for the session. Your own
`config.toml` is never written; turning dev mode off puts everything back.

## Commands

```sh
wispd dev on                         # start a session
wispd dev run docs/dev-tasks/starter.txt
wispd dev run tasks.txt --vs brain.default=openrouter:acme/model
wispd dev review                     # spot-check the judge on up to five tasks
wispd dev runs                       # the reports (add --json for data)
wispd dev stop                       # stop after the current task
wispd dev off                        # end the session
```

`--vs key=value` runs the list twice. The second pass changes that one
setting on a copy of your config, and the report pairs the results task by
task. Only one setting can be changed, and safety and spend settings cannot.

The session turns itself off after 5 runs. An A/B run counts as one.

## Safety

- A run denies typing text, key presses, shell, external calls, posting and
  closing windows. Write only tasks that open, find, switch or control
  playback.
- A step that would ask you to confirm is not answered. The task ends as
  `stopped`, and a task that routes to an agent, a lesson, a setting, a
  walkthrough or dictation is skipped as `stopped` without running.
- The judge reads the final screen and runs on the eval key
  (`openrouter/orchestral`, never the default key). Each run has a spending
  cap, `[dev] judge_cap_usd` ($1 by default). Past the cap the rest of the
  run is marked unjudged and the report says so.

## The gate counts only your labels

A judge verdict is never written to the labels file. The v1 gate counts
owner-confirmed labels only. `wispd dev review` shows you a few judged
tasks; confirm or flip each one, and that label (yours) is what counts. The
report shows judged accuracy and confirmed accuracy separately.

## Writing a task list

A plain text file, one task per line, written as you would say it.
Lines that start with `#` and blank lines are ignored.

```text
# media
pause youtube
open my stripe tab
```

Keep tasks small and safe, with one visible result each, so the judge can
tell whether it worked. The shipped list is `docs/dev-tasks/starter.txt`;
copy it and add the tasks wisp has missed for you.
