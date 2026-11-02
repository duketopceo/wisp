import * as THREE from "./vendor/three.module.js";
import {scenarios, scriptFor} from "./model.mjs";

// A procedural explanation, not an imitation of any connected application.
// Three.js is presentation-only; the DOM desktop remains the interaction path.
export function createScene(host, story, onFailure) {
  const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, powerPreference: "low-power"});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const world = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-6, 6, 3, -3, .1, 40);
  camera.position.set(0, 1.3, 16);
  camera.lookAt(0, 0, 0);
  world.add(new THREE.AmbientLight(0xffebd2, 2));
  const light = new THREE.DirectionalLight(0xffc68c, 3);
  light.position.set(-3, 5, 8);
  world.add(light);
  const desktop = new THREE.Group();
  world.add(desktop);
  const resources = [];
  const own = resource => (resources.push(resource), resource);

  const windowIds = ["personal", "work", "pay", "media"];
  const panelMeta = {
    personal: {title: "Mail — Personal", scenario: "mail"},
    work: {title: "Tasks — Work", scenario: "work"},
    pay: {title: "Checkout — Stripe", scenario: "sensitive"},
    media: {title: "Player — Media", scenario: "media"},
  };

  function paintPanel(ctx, title, script, accent) {
    ctx.clearRect(0, 0, 960, 620);
    ctx.fillStyle = "#25211d";
    ctx.beginPath();
    ctx.roundRect(0, 0, 960, 620, 28);
    ctx.fill();
    ctx.strokeStyle = accent ? "#f5a15b" : "#615345";
    ctx.lineWidth = 3;
    ctx.stroke();
    ctx.fillStyle = "#c1b6a6";
    for (let i = 0; i < 3; i++) {
      ctx.beginPath();
      ctx.arc(34 + i * 20, 32, 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.font = "400 23px Outfit";
    ctx.fillText(title, 120, 40);
    ctx.strokeStyle = "#403a33";
    ctx.beginPath(); ctx.moveTo(0, 66); ctx.lineTo(960, 66); ctx.stroke();
    ctx.fillStyle = accent ? "#f5a15b" : "#f6eee1";
    ctx.font = "700 36px Outfit";
    ctx.fillText(script.status, 64, 120);
    const controlBoxes = {};
    script.controls.forEach((control, i) => {
      const y = 170 + i * 100;
      const active = Boolean(control.active);
      ctx.fillStyle = active ? "#3a2f24" : "#2c2823";
      ctx.beginPath();
      ctx.roundRect(64, y, 832, 84, 14);
      ctx.fill();
      if (active) {
        ctx.strokeStyle = "#f5a15b";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.fillStyle = "#c1b6a6";
      ctx.font = "400 24px Outfit";
      ctx.fillText(control.label, 92, y + 34);
      ctx.fillStyle = active || control.sensitive ? "#f5a15b" : "#f6eee1";
      ctx.font = "700 30px Outfit";
      ctx.fillText(control.value, 92, y + 68);
      controlBoxes[control.id] = {x: 64, y, w: 832, h: 84, cx: 480, cy: y + 42};
    });
    // Drawings: highlights, rings, numbered callouts, and arrows between controls.
    for (const mark of script.drawings) {
      if (mark.type === "hl" && controlBoxes[mark.target]) {
        const box = controlBoxes[mark.target];
        ctx.strokeStyle = "rgba(245,161,91,.85)";
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.roundRect(box.x - 6, box.y - 6, box.w + 12, box.h + 12, 16);
        ctx.stroke();
      } else if (mark.type === "ring" && controlBoxes[mark.target]) {
        const box = controlBoxes[mark.target];
        ctx.strokeStyle = "#f5a15b";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(box.x + box.w - 48, box.cy, 28, 0, Math.PI * 2);
        ctx.stroke();
      } else if (mark.type === "number" && controlBoxes[mark.target]) {
        const box = controlBoxes[mark.target];
        const nx = box.x - 8;
        const ny = box.y - 8;
        ctx.fillStyle = "#f5a15b";
        ctx.beginPath();
        ctx.arc(nx, ny, 18, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#131211";
        ctx.font = "700 22px Outfit";
        ctx.textAlign = "center";
        ctx.fillText(String(mark.n), nx, ny + 7);
        ctx.textAlign = "left";
        if (mark.text) {
          ctx.fillStyle = "#f6eee1";
          ctx.font = "600 22px Outfit";
          ctx.fillText(mark.text, nx + 28, ny + 7);
        }
      } else if (mark.type === "arrow") {
        const a = mark.from === "ember"
          ? {cx: 880, cy: 560}
          : controlBoxes[mark.from];
        const b = controlBoxes[mark.to];
        if (!a || !b) continue;
        ctx.strokeStyle = "#f5a15b";
        ctx.fillStyle = "#f5a15b";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(a.cx, a.cy);
        ctx.quadraticCurveTo((a.cx + b.cx) / 2, Math.min(a.cy, b.cy) - 40, b.cx, b.cy);
        ctx.stroke();
        const angle = Math.atan2(b.cy - (Math.min(a.cy, b.cy) - 40), b.cx - (a.cx + b.cx) / 2);
        ctx.beginPath();
        ctx.moveTo(b.cx, b.cy);
        ctx.lineTo(b.cx - 14 * Math.cos(angle - .4), b.cy - 14 * Math.sin(angle - .4));
        ctx.lineTo(b.cx - 14 * Math.cos(angle + .4), b.cy - 14 * Math.sin(angle + .4));
        ctx.closePath();
        ctx.fill();
      }
    }
    return controlBoxes;
  }

  function panel(id) {
    const canvas = document.createElement("canvas");
    canvas.width = 960;
    canvas.height = 620;
    const ctx = canvas.getContext("2d");
    const texture = own(new THREE.CanvasTexture(canvas));
    texture.colorSpace = THREE.SRGBColorSpace;
    const material = own(new THREE.MeshBasicMaterial({map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide}));
    const mesh = new THREE.Mesh(own(new THREE.PlaneGeometry(5.2, 3.36)), material);
    mesh.userData = {id, canvas, ctx, texture};
    desktop.add(mesh);
    return mesh;
  }

  const panels = windowIds.map(panel);
  const ember = new THREE.Group();
  desktop.add(ember);
  const material = own(new THREE.MeshStandardMaterial({color: 0xf5a15b, roughness: .45, metalness: .05}));
  const geometry = own(new THREE.SphereGeometry(.35, 32, 24));
  const vertices = geometry.attributes.position;
  for (let i = 0; i < vertices.count; i++) {
    const y = vertices.getY(i);
    const top = Math.max(0, y / .35);
    vertices.setXYZ(i, vertices.getX(i) * (1 - top * .6) + top ** 3 * .18,
      y + top ** 3 * .35, vertices.getZ(i) * (1 - top * .5));
  }
  geometry.computeVertexNormals();
  ember.add(new THREE.Mesh(geometry, material));
  const ring = new THREE.Mesh(own(new THREE.TorusGeometry(.55, .012, 8, 64)),
    own(new THREE.MeshBasicMaterial({color: 0xf5a15b})));
  ember.add(ring);
  host.append(renderer.domElement);
  let state = {phase: "idle", scenario: "mail"};
  let frame = 0;
  let visible = false;
  let disposed = false;
  let rendered = false;
  let pointerX = 0;
  let pointerY = 0;
  const target = new THREE.Vector3();

  function refreshTextures() {
    panels.forEach(mesh => {
      const id = mesh.userData.id;
      const meta = panelMeta[id];
      const localState = {
        phase: state.scenario === meta.scenario ? state.phase : "idle",
        scenario: meta.scenario,
      };
      const script = scriptFor(localState);
      const accent = id === "pay" || (state.phase !== "idle" && scenarios[state.scenario].window === id);
      paintPanel(mesh.userData.ctx, meta.title, script, accent);
      mesh.userData.texture.needsUpdate = true;
    });
  }

  function resize() {
    const {width, height} = host.getBoundingClientRect();
    renderer.setSize(width, height, false);
    const halfWidth = width < 600 ? 3.3 : 6.2;
    camera.left = -halfWidth; camera.right = halfWidth;
    camera.top = halfWidth * height / width;
    camera.bottom = -camera.top;
    camera.updateProjectionMatrix();
  }
  function draw(time) {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    const rect = story.getBoundingClientRect();
    const progress = THREE.MathUtils.clamp((innerHeight * .55 - rect.top) /
      Math.max(1, rect.height - innerHeight * .2), 0, 1);
    // A stacked desktop opens into depth-separated windows, then settles.
    const unfold = Math.sin(progress * Math.PI);
    desktop.rotation.set(-.09 + unfold * .12 + pointerY * .035, -.12 + progress * .24 + pointerX * .045, -.025);
    const activeId = scenarios[state.scenario].window;
    const activeIndex = windowIds.indexOf(activeId);
    const visiblePanels = state.scenario === "media" ? [3, 1, 2] : [0, 1, 2];
    const others = visiblePanels.filter(i => i !== activeIndex);
    panels.forEach((mesh, i) => {
      mesh.visible = visiblePanels.includes(i);
      if (!mesh.visible) return;
      const selected = i === activeIndex;
      const side = selected ? 0 : others.indexOf(i) === 0 ? -1 : 1;
      mesh.position.set(side * (1.5 + unfold * 1.25),
        selected ? .15 + unfold * .25 : -.15 - unfold * .2,
        selected ? 1.1 : -.2 - unfold * 1.1);
      mesh.rotation.y = -side * (.11 + unfold * .16);
      mesh.scale.setScalar(selected ? 1.08 : .83);
      mesh.renderOrder = selected ? 3 : i;
      mesh.material.opacity = state.phase === "idle" || selected ? 1 : .48;
    });
    target.copy(panels[activeIndex].position);
    target.x += 1.25;
    target.y -= .7;
    target.z = 3.1;
    if (state.phase === "idle") target.set(2.6, -.7, 3.2);
    ember.position.lerp(target, .07);
    ember.position.y += Math.sin(time * .0018) * .002;
    const breath = 1 + Math.sin(time * .003) * (state.phase === "listening" ? .13 : .035);
    ember.scale.setScalar(breath);
    ring.visible = state.phase === "awaiting_choice";
    ring.rotation.z = time * .0004;
    try {
      if (renderer.getContext().isContextLost()) {
        fail();
        return;
      }
      renderer.render(world, camera);
    } catch {
      fail();
      return;
    }
    if (!rendered) {
      host.dataset.rendered = "true";
      rendered = true;
    }
    frame = requestAnimationFrame(draw);
  }
  function reconcile() {
    if (disposed) return;
    const active = visible && !document.hidden;
    host.dataset.rendering = active ? "running" : "paused";
    if (active && !frame) frame = requestAnimationFrame(draw);
    if (!active && frame) { cancelAnimationFrame(frame); frame = 0; }
  }
  function pointer(event) {
    const r = host.getBoundingClientRect();
    pointerX = (event.clientX - r.left) / r.width - .5;
    pointerY = (event.clientY - r.top) / r.height - .5;
  }
  function leave() { pointerX = pointerY = 0; }
  function fail() { dispose(); onFailure(); }
  function lost(event) { event.preventDefault(); fail(); }
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    sizing.disconnect();
    document.removeEventListener("visibilitychange", reconcile);
    host.removeEventListener("pointermove", pointer);
    host.removeEventListener("pointerleave", leave);
    renderer.domElement.removeEventListener("webglcontextlost", lost);
    resources.forEach(resource => {
      try { resource.dispose(); } catch { /* Context loss may invalidate GPU cleanup. */ }
    });
    try { renderer.dispose(); } catch { /* The static fallback must still be reachable. */ }
    renderer.domElement.remove();
    host.dataset.rendering = "paused";
  }
  const observer = new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting;
    reconcile();
  }, {threshold: 0});
  const sizing = new ResizeObserver(resize);
  sizing.observe(host);
  observer.observe(host);
  document.addEventListener("visibilitychange", reconcile);
  host.addEventListener("pointermove", pointer, {passive: true});
  host.addEventListener("pointerleave", leave);
  renderer.domElement.addEventListener("webglcontextlost", lost);
  refreshTextures();
  resize();
  return {
    setState(next) {
      state = next;
      refreshTextures();
    },
    dispose,
  };
}
