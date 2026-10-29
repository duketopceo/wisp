# App-skill format spec

Contract for every wisp app skill — distilled by `scripts/skill_distill.py`,
seeded in `wisp/skills_seed/apps/`, or hand-written. Conventions come from
generic agent-skill practice (Hermes-style frontmatter, which wisp's own
`wisp/skills.py` already implements), wisp's seed skills, and our own
verified captures — never from non-MIT third-party files.

## Frontmatter (whitelist)

Only these keys may appear. Anything else — especially `tool:`, `version:`,
`author:`, `metadata:` — is stripped by `skill_distill.sanitize_frontmatter`
and must be rejected on hand-written review. App skills are doc skills:
they never register executable tools.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | skill slug (`<app>-app` for UI maps) |
| `description` | yes | routing text — what it covers AND what it does not ("Use for X; not for Y") — feeds `index()` and human reading |
| `url_hosts` | web apps | comma list; `match_app_skill_info()` matches on this — **a web app without it never auto-injects** |
| `app_classes` | native apps | comma list of window classes; the other half of the matcher |
| `asks` | optional | `;`-separated example asks surfaced on match |
| `tier` | optional | `safe` only for read-only UI-map skills |
| `provenance` | yes | where the content came from (`authored: crawl <date>`, `adapted: MIT <repo>`) |
| `draft` | optional | `first-run (unverified)` until a verify pass confirms controls/workflows |

## Body sections (in order)

1. `## Overview` — what the app is + the 3 most common tasks.
2. `## Screens` — one line per screen: name — purpose. ~10–15 screens is
   the coverage bar: main view, every nav/sidebar destination, task
   surfaces (compose/create/edit/share), common settings, 1–2 modals,
   search/results. Skip content rows, marketing pages, empty states.
3. `## Controls` — control — where it lives — what it does. Named
   controls only (voice asks reference names, not pixels).
4. `## Workflows` — numbered click paths for the common tasks, concrete
   enough to follow ("open thread → reply arrow → type → Send").
5. `## Tools` — APIs/CLIs/MCP that cover the app, or "none known". Only
   verified coverage; pass `--tools-note` to the distiller.
6. `## Verify before done` — how to confirm an action worked before
   claiming it (read-back, reload, state check). Never "sent" when it's
   a draft.
7. `## Gotchas` — observed traps only. Anything not seen in captures is
   written as `unverified — needs a deeper capture`.

## Rules

- **Honest coverage.** `draft: first-run` stays until a verify crawl
  confirms the controls. Thin sections say "unverified", never invented.
- **Instruction-content review.** Any adapted text is reviewed for
  behavioral directives (commands, credential handling,
  confirmation-suppression) before shipping — license tier governs
  copying rights, not injection trust.
- **Clean sources.** Adapted content comes only from upstream-verified
  MIT sources (e.g. `NousResearch/hermes-agent`), never from extracted
  app bundles. Attribution rides in `provenance:`.
- **No secrets** in skills — no account names, tokens, or user data.
