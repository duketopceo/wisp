.pragma library

// What's-new card model (B26): turns `wispd whatsnew --json` into a card
// and builds the argv for its actions. Pure functions, no strings shown to
// users. The daemon decides whether there is anything to show (first
// install, an already seen version and a version with no changelog entry
// all come back as no card); this only normalizes what it sent.

var MAX_LINES = 3

// `wispd ... --json` stdout (envelope or bare data) -> card or null
function parse(stdout) {
  var o
  try { o = JSON.parse(stdout) } catch (e) { return null }
  var d = o && o.data ? o.data : o
  var c = d ? d.card : null
  if (!c || typeof c !== "object") return null
  var raw = c.lines
  var src = raw && typeof raw !== "string" && typeof raw.length === "number" ? raw : []
  var lines = []
  for (var i = 0; i < src.length && lines.length < MAX_LINES; i++) {
    var t = typeof src[i] === "string" ? src[i].replace(/\s+/g, " ").trim() : ""
    if (t !== "") lines.push(t)
  }
  if (lines.length === 0) return null
  return { title: String(c.title || c.version || ""), date: String(c.date || ""),
           lines: lines, more: typeof c.more === "number" && c.more > 0 ? c.more : 0,
           url: String(c.url || "") }
}

function visible(card) { return card !== null && card !== undefined }

function statusCommand(wispd) { return [wispd, "whatsnew", "--json"] }

function seenCommand(wispd) { return [wispd, "whatsnew", "--seen", "--json"] }

// only the project's own https address is ever opened
function linkCommand(url) {
  return /^https:\/\/github\.com\//.test(url || "") ? ["xdg-open", url] : []
}
