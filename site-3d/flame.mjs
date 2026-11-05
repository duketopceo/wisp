import * as THREE from "./vendor/three.module.js";

// The Wisp flame (assets/brand/wisp-flame): one small canvas in the hero.
// Presentation only. If anything fails the caller keeps the animated WebP.
const MODEL = "assets/wisp-flame/wisp-flame.glb";
// The model's clips are idle, listening, thinking, speaking.
const CLIP = {idle: "idle", listening: "listening", thinking: "thinking",
  acting: "speaking", awaiting_choice: "listening", done: "idle", cancelled: "idle"};

export async function createFlame(host, onFailure) {
  const {GLTFLoader} = await import("./vendor/loaders/GLTFLoader.js");
  const gltf = await new GLTFLoader().loadAsync(MODEL);
  const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, powerPreference: "low-power"});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const world = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, .1, 50);
  camera.position.set(0, .45, 6.2);
  camera.lookAt(0, .45, 0);
  world.add(gltf.scene);
  const mixer = new THREE.AnimationMixer(gltf.scene);
  const actions = Object.fromEntries(gltf.animations.map(clip => [clip.name, mixer.clipAction(clip)]));
  let current;
  function play(name) {
    const next = actions[name] || actions.idle;
    if (!next || next === current) return;
    next.reset().play();
    current?.crossFadeTo(next, .35, false);
    current = next;
  }
  play("idle");
  host.append(renderer.domElement);

  const clock = new THREE.Clock();
  let frame = 0;
  let visible = false;
  let disposed = false;
  let rendered = false;

  function resize() {
    const {width, height} = host.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  function draw() {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    mixer.update(Math.min(clock.getDelta(), .1));
    try {
      if (renderer.getContext().isContextLost()) return fail();
      renderer.render(world, camera);
    } catch {
      return fail();
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
    if (active && !frame) { clock.getDelta(); frame = requestAnimationFrame(draw); }
    if (!active && frame) { cancelAnimationFrame(frame); frame = 0; }
  }
  function fail() { dispose(); onFailure(); }
  function lost(event) { event.preventDefault(); fail(); }
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    sizing.disconnect();
    document.removeEventListener("visibilitychange", reconcile);
    renderer.domElement.removeEventListener("webglcontextlost", lost);
    gltf.scene.traverse(node => {
      if (!node.isMesh) return;
      try {
        node.geometry.dispose();
        for (const material of [].concat(node.material)) material.dispose();
      } catch { /* Context loss may invalidate GPU cleanup. */ }
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
  renderer.domElement.addEventListener("webglcontextlost", lost);
  resize();
  return {setState: state => play(CLIP[state.phase]), dispose};
}
