.pragma library
// Ask chips (B21): what a quick tap of the talk key offers. Pure view logic;
// the daemon decides when (wisp/chips.py), this only normalizes what it sent.

var MAX = 3
var SHOW_MS = 9000          // how long the chips stay up after a tap
var TITLE = "Try saying"

// state.chips -> { show, title, asks:[string], seq }
function view(chips) {
  var asks = []
  // a list handed over from C++ or JSON is array-like, not always an Array
  var raw = chips ? chips.asks : null
  var src = raw && typeof raw !== "string" && typeof raw.length === "number" ? raw : []
  for (var i = 0; i < src.length && asks.length < MAX; i++) {
    var t = typeof src[i] === "string" ? src[i].replace(/\s+/g, " ").trim() : ""
    if (t !== "" && asks.indexOf(t) < 0) asks.push(t.length > 70 ? t.slice(0, 69) + "…" : t)
  }
  return { show: asks.length > 0, title: TITLE, asks: asks,
           seq: chips && typeof chips.seq === "number" ? chips.seq : 0 }
}

// the fade runs only in full motion; reduced and off show them at once
function fadeMs(motion) { return motion === "full" ? 160 : 0 }

// chips never sit over a live turn: only while the service is quiet
function quiet(status) { return status === "done" || status === "idle" }
