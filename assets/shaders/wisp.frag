#version 440
// Wisp creature (Ember U7). One quad, one fragment shader, about 40 ALU:
// a soft corona (the only soft edge on screen), a body whose edge frays as
// cohesion drops, a core, and a wick that leans toward the gaze. Dark mode
// adds light; light mode draws ink in water (same shape, opaque tone,
// alpha from the falloff). Uniform values come from creature.js.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 ember;      // tone: ember, needsYou, fail or inkMuted token
    vec4 core;       // emberCore token
    vec2 gaze;       // wick and core lean, -1..1
    float energy;    // brightness 0..1
    float cohesion;  // 1 clean disc, 0 frayed
    float heat;      // 0 ember .. 1 core-warm
    float time;      // seconds, already quantized by the host
    float mode;      // 0 dark additive, 1 light ink
    float dashed;    // 1 for offline: ring only, no body
};

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x),
               mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}

void main() {
    vec2 p = (qt_TexCoord0 - 0.5) * 2.0;
    float r = length(p);
    // fray: low cohesion lets noise bite into the edge
    float n = vnoise(p * 3.0 + vec2(time * 0.35, -time * 0.2));
    float edge = 0.52 + (n - 0.5) * (1.0 - cohesion) * 0.5;
    float body = 1.0 - smoothstep(edge - 0.08 * cohesion - 0.02, edge, r);
    float corona = exp(-pow(r / (0.55 + 0.35 * energy), 2.0)) * (0.25 + 0.75 * energy);
    // wick: a small tail opposite the gaze, curling with time when thinking
    vec2 w = p + gaze * 0.28;
    float wick = exp(-dot(w, w) * 9.0) * (0.35 + 0.4 * heat);
    // core
    vec2 c = p - gaze * 0.10;
    float core_a = exp(-dot(c, c) * 16.0) * (0.55 + 0.45 * energy);
    float ring = dashed * smoothstep(0.04, 0.0, abs(r - 0.7)) *
        step(0.5, fract(atan(p.y, p.x) * 1.9099 + 0.5));
    float a = clamp(corona * 0.55 + body * (0.35 + 0.5 * energy) + wick * 0.4 + ring, 0.0, 1.0);
    a *= (1.0 - dashed * 0.85) + dashed * ring;
    vec3 tone = mix(ember.rgb, core.rgb, clamp(core_a * (0.4 + heat), 0.0, 1.0));
    if (mode > 0.5) tone = mix(ember.rgb * 0.55, ember.rgb, 1.0 - core_a);
    float alpha = clamp(a + core_a * 0.5 * (1.0 - dashed), 0.0, 1.0) * qt_Opacity;
    fragColor = vec4(tone * alpha, alpha);
}
