import * as THREE from "./vendor/three.module.js";

// A procedural explanation, not an imitation of any connected application.
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

  function panel(title, label, lines, accent = false) {
    const canvas = document.createElement("canvas");
    canvas.width = 960;
    canvas.height = 620;
    const ctx = canvas.getContext("2d");
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
    ctx.font = "700 52px Outfit";
    ctx.fillText(label, 64, 170);
    ctx.font = "400 42px Outfit";
    ctx.fillStyle = "#c1b6a6";
    lines.forEach((line, i) => ctx.fillText(line, 64, 244 + i * 60));
    ctx.fillStyle = accent ? "#f5a15b" : "#403a33";
    ctx.beginPath(); ctx.roundRect(64, 456, 460, 72, 12); ctx.fill();
    ctx.fillStyle = accent ? "#131211" : "#f6eee1";
    ctx.font = "700 38px Outfit";
    ctx.fillText(accent ? "Your confirmation" : "A little more reach", 88, 502);
    const texture = own(new THREE.CanvasTexture(canvas));
    texture.colorSpace = THREE.SRGBColorSpace;
    const material = own(new THREE.MeshBasicMaterial({map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide}));
    const mesh = new THREE.Mesh(own(new THREE.PlaneGeometry(5.2, 3.36)), material);
    desktop.add(mesh);
    return mesh;
  }

  const personal = panel("Personal browser", "A task, in context.", ["Read the active window.", "Find the right browser.", "Show the next step."]);
  const work = panel("Work browser", "Keep work in its place.", ["Use the right profile.", "Switch to the right tab.", "Keep the feedback visible."]);
  const confirm = panel("Sensitive action", "Pause before the change.", ["Read and inspect.", "Review the proposed action.", "Confirm before it proceeds."], true);
  const media = panel("Media player", "Toggle playback.", ["Send the playback toggle.", "Then inspect the player.", "Do not assume paused."]);
  const panels = [personal, work, confirm, media];
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
    // A stacked desktop opens into three depth-separated windows, then settles.
    const unfold = Math.sin(progress * Math.PI);
    desktop.rotation.set(-.09 + unfold * .12 + pointerY * .035, -.12 + progress * .24 + pointerX * .045, -.025);
    const activeIndex = {mail: 0, work: 1, sensitive: 2, media: 3}[state.scenario];
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
      mesh.scale.setScalar(selected ? 1 : .83);
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
  resize();
  return {setState(next) { state = next; }, dispose};
}
