---
version: alpha
name: Wisp-design-system
description: A quiet instrument, not a mascot. Wisp's surfaces are small
  chrome floating over a desktop the user is already looking at — the
  design recedes. One dark and one light palette, hand-paired (never
  inverted). The companion orb is a single dot of color; the ghost
  cursor is the only element allowed to be loud, because it must never
  be mistaken for the user's own pointer.

colors:
  dark:
    canvas: "#1a1b26"
    surface: "#283457"
    hairline: "#3b4261"
    ink: "#c0caf5"
    muted: "#9aa5ce"
    faint: "#565f89"
    accent: "#7aa2f7"
    accent-alt: "#bb9af7"
    guide: "#7dcfff"
    ok: "#9ece6a"
    warn: "#e0af68"
    err: "#e05555"
  light:
    canvas: "#f5f6fa"
    surface: "#e2e6f2"
    hairline: "#c3c9dd"
    ink: "#1f2335"
    muted: "#4c5578"
    faint: "#8a91ad"
    accent: "#2e7de9"
    accent-alt: "#9854f1"
    guide: "#007197"
    ok: "#33701f"
    warn: "#8f5e15"
    err: "#c43a3a"

typography:
  card-title:
    fontSize: 13px
    fontWeight: 700
  transcript:
    fontSize: 12px
    fontStyle: italic
    color: muted
  body:
    fontSize: 13px
    color: ink
  meta:
    fontSize: 11px
    color: faint
  step-log:
    fontSize: 10px
    fontFamily: monospace
    color: faint
  chip:
    fontSize: 11px
    color: ink

elevation:
  card:
    radius: 12px
    border: hairline 1px
    background: canvas
  chip:
    radius: 6px
    background: surface
  marker-label:
    radius: 6px
    border: accent 1px
    background: canvas

motion:
  orb-breathe: 1400ms in-out sine, scale 1.0-1.15, busy/speaking only
  ghost-peel: 250ms out-cubic, ring to target
  marker-pulse: 1200ms in-out sine, scale 1.0-1.2
  ring-spin: 1100ms linear infinite (busy only)

states:
  idle: faint orb
  listening: accent orb + level waveform
  deciding: accent-alt orb + ring spin
  acting: ok orb + guide ring on cursor
  suggestion: warn orb + card
  error: err orb + err text in card
---

# Wisp design notes

- The ghost cursor (`guide` token) is always the accent-alt of the
  palette — it must read as "not your cursor" at a glance.
- Cards auto-collapse; nothing on screen persists that isn't earning
  its place.
- The bar glyph is a single orb-color dot — no text in the bar.
- Light theme exists for daytime/bright-wallpaper setups; the daemon's
  surfaces are the only themed surface, Omarchy chrome stays untouched.
