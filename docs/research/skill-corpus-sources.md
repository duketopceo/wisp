# Third-party skill corpus — provenance boundary

## What exists and where

A third-party assistant app's `.dmg` (`~/Downloads`, 2026-10-23 build) was opened with
`7zz` (7-Zip standalone) on 2026-10-28. Its `Contents/Resources/`
carries its shipped skill library: 48 `.md` files = **38 skill files**
(25 loose + 11 `integration skills dir/*/SKILL.md` + 2 `bundled skills dir`)
plus docs (`AGENTS.md`, `ATTRIBUTION.md`, `the vendor's model-instructions file`)
and bundled references.

The corpus lives **outside the git tree** at
`~/.local/share/wisp/reference/skill-corpus/` — research-only,
deletable at will. Nothing in wisp's deliverables reads or derives from
any non-MIT file in it; it serves only as a discovery map (which apps
have skills, what coverage depth looks like).

## Clean-source rule

Every adapted input is MIT-licensed and fetched from its **upstream public
repo**, never from the extracted copy:

| Source | License | What it covers upstream |
|---|---|---|
| `NousResearch/hermes-agent` | MIT (verified, `LICENSE` @ HEAD) | github, linear, notion, airtable, spotify, imessage, apple-notes/reminders, findmy, maps, codex, claude-code/design, excalidraw, google-workspace, polymarket, obsidian, ocr/documents |
| `dev-gom/claude-code-marketplace` | MIT (claimed by corpus ATTRIBUTION; verify at fetch) | blender |
| Vercel | MIT (`LICENSE.txt` bundled) | vercel-deploy |

Non-MIT corpus files — the 11 composio-coupled integration skills,
the vendor's browser skill, `the vendor's model-instructions file`, `powerpoint.md`
(declared Proprietary), and license-less files — contribute **nothing**:
no text, no structure. These sourcing rules prohibit copying proprietary
inputs; they are not an independent license or EULA review.

## Coverage matrix: surfaced apps → wisp backlog

| App | Wisp issue | Upstream MIT source | Suggested depth |
|---|---|---|---|
| gmail | #207 | hermes google-workspace | screen-map + tools |
| outlook | #208 | none upstream (composio-coupled) | screen-map only |
| excel | #209 | none | screen-map only |
| github | #210 | hermes github | screen-map + tools (done in seed) |
| cloudflare | #206 | none | screen-map only |
| wisp GUI/notch | #211 | n/a — own app | authored |
| perplexity | #213 | none | screen-map only |
| notion | #214 | hermes notion | screen-map + tools |
| slack | #215 | none | screen-map only |
| discord | #216 | none | screen-map only |
| figma | #217 | none | screen-map only |
| vscode | #218 | none (wisp seed exists) | authored/seed |
| linear | #219 | hermes linear | screen-map + tools |
| google-calendar | #220 | hermes google-workspace | screen-map + tools |
| google-docs | #221 | hermes google-workspace | screen-map + tools |
| spotify | #222 | hermes spotify | screen-map + tools |
| obsidian | #223 | hermes obsidian | screen-map + tools |
| chatgpt | #224 | none | screen-map only |
| OS settings (mac/win/ubuntu) | #226 | none | boot-and-capture |
| tallyline | own app | n/a | authored |

**Gaps the corpus surfaced that we never filed** (consider for future
issues): airtable, salesforce, imessage, googletasks, hubspot, dropbox,
clickup, microsoft_teams, jira.
