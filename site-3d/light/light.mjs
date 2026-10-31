/* Wisp light preview: wires the pure motion sim and the plain WebGL view to the page.
   The light's look follows ThreeUI Community "energy-orb" (MIT, Copyright (c) 2026 Meng To,
   https://github.com/MengTo/threeui) as a design reference; shader rewritten in ../wisp/gl.mjs.
   See ../vendor/THREEUI-LICENSE.txt and ../../THIRD_PARTY_NOTICES.md.

   Cost rules: section geometry is measured on load, resize and font load only; the animation
   loop reads scrollY and nothing else from layout; it runs only while the light moves, draws at
   most about 30 times a second, and sleeps at rest and while hidden. Breathing is pure CSS. */
import {createSim} from "../wisp/sim.mjs";
import {createGlView} from "../wisp/gl.mjs";

const host = document.getElementById("light");
const canvas = document.getElementById("gl");
const stops = [...document.querySelectorAll("[data-stop]")];
const marks = stops.map(s => s.querySelector(".mark"));
const reducedQuery = matchMedia("(prefers-reduced-motion: reduce)");

const DRAW_GAP_MS = 33;        // time gate: about 30 draws a second at any display rate
const MARGIN = 24;             // keep the light this far inside the viewport
const TIERS = [["high", 1], ["mid", 0.75], ["low", 0.5]];
const SLOW_MS = 42;            // rAF interval EMA above this (about 24 fps) counts as a breach
const BREACH_FRAMES = 30;      // a breach must last this many awake frames
const SETTLE_SKIP = 8;         // frames ignored after wake, resume, resize or a tier change

let geo = {mx: [], my: [], mid: [], vw: innerWidth, vh: innerHeight, size: 400};
let sim = null, view = null, mode = "init";          // "init", "gl" or "css"
let raf = 0, awake = false, hidden = document.visibilityState === "hidden", offscreen = false;
let lastMs = 0, lastDraw = -1e9, tier = 0, ema = 0, slow = 0, skip = SETTLE_SKIP, lastTransform = "";
let activeIndex = 0;

// --- geometry: measured on load, resize and font load, never per frame ---
function measure() {
  const sx = scrollX, sy = scrollY;
  geo = {
    mx: marks.map(m => m.getBoundingClientRect().left + sx + 0.5),
    my: marks.map(m => m.getBoundingClientRect().top + sy + 0.5),
    mid: stops.map(s => { const r = s.getBoundingClientRect(); return r.top + sy + r.height / 2; }),
    vw: innerWidth, vh: innerHeight, size: host.clientWidth || 400,
  };
}

function nearestStop(docY) {                         // binary search on the cached, ascending midpoints
  let lo = 0, hi = geo.mid.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (geo.mid[m] < docY) lo = m + 1; else hi = m; }
  return lo > 0 && docY - geo.mid[lo - 1] < geo.mid[lo] - docY ? lo - 1 : lo;
}

const clampX = x => Math.min(Math.max(x, MARGIN), geo.vw - MARGIN);
const clampY = y => Math.min(Math.max(y, MARGIN), geo.vh - MARGIN);

function liveTarget() {                              // reads scrollY only
  const sy = scrollY;
  activeIndex = nearestStop(sy + geo.vh / 2);
  return [clampX(geo.mx[activeIndex]), clampY(geo.my[activeIndex] - sy)];
}

function stopTarget(i) {                             // where the mark sits when its stop is centred
  return [clampX(geo.mx[i]), clampY(geo.my[i] - (geo.mid[i] - geo.vh / 2))];
}

function place(x, y) {
  const d = devicePixelRatio || 1;
  const t = `translate3d(${(Math.round(x * d) / d).toFixed(3)}px,${(Math.round(y * d) / d).toFixed(3)}px,0)`;
  if (t !== lastTransform) { host.style.transform = t; lastTransform = t; }
}

// --- CSS orb: the one fallback; no per-frame script, drift is a CSS transition ---
let cssStop = -1;
function placeCss() {
  const i = nearestStop(scrollY + geo.vh / 2);
  if (i === cssStop) return;                          // scrolling within one stop moves nothing
  cssStop = i;
  const [x, y] = stopTarget(i);
  place(x, y);
}

function toCss(reason) {
  if (mode === "css") return;
  const keep = lastTransform;
  stopLoop();
  mode = "css";
  view?.dispose(); view = null; sim = null;
  canvas.remove();
  host.dataset.renderer = "static";
  host.dataset.rendering = "paused";
  host.dataset.tier = "css";
  host.dataset.reason = reason;
  host.style.transform = keep;                        // hand-off keeps the head where it was
  cssStop = keep ? nearestStop(scrollY + geo.vh / 2) : -1;   // stay put until the active stop changes
  placeCss();
  host.dataset.rendered = "true";
}

// --- the loop: awake only while the light moves ---
function stopLoop() {
  if (raf) cancelAnimationFrame(raf);
  raf = 0; awake = false;
  if (host.dataset.renderer === "webgl") host.dataset.rendering = "paused";
}

function wake() {
  if (mode !== "gl" || awake || hidden) return;
  awake = true; skip = SETTLE_SKIP; lastMs = 0;
  host.dataset.rendering = "running";
  raf = requestAnimationFrame(tick);
}

function budget(dt) {
  if (skip > 0) { skip--; return; }
  ema += (dt - ema) * 0.1;
  slow = ema > SLOW_MS ? slow + 1 : 0;
  if (slow < BREACH_FRAMES) return;
  slow = 0; ema = 0; skip = SETTLE_SKIP;
  if (tier < TIERS.length - 1) {                      // step resolution down, never up
    tier++;
    host.dataset.tier = TIERS[tier][0];
    view.resize(geo.size, devicePixelRatio, TIERS[tier][1]);
  } else toCss("budget");
}

function tick(ms) {
  raf = 0;
  if (mode !== "gl" || hidden) { awake = false; return; }
  try {
    const first = lastMs === 0;
    const dt = first ? 1 / 60 : (ms - lastMs) / 1000;
    if (!first) budget(ms - lastMs);
    lastMs = ms;
    if (mode !== "gl") return;
    const [tx, ty] = liveTarget();
    sim.setTarget(tx, ty);
    const s = sim.step(dt);
    place(s.x, s.y);
    const rest = sim.settled;
    // An off-screen light still moves (a resize can put it there and it must come back) but is not drawn.
    if (!offscreen && (rest || ms - lastDraw >= DRAW_GAP_MS)) { view.draw(s, ms / 1000); lastDraw = ms; }
    if (rest) { awake = false; host.dataset.rendering = "paused"; return; }   // final frame drawn, sleep
    raf = requestAnimationFrame(tick);
  } catch { toCss("draw-failed"); }
}

// --- wiring ---
function refresh() {
  measure();
  if (mode === "css") { cssStop = -1; placeCss(); return; }
  if (view) view.resize(geo.size, devicePixelRatio, TIERS[tier][1]);
  skip = SETTLE_SKIP;
  wake();
}

function onVisibility() {
  hidden = document.visibilityState === "hidden";
  host.dataset.breath = hidden || offscreen ? "paused" : "running";
  if (hidden) stopLoop(); else wake();
}

function start() {
  measure();
  if (reducedQuery.matches) { toCss("reduced-motion"); return; }
  view = createGlView(canvas, {onLost: () => toCss("context-lost")});
  if (!view) { toCss("no-webgl"); return; }
  const [x, y] = liveTarget();
  sim = createSim({x, y});
  mode = "gl";
  place(x, y);
  try {
    view.resize(geo.size, devicePixelRatio, TIERS[0][1]);
    view.draw(sim.state, 0);
  } catch { toCss("draw-failed"); return; }
  host.dataset.renderer = "webgl";
  host.dataset.rendering = "paused";
  host.dataset.tier = TIERS[0][0];
  host.dataset.rendered = "true";
}

start();
addEventListener("scroll", () => { if (mode === "gl") wake(); else placeCss(); }, {passive: true});
addEventListener("resize", refresh);
addEventListener("orientationchange", refresh);
document.addEventListener("visibilitychange", onVisibility);
document.fonts?.ready.then(refresh);
if (typeof ResizeObserver === "function") new ResizeObserver(refresh).observe(document.body);
if (typeof IntersectionObserver === "function") {
  new IntersectionObserver(entries => {
    offscreen = !entries[entries.length - 1].isIntersecting;
    host.dataset.breath = hidden || offscreen ? "paused" : "running";
    if (!offscreen) wake();                             // redraws the resting frame it skipped
  }).observe(host);
}
reducedQuery.addEventListener?.("change", () => { if (reducedQuery.matches) toCss("reduced-motion"); });
