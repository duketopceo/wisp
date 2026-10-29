---
title: App Skills at Companion Depth - Plan
type: feat
date: 2026-10-28
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# App Skills at Companion Depth - Plan

## Goal Capsule

- **Objective:** Wisp's self-authored app skills carry the same depth that made the leading menu-bar assistant's app knowledge useful — routing metadata that decides when a skill applies, a tool/API cookbook where one exists, the crawl-derived UI map we already produce, and an explicit "check before you say done" contract — so asking about an app works on first try instead of needing a human who knows the app.
- **Means:**
  - A format spec (`docs/research/app-skill-format.md`) built from generic agent-skill conventions, upstream MIT sources, and wisp's own seeds — never from non-MIT corpus files (KTD1, KTD2).
  - `scripts/skill_distill.py` grows the new sections plus a repaired merge prompt (KTD3).
  - Two provenance-clean exemplar skills seeded from MIT-licensed upstreams plus our own verified captures (KTD4).
  - Clean-source rule enforced: only upstream-verified MIT sources are inputs; the extracted corpus is a discovery map only and may be deleted (KTD2).
- **Authority:** Session decisions from the 2026-10-28 app-skill thread. Sources are upstream MIT repos (`NousResearch/hermes-agent`, community marketplaces — the same files that third-party assistants vendor) plus wisp's own crawls and seeds; the extracted DMG corpus served only as a discovery map and is not an input to any deliverable. Issues #206–#226 cover the per-app backlog; #225 (`learn-this-app`) is the routine this plan informs.
- **Stop conditions:** Stop and report if a unit requires reading or deriving from any non-MIT corpus file, or if an upstream source's license cannot be confirmed MIT.
- **Execution profile:** Python tooling (`scripts/`, `tests/`) plus markdown docs. No daemon changes; `wisp/skills.py` is read-only context for this plan (its frontmatter format already matches).
- **Finish and ship:** `ce-work` implements and verifies; results land on `spike/lfm-local` or its successor branch; PR per repo norm.

---

## Product Contract

### Summary

The extracted third-party skill corpus revealed which apps/skills exist and which files are MIT-vendored upstream — but to keep wisp fully clear of EULA/proprietary exposure, the corpus is used ONLY as a discovery map: no Tier B/C file is an input to any deliverable (not text, not structure). MIT-licensed skill sources are fetched from their upstream repos, never from the extracted copy. Wisp's distiller currently produces thin first-run drafts (screen list + echoed section headers). This plan upgrades the format to companion depth — routing frontmatter, tools section, verify-before-done section — seeds two clean exemplar skills, and records the corpus's status outside the git tree.

### Problem Frame

Our generated skills describe screens but don't teach *doing*: no tool/API guidance, no verification contract, and the merge step echoes template headers instead of populating Workflows and Gotchas. Meanwhile the corpus shows the coverage depth that works — tool cookbooks, pagination rules, verify-before-done blocks — and roughly half of it is MIT-licensed (vendored upstream from `NousResearch/hermes-agent` and community sources), making it legally adaptable. The corpus now lives at `~/.local/share/wisp/reference/skill-corpus/` (outside the git tree) so no proprietary bytes sit in the repo.

### Requirements

- R1. No non-MIT corpus text is copied into wisp artifacts. Adaptation rights apply only to MIT sources — verified by upstream repo license, and fetched from upstream, not from the extracted copy. Tier B/C corpus files contribute nothing — no text, no structure. Enforced by a scripted n-gram check (Verification Contract), not eyeballs alone.
- R2. `docs/research/app-skill-format.md` defines the wisp app-skill spec: required frontmatter is a whitelist — `name`, `description` (carrying routing semantics — what it covers AND what it does not), `url_hosts` and/or `app_classes` (the fields `match_app_skill_info()` in `wisp/skills.py` actually routes on — a skill without them never auto-injects for the focused app), optional `asks:`, `tier: safe` permitted for read-only maps, `provenance` + first-run fields. `tool:` and source-corpus keys (`version`, `author`, `license`, `metadata:`) are stripped or rejected — app skills are doc skills, never executable registrations. Body sections: `Overview`, `Screens`, `Controls`, `Workflows`, `Tools` (optional, when an API/MCP/CLI covers the app), `Verify before done`, `Gotchas`.
- R2b. Any text adapted from upstream MIT sources gets an instruction-content review before shipping — commands to execute, credential/token handling, confirmation-suppression language ("no need to ask") are removed. License tier governs copying rights, not injection trust; MIT text gets the same review as authored text.
- R3. `scripts/skill_distill.py` emits the R2 section set and its merge prompt populates `Workflows`/`Gotchas` from captured screens rather than echoing headers.
- R4. Two exemplar skills ship — `github` (adapted from upstream MIT github-* files, attribution kept; `wisp/skills_seed/apps/github/` already exists, so fold the deeper content into that seed rather than duplicating it) and `gmail` (authored from our own verified 7-screen crawl; google-workspace.md adapted from upstream MIT source). `Gotchas`/`Verify` content limited to observed evidence or explicitly marked unverified — a thin crawl cannot support invented gotchas.
- R5. The tier/priority coverage table lands in `docs/research/skill-corpus-sources.md`; a `gh issue comment` on #225 noting it is optional.
- R6. `docs/research/` records the provenance boundary: the extracted corpus is research-only, may be deleted at will (the plan depends on nothing in it), and the repo git tree contains zero corpus bytes.

### Success Criteria

- `python scripts/skill_distill.py` on a captured app produces all R2 sections populated (not template echoes), checked on at least the two existing captures (gmail 7-screen + perplexity), including a no-hallucination check (statements traceable to captured screens).
- Exemplar skills load via `wisp/skills.py` `index()` AND route: `match_app_skill_info()` returns the exemplar for a matching `url_hosts`/`app_classes` probe.
- `git status` shows no `skill-corpus/` path anywhere in the tree; the corpus is readable at its new home for future reference.
- New tests pass alongside the existing suite.

### Scope Boundaries

- No re-crawl work in this plan — the batch crawler and per-app distills are #225/follow-up.
- No `wisp/skills.py` changes unless the spec needs a new frontmatter field; the current `name`/`description`/`tool`/`tier` schema already suffices.
- No shipping or re-publishing of corpus files; no Composio coupling — their integration skills assume a tool server wisp doesn't have.

### Outstanding Questions

- (deferred) Minimal behavioral probe that would falsify "deeper format improves first-try app answers" — e.g. same task set against thin vs companion-depth skills — before #225 auto-generates at scale.
- (deferred) Whether `tier: safe` should be the distiller default for read-only UI-map skills (all 15 existing `skills_seed/apps` carry it).
- (deferred) Which per-app skill gets the `Tools` section first — depends on which apps have reachable APIs/MCPs in wisp's toolbelt.

### Sources

- Upstream MIT skill sources (fetch these, not the extracted copies): `NousResearch/hermes-agent` (github-*, linear, notion, spotify, airtable, apple-*, imessage, maps, excalidraw, codex, claude-*, google-workspace, findmy, ocr-and-documents), `dev-gom/claude-code-marketplace` (blender), Vercel (vercel-deploy)
- Extracted corpus at `~/.local/share/wisp/reference/skill-corpus/` — discovery map only, not a deliverable input; deletable at will
- `scripts/skill_distill.py`, `wisp/skills.py`, `wisp/skills_seed/apps/` — current machinery (15 existing seeds already carry `tier: safe`, `app_classes`/`url_hosts`, `asks:`)
- Generated drafts: `~/.local/share/wisp/skills/gmail-app/`, `perplexity-app/`

---

## Planning Contract

### Key Technical Decisions

- **KTD1 — Format spec over code first.** The spec's shape comes from generic agent-skill conventions wisp already uses (Hermes-style `name`/`description` routing frontmatter — which the MIT upstreams also use — plus wisp's own `url_hosts`/`app_classes`/`asks` matcher fields and `tier: safe` seed convention) and cookbook-with-verify-block structure visible in the public MIT skill ecosystem. Spec doc first so `skill_distill.py` and future hand-written skills share one contract.
- **KTD2 — Clean-source rule, enforced.** Every adapted input is MIT-licensed and fetched from its upstream public repo — `NousResearch/hermes-agent`, community marketplaces, Vercel — never from the extracted DMG copy. Non-MIT files in that corpus (11 integration skills, the vendor's browser skill, `the vendor's model-instructions file`, `powerpoint.md`, license-less files) contribute nothing — no text, no structure — eliminating EULA/proprietary exposure entirely rather than managing it. The extracted corpus remains on disk purely as a discovery map (which apps have skills, what coverage looks like) and may be deleted; nothing in the deliverables traces to it.
- **KTD3 — Merge prompt repair is the highest-leverage distiller fix.** Current merge echoes section headers (observed on the 7-screen Gmail run). Fix: per-section extraction prompts (controls table first, then workflows from control sequences), plus a concrete populated example in the prompt. Sections `Tools` and `Verify before done` added to the merge template.
- **KTD4 — Exemplars are provenance-clean by construction.** `github` adapts MIT files; `gmail` is authored fresh from our captured screens with only section structure borrowed. Both carry `provenance:` frontmatter naming their source tier, modeling the convention for #225's auto-generated skills.

### Assumptions

- Upstream repos are verified MIT at fetch time — U1's ledger records `upstream-verified` state per source; any file whose upstream license can't be confirmed is dropped from inputs rather than adapted on trust.
- No reliance on the shipped-artifact corpus at all: even if the vendor EULA prohibits inspection, nothing in the deliverables reads or derives from Tier B/C files (KTD2).
- Wisp skill frontmatter needs no new code for this work; `provenance:` rides as a free-form extra key (skills.py ignores unknown keys — verify during U1).
- The behavioral bet (deeper format → better first-try app answers) is plausible but unproven; falsification is a deferred probe, not a gate (Outstanding Questions).

### Sequencing

U1 spec → U2 distiller (depends on spec) → U3 exemplars (independent, validates spec) → U4 hygiene/backlog notes (independent).

---

## Implementation Units

### U1. App-skill format spec + corpus license ledger

**Files:** `docs/research/app-skill-format.md` (new), `docs/research/skill-corpus-sources.md` (new, pointer+provenance note replacing the removed tree dir)

**Approach:** Write the R2 spec with per-section rules: the whitelist frontmatter set including `url_hosts`/`app_classes`/`asks` (the real router per `wisp/skills.py:403-455`), `Tools` section contract (tool name — arg shape — failure rule), `Verify before done` (read-back requirement), provenance field, and the R2b instruction-content rule. `skill-corpus-sources.md` records: the clean-source rule (upstream MIT only), corpus location `~/.local/share/wisp/reference/skill-corpus/` as discovery-map-only/deletable, and a per-source upstream-license ledger (`upstream-verified` or dropped).

**Test scenarios:** docs-only unit — verify no `skill-corpus/` path tracked by git (`git status`/`git ls-files`), corpus dir exists at new home with all 48 files (count check), spec file renders.

### U2. `skill_distill.py` — new sections + merge repair

**Files:** `scripts/skill_distill.py`, `tests/test_skill_distill.py`

**Approach:** Extend `_MERGE` to the R2 section set; add a worked one-paragraph example of a populated `Workflows`/`Gotchas` inside the prompt (few-shot, written by us); add `--tools-note` (known API coverage) plus `--hosts`/`--classes` flags that emit `url_hosts`/`app_classes`/`asks` frontmatter — without these the skill never auto-injects for the focused app (`match_app_skill_info` only reads those keys). Stamp `provenance:` + first-run frontmatter; strip/reject `tool:` and corpus-schema keys (`version`, `author`, `metadata:`) so a distilled skill can never register an executable tool. Keep per-screen describe prompt as-is (it works). The header-echo fix was observed on one run — validate the repaired prompt on both existing captures (gmail + perplexity), not just the fixture test.

**Test scenarios:**
- Merge output contains all required section headers when given fixture descriptions.
- `Workflows`/`Gotchas` bodies are non-empty and don't echo the literal template text, AND contain no claims untraceable to input descriptions (hallucination check).
- `--tools-note` content lands in `Tools`; absent flag leaves the section out or marked none.
- Frontmatter carries `name`, `description`, `url_hosts` or `app_classes` when flags are passed, `provenance`, and a first-run marker.
- A skill carrying `tool:` fails sanitization rather than registering a tool.

### U3. Two provenance-clean exemplar skills

**Files:** `tests/fixtures/skills/gmail-app/SKILL.md` (new), plus edits folded into `wisp/skills_seed/apps/github/SKILL.md` (existing seed — extend rather than collide; a repo-root `skills/` dir is never scanned)

**Approach:** `github` folds adapted content from upstream MIT `github-*` files (fetched from `NousResearch/hermes-agent`, attribution line kept) into the existing seed, condensed to wisp's section set. `gmail-app` authored from our own 7-screen captures + distilled descriptions; upstream MIT `google-workspace.md` may be adapted (attribution kept). Both carry `provenance:` (e.g. `adapted: MIT nousresearch/hermes-agent / authored: crawl 2026-10-28`) plus `url_hosts`/`app_classes` and `asks:` per R2. R2b instruction-content review applied to every adapted paragraph (strip command directives, credential handling, confirmation-suppression language). `Gotchas`/`Verify` populated only from observed evidence, else marked unverified.

**Test scenarios:**
- `wisp/skills.py` `index()` picks up both from a temp `SKILLS_DIR` (existing loader test pattern); `match_app_skill_info()` returns `gmail-app` on a `mail.google.com` probe and `github` on a `github.com` probe.
- Each file parses frontmatter (whitelist keys only — no `tool:`) and contains all required spec sections.
- Scripted n-gram check (n≈8–12 word sequences from non-MIT corpus files) finds zero matches in shipped artifacts — automated gate, supplemented by implementer review.

### U4. Backlog coverage matrix + issue note

**Files:** `docs/research/skill-corpus-sources.md` (required per R5 — table lands there); optionally a `gh issue comment` on #225

**Approach:** Table mapping the app list the corpus surfaced → wisp issues #206–#226 → upstream source availability (MIT upstream / none) → suggested depth (screen-map only vs screen+tools). Gaps we never filed (airtable, salesforce, imessage, googletasks, hubspot, dropbox, clickup, microsoft_teams, jira) noted for future issues.

**Test scenarios:** docs-only — table covers all 38 surfaced apps and all open app issues.

---

## Verification Contract

- `python -m pytest tests/test_skill_distill.py tests/test_svc.py -x` (keyless) plus full `pytest tests/` for the touched suite.
- Scripted provenance gate: extract n-gram sequences (n≈8–12 words) from non-MIT corpus files and fail if any appear in shipped artifacts — covers exemplars AND the diff generally (docs, prompts), not just `tests/fixtures/` (a small test or script under `tests/`; the corpus path is read-only input).
- `git ls-files | rg -i skill-corpus` returns nothing; `find ~/.local/share/wisp/reference/skill-corpus -name '*.md' | wc -l` = 48.
- Manual: re-run `skill_distill.py gmail-app --crawl ~/shots/gmail` (and the perplexity capture) and confirm populated Workflows/Gotchas with no untraceable claims.

## Definition of Done

- All R1–R6 met; exemplar skills load through `wisp/skills.py`; corpus lives outside git; spec is the single contract both the distiller and hand-written skills follow.
