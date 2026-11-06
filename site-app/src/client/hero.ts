/* Hero background: the "Ribbon Field" background from ThreeUI Community
   (https://github.com/MengTo/threeui, src/shaders/ribbon-field/, MIT,
   Copyright (c) 2026 Meng To; full notice in /credits.txt).
   Changes from upstream: the React wrapper is unwrapped into one mount
   function so the page needs no client React; the ribbon palette is Wisp's
   (ember, amber, and the flame's blue) instead of teal/indigo/purple; the
   pixel ratio is capped at 1.5; the context fails on major performance
   caveats; context loss and errors fall back to the static frame. The
   shader's structure (three ribbons, bloom, halftone dots) is upstream's. */

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

  float rightFade = smoothstep(0.22, 0.70, uv.x);
  float centerDark = 1.0 - smoothstep(0.0, 0.88, distance(uv, vec2(0.18, 0.48)));

  float r1 = ribbon(vec2(uv.x + drift, uv.y), 0.03, 0.0065, t + 0.9);
  float r2 = ribbon(vec2(uv.x - drift * 0.7, uv.y), -0.23, 0.0085, t + 3.25);
  float r3 = ribbon(vec2(uv.x + drift * 0.4, uv.y), 0.25, 0.014, t + 1.85);
  float glow = r1 * 1.14 + r2 * 1.05 + r3 * 0.48;

  // Wisp palette: amber, ember, deep ember, flame blue.
  vec3 amber = vec3(0.98, 0.70, 0.33);
  vec3 ember = vec3(0.93, 0.42, 0.16);
  vec3 deep = vec3(0.62, 0.20, 0.08);
  vec3 flame = vec3(0.62, 0.84, 1.0);

  vec3 col = vec3(0.0);
  col += amber * r1 * 0.95;
  col += ember * r1 * 0.45;
  col += flame * r3 * 0.40;
  col += ember * r2 * 0.70;
  col += deep * (r2 + r3) * 0.30;

  float bloom = exp(-pow(distance(uv, vec2(0.76, 0.40 + 0.035 * sin(t))), 2.0) / 0.050);
  bloom += exp(-pow(distance(uv, vec2(0.71, 0.75 + 0.025 * cos(t))), 2.0) / 0.030);
  col += vec3(1.0, 0.62, 0.30) * bloom * 0.30;

  vec2 grid = fract(gl_FragCoord.xy / 7.0) - 0.5;
  float dotShape = smoothstep(0.29, 0.11, length(grid));
  float noise = hash(floor(gl_FragCoord.xy / 7.0));
  float scan = 0.72 + 0.28 * sin((uv.x + uv.y) * 38.0 + time * 1.3);
  float dots = dotShape * (0.48 + 0.52 * noise) * scan;

  float micro = hash(gl_FragCoord.xy + time) * 0.025;
  float alpha = clamp((glow * 1.55 + bloom * 0.50) * dots * rightFade, 0.0, 1.0);
  alpha *= 1.0 - centerDark * 0.56;

  vec3 base = vec3(0.05, 0.04, 0.035);
  vec3 finalColor = mix(base, col, clamp(alpha * 1.55, 0.0, 1.0));
  finalColor += micro * rightFade;
  gl_FragColor = vec4(finalColor, 1.0);
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
export function mountRibbonField(host: HTMLElement, { onLost }: { onLost?: () => void } = {}): (() => void) | null {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl", {
    alpha: false, antialias: false, depth: false, stencil: false,
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
    };
    const render = (now: number) => {
      frame = 0;
      if (stopped) return;
      try {
        mouseX += (targetX - mouseX) * 0.035; mouseY += (targetY - mouseY) * 0.035;
        gl.uniform1f(time, (now - startedAt) * 0.001);
        gl.uniform2f(pointerUniform, mouseX, mouseY);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      } catch { stop(); onLost?.(); return; }
      if (host.dataset.rendered !== "true") { host.dataset.hero = "webgl"; host.dataset.rendered = "true"; }
      if (visible && !document.hidden) frame = requestAnimationFrame(render);
    };
    const wake = () => { if (!frame && !stopped && visible && !document.hidden) frame = requestAnimationFrame(render); };

    const lost = (event: Event) => { event.preventDefault(); stop(); onLost?.(); };
    canvas.addEventListener("webglcontextlost", lost);
    const ro = new ResizeObserver(resize);
    const io = new IntersectionObserver(([entry]) => { visible = entry?.isIntersecting ?? true; wake(); });
    ro.observe(host); io.observe(host);
    const area = host.parentElement ?? host;
    area.addEventListener("pointermove", pointer, { passive: true });
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
