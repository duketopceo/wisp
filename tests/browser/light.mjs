// Browser gates for the /light/ preview: "no flicker" as measurements, not adjectives.
// Chromium: forced software GL (SwiftShader), CPU throttle, synthetic 120 Hz rAF, stability readback.
// WebKit: structure, fallbacks and error checks only. Instrumentation is injected with
// addInitScript and never ships. Timing passes never call readPixels or gl.finish.
import assert from "node:assert/strict";
import {mkdir, readFile, writeFile} from "node:fs/promises";
import {chromium, webkit} from "playwright";

const base = new URL("light/", process.env.WISP_SITE_URL || "http://127.0.0.1:3000/");
const engines = (process.env.WISP_BROWSERS || "chromium").split(",");
const output = process.env.WISP_QA_OUTPUT || "../../build/browser-qa";
const budget = JSON.parse(await readFile(new URL("./light-budget.json", import.meta.url), "utf8"));
await mkdir(output, {recursive: true});

// Hard ceilings from the plan (KTD6). light-budget.json may only tighten them.
const CEIL = {maxDrawsPerSecond: 31, p95DrawIntervalMs: 50, fractionDrawIntervalsOver50ms: 0.05,
  maxBlankFrames: 0, overshootDevicePx: 0.5, premultipliedViolations: 0, borderAlphaMax: 1, glowRiseMax: 2,
  restAnimationFrames: 0, restDraws: 0, maxStepDowns: 2, restPositionTolerancePx: 2};
const B = {...budget.ceilings, ...budget.bounds};
assert.deepEqual(budget.ceilings, CEIL, "light-budget.json ceilings must equal the plan ceilings");
for (const [k, v] of Object.entries(CEIL)) assert.ok(B[k] <= v, `light-budget.json loosens ${k}: ${B[k]} > ${v}`);

const metrics = {};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const quantile = (xs, q) => { const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(q * s.length))]; };

// ---- page-side instrumentation (injected, never shipped) ----
function instrument(o) {
  const t = window.__t = {draws: [], raf: 0, stab: [], lastRay: null, tf: [], states: [], read: !!o.read};
  const raf0 = window.requestAnimationFrame.bind(window);
  t.raf0 = raf0;
  if (o.hz) {                                   // synthetic display rate, delivered from a timer
    let q = [], id = 0;
    window.requestAnimationFrame = cb => { q.push([++id, cb]); return id; };
    window.cancelAnimationFrame = i => { q = q.filter(e => e[0] !== i); };
    setInterval(() => { const run = q; q = []; const now = performance.now(); for (const [, cb] of run) { t.raf++; cb(now); } }, 1000 / o.hz);
  } else {
    window.requestAnimationFrame = cb => raf0(ts => { t.raf++; cb(ts); });
  }
  const orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, args) {
    if (o.noWebgl && String(type).startsWith("webgl")) return null;
    if (o.caveat && String(type).startsWith("webgl") && args?.failIfMajorPerformanceCaveat) return null;
    if (o.forceGl && args && "failIfMajorPerformanceCaveat" in args) args = {...args, failIfMajorPerformanceCaveat: false};
    return orig.call(this, type, args);
  };
  const proto = window.WebGLRenderingContext?.prototype;
  if (proto) {
    const draw = proto.drawArrays;
    proto.drawArrays = function (...a) {
      if (o.failDraw) { window.__drawFailed = true; throw new Error("Injected renderer failure"); }
      draw.apply(this, a);
      t.draws.push(performance.now());
      if (t.read) {
        const w = this.drawingBufferWidth, h = this.drawingBufferHeight, buf = new Uint8Array(w * h * 4);
        this.readPixels(0, 0, w, h, this.RGBA, this.UNSIGNED_BYTE, buf);
        let viol = 0, border = 0;
        for (let i = 0; i < buf.length; i += 4) {
          const a = buf[i + 3];
          if (buf[i] > a + 1 || buf[i + 1] > a + 1 || buf[i + 2] > a + 1) viol++;
        }
        for (let x = 0; x < w; x++) for (const y of [0, h - 1]) border = Math.max(border, buf[(y * w + x) * 4 + 3]);
        for (let y = 0; y < h; y++) for (const x of [0, w - 1]) border = Math.max(border, buf[(y * w + x) * 4 + 3]);
        const cy = h >> 1, ray = [];
        for (let x = w >> 1; x < w; x++) { const i = (cy * w + x) * 4; ray.push(0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2]); }
        t.lastRay = {side: w, ray};
        t.premult = this.getContextAttributes().premultipliedAlpha;
        t.stab.push({t: performance.now(), center: buf[((cy * w) + (w >> 1)) * 4 + 3], viol, border});
      }
    };
  }
  addEventListener("DOMContentLoaded", () => {
    const host = document.getElementById("light");
    if (!host) return;
    const note = () => t.states.push({t: performance.now(), r: host.dataset.renderer, tier: host.dataset.tier,
      rendering: host.dataset.rendering, canvas: host.querySelector("canvas") !== null});
    new MutationObserver(note).observe(host, {attributes: true});
    note();
    setInterval(() => t.tf.push({t: performance.now(), v: host.style.transform}), 16);
  });
}
const px = v => { const m = /translate3d\(([-\d.]+)px,\s*([-\d.]+)px/.exec(v || ""); return m ? [+m[1], +m[2]] : null; };

async function launch(name, extra = {}) {
  if (name === "webkit") return webkit.launch({headless: true, ...(process.env.WISP_WEBKIT_PATH ? {executablePath: process.env.WISP_WEBKIT_PATH} : {})});
  return chromium.launch({headless: true, args: ["--enable-unsafe-swiftshader"],
    ...(process.env.WISP_CHROMIUM_PATH ? {executablePath: process.env.WISP_CHROMIUM_PATH} : {channel: "chromium"}), ...extra});
}

async function open(browser, o = {}) {
  const context = await browser.newContext({viewport: o.viewport || {width: 1440, height: 900},
    javaScriptEnabled: o.js !== false, reducedMotion: o.reduced ? "reduce" : "no-preference"});
  const page = await context.newPage();
  const seen = {errors: [], external: [], csp: []};
  page.on("pageerror", e => seen.errors.push(e.stack || e.message));
  page.on("console", m => { if (/Content Security Policy/i.test(m.text())) seen.csp.push(m.text()); });
  page.on("request", r => { if (new URL(r.url()).origin !== base.origin) seen.external.push(r.url()); });
  if (o.js !== false) await page.addInitScript(instrument, o);
  if (o.blockModule) await context.route("**/light.mjs", r => r.abort());
  let cdp = null;
  if (o.throttle && o.engine === "chromium") {
    cdp = await context.newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", {rate: o.throttle});
  }
  await page.goto(base.href, {waitUntil: "networkidle"});
  return {context, page, seen, cdp};
}

const host = page => page.locator("#light");
const attr = (page, n) => page.evaluate(k => document.getElementById("light").dataset[k], n);
const waitFor = (page, expr, arg, timeout = 20000) => page.waitForFunction(expr, arg, {timeout});
const asleep = page => waitFor(page, () => document.getElementById("light").dataset.rendering === "paused");
const noOffsets = seen => { assert.deepEqual(seen.errors, []); assert.deepEqual(seen.external, []); assert.deepEqual(seen.csp, []); };
const fit = async page => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

async function drift(page, from, to, ms) {
  return page.evaluate(([a, b, d]) => new Promise(res => {
    const t0 = performance.now(), raf = window.__t.raf0;
    const t = window.__t, start = performance.now();
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / d);
      scrollTo({top: a + (b - a) * k, behavior: "instant"});
      if (k < 1) raf(step); else res([start, performance.now()]);
    };
    raf(step);
  }), [from, to, ms]);
}

// ---- gates ----
async function budgetGate(label, o, engine) {
  const {context, page, seen} = await open(engine, {...o, engine: "chromium"});
  try {
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "webgl");
    await asleep(page);
    const [t0, t1] = await drift(page, 0, 1700, 3000);
    await page.evaluate(() => window.__t.drawsMarker = window.__t.draws.length);
    const driftDraws = await page.evaluate(([a, b]) => window.__t.draws.filter(x => x >= a && x <= b), [t0, t1]);
    assert.ok(driftDraws.length > 10, `${label}: light must actually draw while moving (${driftDraws.length})`);
    const iv = driftDraws.slice(1).map((x, i) => x - driftDraws[i]);
    let worst = 0;
    for (let i = 0, j = 0; i < driftDraws.length; i++) {
      while (driftDraws[i] - driftDraws[j] > 1000) j++;
      worst = Math.max(worst, i - j + 1);
    }
    const p95 = quantile(iv, 0.95), over = iv.filter(x => x > 50).length / iv.length;
    metrics[label] = {draws: driftDraws.length, maxPerSecond: worst, p95IntervalMs: +p95.toFixed(1),
      fractionOver50ms: +over.toFixed(3), medianIntervalMs: +quantile(iv, 0.5).toFixed(1)};
    assert.ok(worst <= B.maxDrawsPerSecond, `${label}: ${worst} draws in one second`);
    assert.ok(p95 <= B.p95DrawIntervalMs, `${label}: p95 draw interval ${p95}`);
    assert.ok(over <= B.fractionDrawIntervalsOver50ms, `${label}: ${over} of draw intervals over 50 ms`);
    // rest: after settling, zero animation frames, zero draws and an identical host transform
    await asleep(page);
    await sleep(300);
    const before = await page.evaluate(() => ({raf: window.__t.raf, draws: window.__t.draws.length, n: window.__t.tf.length}));
    await sleep(2000);
    const after = await page.evaluate(() => ({raf: window.__t.raf, draws: window.__t.draws.length,
      tf: window.__t.tf.slice(-125).map(s => s.v)}));
    assert.equal(after.raf - before.raf, B.restAnimationFrames, `${label}: animation frames at rest`);
    assert.equal(after.draws - before.draws, B.restDraws, `${label}: draws at rest`);
    assert.equal(new Set(after.tf).size, 1, `${label}: host transform changed at rest`);
    metrics[label].restFrames = after.raf - before.raf;
    // degradation: monotone step-downs, at most two, one final hand-off with no empty frame
    const states = await page.evaluate(() => window.__t.states);
    const tiers = states.map(s => s.tier).filter(Boolean);
    const order = ["high", "mid", "low", "css"];
    const idx = tiers.map(v => order.indexOf(v));
    assert.deepEqual(idx, [...idx].sort((a, b) => a - b), `${label}: tiers must only step down: ${tiers}`);
    const steps = new Set(tiers.filter(v => v !== "css")).size - 1;
    assert.ok(steps <= B.maxStepDowns, `${label}: ${steps} step-downs`);
    const toCssCount = tiers.filter((v, i) => v === "css" && tiers[i - 1] !== "css").length;
    assert.ok(toCssCount <= 1, `${label}: hand-off must happen once`);
    for (const s of states) assert.ok((s.r === "webgl" && s.canvas) || s.r === "static", `${label}: state with neither canvas nor orb ${JSON.stringify(s)}`);
    metrics[label].tiers = [...new Set(tiers)];
    noOffsets(seen);
    return {finalRenderer: await attr(page, "renderer"), finalTier: await attr(page, "tier")};
  } finally { await context.close(); }
}

async function stabilityGate(engine, label, viewport) {
  const {context, page, seen} = await open(engine, {viewport, read: true, forceGl: true, engine: "chromium"});
  try {
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "webgl");
    await asleep(page);
    await page.evaluate(() => { window.__t.stab.length = 0; });
    const half = drift(page, 0, 1700, 1500);
    await sleep(700);
    await page.setViewportSize({width: 1100, height: 800});     // resize mid-motion
    await half;
    await page.setViewportSize(viewport);
    const [, end] = await drift(page, 1700, 2600, 1500);
    await asleep(page);
    await sleep(300);
    const r = await page.evaluate(([e]) => {
      const t = window.__t;
      return {stab: t.stab, tf: t.tf.filter(s => s.t >= e), last: t.lastRay, dpr: devicePixelRatio};
    }, [end]);
    const frames = r.stab;
    assert.ok(frames.length > 10, `${label}: sampled frames ${frames.length}`);
    const blank = frames.filter(f => f.center < 128).length;
    const viol = frames.reduce((s, f) => s + f.viol, 0);
    const border = Math.max(...frames.map(f => f.border));
    assert.ok(blank <= B.maxBlankFrames, `${label}: ${blank} blank frames`);
    assert.ok(viol <= B.premultipliedViolations, `${label}: ${viol} premultiplied violations`);
    assert.ok(border <= B.borderAlphaMax, `${label}: border alpha ${border}`);
    // The readback cannot tell a non-premultiplied canvas from a premultiplied one, so pin the attribute.
    assert.equal(await page.evaluate(() => window.__t.premult), true, `${label}: context must be premultiplied`);
    // after the scripted scroll ends: no overshoot past the rest point, no reversal toward it
    const pts = r.tf.map(s => px(s.v)).filter(Boolean);
    const fin = pts[pts.length - 1];
    const d = pts.map(p => Math.hypot(p[0] - fin[0], p[1] - fin[1]));
    let rise = 0;
    for (let i = 1; i < d.length; i++) rise = Math.max(rise, d[i] - d[i - 1]);
    const over = Math.max(0, ...pts.map(p => {
      const dir = [fin[0] - pts[0][0], fin[1] - pts[0][1]], len = Math.hypot(...dir) || 1;
      return ((p[0] - fin[0]) * dir[0] + (p[1] - fin[1]) * dir[1]) / len;
    }));
    assert.ok(over * r.dpr <= B.overshootDevicePx, `${label}: overshoot ${over} css px`);
    assert.ok(rise * r.dpr <= B.overshootDevicePx, `${label}: reversed toward the rest point by ${rise}`);
    // glow profile on the rest frame: non-increasing outward beyond the core, within 2/255
    const {side, ray} = r.last;
    const core = 0.075 * side + 3;
    let up = 0;
    for (let i = Math.ceil(core) + 1; i < ray.length; i++) up = Math.max(up, ray[i] - ray[i - 1]);
    assert.ok(up <= B.glowRiseMax, `${label}: glow rises outward by ${up}/255`);
    metrics[label] = {frames: frames.length, blank, premultViolations: viol, borderAlpha: border,
      overshootCssPx: +over.toFixed(3), reversalCssPx: +rise.toFixed(3), glowRise: +up.toFixed(2)};
    noOffsets(seen);
  } finally { await context.close(); }
}

async function stopsGate(engine, label, viewport) {
  const {context, page, seen} = await open(engine, {viewport, forceGl: true, engine: "chromium"});
  try {
    await waitFor(page, () => ["webgl", "static"].includes(document.getElementById("light").dataset.renderer));
    await fit(page);
    const n = await page.locator("[data-stop]").count();
    assert.equal(n, 7);   // hero, stops 01 to 05, install block
    for (let i = 0; i < n; i++) {
      await page.evaluate(k => {
        const s = document.querySelectorAll("[data-stop]")[k];
        const r = s.getBoundingClientRect();
        scrollTo({top: scrollY + r.top + r.height / 2 - innerHeight / 2, behavior: "instant"});
      }, i);
      if ((await attr(page, "renderer")) === "webgl") { await sleep(100); await asleep(page); }
      else await sleep(1200);
      await sleep(250);
      const r = await page.evaluate(k => {
        const h = document.getElementById("light"), hr = h.getBoundingClientRect();
        const cx = hr.left + hr.width / 2, cy = hr.top + hr.height / 2, S = hr.width;
        const m = document.querySelectorAll("[data-stop] .mark")[k].getBoundingClientRect();
        const clamp = (v, hi) => Math.min(Math.max(v, 24), hi - 24);
        const want = [clamp(m.left + .5, innerWidth), clamp(m.top + .5, innerHeight)];
        const radius = 0.145 * S;                                  // core plus the visible glow disc
        let gap = Infinity;
        for (const e of document.querySelectorAll("[data-stop] > div > *")) {
          const q = e.getBoundingClientRect();
          if (q.width === 0 || q.bottom < 0 || q.top > innerHeight) continue;
          const dx = Math.max(q.left - cx, 0, cx - q.right), dy = Math.max(q.top - cy, 0, cy - q.bottom);
          gap = Math.min(gap, Math.hypot(dx, dy) - radius);
        }
        return {err: Math.hypot(cx - want[0], cy - want[1]), gap, S};
      }, i);
      assert.ok(r.err <= B.restPositionTolerancePx, `${label} stop ${i}: rests ${r.err.toFixed(2)} px from its mark`);
      assert.ok(r.gap >= 0, `${label} stop ${i}: light overlaps text by ${(-r.gap).toFixed(1)} px`);
      await page.screenshot({path: `${output}/light-${label}-stop${i}.png`});
    }
    await page.setViewportSize({width: viewport.width === 1440 ? 390 : 1440, height: 844});   // reflow moves marks
    await sleep(300);
    if ((await attr(page, "renderer")) === "webgl") await asleep(page);
    await sleep(1200);
    const ok = await page.evaluate(() => {
      const h = document.getElementById("light").getBoundingClientRect();
      return h.left + h.width / 2 >= 0 && h.left + h.width / 2 <= innerWidth;
    });
    assert.equal(ok, true);
    noOffsets(seen);
  } finally { await context.close(); }
}

async function hiddenGate(engine) {
  const {context, page, seen} = await open(engine, {forceGl: true, engine: "chromium"});
  try {
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "webgl");
    await asleep(page);
    const flip = v => page.evaluate(h => {
      Object.defineProperty(document, "visibilityState", {configurable: true, get: () => h ? "hidden" : "visible"});
      document.dispatchEvent(new Event("visibilitychange"));
    }, v);
    await flip(true);
    const n = await page.evaluate(() => window.__t.draws.length);
    await drift(page, 0, 900, 800);
    await sleep(500);
    assert.equal(await page.evaluate(() => window.__t.draws.length), n, "hidden tab must not draw");
    assert.equal(await attr(page, "breath"), "paused");
    await flip(false);
    await waitFor(page, () => window.__t.draws.length > 0 && document.getElementById("light").dataset.rendering === "paused");
    assert.ok((await page.evaluate(() => window.__t.draws.length)) > n, "visible again must resume and settle");
    assert.equal(await attr(page, "breath"), "running");
    noOffsets(seen);
  } finally { await context.close(); }
}

async function fallbackGate(name, engine) {
  const modes = {
    "no-js": {js: false}, "no-webgl": {noWebgl: true}, "caveat": {caveat: true},
    "draw-failed": {failDraw: true}, "reduced": {reduced: true}, "module-failed": {blockModule: true},
    "context-lost": {forceGl: true},
  };
  for (const [mode, o] of Object.entries(modes)) {
    const {context, page, seen} = await open(engine, {...o, viewport: {width: 390, height: 844}, engine: name});
    try {
      if (mode === "no-js" || mode === "module-failed") await sleep(300);
      else if (mode === "context-lost") {
        if ((await attr(page, "renderer")) === "webgl") {
          const lost = await page.locator("#gl").evaluate(c => {
            const x = c.getContext("webgl").getExtension("WEBGL_lose_context");
            if (x) x.loseContext();
            return !!x;
          });
          if (!lost && name === "chromium") throw new Error("No context-loss extension available");
          if (!lost) continue;                 // this engine cannot simulate loss; nothing to assert
        }
      }
      await waitFor(page, () => document.getElementById("light").dataset.renderer === "static" || document.getElementById("light").dataset.renderer === "webgl");
      if (mode !== "context-lost" || (await attr(page, "renderer")) !== "static") {
        if (mode === "context-lost") await waitFor(page, () => document.getElementById("light").dataset.renderer === "static");
      }
      if (mode !== "no-js" && mode !== "module-failed") assert.equal(await attr(page, "renderer"), "static", mode);
      assert.equal(await page.locator("#gl:visible").count(), 0, `${mode}: no canvas shown`);
      assert.equal(await page.locator("#light .orb").isVisible(), true, `${mode}: CSS orb visible`);
      const box = await page.locator("#light .orb").boundingBox();
      assert.ok(box && box.width > 20, `${mode}: orb has a size`);
      if (mode === "draw-failed" && name === "chromium") assert.equal(await page.evaluate(() => window.__drawFailed), true);
      await page.locator("#install").scrollIntoViewIfNeeded();
      assert.equal(await page.locator(".term").isVisible(), true, `${mode}: install block readable`);
      if (mode === "reduced") {
        const tr = await page.evaluate(() => getComputedStyle(document.getElementById("light")).transitionDuration);
        assert.match(tr, /^0s(, 0s)*$/, "reduced motion: no transition on transform");
        const anim = await page.evaluate(() => getComputedStyle(document.querySelector("#light .breath")).animationName);
        assert.equal(anim, "none", "reduced motion: no breathing");
        // scrolling within one stop leaves the transform unchanged; a new stop changes it
        await page.evaluate(() => scrollTo({top: 0, behavior: "instant"}));
        await sleep(150);
        const a = await page.evaluate(() => document.getElementById("light").style.transform);
        await page.evaluate(() => scrollTo({top: 60, behavior: "instant"}));
        await sleep(150);
        const b = await page.evaluate(() => document.getElementById("light").style.transform);
        assert.equal(a, b, "reduced motion: scrolling within a stop must not move the light");
        await page.evaluate(() => document.querySelector("#install").scrollIntoView({behavior: "instant"}));
        await sleep(150);
        const c = await page.evaluate(() => document.getElementById("light").style.transform);
        assert.notEqual(a, c, "reduced motion: a new stop re-places the light");
      }
      assert.deepEqual(seen.errors, [], mode);
    } finally { await context.close(); }
  }
}

async function handoffGate(engine) {
  // A forced hand-off keeps the light's centre and size.
  const {context, page, seen} = await open(engine, {forceGl: true, engine: "chromium"});
  try {
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "webgl");
    await asleep(page);
    const before = await page.locator("#light").boundingBox();
    await page.locator("#gl").evaluate(c => c.getContext("webgl").getExtension("WEBGL_lose_context").loseContext());
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "static");
    await sleep(1300);
    const after = await page.locator("#light").boundingBox();
    assert.ok(Math.abs(after.x - before.x) <= 2 && Math.abs(after.y - before.y) <= 2, "hand-off moved the light");
    assert.equal(after.width, before.width);
    metrics.handoff = {dx: after.x - before.x, dy: after.y - before.y};
    noOffsets(seen);
  } finally { await context.close(); }
}

// Forces the runtime budget path: a slow synthetic rAF breaches the frame budget while the light is moving.
async function breachGate(engine) {
  const {context, page, seen} = await open(engine, {forceGl: true, hz: 12, engine: "chromium"});
  try {
    await waitFor(page, () => document.getElementById("light").dataset.renderer === "webgl");
    await asleep(page);
    const drive = page.evaluate(() => new Promise(res => {
      const raf = window.__t.raf0, t0 = performance.now();
      const step = () => {
        const k = (performance.now() - t0) / 1000;
        scrollTo({top: 600 + 500 * Math.sin(k * 0.8), behavior: "instant"});
        if (document.getElementById("light").dataset.renderer === "static" || k > 40) res(k); else raf(step);
      };
      raf(step);
    }));
    await drive;
    const states = await page.evaluate(() => window.__t.states);
    const order = ["high", "mid", "low", "css"];
    const seq = states.map(s => s.tier).filter((v, i, a) => v && v !== a[i - 1]);
    assert.deepEqual(seq, order, `breach must step down in order and hand off once: ${seq}`);
    for (const s of states) assert.ok((s.r === "webgl" && s.canvas) || s.r === "static", "no frame with neither canvas nor orb");
    assert.equal(await page.locator("#gl").count(), 0, "canvas removed after hand-off");
    // The hand-off came mid-flight; the orb must glide onto the active stop's mark, not stay parked.
    await sleep(1500);
    const err = await page.evaluate(() => {
      const h = document.getElementById("light").getBoundingClientRect();
      const stops = [...document.querySelectorAll("[data-stop]")].map(s => { const r = s.getBoundingClientRect(); return r.top + scrollY + r.height / 2; });
      const probe = scrollY + innerHeight / 2;
      let i = 0; stops.forEach((m, k) => { if (Math.abs(m - probe) < Math.abs(stops[i] - probe)) i = k; });
      const m = document.querySelectorAll("[data-stop] .mark")[i].getBoundingClientRect();
      const clamp = (v, hi) => Math.min(Math.max(v, 24), hi - 24);
      const x = clamp(m.left + .5, innerWidth), y = clamp(m.top + scrollY + .5 - (stops[i] - innerHeight / 2), innerHeight);
      return Math.hypot(h.left + h.width / 2 - x, h.top + h.height / 2 - y);
    });
    metrics.breach = {sequence: seq, handoffAlignmentErrorPx: +err.toFixed(2)};
    assert.ok(err <= B.restPositionTolerancePx, `breach hand-off left the light ${err.toFixed(1)} px off its mark`);
    noOffsets(seen);
  } finally { await context.close(); }
}

async function pageGate(name, engine) {
  const {context, page, seen} = await open(engine, {forceGl: true, engine: name});
  try {
    await waitFor(page, () => ["webgl", "static"].includes(document.getElementById("light").dataset.renderer));
    const h = host(page);
    assert.equal(await h.getAttribute("aria-hidden"), "true");
    assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById("light")).pointerEvents), "none");
    for (const [w, ht] of [[320, 740], [390, 844], [1440, 900]]) {
      await page.setViewportSize({width: w, height: ht});
      await fit(page);
    }
    await page.setViewportSize({width: 1440, height: 900});
    // light resting over the install block: link click and Tab order behave as without it
    await page.evaluate(() => document.querySelector("#install").scrollIntoView({behavior: "instant"}));
    await sleep(1500);
    const hit = await page.evaluate(() => {
      const r = document.querySelector(".pill").getBoundingClientRect();
      const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return e.closest("#light") === null;
    });
    assert.equal(hit, true, "light must not intercept clicks");
    const focused = [];
    for (let i = 0; i < 8; i++) { await page.keyboard.press("Tab"); focused.push(await page.evaluate(() => !!document.activeElement.closest("#light"))); }
    assert.equal(focused.some(Boolean), false, "light has no tab stop");
    noOffsets(seen);
  } finally { await context.close(); }
}

for (const name of engines) {
  const browser = await launch(name);
  try {
    const first = await open(browser, {engine: name});
    await waitFor(first.page, () => ["webgl", "static"].includes(document.getElementById("light").dataset.renderer));
    const defaultRenderer = await attr(first.page, "renderer");
    metrics[`${name}-default-renderer`] = defaultRenderer;
    noOffsets(first.seen);
    await first.context.close();
    await fallbackGate(name, browser);
    await pageGate(name, browser);
    if (name !== "chromium") continue;

    // Forced GL (caveat flag stripped) so the gates measure the renderer even on a software GPU.
    const runs = [
      ["1x", {forceGl: true}], ["1x-120hz", {forceGl: true, hz: 120}],
      ["4x", {forceGl: true, throttle: 4}], ["6x", {forceGl: true, throttle: 6}],
    ];
    for (const [label, o] of runs) {
      const end = await budgetGate(label, o, browser);
      if (label === "1x") {
        assert.equal(end.finalRenderer, "webgl", "forced-GL 1x run must stay on webgl");
        assert.equal(end.finalTier, "high", "forced-GL 1x run must stay at the top tier");
      }
    }
    await stabilityGate(browser, "stability-1440", {width: 1440, height: 900});
    await stabilityGate(browser, "stability-390", {width: 390, height: 844});
    await stopsGate(browser, "1440", {width: 1440, height: 900});
    await stopsGate(browser, "390", {width: 390, height: 844});
    await breachGate(browser);
    await hiddenGate(browser);
    await handoffGate(browser);
  } finally {
    await browser.close();
  }
}
await writeFile(`${output}/light-metrics.json`, JSON.stringify(metrics, null, 2));
console.log(JSON.stringify({light: "pass", engines, metrics}, null, 1));
