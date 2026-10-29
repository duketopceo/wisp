---
name: github
description: GitHub web UI and gh CLI — PRs, issues, reviews, repos, code search
tier: safe
url_hosts: github.com, gist.github.com
asks: How do I review this pull request; Where do I find the failing check; How do I clone this repo
provenance: wisp seeds + adapted under MIT from nousresearch/hermes-agent github skill
---
# github

GitHub web shortcuts (press `?` on any page for the full list):
- **Command palette / search:** `Ctrl+K` or `/`
- **Go to file in repo:** `T`; **Open in github.dev editor:** `.`
- **Code / Issues / Pull requests tabs:** `G C`, `G I`, `G P`
- **PR review:** "Files changed" tab, `Review changes` button at top-right

## Workflows

1. Review a PR: open the PR → "Files changed" tab → read the diff →
   `Review changes` (top-right) → Comment / Approve / Request changes.
2. Find a failing check: PR page → "Checks" tab → failed job →
   the job's log shows the failing step.
3. Clone a repo: repo page → green `<> Code` button → copy the SSH or
   HTTPS URL, or `gh repo clone owner/repo` in a terminal.
4. File an issue: `Issues` tab → `New issue` → title + body →
   `Submit new issue`.

## Tools

- `gh` CLI covers everything the web UI does and more when a terminal
  lane is available: `gh pr view`, `gh pr checks`, `gh issue list
  --search`, `gh pr merge`. Prefer a fresh `gh` read over memory for
  anything remote (CI state, merge state, issue state).

## Verify before done

- Never report CI green without a fresh `gh pr checks` or the Checks
  tab actually loaded.
- Never claim merged without seeing `state: Merged` (PR page banner or
  `gh pr view --json state,mergedAt`).
- Read full context before writing — issue/PR decisions live in the
  comment threads, not the title.

## Gotchas

- `Review changes` only appears on the "Files changed" tab, not
  "Conversation".
- Forks default the PR base to the upstream repo — check the
  `base:` dropdown when a PR looks wrong.
- `unverified — needs a deeper capture`: keyboard-driven review flows
  and draft-PR states.
