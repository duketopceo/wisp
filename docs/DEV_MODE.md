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

## Gauntlet mode

`wispd dev run FILE --profile hybrid --profile openrouter` is gauntlet mode:
each task runs once per arm profile (a TOML file of section.key overrides
under `docs/dev-tasks/profiles/`, or a path), arms interleaved task by task,
and the report names the arms. Profiles may set the spend and safety keys
that `--vs` refuses, because they are checked-in files.

A gauntlet run adds three allowances on its own config copy, and nothing
else changes (the deny list, "every confirm answers no" and the shell switch
stay):

- typing and key presses, only into sandbox windows. A sandbox window is one
  the driver spawned, named by its Hyprland window address (`--window ADDR`),
  never by class or workspace. The focused window is read again right before
  each keystroke; if it is not a sandbox window the task ends as `stopped`
  and nothing is typed;
- `skill_manage` create and edit (delete and file operations stay refused),
  so a learn turn can save an app skill. A run that injects an `[app_skill]`
  block writes an `app_skill` trace event (name, how it matched, characters),
  so a second run's reuse can be seen;
- trajectories, so a second try can build on the first.

Spend is capped across invocations. Every task, judge and click-probe charge
is appended to a spend file (`--spend-file`, `--cap`, default $10); a task
starts only while the cap covers every arm's per-task stop
(`[agents] act_max_usd` in the profile), so a nearly spent cap stops all arms
at the same task. The judge falls back to the `OPENROUTER_API_KEY` env var
(the eval key, set by `orch`) when the keyring is not unlocked. Gauntlet
runs do not count against the five-run session limit. The report splits
spend by provider.

Do not drive this by hand. `scripts/gauntlet.py` borrows the daemon slot,
builds the sandbox and runs the case battery; see its `--help`. Run it only
under `orch`, in an approved session.

Your own labels on gauntlet turns reach the v1 gate only through you:
review them against the gauntlet data directory with `wispd dev review`
(the driver prints the command), then `wispd dev import-labels DIR` copies
the turns you labelled `correct` or `incorrect`, and those labels, into
your own data. It skips turns already there, so running it twice copies
nothing. The judge never writes a label.

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
