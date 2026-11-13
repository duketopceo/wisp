.pragma library

// One-tap rating (U2): which cards can be rated, the argv the service runs,
// and the receipt line a rated card shows. Pure; the components feed it the
// reducer view and WispService.lastAction.

// The bar pill's 8 s rating window: a finished answer only. A cancelled or
// errored turn never opens it (the pill has already shown why it stopped).
function rateable(status, answer, result, errorCode) {
  if (status !== "done" || answer === "") return false
  if (errorCode !== "" && errorCode !== undefined) return false
  return !/^(CANCELLED|ERROR|INTERRUPTED|ABORTED)/i.test(String(result))
}

// The answer card's thumbs (RateRow): every terminal turn, including one
// the owner stopped or that errored. `wispd label set` stores such a verdict
// as `cut-short`, so it is kept and shown while the accuracy gate ignores
// it. This is why the card has its own rule instead of reusing `rateable`.
function cardRateable(status) {
  return status === "done"
}

// True when the turn ended by being stopped rather than finishing: the
// card still offers its thumbs and this only labels the receipt.
function cutShort(result, errorCode) {
  if (errorCode === "cancelled") return true
  return /^(CANCELLED|ERROR|INTERRUPTED|ABORTED)/i.test(String(result))
}

// `wispd label set --json [--turn T] [--stdin] -- verdict`: the optional
// note is typed text, so the caller writes it to the child's stdin
// (`--stdin`) instead of putting it on the command line, where other local
// accounts can read it.
function labelCommand(wispd, verdict, turn, note) {
  var cmd = [wispd, "label", "set", "--json"]
  if (turn) cmd = cmd.concat(["--turn", turn])
  if (note) cmd = cmd.concat(["--stdin"])
  return cmd.concat(["--", verdict])
}

// closes the open note without writing a label
function skipCommand(wispd) { return labelCommand(wispd, "skip", "", "") }

// What a card shows once its rating went out. `last` is the service's
// lastAction ({verb, pending, ok, status, message, turn}); only an ack for
// this card's turn counts. kind: none | receipt | muted.
function receipt(last, turn, verdict, ui) {
  if (!last || last.verb !== "label" || last.turn !== turn)
    return { kind: "none", text: "" }
  if (last.pending || last.ok === true)
    return { kind: "receipt",
             text: ui(verdict === "incorrect" ? "ui.rate.wrong" : "ui.rate.good") }
  if (last.status === "not_found")
    return { kind: "muted", text: ui("ui.rate." + last.status) }
  if (last.status === "not_ratable")
    return { kind: "muted", text: ui("ui.rate.not_ratable") }
  return { kind: "muted", text: String(last.message || "") }
}
