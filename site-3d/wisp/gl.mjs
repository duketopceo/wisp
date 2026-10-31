/* Plain WebGL1 view of the wisp light: a shaded core, a soft wispy tail and a glow in one draw call.
   The look follows ThreeUI Community "energy-orb" (MIT, Copyright (c) 2026 Meng To,
   https://github.com/MengTo/threeui) as a design reference; the shader is rewritten, not copied.
   See vendor/THREEUI-LICENSE.txt and THIRD_PARTY_NOTICES.md.
   No page, DOM-layout or three.js dependency: the shader sources are exported for reuse. */
export const TAIL_N = 16;          // tail quads; the sim hands over this many trail offsets
export const DPR_CAP = 1.5;        // device pixel ratio ceiling (fill cost is fixed by the box, not the page)
const TAIL_MIN = 0.01;             // below this tail length the tail is skipped; its alpha already faded to zero
const NOISE = 64;

export const VERTEX_SRC = `
attribute vec2 aCorner;
attribute float aSlot;             // -1 core, otherwise trail slot (0 newest)
uniform vec2 uTrail[${TAIL_N}];
uniform float uTime, uTailLen;
varying vec2 vUv;
varying float vKind;
varying float vFade;
void main() {
  vUv = aCorner;
  vec2 c = vec2(0.0);
  float half_ = 0.5;
  vKind = 1.0;
  vFade = 1.0;
  if (aSlot > -0.5) {
    int k = int(aSlot + 0.5);
    float f = aSlot / ${(TAIL_N - 1).toFixed(1)};           // 0 near the head, 1 at the tip
    vec2 off = uTrail[k];
    vec2 dir = off / (length(off) + 1e-4);
    vec2 side = vec2(-dir.y, dir.x);
    float z = 1.0 - f;                                        // farther points are smaller and fainter
    c = off + side * sin(uTime * 2.1 + aSlot * 0.9) * 0.03 * uTailLen;
    half_ = (0.14 + 0.2 * z) * (0.5 + 0.5 * uTailLen);
    vKind = 0.0;
    vFade = pow(z, 1.4) * smoothstep(0.0, 0.35, uTailLen);
  }
  gl_Position = vec4(c + aCorner * half_, 0.0, 1.0);
}`;

export const FRAGMENT_SRC = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D uNoise;
uniform float uTime;
varying vec2 vUv;
varying float vKind;
varying float vFade;
float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }
void main() {
  float r = length(vUv);
  float edge = 1.0 - smoothstep(0.82, 1.0, r);               // reaches exactly zero before the quad edge
  vec3 glowCol = vec3(0.40, 0.72, 1.0);
  vec3 col;
  float a;
  if (vKind > 0.5) {
    float rc = 0.3;
    float glow = pow(1.0 - min(r, 1.0), 2.5) * edge * 0.9;
    col = glowCol;
    a = glow;
    if (r < rc) {
      float z = sqrt(1.0 - (r / rc) * (r / rc));
      vec3 n = vec3(vUv / rc, z);
      float ca = uTime * 0.05;
      vec2 p = vec2(n.x * cos(ca) + n.z * sin(ca), n.y) * 0.5 + 0.5;
      float veil = texture2D(uNoise, p * 0.8 + vec2(0.0, uTime * 0.01)).r;
      veil = veil * 0.6 + texture2D(uNoise, p * 1.7 - vec2(uTime * 0.008, 0.0)).r * 0.4;
      float diff = clamp(dot(n, normalize(vec3(-0.4, 0.55, 0.75))), 0.0, 1.0);
      float rim = pow(1.0 - z, 2.5);
      vec3 mid = vec3(0.16, 0.38, 0.52), bright = vec3(0.49, 0.81, 1.0);
      vec3 core = mix(mid, bright, 0.35 + 0.65 * diff) + vec3(0.12, 0.2, 0.25) * (veil - 0.5);
      core += vec3(0.5, 0.8, 1.0) * rim * 0.35;
      float cover = 1.0 - smoothstep(rc - 0.02, rc, r);
      col = mix(col, clamp(core, 0.0, 1.0), cover);
      a = max(a, cover);
    }
  } else {
    float g = pow(1.0 - min(r, 1.0), 2.2) * edge;
    col = vec3(0.30, 0.62, 0.95);
    a = g * vFade * 0.55;
  }
  float d = (ign(gl_FragCoord.xy) - 0.5) / 255.0;
  a = clamp(a + d * a, 0.0, 1.0);                             // dither scaled by alpha: transparent stays exactly zero
  gl_FragColor = vec4(col * a, a);                            // premultiplied
}`;

function noiseTexture(gl) {
  const data = new Uint8Array(NOISE * NOISE * 4);
  const hash = (x, y) => { let h = (x * 374761393 + y * 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967295; };
  const lat = (x, y, s) => hash(((x % s) + s) % s, ((y % s) + s) % s);
  const value = (u, v, s) => {                                // tileable value noise on an s x s lattice
    const x = Math.floor(u * s), y = Math.floor(v * s), fx = u * s - x, fy = v * s - y;
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const a = lat(x, y, s), b = lat(x + 1, y, s), c = lat(x, y + 1, s), d = lat(x + 1, y + 1, s);
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
  };
  for (let y = 0; y < NOISE; y++) for (let x = 0; x < NOISE; x++) {
    const u = x / NOISE, v = y / NOISE;
    const n = (value(u, v, 4) * 0.55 + value(u, v, 8) * 0.3 + value(u, v, 16) * 0.15) * 255;
    const i = (y * NOISE + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = n; data[i + 3] = 255;
  }
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, NOISE, NOISE, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
  return tex;
}

/** Create the view on `canvas`, or return null when WebGL is missing, a software renderer is
    refused (failIfMajorPerformanceCaveat) or the shaders do not build, so the page can fall back.
    onLost fires once after context loss; no draw happens after that. */
export function createGlView(canvas, {onLost} = {}) {
  let gl = null;
  try {
    gl = canvas.getContext("webgl", {
      alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false,
      powerPreference: "low-power", failIfMajorPerformanceCaveat: true, preserveDrawingBuffer: false,
    });
  } catch { gl = null; }
  if (!gl) return null;

  const compile = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const vs = compile(gl.VERTEX_SHADER, VERTEX_SRC), fs = compile(gl.FRAGMENT_SHADER, FRAGMENT_SRC);
  const program = gl.createProgram();
  if (!vs || !fs) return null;
  gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  // One static buffer: tail quads oldest to newest, then the core last (premultiplied "over" is
  // order dependent, so the core must land on top). Core-only frames draw just the last quad.
  const corners = [[-1, -1], [1, -1], [-1, 1], [-1, 1], [1, -1], [1, 1]];
  const data = [];
  for (let j = 0; j < TAIL_N; j++) for (const [x, y] of corners) data.push(x, y, TAIL_N - 1 - j);
  for (const [x, y] of corners) data.push(x, y, -1);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
  const aCorner = gl.getAttribLocation(program, "aCorner"), aSlot = gl.getAttribLocation(program, "aSlot");
  gl.enableVertexAttribArray(aCorner); gl.vertexAttribPointer(aCorner, 2, gl.FLOAT, false, 12, 0);
  gl.enableVertexAttribArray(aSlot); gl.vertexAttribPointer(aSlot, 1, gl.FLOAT, false, 12, 8);
  const uTrail = gl.getUniformLocation(program, "uTrail"), uTime = gl.getUniformLocation(program, "uTime");
  const uTailLen = gl.getUniformLocation(program, "uTailLen");
  gl.activeTexture(gl.TEXTURE0);
  const texture = noiseTexture(gl);
  gl.uniform1i(gl.getUniformLocation(program, "uNoise"), 0);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.clearColor(0, 0, 0, 0);

  let lost = false, disposed = false, last = null, lastTime = 0, side = 0;

  function lose(event) {
    event.preventDefault();
    if (lost) return;
    lost = true;
    onLost?.();
  }
  canvas.addEventListener("webglcontextlost", lose);

  function draw(state, time) {
    if (lost || disposed) return;
    last = state; lastTime = time;
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2fv(uTrail, state.trail);
    gl.uniform1f(uTime, time);
    gl.uniform1f(uTailLen, state.tailLen);
    const tail = state.tailLen > TAIL_MIN;
    gl.drawArrays(gl.TRIANGLES, tail ? 0 : TAIL_N * 6, tail ? (TAIL_N + 1) * 6 : 6);
  }

  /** Square box of `cssSize` CSS px at the capped pixel ratio times a quality scale. Redraws in
      the same call, so a resize never leaves a cleared canvas for a frame. */
  function resize(cssSize, dpr, scale = 1) {
    if (lost || disposed) return side;
    side = Math.max(1, Math.round(cssSize * Math.min(dpr || 1, DPR_CAP) * scale));
    canvas.width = canvas.height = side;
    gl.viewport(0, 0, side, side);
    if (last) draw(last, lastTime);
    return side;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    canvas.removeEventListener("webglcontextlost", lose);
    try { gl.deleteTexture(texture); gl.deleteProgram(program); } catch { /* loss may invalidate cleanup */ }
  }

  return {draw, resize, dispose, get side() { return side; }, get lost() { return lost; }};
}
