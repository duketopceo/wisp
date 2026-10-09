.pragma library

// Companion surface rules (Ember U11, U12): which transient overlays show.
// Pure; the host window feeds it the reducer view and applies the result.
// The corner creature and console were dropped 2026-10-07 — the live
// surface is the bar pill; these rules govern only wisp-points.

var PILL_STATUSES = ["listening", "transcribing", "awaiting_choice"]

// The listening pill owns live progress and choices.
function pillVisible(status) { return PILL_STATUSES.indexOf(status) >= 0 }
