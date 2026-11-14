---
title: "feat: Connector catalog, custom MCP, and paid proxy bundle decision"
type: feat
date: 2026-11-14
depends_on: docs/plans/2026-11-08-1749-feat-wisp-companion-core-plan.md
roadmap_area: 6+11
---

# Connector catalog, custom MCP, and paid proxy bundle decision

## Goal Capsule

- **Objective:** Close connector parity with HeyClicky's built-in app catalog + custom MCP + multi-account, and decide the paid proxy bundle (HeyClicky's pricing anchor) while keeping BYOK primary.
- **Means:** Extend `wisp/agent_mcp.py`, `wisp/mcpauth.py` (OAuth via BrowserOS Strata), `wisp/tools/mcpclient.py`; add onboarding connector pick step reusing `wispd onboard` checklist. No new daemon.
- **Authority:** Sonar-verified 2026-11-14 (heyclicky.com + pricing sources): built-in catalog includes Gmail, Google Calendar/Drive/Sheets, Notion, Linear; custom MCP servers addable; multiple accounts per app; screenshots/transcripts/prompts proxied to providers; OAuth tokens brokered by hosted third party. Pricing: free $0 = 25 talk + 25 agent/mo + dictation; Pro $20/mo = unlimited talk/dictation + 150 agents; Max $100/mo = 1,000 agents. Wisp decision: BYOK stays default; proxy bundle is optional (roadmap Area 11, "later").
- **Stop conditions:** Stop if any connector needs first-party app credentials beyond OAuth (Supabase/Stripe-class tokens in user config are out of scope); do not implement billing until proxy unit tests pass.

## Requirements

- **R1 (catalog, v1 slice).** Five connectors first: Gmail, Google Calendar, Google Drive, Notion, Linear (Strata OAuth path already exists via `wispd connect`). Multi-account labeling (Work/Personal) on each; results say which account answered.
- **R2 (custom MCP).** URL-or-command MCP registration honoring capability read ("reads capability list so voice knows when to use it"); results framed as data (2026-11-13 framing rule when present).
- **R3 (skills parity).** Built-in catalog ships `SKILL.md` seeds mirroring `wisp/skills_seed/apps/` pattern + synthetic teach fixture per connector.
- **R4 (paid bundle decision).** Define the optional proxy: Wisp-issued key (trading only usage metadata + encrypted content), BYOK unaffected. Pricing proposal anchored to HC ($20 Pro-class) but owned numbers decided at `wispd eval` cost data; no billing code until eval gate passes.

## Units

| ID | Work | Files | Test |
|---|---|---|---|
| U1 | Catalog v1 (Gmail/Calendar/Drive/Notion/Linear) OAuth + multi-account grep `wisp/agents.py` login hints | `wisp/mcpauth.py`, `wisp/agent_mcp.py` | `tests/test_connectors.py`: account label on result; capability read gates toolbelt |
| U2 | Custom MCP registry + upstream tools passthrough + framing | `wisp/tools/mcpclient.py` | `tests/test_connectors.py`: dynamic tool registration; malformed capability list refused |
| U3 | Proxy bundle spec (host, limits, usage metering, opt-in UX) — spec only, no billing | `docs/TRUST.md`, new `docs/PROXY_BUNDLE.md` | `tests/test_trust.py` extended: proxy hosts listed before code ships |

## Non-goals

- No per-message metering in code; no Stripe integration; no multi-account for non-catalog servers.

## Risks

- OAuth broker dependency: Strata outage blocks connector onboarding — degrade to catalog-off with `wispd doctor` clear status.
- Account mixing (Work/Personal Gmail) is a tenant-isolation bug class: tests must prove cross-account result leakage is rejected.
