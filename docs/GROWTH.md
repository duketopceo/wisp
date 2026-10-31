# Private growth and the weekly recap

B31 has two independent paths:

1. An owner-run snapshot of public GitHub signals, written to a local JSON file.
2. An opt-in, local weekly usage card in the Panel's Now tab.

Neither path sends product usage, conversations, screenshots, prompts, keys, or
recap contents anywhere. No background growth job, community posting, email
automation, referral system, or remote dashboard is enabled. Activity counts
are not an accuracy score, proof of useful outcomes, or reinforcement learning.
Release first, run Wisp, inspect real outcomes, then improve routing and skills;
actual RL is a separate later project.

## Owner-run public snapshot

`scripts/growth_snapshot.py` is **source-checkout maintenance tooling**. It is
not an installed `wispd` command or a runtime dependency of the weekly recap.
Run it from the repository root:

```sh
# Entirely offline; deterministic fixture, not live growth figures.
python scripts/growth_snapshot.py \
  --fixture tests/fixtures/growth/github_public.json \
  --output-dir /tmp/wisp-growth-fixture

# Explicit live read of a public repo, using your existing gh setup.
python scripts/growth_snapshot.py \
  --repo duketopceo/wisp \
  --output-dir ./growth-snapshots
```

There is no authentication setup, login, token flag, credential inspection, or
token printing in this script. Its live path invokes `gh api`: REST GETs for
public repository metadata, release and asset pages, and optional traffic;
one fixed GraphQL **query**, never a mutation, for issue and discussion counts.
The live path requires a working owner-provided `gh` installation. It never
creates an issue, discussion, release, post, commit, or remote file.

`--fixture` never invokes `gh`, a subprocess, or the network. The fixture's
`date` determines the filename by default. `--date YYYY-MM-DD` explicitly
overrides the snapshot day; live mode otherwise uses today's UTC date.
The result is `growth-YYYY-MM-DD.json`, with sorted keys, two-space indentation
and a trailing newline. Repeating the same fixture and date produces identical
bytes. Re-running live mode on the same date replaces that local day's file.
Do not treat a date override as historical API retrieval.

Public repository metadata must be available and explicitly say
`private: false`. Otherwise the script exits with a generic error without
writing a snapshot. Raw API errors and `gh` stderr are not forwarded.

### JSON contract, version 1

The following is the checked-in **offline fixture**, not observed Wisp growth:

```json
{
  "schema_version": 1,
  "date": "2026-10-30",
  "repository": "duketopceo/wisp",
  "stars": {"value": 17, "status": "available"},
  "forks": {"value": 4, "status": "available"},
  "release_downloads": {"value": 25, "status": "available"},
  "issues": {"value": 12, "status": "available"},
  "discussions": {"value": 3, "status": "available"},
  "traffic": {
    "clones": {"count": null, "uniques": null, "status": "unavailable"},
    "views": {"count": 0, "uniques": 0, "status": "available"}
  }
}
```

- `stars` and `forks` are the repository's reported counts at collection time.
- `release_downloads` sums all fetched release-asset `download_count` values,
  with pagination for both release and asset lists. It is not installs,
  unique users, downloads from every distribution channel, or active users.
  If any release/asset data is unavailable, the total is `null`, not a partial
  number falsely presented as complete.
- `issues` is the issue count returned by the repository query, including open
  and closed issues, not the REST field that also counts open pull requests.
  `discussions` is the discussion count returned by the same query.
- `traffic` contains only the aggregate count/uniques returned by the traffic
  endpoints, not user identities or request logs. These endpoint aggregates
  are not lifetime totals. Permission-denied or absent traffic is
  `status: "unavailable"` with `null` counts. A reported zero remains
  `status: "available"` with numeric zero. **Unknown is never zero.**
- Consumers must understand `schema_version`, preserve unavailable values and
  avoid implying that activity, stars, or downloads measure product quality.
  Raw API payloads, environment variables, and tokens are not part of this
  allowlisted output contract.

### Tallyline is a separate app

This JSON file is the only integration contract. A separate Tallyline app may
be taught to read the file manually in future work; this change does not edit,
deploy, authenticate to, or write into Tallyline. There is no automatic upload,
webhook, cross-repository change, or remote-write adapter. Keep local snapshots
local unless the owner independently chooses otherwise.

## Private weekly recap

The feature is off by default, including when `[growth]` is absent. Only the
literal boolean setting `true` opts in:

```sh
wispd config set growth.weekly_recap true
wispd recap --json                  # read-only; does not consume the card
wispd recap --claim --json          # reserve this week's delivery once
wispd recap --off                   # persist the off switch locally
```

Equivalent config:

```toml
[growth]
weekly_recap = "false"
```

The setting is CLI/config-only, not a new Settings row requiring untranslated
copy. The visible card has existing translated **hide** and **off** actions.
Hide dismisses the current card; off also writes the setting to false.
There is no daemon restart, daemon protocol change, or network request.

The Panel reads config on open, then runs one local `wispd recap --claim --json`
process when Now is visible and opt-in is enabled. Switching from another tab
to Now can trigger that read; other tabs do not consume a week's card.
There is no recap timer or polling loop. Disabling clears the card immediately
and suppresses any response already in flight. Errors use the existing action
feedback; a failed recap read never invents a card.

### Window and local data

The recap covers the **last completed local Monday-Sunday calendar week**,
not a rolling 168-hour window. This prevents a Friday panel open from consuming
an unfinished week's card. Aware timestamps are converted to the user's local
date; naive historical ledger timestamps are interpreted as local time.

It reads files only from Wisp's local `config.DATA_DIR`:

- `decisions.jsonl`: distinct active dates and decision-row count, called turns,
  matching the existing digest's row-count convention.
- `usage.jsonl`: recorded local ledger dollars.
- `spend.jsonl`, when present: historical rows read through the ledger's
  existing legacy-row conversion; neither old nor current logs are rewritten.

Missing files are `missing`; unreadable or undecodable files are `unreadable`;
corrupt JSON, wrong-shaped rows, invalid timestamps, and invalid dollar values
are skipped and counted as `partial`. These states are returned in `logs`.
Partial activity is explained on the card. Partial spend is labeled partial.
If no valid activity exists in the week, no card or delivery marker is created.
If no usable spend source exists, dollars are `null` and the card says
**spend unavailable**, never `$0.00`.

**Recorded is not measured.** Existing usage rows preserve dollar amounts but
do not retain whether each amount was provider-reported or estimated.
Consequently `spend.recorded_usd` is the sum of readable local records, while
`measured_usd` and `estimated_usd` are explicitly `null` and
`basis` is `source_not_recorded`. The card states that recorded costs may include
estimates and that the measured/estimated shares are unknown. It never calls
this a provider invoice or attributes invented precision to a cost estimate.
`complete` describes local log readability, not billing completeness.

### Delivery and off-switch semantics

The delivery key is the completed week's Monday, e.g. `2026-10-19`.
`--claim` atomically creates
`DATA_DIR/recap-weeks/2026-10-19.json` with exclusive creation and mode `0600`
inside a mode-`0700` directory. The marker contains only the week and local
claim timestamp. A second process or later panel open receives `already_seen`
with no card. The next completed week gets its own key.

This is **at-most-once reservation**, not a guaranteed-render acknowledgement.
Closing or crashing the Panel after reservation may consume the card without
the user seeing it. A corrupt/empty existing marker is also treated as seen
to avoid duplicates. If local claim state cannot be saved, no card is delivered.
Read-only `wispd recap` does not create a marker, but respects an existing one.
Off leaves source logs and previous delivery markers alone and prevents future
recap reads/claims; it is not a log-erasure or usage-logging switch.

### CLI response

The existing CLI JSON envelope wraps:

```json
{
  "enabled": true,
  "reason": "ready",
  "card": {
    "week_start": "2026-10-19",
    "week_end": "2026-10-25",
    "days_used": 5,
    "turns": 6,
    "spend": {
      "recorded_usd": 0.83,
      "measured_usd": null,
      "estimated_usd": null,
      "basis": "source_not_recorded",
      "complete": true
    },
    "title": "your week with wisp",
    "summary": "you used wisp 5 days, 6 turns, $0.83 recorded",
    "activity_note": "",
    "spend_note": "Recorded costs may include estimates; measured and estimated shares are unknown."
  },
  "logs": {
    "decisions": {"state": "ok", "skipped": 0},
    "usage": {"state": "ok", "skipped": 0},
    "legacy_usage": {"state": "missing", "skipped": 0}
  }
}
```

Other `reason` values are `disabled`, `already_seen`, `no_activity`, and
`state_unavailable`, with `card: null`. `logs` is empty if no logs were read.
These are normal states, not failed remote operations.

## Focused verification

```sh
python -m unittest discover -s tests -p 'test_growth_*.py'
python -m unittest discover -s tests -p test_telemetry.py
python -m unittest discover -s tests -p test_ledger.py
python -m unittest discover -s tests -p test_copy_lint.py
```

Growth tests use fake GitHub responses, temporary local logs and network-ban
guards. The UI test executes the actual service function bodies under Node
without starting Quickshell. Native Qt card tests live at
`tests/qml/lib/tst_growth_recap.qml`; run them in the existing Qt test harness
when Qt is available. The 168-hour digest regression checks the week-long
histogram and unchanged 24-hour behavior. No live growth query, community
activation, or claim of routing/skill quality is needed to run these checks.

## Owner's first-100-user listening guide — plan only

**Nothing below is activated by this release.** Asking people, posting an
invitation, sending messages, or enabling a community channel requires the
owner's explicit approval. "First 100" is a learning target, not a claim that
Wisp has 100 users. Do not infer identities or recruit people from aggregate
GitHub traffic.

1. **Start where permission already exists.** Prefer an existing GitHub
   Discussions space for an owner-approved invitation and voluntary replies.
   If Discussions is not enabled, do not enable it automatically or create a
   new channel. Decide the venue and consent boundary with the owner first.
   Work in small batches, one person at a time, rather than bulk outreach.
2. **Ask about real work, not whether the demo looks nice.** Offer a short
   conversation to a consenting user: "What were you trying to finish?",
   "Show me the last time Wisp helped or got in your way", and "Did the
   intended action actually happen?" Ask what happened after the assistant's
   answer, not just whether the turn returned an OK result.
3. **Check return use without surveillance.** Ask whether they returned around
   day five, what brought them back, and what stopped them. They may consult
   their private recap or share a number voluntarily; never require their
   logs, screenshots, account data, or a telemetry opt-in.
4. **Get a minimum reproducible example with consent.** Ask for the smallest
   non-sensitive prompt/workflow, Wisp version, platform, expected result and
   actual result. Explain what will be retained before saving notes. Do not
   request keys, private screenshots, or raw conversation archives.
5. **Turn learning into a bounded fix.** Separate installation trouble,
   confusing UI, wrong routing, missing skill and false success. Keep a local
   consented note and an owner-approved issue with a reproducible acceptance
   case. Prioritize repeated real failures, not stars or turn counts. Verify
   the intended external result before labeling a task successful.
6. **Close the loop manually.** With permission, reply in the already agreed
   conversation when a fix is available and ask whether it solves the real
   task. No automated follow-up, imported contact list, or public testimonial
   without separate consent. Repeat with the next small batch until the
   owner has useful evidence from the intended first 100 users.

Keep the sequence honest: ship a usable release, let the owner run it, repair
routing/skills from observed failures and verified outcomes, then consider
actual RL separately. Neither a usage recap nor a public growth chart is an RL
reward signal by itself.
