import {initial, transition, scenarios} from "./model.mjs";

const scene = document.querySelector("#scene");
const fallback = document.querySelector("#scene-fallback");
const story = document.querySelector(".workspace-story");
const note = document.querySelector(".scene-note");
const status = document.querySelector("#demo-state");
const approve = document.querySelector("#approve-demo");
const cancel = document.querySelector("#cancel-demo");
const pauseMotion = document.querySelector("#pause-motion");
const reset = document.querySelector("#reset-demo");
const sensitiveRules = document.querySelector("#sensitive-rules");
const examples = [...document.querySelectorAll("[data-scenario]")];
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
let state = initial();
let timer;
let sceneHandle;
let generation = 0;
let motionPaused = false;

function renderState() {
  const focusedControl = document.activeElement;
  const target = scenarios[state.scenario].target;
  const messages = {
    idle: "Ready. Choose an example below.",
    listening: `Listening example: “${scenarios[state.scenario].ask}”`,
    thinking: `Finding context: ${target}.`,
    acting: `Illustrating the next step: ${target}.`,
    awaiting_choice: "Paused. A sensitive action needs your confirmation.",
    done: state.scenario === "media"
      ? "Playback-toggle example complete. Real playback state would still need inspection."
      : "Example complete. Nothing on your computer was changed.",
    cancelled: "Example cancelled. Nothing was changed.",
  };
  status.textContent = messages[state.phase];
  status.dataset.phase = state.phase;
  approve.hidden = state.phase !== "awaiting_choice";
  cancel.disabled = !["listening", "thinking", "acting", "awaiting_choice"].includes(state.phase);
  reset.disabled = state.phase === "idle";
  sensitiveRules.hidden = state.scenario !== "sensitive";
  for (const button of examples) {
    button.disabled = false;
    button.setAttribute("aria-pressed", String(state.phase !== "idle" && state.scenario === button.dataset.scenario));
  }
  sceneHandle?.setState(state);
  if ((focusedControl === cancel && cancel.disabled) || (focusedControl === reset && reset.disabled)) {
    examples.find(button => button.dataset.scenario === state.scenario).focus({preventScroll: true});
  }
}

function dispatch(event) {
  clearTimeout(timer);
  state = transition(state, event);
  renderState();
  // These are storytelling delays, not measured model or product latencies.
  if (["listening", "thinking", "acting"].includes(state.phase)) {
    const turn = state.turn;
    timer = setTimeout(() => dispatch({type: "advance", turn}), 850);
  }
}

for (const button of examples) {
  button.addEventListener("click", () => dispatch({type: "start", scenario: button.dataset.scenario}));
}
approve.addEventListener("click", () => {
  dispatch({type: "approve"});
  // The confirmation button disappears after use; keep keyboard focus useful.
  cancel.focus({preventScroll: true});
});
cancel.addEventListener("click", () => {
  dispatch({type: "cancel"});
  examples.find(button => button.dataset.scenario === state.scenario).focus({preventScroll: true});
});
reset.addEventListener("click", () => dispatch({type: "reset"}));
renderState();

function staticScene() {
  scene.dataset.renderer = "static";
  delete scene.dataset.rendered;
  fallback.hidden = false;
  note.hidden = true;
}

async function mountScene() {
  const epoch = ++generation;
  sceneHandle?.dispose();
  sceneHandle = undefined;
  staticScene();
  pauseMotion.disabled = reduced.matches;
  pauseMotion.textContent = reduced.matches ? "Reduced motion on" : motionPaused ? "Resume motion" : "Pause motion";
  pauseMotion.setAttribute("aria-pressed", String(motionPaused || reduced.matches));
  if (reduced.matches || motionPaused) return;
  scene.dataset.renderer = "loading";
  try {
    await document.fonts.ready;
    const {createScene} = await import("./scene.mjs");
    if (epoch !== generation || reduced.matches || motionPaused) return;
    sceneHandle = createScene(scene, story, () => {
      sceneHandle = undefined;
      staticScene();
    });
    sceneHandle.setState(state);
    fallback.hidden = true;
    note.hidden = false;
    scene.dataset.renderer = "webgl";
  } catch {
    // The real companion image remains available if WebGL or its module fails.
    if (epoch === generation) staticScene();
  }
}
reduced.addEventListener("change", mountScene);
pauseMotion.addEventListener("click", () => {
  motionPaused = !motionPaused;
  mountScene();
});
mountScene();

const copy = document.querySelector("#copy-install");
copy.disabled = false;
copy.addEventListener("click", async () => {
  const message = document.querySelector("#copy-status");
  try {
    await navigator.clipboard.writeText(document.querySelector("#install-code").textContent);
    message.textContent = "Command copied. Review the installation guide before running it.";
  } catch {
    message.textContent = "Clipboard unavailable. Select and copy the command above.";
  }
});
window.addEventListener("pagehide", event => {
  if (!event.persisted) {
    generation++;
    clearTimeout(timer);
    sceneHandle?.dispose();
    reduced.removeEventListener("change", mountScene);
  }
});
