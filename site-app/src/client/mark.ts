// The Wisp comet, drawn on a 2D canvas over the SVG still: a soft dot on a slow
// drift with one tapered tail, leaning toward the pointer while it hovers the
// stage. Sizes are in units of u (the dot's radius), so the comet scales with
// the stage and its whole swing stays inside it. The sim steps at a fixed 60 Hz
// so drift speed does not depend on the display's frame rate.
//
// The loop runs only while the stage is on screen and the tab is visible; the
// first frame is drawn the first time the stage is seen, which is also when
// onLive fires and the caller can hide the still.
const STEP = 1 / 60;
const CAP = 420;
const MAX_TAIL = 96;
const TAU = Math.PI * 2;
const GLOW = 2.6; // glow radius in u

export type Mark = { stop: () => void; recolor: () => void };

function rgb(css: string): [number, number, number] {
  const hex = css.trim().replace("#", "");
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

export function mountMark(stage: HTMLElement, hooks: { onLive: () => void; onLost: () => void }): Mark {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d canvas");
  canvas.setAttribute("aria-hidden", "true");
  stage.prepend(canvas);

  const dpr = Math.min(devicePixelRatio || 1, 2);
  let w = 0, h = 0, u = 1;
  let solid = "", glow0 = "", glow1 = "";
  const hx = new Float32Array(CAP), hy = new Float32Array(CAP);
  let n = 0;
  const tx = new Float32Array(MAX_TAIL), ty = new Float32Array(MAX_TAIL);
  let t = -3, ax = 0, ay = 0, x = 0, y = 0;
  let px: number | null = null, py: number | null = null;
  let acc = 0, last = 0, raf = 0, seen = false, visible = false;

  const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v));

  const colors = () => {
    const [r, g, b] = rgb(getComputedStyle(stage).getPropertyValue("--pop"));
    solid = `rgb(${r},${g},${b})`;
    glow0 = `rgba(${r},${g},${b},.22)`;
    glow1 = `rgba(${r},${g},${b},0)`;
  };

  const size = () => {
    w = stage.clientWidth;
    h = stage.clientHeight;
    u = Math.min(w, h) / 18;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const step = () => {
    t += STEP;
    const rx = w / 2, ry = h / 2;
    const gx = px === null ? rx : rx + clamp((px - rx) * 0.3, GLOW * u);
    const gy = py === null ? ry : ry + clamp((py - ry) * 0.3, 2 * u);
    const k = 1 - Math.exp(-STEP * 4);
    ax += (gx - ax) * k;
    ay += (gy - ay) * k;
    const L = 3 * u;
    x = ax + L * 0.8 * (Math.sin(0.7 * t) + 0.16 * Math.sin(1.9 * t + 1));
    y = ay + L * 0.62 * (Math.sin(0.53 * t) + 0.16 * Math.sin(1.4 * t + 2));
    const i = n % CAP;
    hx[i] = x;
    hy[i] = y;
    n++;
  };

  // Walk the history from the newest point, keeping a point whenever it is at
  // least `gap` from the last kept one, until `len` of path is covered.
  const tail = (len: number, gap: number) => {
    let m = 1, run = 0, lx = x, ly = y;
    tx[0] = x;
    ty[0] = y;
    for (let k = 2; k <= Math.min(n, CAP) && run < len && m < MAX_TAIL; k++) {
      const i = (n - k) % CAP;
      const d = Math.hypot(hx[i] - lx, hy[i] - ly);
      if (d >= gap) {
        run += d;
        lx = tx[m] = hx[i];
        ly = ty[m] = hy[i];
        m++;
      }
    }
    return m;
  };

  const draw = () => {
    ctx.clearRect(0, 0, w, h);
    const m = tail(6 * u, 0.12 * u);
    ctx.lineCap = "round";
    ctx.strokeStyle = solid;
    for (let i = 0; i < m - 1; i++) {
      ctx.lineWidth = 1.5 * u * Math.pow(1 - i / (m - 1), 1.15) + 0.2;
      ctx.beginPath();
      ctx.moveTo(tx[i], ty[i]);
      ctx.lineTo(tx[i + 1], ty[i + 1]);
      ctx.stroke();
    }
    const g = ctx.createRadialGradient(x, y, 0, x, y, GLOW * u);
    g.addColorStop(0, glow0);
    g.addColorStop(1, glow1);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, GLOW * u, 0, TAU);
    ctx.fill();
    ctx.fillStyle = solid;
    ctx.beginPath();
    ctx.arc(x, y, u, 0, TAU);
    ctx.fill();
  };

  const guarded = (fn: () => void) => {
    try { fn(); } catch { stop(); hooks.onLost(); }
  };

  const frame = (now: number) => {
    raf = 0;
    if (!visible || document.hidden) return;
    acc += Math.min((now - last) / 1000, 0.1);
    last = now;
    guarded(() => {
      while (acc >= STEP) { step(); acc -= STEP; }
      draw();
    });
    if (visible && !document.hidden) raf = requestAnimationFrame(frame);
  };

  const run = () => {
    if (raf || !seen || !visible || document.hidden) return;
    acc = 0;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  };

  const first = () => {
    seen = true;
    guarded(() => {
      ax = w / 2;
      ay = h / 2;
      for (let i = 0; i < 180; i++) step(); // fill the tail before the first frame
      draw();
      hooks.onLive();
    });
  };

  const io = new IntersectionObserver((entries) => {
    visible = entries[entries.length - 1].isIntersecting;
    if (visible && !seen && !document.hidden) first();
    if (visible) run();
  }, { rootMargin: "80px" });
  const onVisibility = () => {
    if (document.hidden) return;
    if (visible && !seen) first(); // the first frame waits for a visible tab
    run();
  };
  // A lost 2D context draws nothing and comes back blank: give the still back.
  const onContextLost = (e: Event) => { e.preventDefault(); stop(); hooks.onLost(); };
  const onMove = (e: PointerEvent) => {
    const r = stage.getBoundingClientRect();
    px = e.clientX - r.left;
    py = e.clientY - r.top;
  };
  const onLeave = () => { px = py = null; };
  const ro = new ResizeObserver(() => {
    if (!w || (w === stage.clientWidth && h === stage.clientHeight)) return;
    size();
    if (seen) guarded(draw);
  });

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    visible = false;
    io.disconnect();
    ro.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    canvas.removeEventListener("contextlost", onContextLost);
    stage.removeEventListener("pointermove", onMove);
    stage.removeEventListener("pointerleave", onLeave);
    canvas.remove();
  }

  colors();
  size();
  stage.addEventListener("pointermove", onMove);
  stage.addEventListener("pointerleave", onLeave);
  canvas.addEventListener("contextlost", onContextLost);
  document.addEventListener("visibilitychange", onVisibility);
  ro.observe(stage);
  io.observe(stage);
  return { stop, recolor: () => { colors(); if (seen) guarded(draw); } };
}
