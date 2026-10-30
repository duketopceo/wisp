// This reducer drives an illustration, never a computer or model API.
export const scenarios = Object.freeze({
  mail: {ask: "Check my email.", target: "Personal browser", sensitive: false},
  work: {ask: "Open my work tasks.", target: "Work browser", sensitive: false},
  sensitive: {ask: "Submit this payment.", target: "Sensitive action", sensitive: true},
  media: {ask: "Toggle playback.", target: "Media controls", sensitive: false},
});

export function initial() {
  return {phase: "idle", scenario: "mail", turn: 0};
}

export function transition(state, event) {
  if (event.type === "reset") return {...initial(), turn: state.turn + 1};
  if (event.type === "start" && scenarios[event.scenario]) {
    return {phase: "listening", scenario: event.scenario, turn: state.turn + 1};
  }
  if (event.turn !== undefined && event.turn !== state.turn) return state;
  const active = ["listening", "thinking", "acting", "awaiting_choice"];
  if (event.type === "cancel" && active.includes(state.phase)) {
    return {...state, phase: "cancelled"};
  }
  if (event.type === "approve" && state.phase === "awaiting_choice") {
    return {...state, phase: "acting"};
  }
  if (event.type !== "advance") return state;
  const next = {
    listening: "thinking",
    thinking: scenarios[state.scenario].sensitive ? "awaiting_choice" : "acting",
    acting: "done",
  }[state.phase];
  return next ? {...state, phase: next} : state;
}
