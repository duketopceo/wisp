/* Guiding-light preview: one small light that rests beside each section.
   The fragment shader is adapted from ThreeUI Community "energy-orb" (MIT, Copyright (c) 2026 Meng To,
   https://github.com/MengTo/threeui): recoloured to wisp's `guide` token, smaller, slower. See
   vendor/THREEUI-LICENSE.txt and THIRD_PARTY_NOTICES.md. */
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const light = document.getElementById("light"), cv = document.getElementById("gl");
const stops = [...document.querySelectorAll("[data-stop]")];

// --- the light: ThreeUI energy-orb fragment shader (MIT), recoloured to wisp `guide` and toned down ---
const VS = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
const FS = `precision highp float;uniform float uT;uniform vec2 uR;
float hash(vec3 p){p=fract(p*0.3183099+vec3(0.1,0.2,0.3));p*=17.0;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x);vec3 f=fract(x);f=f*f*(3.0-2.0*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
 mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float v=0.0;float a=0.5;for(int i=0;i<4;i++){v+=a*noise(p);p=p*2.03+vec3(1.7);a*=0.5;}return v;}
void main(){
 vec2 uv=(gl_FragCoord.xy-0.5*uR)/min(uR.x,uR.y);
 float r=length(uv);float R=0.075;vec3 col=vec3(0.0);float alpha=0.0;
 if(r<R){
  float z=sqrt(R*R-r*r);vec3 n=normalize(vec3(uv,z));
  float ca=uT*0.05;mat3 rot=mat3(cos(ca),0.,sin(ca),0.,1.,0.,-sin(ca),0.,cos(ca));vec3 sp=rot*n;
  float f1=fbm(sp*2.2+vec3(0.0,uT*0.04,0.0));
  float f2=fbm(sp*3.6-vec3(uT*0.03,0.0,uT*0.02)+f1*1.4);
  float veil=smoothstep(0.35,0.75,f2);
  vec3 deep=vec3(0.03,0.07,0.11),mid=vec3(0.16,0.38,0.52),bright=vec3(0.49,0.81,1.0);
  col=mix(mid,bright,0.55+veil*0.45);
  col+=vec3(0.5,0.8,1.0)*pow(z/R,3.0)*0.35;
  alpha=1.0;
 }else{
  float glow=clamp(exp(-(r-R)*7.0),0.0,1.0);glow=glow*glow*0.8;
  col=vec3(0.40,0.72,1.0)*glow;alpha=glow*0.75;
 }
 gl_FragColor=vec4(col,alpha);}`;
const gl = cv.getContext("webgl",{alpha:true,premultipliedAlpha:false,antialias:true});
let draw = () => {};
if (!gl) light.classList.add("nogl"); else {
  const sh = (t,s) => { const o = gl.createShader(t); gl.shaderSource(o,s); gl.compileShader(o); return o; };
  const pr = gl.createProgram(); gl.attachShader(pr,sh(gl.VERTEX_SHADER,VS)); gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,FS)); gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr,gl.LINK_STATUS)) light.classList.add("nogl"); else {
    gl.useProgram(pr); gl.bindBuffer(gl.ARRAY_BUFFER,gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr,"p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
    const uT = gl.getUniformLocation(pr,"uT"), uR = gl.getUniformLocation(pr,"uR");
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
    draw = t => {
      const d = Math.min(devicePixelRatio||1,2), w = Math.round(light.clientWidth*d);
      if (cv.width !== w) { cv.width = cv.height = w; gl.viewport(0,0,w,w); }
      gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(uT,t); gl.uniform2f(uR,w,w); gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    };
  }
}

// --- the light rests beside the section in view, and drifts there slowly when you scroll ---
let x = innerWidth * .7, y = innerHeight * .4, last = 0;
const active = () => stops.reduce((b,s) => { const r = s.getBoundingClientRect(), m = r.top + r.height / 2;
  return Math.abs(m - innerHeight / 2) < Math.abs(b.m - innerHeight / 2) ? {s,m} : b; }, {s:stops[0],m:1e9}).s;
function target(){
  const r = active().querySelector(".mark").getBoundingClientRect();
  return [r.left, r.top];
}
function place(){ light.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`; }
if (reduce) {                       // no drift, no animation: snap to the section, draw one still frame
  const snap = () => { [x,y] = target(); place(); draw(4); };
  addEventListener("scroll",snap,{passive:true}); addEventListener("resize",snap); snap();
} else {
  [x,y] = target(); place();
  const tick = ms => {
    const dt = Math.min((ms - last) / 1000, .1); last = ms;
    const [tx,ty] = target(), k = 1 - Math.exp(-dt * 1.6);           // slow ease: ~1s to settle
    const bob = Math.sin(ms / 2600) * 6;                              // faint idle breathing in place
    x += (tx - x) * k; y += (ty + bob - y) * k; place(); draw(ms / 1000);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
