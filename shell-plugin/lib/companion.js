.pragma library

// Companion surface rules (Ember U11, U12): when the corner creature, the
// pill and the console show. Pure; the host window feeds it the reducer
// view plus its own flags and applies the result. No timers: the busy
// watchdog (KTD8) stays in Companion.qml until the host is rebuilt on
// these components.

var PILL_STATUSES = ["listening", "transcribing", "awaiting_choice"]

// The listening pill owns live progress and choices.
function pillVisible(status) { return PILL_STATUSES.indexOf(status) >= 0 }

// The corner creature rests unless the user hid it or a fullscreen window
// has focus. Hiding lasts until the next Super+D or bar click (`reveal`).
function cornerVisible(hidden, fullscreen) { return !hidden && !fullscreen }

// Console opens on a user click, a pending choice, or a confirm; the
// working statuses (listening, deciding, acting) never open it alone.
function consoleOpen(status, hasChoices, userOpen) {
  if (status === "awaiting_choice" || hasChoices) return true
  return !!userOpen
}

// The user click toggles; resolving the choice closes an auto-opened
// console (a user-opened one stays until clicked again).
function userToggle(userOpen) { return !userOpen }

// Input region: the creature's bounds only (x, y, w, h), 28px minimum hit
// target around it.
function inputRegion(creatureBox, actions, actionsWidth) {
  var w = Math.max(28, creatureBox) + (actions ? actionsWidth : 0)
  return { x: 0, y: 0, w: w, h: Math.max(28, creatureBox) }
}
