import {scenarios, scriptFor} from "./model.mjs";

// DOM desktop: readable windows, control changes, and drawing overlays.
// This is the non-WebGL interaction path and stays useful when Three pauses.
export function createDesktop(host) {
  host.replaceChildren();
  host.classList.add("desktop-root");

  const stage = document.createElement("div");
  stage.className = "desktop-stage";
  host.append(stage);

  const windows = {
    personal: makeWindow("personal", "Mail — Personal", "Personal browser"),
    work: makeWindow("work", "Tasks — Work", "Work browser"),
    pay: makeWindow("pay", "Checkout — Stripe", "Sensitive action"),
    media: makeWindow("media", "Player — Media", "Media controls"),
  };
  for (const node of Object.values(windows)) stage.append(node.root);

  const draw = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  draw.setAttribute("class", "draw-layer");
  draw.setAttribute("aria-hidden", "true");
  stage.append(draw);

  const guide = document.createElement("ol");
  guide.className = "desktop-guide";
  guide.setAttribute("aria-live", "polite");
  host.append(guide);

  let state = {phase: "idle", scenario: "mail", turn: 0};

  function makeWindow(id, title, eyebrow) {
    const root = document.createElement("article");
    root.className = `desk-window desk-window--${id}`;
    root.dataset.window = id;
    root.innerHTML = `
      <header class="desk-chrome">
        <span class="desk-dots" aria-hidden="true"></span>
        <span class="desk-eyebrow">${eyebrow}</span>
        <span class="desk-title">${title}</span>
      </header>
      <div class="desk-body">
        <p class="desk-status" data-role="status"></p>
        <ul class="desk-controls" data-role="controls"></ul>
      </div>`;
    return {
      root,
      status: root.querySelector('[data-role="status"]'),
      controls: root.querySelector('[data-role="controls"]'),
    };
  }

  function renderControls(list, controls) {
    list.replaceChildren();
    for (const control of controls) {
      const item = document.createElement("li");
      item.className = "desk-control";
      item.dataset.control = control.id;
      if (control.active) item.dataset.active = "true";
      if (control.sensitive) item.dataset.sensitive = "true";
      item.innerHTML = `
        <span class="desk-control-label">${control.label}</span>
        <span class="desk-control-value">${control.value}</span>`;
      list.append(item);
    }
  }

  function controlPoint(windowId, controlId) {
    const win = windows[windowId]?.root;
    const el = win?.querySelector(`[data-control="${controlId}"]`);
    if (!el) return null;
    const stageBox = stage.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    return {
      x: box.left - stageBox.left + box.width / 2,
      y: box.top - stageBox.top + box.height / 2,
      w: box.width,
      h: box.height,
      left: box.left - stageBox.left,
      top: box.top - stageBox.top,
    };
  }

  function emberPoint() {
    const stageBox = stage.getBoundingClientRect();
    return {x: stageBox.width * 0.88, y: stageBox.height * 0.78};
  }

  function pointFor(ref, windowId) {
    if (ref === "ember") return emberPoint();
    return controlPoint(windowId, ref);
  }

  function ensureDefs() {
    const ns = "http://www.w3.org/2000/svg";
    let defs = draw.querySelector("defs");
    if (defs) return defs;
    defs = document.createElementNS(ns, "defs");
    defs.innerHTML = `
      <marker id="draw-arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
        <path d="M0,0 L6,3 L0,6 Z" class="draw-arrowhead"></path>
      </marker>`;
    draw.append(defs);
    return defs;
  }

  function renderDrawings(drawings, windowId) {
    const ns = "http://www.w3.org/2000/svg";
    draw.replaceChildren();
    ensureDefs();
    const stageBox = stage.getBoundingClientRect();
    draw.setAttribute("viewBox", `0 0 ${Math.max(1, stageBox.width)} ${Math.max(1, stageBox.height)}`);
    draw.setAttribute("width", "100%");
    draw.setAttribute("height", "100%");

    for (const mark of drawings) {
      if (mark.type === "hl") {
        const pt = controlPoint(windowId, mark.target);
        if (!pt) continue;
        const rect = document.createElementNS(ns, "rect");
        rect.setAttribute("x", String(pt.left - 6));
        rect.setAttribute("y", String(pt.top - 4));
        rect.setAttribute("width", String(pt.w + 12));
        rect.setAttribute("height", String(pt.h + 8));
        rect.setAttribute("rx", "10");
        rect.setAttribute("class", "draw-hl");
        draw.append(rect);
      } else if (mark.type === "ring") {
        const pt = controlPoint(windowId, mark.target);
        if (!pt) continue;
        const circle = document.createElementNS(ns, "circle");
        circle.setAttribute("cx", String(pt.x));
        circle.setAttribute("cy", String(pt.y));
        circle.setAttribute("r", String(Math.max(pt.w, pt.h) * 0.42 + 10));
        circle.setAttribute("class", "draw-ring");
        draw.append(circle);
      } else if (mark.type === "arrow") {
        const a = pointFor(mark.from, windowId);
        const b = pointFor(mark.to, windowId);
        if (!a || !b) continue;
        const path = document.createElementNS(ns, "path");
        const midX = (a.x + b.x) / 2;
        const midY = Math.min(a.y, b.y) - 28;
        path.setAttribute("d", `M ${a.x} ${a.y} Q ${midX} ${midY} ${b.x} ${b.y}`);
        path.setAttribute("class", "draw-arrow");
        path.setAttribute("marker-end", "url(#draw-arrowhead)");
        draw.append(path);
      } else if (mark.type === "number") {
        const pt = controlPoint(windowId, mark.target) || emberPoint();
        const cx = pt.left !== undefined ? pt.left - 8 : pt.x;
        const cy = pt.top !== undefined ? pt.top - 8 : pt.y - 18;
        const g = document.createElementNS(ns, "g");
        g.setAttribute("class", "draw-number");
        const circle = document.createElementNS(ns, "circle");
        circle.setAttribute("cx", String(cx));
        circle.setAttribute("cy", String(cy));
        circle.setAttribute("r", "12");
        const text = document.createElementNS(ns, "text");
        text.setAttribute("x", String(cx));
        text.setAttribute("y", String(cy + 4));
        text.setAttribute("text-anchor", "middle");
        text.textContent = String(mark.n);
        g.append(circle, text);
        draw.append(g);
        if (mark.text) {
          const label = document.createElementNS(ns, "text");
          label.setAttribute("class", "draw-caption");
          label.setAttribute("x", String(cx + 18));
          label.setAttribute("y", String(cy + 4));
          label.textContent = mark.text;
          draw.append(label);
        }
      }
    }
  }

  function renderGuide(steps) {
    guide.replaceChildren();
    for (const step of steps) {
      const item = document.createElement("li");
      item.textContent = step;
      guide.append(item);
    }
  }

  function fillWindow(id, scenarioKey, phase) {
    const win = windows[id];
    const script = scriptFor({phase, scenario: scenarioKey});
    win.status.textContent = script.status;
    renderControls(win.controls, script.controls);
    return script;
  }

  function setState(next) {
    state = next;
    const meta = scenarios[state.scenario];
    const activeId = meta.window;
    const overview = state.phase === "idle";
    stage.dataset.mode = overview ? "overview" : "focus";

    fillWindow("personal", "mail", overview ? "idle" : state.scenario === "mail" ? state.phase : "idle");
    fillWindow("work", "work", overview ? "idle" : state.scenario === "work" ? state.phase : "idle");
    fillWindow("pay", "sensitive", overview ? "idle" : state.scenario === "sensitive" ? state.phase : "idle");
    fillWindow("media", "media", overview ? "idle" : state.scenario === "media" ? state.phase : "idle");

    for (const [id, win] of Object.entries(windows)) {
      win.root.classList.toggle("is-focus", id === activeId);
      win.root.classList.toggle("is-dim", !overview && id !== activeId);
      // Focus mode keeps dim siblings for depth; the active window stays readable and large.
      win.root.dataset.depth = overview ? "stack" : id === activeId ? "front" : "back";
    }

    const script = scriptFor(state);
    renderGuide(script.steps);
    requestAnimationFrame(() => renderDrawings(overview ? [] : script.drawings, activeId));
  }

  const onResize = () => setState(state);
  window.addEventListener("resize", onResize);
  setState(state);

  return {
    setState,
    dispose() {
      window.removeEventListener("resize", onResize);
      host.replaceChildren();
      host.classList.remove("desktop-root");
    },
  };
}
