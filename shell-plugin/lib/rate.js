.pragma library

// One-tap rating (U2): which cards can be rated, the argv the service runs,
// and the receipt line a rated card shows. Pure; the components feed it the
// reducer view and WispService.lastAction.

// A finished answer can be rated; a cancelled or errored turn cannot (the
// daemon refuses those too, with not_ratable).
function rateable(status, answer, result, errorCode) {
  if (status !== "done" || answer === "") return false
  if (errorCode !== "" && errorCode !== undefined) return false
  return !/^(CANCELLED|ERROR|INTERRUPTED|ABORTED)/i.test(String(result))
}

// `wispd label set --json [--turn T] -- verdict [note]`: options first so
// the optional note words are not read as options.
function labelCommand(wispd, verdict, turn, note) {
  var cmd = [wispd, "label", "set", "--json"]
  if (turn) cmd = cmd.concat(["--turn", turn])
  cmd = cmd.concat(["--", verdict])
  if (note) cmd = cmd.concat([note])
  return cmd
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
  if (last.status === "not_found" || last.status === "not_ratable")
    return { kind: "muted", text: ui("ui.rate." + last.status) }
  return { kind: "muted", text: String(last.message || "") }
}
