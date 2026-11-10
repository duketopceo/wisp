/* Hero background: the "Ribbon Field" background from ThreeUI Community
   (https://github.com/MengTo/threeui, src/shaders/ribbon-field/, MIT,
   Copyright (c) 2026 Meng To; full notice in /credits.txt).
   Changes from upstream: the React wrapper is unwrapped into one mount
   function so the page needs no client React; the ribbons are drawn in the
   page's pop colour (and tints of it) on a transparent canvas, so the page
   theme shows through; the shader leaves quiet zones behind the comet mark and
   the copy; the pixel ratio is capped at 1.5; the context fails on major
   performance caveats; context loss and errors fall back to the static frame;
   reduced motion draws one still frame. The shader's structure (three
   ribbons, bloom, halftone dots) is upstream's. */

const VERTEX = `
attribute vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAGMENT = `
precision highp float;
uniform vec2 resolution;
uniform float time;
uniform vec2 pointer;
uniform vec3 comet;   // x, y (px, GL origin), radius of the quiet zone behind the mark
uniform vec4 copy;    // x0, y0, x1, y1 (px, GL origin) of the text column

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float ribbon(vec2 uv, float offset, float width, float phase) {
  float y = 0.55 + 0.20 * sin((uv.x * 2.15) + phase) + 0.045 * sin((uv.x * 7.0) - phase * 0.7);
  float d = abs(uv.y - y - offset);
  return exp(-(d * d) / width);
}

void main() {
  vec2 uv = gl_FragCoord.xy / resolution.xy;
  float t = time * 0.22;
  float drift = (pointer.x - 0.5) * 0.06;

  float r1 = ribbon(vec2(uv.x + drift, uv.y), 0.03, 0.0065, t + 0.9);
  float r2 = ribbon(vec2(uv.x - drift * 0.7, uv.y), -0.23, 0.0085, t + 3.25);
  float r3 = ribbon(vec2(uv.x + drift * 0.4, uv.y), 0.25, 0.014, t + 1.85);
  float glow = r1 * 1.14 + r2 * 1.05 + r3 * 0.48;

  // Wisp pop #FF5B1F, a lighter tint of it, and a deeper shade.
  vec3 pop = vec3(1.0, 0.357, 0.122);
  vec3 tint = vec3(1.0, 0.66, 0.40);
  vec3 deep = vec3(0.70, 0.22, 0.07);

  vec3 col = vec3(0.0);
  col += tint * r1 * 0.80;
  col += pop * r1 * 0.55;
  col += tint * r3 * 0.45;
  col += pop * r2 * 0.75;
  col += deep * (r2 + r3) * 0.30;

  float bloom = exp(-pow(distance(uv, vec2(0.76, 0.40 + 0.035 * sin(t))), 2.0) / 0.050);
  bloom += exp(-pow(distance(uv, vec2(0.71, 0.75 + 0.025 * cos(t))), 2.0) / 0.030);
  col += pop * bloom * 0.30;

  vec2 grid = fract(gl_FragCoord.xy / 7.0) - 0.5;
  float dotShape = smoothstep(0.29, 0.11, length(grid));
  float noise = hash(floor(gl_FragCoord.xy / 7.0));
  float scan = 0.72 + 0.28 * sin((uv.x + uv.y) * 38.0 + time * 1.3);
  float dots = dotShape * (0.48 + 0.52 * noise) * scan;

  float alpha = clamp((glow * 2.8 + bloom * 0.50) * dots, 0.0, 1.0);

  // Quiet zones: almost nothing behind the comet mark, a veil behind the copy.
  float cometQuiet = smoothstep(comet.z * 0.3, comet.z * 0.85, distance(gl_FragCoord.xy, comet.xy));
  vec2 q = abs(gl_FragCoord.xy - (copy.xy + copy.zw) * 0.5) - (copy.zw - copy.xy) * 0.5;
  float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
  float copyQuiet = 1.0 - 0.55 * (1.0 - smoothstep(0.0, 160.0 * comet.z / 180.0, sd));
  alpha *= (0.05 + 0.95 * cometQuiet) * copyQuiet;

  vec3 mixed = col / max(max(col.r, max(col.g, col.b)), 0.001);
  gl_FragColor = vec4(mixed * alpha, alpha);
}
`;

const DPR_CAP = 1.5;

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) ?? "shader");
  return shader;
}

/** Mounts the ribbon field into `host`; returns a stop function, or null when
 *  WebGL is unavailable (the static frame stays). */
export function mountRibbonField(host: HTMLElement, { onLost, still = false }: { onLost?: () => void; still?: boolean } = {}): (() => void) | null {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl", {
    alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false,
    failIfMajorPerformanceCaveat: true, powerPreference: "low-power",
  });
  if (!gl) { host.dataset.hero = "static"; return null; }

  let frame = 0, visible = true, stopped = false;
  let program: WebGLProgram | null = null;
  const cleanups: Array<() => void> = [];
  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (frame) cancelAnimationFrame(frame);
    cleanups.forEach((fn) => fn());
    canvas.remove();
    host.dataset.hero = "static";
    delete host.dataset.rendered;
  };

  try {
    const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX), fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    program = gl.createProgram();
    if (!program) throw new Error("program");
    gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) ?? "link");
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const resolution = gl.getUniformLocation(program, "resolution");
    const time = gl.getUniformLocation(program, "time");
    const cometUniform = gl.getUniformLocation(program, "comet");
    const copyUniform = gl.getUniformLocation(program, "copy");
    const pointerUniform = gl.getUniformLocation(program, "pointer");
    let mouseX = 0.72, mouseY = 0.42, targetX = 0.72, targetY = 0.42;
    const startedAt = performance.now();

    const pointer = (event: PointerEvent) => {
      const b = host.getBoundingClientRect();
      targetX = (event.clientX - b.left) / Math.max(b.width, 1);
      targetY = 1 - (event.clientY - b.top) / Math.max(b.height, 1);
    };
    const resize = () => {
      const b = host.getBoundingClientRect(), ratio = Math.min(devicePixelRatio || 1, DPR_CAP);
      canvas.width = Math.max(1, Math.floor(b.width * ratio));
      canvas.height = Math.max(1, Math.floor(b.height * ratio));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(resolution, canvas.width, canvas.height);
      zones(b, ratio);
    };
    // Quiet zones from the real layout: the mark's stage and the copy column.
    const zones = (b: DOMRect, ratio: number) => {
      const area = host.parentElement ?? host;
      const mark = area.querySelector<HTMLElement>("#hero-mark")?.getBoundingClientRect();
      const text = area.querySelector<HTMLElement>("#hero-title")?.parentElement?.getBoundingClientRect();
      const y = (top: number, bottom: number) => [(b.bottom - bottom) * ratio, (b.bottom - top) * ratio];
      if (mark) {
        const r = Math.min(mark.width, mark.height) * 0.5 * ratio;
        gl.uniform3f(cometUniform, (mark.left + mark.width / 2 - b.left) * ratio, (b.bottom - mark.top - mark.height / 2) * ratio, r);
      } else gl.uniform3f(cometUniform, -1e4, -1e4, 1);
      if (text) {
        const [y0, y1] = y(text.top, text.bottom);
        gl.uniform4f(copyUniform, (text.left - b.left) * ratio, y0, (text.right - b.left) * ratio, y1);
      } else gl.uniform4f(copyUniform, 0, 0, 0, 0);
    };
    const render = (now: number) => {
      frame = 0;
      if (stopped) return;
      try {
        mouseX += (targetX - mouseX) * 0.035; mouseY += (targetY - mouseY) * 0.035;
        gl.uniform1f(time, still ? 4.2 : (now - startedAt) * 0.001);
        gl.uniform2f(pointerUniform, mouseX, mouseY);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      } catch { stop(); onLost?.(); return; }
      if (host.dataset.rendered !== "true") { host.dataset.hero = "webgl"; host.dataset.rendered = "true"; }
      if (!still && visible && !document.hidden) frame = requestAnimationFrame(render);
    };
    const wake = () => { if (!frame && !stopped && visible && !document.hidden) frame = requestAnimationFrame(render); };

    const lost = (event: Event) => { event.preventDefault(); stop(); onLost?.(); };
    canvas.addEventListener("webglcontextlost", lost);
    const ro = new ResizeObserver(() => { resize(); wake(); });
    const io = new IntersectionObserver(([entry]) => { visible = entry?.isIntersecting ?? true; wake(); });
    ro.observe(host); io.observe(host);
    const area = host.parentElement ?? host;
    if (!still) area.addEventListener("pointermove", pointer, { passive: true });
    document.addEventListener("visibilitychange", wake);
    cleanups.push(() => {
      ro.disconnect(); io.disconnect();
      area.removeEventListener("pointermove", pointer);
      document.removeEventListener("visibilitychange", wake);
      canvas.removeEventListener("webglcontextlost", lost);
      if (!gl.isContextLost()) {
        gl.deleteBuffer(buffer); gl.deleteShader(vertex); gl.deleteShader(fragment); gl.deleteProgram(program);
        gl.getExtension("WEBGL_lose_context")?.loseContext();
      }
    });
    host.append(canvas);
    host.dataset.hero = "webgl"; // mounted; data-rendered follows the first frame
    resize();
    wake();
    return stop;
  } catch {
    stop();
    return null;
  }
}
