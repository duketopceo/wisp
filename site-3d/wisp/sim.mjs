// Motion sim for the wisp light: pure maths, no DOM, no GL, no globals, so it runs in Node
// and can be reused by any renderer. Positions are CSS pixels; trail offsets are unit-box
// coordinates (box half-width = 1), scaled by the tail length, which collapses at rest.
const clamp01 = x => Math.min(1, Math.max(0, x));
const smoothstep = (lo, hi, x) => { const t = clamp01((x - lo) / (hi - lo)); return t * t * (3 - 2 * t); };

export function createSim(options = {}) {
  const o = {
    x: 0, y: 0,
    omega: 6,               // spring stiffness (1/s); ~1.5 s to settle
    tailN: 16,              // trail points handed to the renderer
    maxRadius: 0.4,         // trail reach in unit-box coordinates, never the box edge
    tailRefPx: 160,         // pixel lag that maps to maxRadius
    trailInterval: 1 / 60,  // sim seconds between trail samples
    maxDt: 1 / 20,
    speedLo: 20, speedHi: 400,
    tailRise: 12, tailFall: 4,
    posEps: 0.1, speedEps: 2, tailEps: 0.002, settleSteps: 3,
    ...options,
  };
  const n = o.tailN;
  const trail = new Float32Array(n * 2);
  const state = {x: o.x, y: o.y, vx: 0, vy: 0, speed: 0, tailLen: 0, settled: true, trail};
  const target = {x: o.x, y: o.y};
  const trailAge = new Float32Array(n);
  const ring = new Float32Array(n * 2);   // head positions in px, written oldest to newest
  const ringTime = new Float64Array(n);
  let ringHead = 0, clock = 0, sinceSample = 0, quiet = o.settleSteps;
  for (let i = 0; i < n; i++) { ring[2 * i] = o.x; ring[2 * i + 1] = o.y; ringTime[i] = 0; }

  const error = () => Math.hypot(state.x - target.x, state.y - target.y);

  function setTarget(x, y) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    target.x = x; target.y = y;
    // A velocity toward the target faster than omega * distance would overshoot a critically
    // damped spring, so bound it. Velocity within the bound is untouched (no teleport).
    for (const [p, v, t] of [["x", "vx", x], ["y", "vy", y]]) {
      const e = state[p] - t;
      if (e * (state[v] + o.omega * e) < 0) state[v] = -o.omega * e;
    }
    if (error() > o.posEps) { state.settled = false; quiet = 0; }
  }

  function axis(e, v, t) {
    const w = o.omega, k = Math.exp(-w * t), c = v + w * e;
    return [(e + c * t) * k, (v - w * c * t) * k];
  }

  function pushTrail() {
    ring[2 * ringHead] = state.x; ring[2 * ringHead + 1] = state.y; ringTime[ringHead] = clock;
    ringHead = (ringHead + 1) % n;
  }

  function writeTrail() {
    const scale = o.maxRadius / o.tailRefPx * state.tailLen;
    for (let k = 0; k < n; k++) {
      const i = (ringHead - 1 - k + 2 * n) % n;          // k = 0 is the newest sample
      let dx = (ring[2 * i] - state.x) * scale, dy = (ring[2 * i + 1] - state.y) * scale;
      const m = Math.hypot(dx, dy);
      if (m > o.maxRadius) { dx *= o.maxRadius / m; dy *= o.maxRadius / m; }
      trail[2 * k] = dx; trail[2 * k + 1] = dy;
      trailAge[k] = Math.max(0, clock - ringTime[i]);
    }
  }

  function step(dt) {
    if (!(dt > 0) || !Number.isFinite(dt)) return state;
    dt = Math.min(dt, o.maxDt);
    clock += dt;
    const [ex, vx] = axis(state.x - target.x, state.vx, dt);
    const [ey, vy] = axis(state.y - target.y, state.vy, dt);
    state.x = target.x + ex; state.y = target.y + ey; state.vx = vx; state.vy = vy;
    state.speed = Math.hypot(vx, vy);
    const want = smoothstep(o.speedLo, o.speedHi, state.speed);
    const rate = want > state.tailLen ? o.tailRise : o.tailFall;
    state.tailLen += (want - state.tailLen) * (1 - Math.exp(-rate * dt));
    sinceSample += dt;
    if (sinceSample >= o.trailInterval) { sinceSample %= o.trailInterval; pushTrail(); }

    const still = error() < o.posEps && state.speed < o.speedEps && state.tailLen < o.tailEps;
    quiet = still ? quiet + 1 : 0;
    state.settled = quiet >= o.settleSteps;
    if (state.settled) {                                // exact rest: no residual drift, no tail
      state.x = target.x; state.y = target.y; state.vx = state.vy = state.speed = state.tailLen = 0;
      for (let i = 0; i < n; i++) { ring[2 * i] = state.x; ring[2 * i + 1] = state.y; ringTime[i] = clock; }
    }
    writeTrail();
    return state;
  }

  return {
    setTarget, step, state, target, trail, trailAge,
    get settled() { return state.settled; },
    tailN: n, maxRadius: o.maxRadius,
  };
}
