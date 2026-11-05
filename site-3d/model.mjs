// This reducer drives an illustration, never a computer or model API.
export const scenarios = Object.freeze({
  mail: {
    ask: "Check my email.",
    target: "Personal browser",
    sensitive: false,
    window: "personal",
    title: "Mail — Personal",
  },
  work: {
    ask: "Open my work tasks.",
    target: "Work browser",
    sensitive: false,
    window: "work",
    title: "Tasks — Work",
  },
  sensitive: {
    ask: "Submit this payment.",
    target: "Sensitive action",
    sensitive: true,
    window: "pay",
    title: "Checkout — Stripe",
  },
  media: {
    ask: "Toggle playback.",
    target: "Media controls",
    sensitive: false,
    window: "media",
    title: "Player — Media",
  },
});

const scripts = Object.freeze({
  mail: {
    idle: {
      status: "Inbox ready",
      controls: [
        {id: "inbox", label: "Inbox", value: "12 unread", kind: "list"},
        {id: "thread", label: "Thread", value: "Project update from Maya", kind: "row"},
        {id: "reply", label: "Reply", value: "idle", kind: "button"},
      ],
      drawings: [],
      steps: ["Choose an example to begin."],
    },
    listening: {
      status: "Listening",
      controls: [
        {id: "inbox", label: "Inbox", value: "12 unread", kind: "list"},
        {id: "thread", label: "Thread", value: "Project update from Maya", kind: "row"},
        {id: "reply", label: "Reply", value: "idle", kind: "button"},
      ],
      drawings: [{type: "number", n: 1, target: "inbox", text: "Hear the request"}],
      steps: ["1 Hear “Check my email.”"],
    },
    thinking: {
      status: "Finding the personal inbox",
      controls: [
        {id: "inbox", label: "Inbox", value: "selected", kind: "list", active: true},
        {id: "thread", label: "Thread", value: "Project update from Maya", kind: "row"},
        {id: "reply", label: "Reply", value: "idle", kind: "button"},
      ],
      drawings: [
        {type: "hl", target: "inbox"},
        {type: "arrow", from: "ember", to: "inbox"},
        {type: "number", n: 1, target: "inbox", text: "Personal profile"},
      ],
      steps: ["1 Open the personal browser profile", "2 Locate Inbox"],
    },
    acting: {
      status: "Opening the unread thread",
      controls: [
        {id: "inbox", label: "Inbox", value: "open", kind: "list", active: true},
        {id: "thread", label: "Thread", value: "opened", kind: "row", active: true},
        {id: "reply", label: "Reply", value: "ready", kind: "button"},
      ],
      drawings: [
        {type: "hl", target: "thread"},
        {type: "arrow", from: "inbox", to: "thread"},
        {type: "number", n: 2, target: "thread", text: "Unread thread"},
        {type: "ring", target: "reply"},
      ],
      steps: ["1 Personal inbox", "2 Open unread thread", "3 Leave Reply untouched"],
    },
    done: {
      status: "Inbox opened — nothing sent",
      controls: [
        {id: "inbox", label: "Inbox", value: "open", kind: "list", active: true},
        {id: "thread", label: "Thread", value: "opened", kind: "row", active: true},
        {id: "reply", label: "Reply", value: "ready", kind: "button"},
      ],
      drawings: [
        {type: "number", n: 1, target: "inbox", text: "Personal inbox"},
        {type: "number", n: 2, target: "thread", text: "Thread opened"},
      ],
      steps: ["Done. No message was sent."],
    },
  },
  work: {
    idle: {
      status: "Work board idle",
      controls: [
        {id: "profile", label: "Profile", value: "Work", kind: "chip"},
        {id: "board", label: "Board", value: "Sprint 18", kind: "panel"},
        {id: "task", label: "Task", value: "Ship RC2 notes", kind: "row"},
      ],
      drawings: [],
      steps: ["Choose an example to begin."],
    },
    listening: {
      status: "Listening",
      controls: [
        {id: "profile", label: "Profile", value: "Work", kind: "chip"},
        {id: "board", label: "Board", value: "Sprint 18", kind: "panel"},
        {id: "task", label: "Task", value: "Ship RC2 notes", kind: "row"},
      ],
      drawings: [{type: "number", n: 1, target: "profile", text: "Hear the request"}],
      steps: ["1 Hear “Open my work tasks.”"],
    },
    thinking: {
      status: "Switching to the work profile",
      controls: [
        {id: "profile", label: "Profile", value: "Work · active", kind: "chip", active: true},
        {id: "board", label: "Board", value: "Sprint 18", kind: "panel"},
        {id: "task", label: "Task", value: "Ship RC2 notes", kind: "row"},
      ],
      drawings: [
        {type: "hl", target: "profile"},
        {type: "arrow", from: "ember", to: "profile"},
        {type: "number", n: 1, target: "profile", text: "Work profile"},
      ],
      steps: ["1 Select work browser profile", "2 Find the task board"],
    },
    acting: {
      status: "Focusing the sprint task",
      controls: [
        {id: "profile", label: "Profile", value: "Work · active", kind: "chip", active: true},
        {id: "board", label: "Board", value: "Sprint 18 · open", kind: "panel", active: true},
        {id: "task", label: "Task", value: "focused", kind: "row", active: true},
      ],
      drawings: [
        {type: "hl", target: "board"},
        {type: "arrow", from: "profile", to: "task"},
        {type: "number", n: 2, target: "task", text: "Today’s task"},
        {type: "ring", target: "task"},
      ],
      steps: ["1 Work profile", "2 Open board", "3 Focus today’s task"],
    },
    done: {
      status: "Work task focused",
      controls: [
        {id: "profile", label: "Profile", value: "Work · active", kind: "chip", active: true},
        {id: "board", label: "Board", value: "Sprint 18 · open", kind: "panel", active: true},
        {id: "task", label: "Task", value: "focused", kind: "row", active: true},
      ],
      drawings: [
        {type: "number", n: 1, target: "profile", text: "Work profile"},
        {type: "number", n: 2, target: "task", text: "Task focused"},
      ],
      steps: ["Done. No task status was changed."],
    },
  },
  sensitive: {
    idle: {
      status: "Checkout idle",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00", kind: "field"},
        {id: "inspect", label: "Inspect", value: "read-only", kind: "button"},
        {id: "pay", label: "Pay now", value: "armed", kind: "button", sensitive: true},
      ],
      drawings: [],
      steps: ["Choose an example to begin."],
    },
    listening: {
      status: "Listening",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00", kind: "field"},
        {id: "inspect", label: "Inspect", value: "read-only", kind: "button"},
        {id: "pay", label: "Pay now", value: "armed", kind: "button", sensitive: true},
      ],
      drawings: [{type: "number", n: 1, target: "amount", text: "Hear the request"}],
      steps: ["1 Hear “Submit this payment.”"],
    },
    thinking: {
      status: "Reading the checkout page",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00 · verified", kind: "field", active: true},
        {id: "inspect", label: "Inspect", value: "safe read", kind: "button", active: true},
        {id: "pay", label: "Pay now", value: "armed", kind: "button", sensitive: true},
      ],
      drawings: [
        {type: "hl", target: "amount"},
        {type: "arrow", from: "ember", to: "inspect"},
        {type: "number", n: 1, target: "inspect", text: "Safe read"},
      ],
      steps: ["1 Read amount", "2 Navigation/inspect needs no approval"],
    },
    awaiting_choice: {
      status: "Paused for confirmation",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00 · verified", kind: "field", active: true},
        {id: "inspect", label: "Inspect", value: "safe read", kind: "button"},
        {id: "pay", label: "Pay now", value: "needs approval", kind: "button", sensitive: true, active: true},
      ],
      drawings: [
        {type: "hl", target: "pay"},
        {type: "ring", target: "pay"},
        {type: "arrow", from: "inspect", to: "pay"},
        {type: "number", n: 2, target: "pay", text: "Mutation needs you"},
      ],
      steps: ["1 Safe inspect done", "2 Pay now waits for Approve example"],
    },
    acting: {
      status: "Illustrating approved submit",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00 · verified", kind: "field", active: true},
        {id: "inspect", label: "Inspect", value: "safe read", kind: "button"},
        {id: "pay", label: "Pay now", value: "approved · illustrated", kind: "button", sensitive: true, active: true},
      ],
      drawings: [
        {type: "ring", target: "pay"},
        {type: "number", n: 3, target: "pay", text: "Approved example only"},
      ],
      steps: ["1 Inspected", "2 You approved", "3 Illustrative click only"],
    },
    done: {
      status: "Example complete — no charge made",
      controls: [
        {id: "amount", label: "Amount", value: "$48.00 · verified", kind: "field", active: true},
        {id: "inspect", label: "Inspect", value: "safe read", kind: "button"},
        {id: "pay", label: "Pay now", value: "illustrated", kind: "button", sensitive: true},
      ],
      drawings: [
        {type: "number", n: 1, target: "inspect", text: "Read path"},
        {type: "number", n: 2, target: "pay", text: "No live charge"},
      ],
      steps: ["Done. Secrets stayed refused; nothing charged."],
    },
  },
  media: {
    idle: {
      status: "Player idle · playing",
      controls: [
        {id: "track", label: "Track", value: "Night Drive", kind: "label"},
        {id: "play", label: "Playback", value: "playing", kind: "toggle"},
        {id: "inspect", label: "Inspect player", value: "required", kind: "note"},
      ],
      drawings: [],
      steps: ["Choose an example to begin."],
    },
    listening: {
      status: "Listening",
      controls: [
        {id: "track", label: "Track", value: "Night Drive", kind: "label"},
        {id: "play", label: "Playback", value: "playing", kind: "toggle"},
        {id: "inspect", label: "Inspect player", value: "required", kind: "note"},
      ],
      drawings: [{type: "number", n: 1, target: "play", text: "Hear the request"}],
      steps: ["1 Hear “Toggle playback.”"],
    },
    thinking: {
      status: "Finding the playback control",
      controls: [
        {id: "track", label: "Track", value: "Night Drive", kind: "label"},
        {id: "play", label: "Playback", value: "playing", kind: "toggle", active: true},
        {id: "inspect", label: "Inspect player", value: "required", kind: "note"},
      ],
      drawings: [
        {type: "hl", target: "play"},
        {type: "arrow", from: "ember", to: "play"},
        {type: "number", n: 1, target: "play", text: "Playback toggle"},
      ],
      steps: ["1 Locate playback toggle", "2 Do not assume paused"],
    },
    acting: {
      status: "Toggling playback · then inspect",
      controls: [
        {id: "track", label: "Track", value: "Night Drive", kind: "label"},
        {id: "play", label: "Playback", value: "paused", kind: "toggle", active: true},
        {id: "inspect", label: "Inspect player", value: "check state", kind: "note", active: true},
      ],
      drawings: [
        {type: "ring", target: "play"},
        {type: "arrow", from: "play", to: "inspect"},
        {type: "number", n: 2, target: "play", text: "Toggle sent"},
        {type: "number", n: 3, target: "inspect", text: "Inspect real state"},
      ],
      steps: ["1 Find toggle", "2 Send toggle", "3 Inspect player state"],
    },
    done: {
      status: "Toggle illustrated · inspect still required",
      controls: [
        {id: "track", label: "Track", value: "Night Drive", kind: "label"},
        {id: "play", label: "Playback", value: "paused", kind: "toggle", active: true},
        {id: "inspect", label: "Inspect player", value: "still required", kind: "note", active: true},
      ],
      drawings: [
        {type: "number", n: 1, target: "play", text: "Toggle illustrated"},
        {type: "number", n: 2, target: "inspect", text: "Verify on device"},
      ],
      steps: ["Done. Real playback still needs inspection."],
    },
  },
});

export function initial() {
  return {phase: "idle", scenario: "mail", turn: 0};
}

export function scriptFor(state) {
  const pack = scripts[state.scenario] || scripts.mail;
  if (state.phase === "cancelled") {
    const base = pack.idle;
    return {
      ...base,
      status: "Cancelled — desktop unchanged",
      drawings: [],
      steps: ["Cancelled. Nothing was changed."],
    };
  }
  return pack[state.phase] || pack.idle;
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
