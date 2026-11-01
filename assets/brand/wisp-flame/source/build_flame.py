"""Build the Wisp flame (C2: translucent flame with a bright heart) in Blender.

Source of truth for assets/brand/wisp-flame/. Run headless:

    blender --background --factory-startup --python build_flame.py -- --out DIR [--frames N] [--size PX]

It builds the scene from nothing, saves DIR/wisp-flame.blend, exports
DIR/wisp-flame.glb (one glTF animation per state, NLA_TRACKS), renders each
state's loop as PNG frames into DIR/frames/<state>/ and a still into
DIR/still-512.png. Render settings come from the arguments, not the scene.

States differ in the glTF only through transforms and the tip-bend morph
weight; emission strength is keyed for the renders only (glTF players do not
animate material values).
"""
import argparse
import math
import os
import sys

import bmesh
import bpy

GUIDE = (0x7D / 255, 0xCF / 255, 0xFF / 255, 1.0)
MID = (0x29 / 255, 0x5F / 255, 0x85 / 255, 1.0)
HOT = (0xEA / 255, 0xF7 / 255, 0xFF / 255, 1.0)
STATES = ("idle", "listening", "thinking", "speaking")
TAU = 2 * math.pi


def srgb_to_linear(c):
    def ch(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (ch(c[0]), ch(c[1]), ch(c[2]), c[3])


GUIDE_L, MID_L, HOT_L = (srgb_to_linear(c) for c in (GUIDE, MID, HOT))


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--frames", type=int, default=48)
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--no-render", action="store_true")
    return p.parse_args(argv)


def reset():
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
                 bpy.data.actions, bpy.data.cameras, bpy.data.lights,
                 bpy.data.shape_keys):
        for item in list(coll):
            try:
                coll.remove(item)
            except (RuntimeError, ReferenceError, AttributeError):
                pass


# --- geometry -------------------------------------------------------------

def flame_profile(n=48, belly=0.47, height=1.85, base=-0.55):
    """(radius, z): round base (sqrt near the bottom) tapering to a fine point.

    sqrt(t(1-t)) * (1-t)^0.8 peaks near t = 0.28; dividing by that peak makes
    `belly` the widest radius."""
    peak = math.sqrt(0.278 * 0.722) * 0.722 ** 0.8
    pts = []
    for i in range(n + 1):
        t = i / n
        r = belly * math.sqrt(t * (1 - t)) * (1 - t) ** 0.8 / peak
        pts.append((max(r, 0.0), base + t * height))
    return pts


def revolve(profile, segs=48):
    """Explicit vertices and faces (no modifier) so the shape key exports."""
    verts, faces, rings = [], [], []
    for r, y in profile:
        if r < 1e-4:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, y))
            continue
        ring = []
        for s in range(segs):
            a = TAU * s / segs
            ring.append(len(verts))
            verts.append((r * math.cos(a), r * math.sin(a), y))
        rings.append(ring)
    for lo, hi in zip(rings, rings[1:]):
        if len(lo) == 1 and len(hi) > 1:
            faces += [(lo[0], hi[(s + 1) % segs], hi[s]) for s in range(segs)]
        elif len(hi) == 1 and len(lo) > 1:
            faces += [(lo[s], lo[(s + 1) % segs], hi[0]) for s in range(segs)]
        elif len(lo) > 1:
            faces += [(lo[s], lo[(s + 1) % segs], hi[(s + 1) % segs], hi[s]) for s in range(segs)]
    return verts, faces


def mesh_object(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def sphere_object(name, radius, segs=32, rings=16, ico=False):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    if ico:
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=radius)
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def add_bend_key(shell):
    """Shape key 'bend': the tip leans +X, growing toward the top."""
    shell.shape_key_add(name="Basis", from_mix=False)
    kb = shell.shape_key_add(name="bend", from_mix=False)
    kb.slider_min, kb.slider_max = -1.0, 1.0
    for i, v in enumerate(shell.data.vertices):
        x, y, z = v.co
        k = smoothstep(-0.1, 1.3, z)
        kb.data[i].co = (x + k * k * 0.6, y + k * k * 0.1, z)
    return kb


# --- materials --------------------------------------------------------------

def principled(name, base, emission, strength, alpha, blended):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Emission Color"].default_value = emission
    bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Alpha"].default_value = alpha
    bsdf.inputs["Roughness"].default_value = 0.35
    if blended:
        m.surface_render_method = "BLENDED"
        m.use_transparency_overlap = False
    m.use_backface_culling = blended
    return m


def rim_shell_material(m):
    """Render-only: Fresnel rim in cyan over the deep-blue mid, edges more opaque."""
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = tuple(c * 0.8 for c in MID_L[:3]) + (1.0,)
    mix.inputs[7].default_value = GUIDE_L
    nt.links.new(lw.outputs["Facing"], mix.inputs[0])
    nt.links.new(mix.outputs[2], bsdf.inputs["Emission Color"])
    amap = nt.nodes.new("ShaderNodeMapRange")
    amap.inputs["To Min"].default_value = 0.30
    amap.inputs["To Max"].default_value = 1.0
    nt.links.new(lw.outputs["Facing"], amap.inputs["Value"])
    nt.links.new(amap.outputs["Result"], bsdf.inputs["Alpha"])
    bsdf.inputs["Emission Strength"].default_value = 1.6
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)


def halo_material():
    """Render-only soft glow: an emissive volume, so it has no transparency
    sorting against the shell and stays smooth (thicker means brighter)."""
    m = bpy.data.materials.new("halo")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = GUIDE_L
    em.inputs["Strength"].default_value = 1.4
    nt.links.new(em.outputs["Emission"], out.inputs["Volume"])
    return m


# --- animation --------------------------------------------------------------

def state_curves(state, t):
    """Per-state values at loop phase t in [0, 1). Every term is periodic in t."""
    s1, s2, s3 = math.sin(TAU * t), math.sin(2 * TAU * t), math.sin(3 * TAU * t)
    if state == "idle":
        return dict(bend=0.55 * s1, heart=1.0 + 0.07 * s1, glow=3.5 + 0.6 * s1, tail=1.0, swirl=0.0, body=(1.0, 1.0))
    if state == "listening":
        return dict(bend=0.1 * s1, heart=1.3 + 0.04 * s2, glow=6.5 + 0.4 * s2, tail=0.7, swirl=0.0, body=(0.95, 1.08))
    if state == "thinking":
        return dict(bend=0.35 * s2, heart=1.0 + 0.2 * s3, glow=4.0 + 2.2 * s3, tail=0.85, swirl=1.0, body=(1.0, 1.0))
    # speaking: syllable-like pulses
    pulse = abs(math.sin(2 * TAU * t)) * 0.7 + abs(math.sin(3 * TAU * t + 0.6)) * 0.3
    return dict(bend=0.28 * s1, heart=1.05 + 0.32 * pulse, glow=4.0 + 4.0 * pulse, tail=1.0, swirl=0.0,
                body=(1.0 + 0.04 * pulse, 1.0 + 0.04 * pulse))


TAIL_BASE = [(0.0, 1.42), (0.03, 1.58), (0.07, 1.72), (0.12, 1.85)]


def push_to_track(idb, state):
    """Move idb's active action into an NLA track named for the state."""
    ad = idb.animation_data
    act = ad.action
    # Blender 5 may share one action between an object and its data (one slot
    # each), so keep the slot this data-block was actually animated through.
    slot = getattr(ad, "action_slot", None)
    act.name = f"{state}.anim"
    track = ad.nla_tracks.new()
    track.name = state
    strip = track.strips.new(state, 1, act)
    if slot is not None and hasattr(strip, "action_slot"):
        strip.action_slot = slot
    strip.extrapolation = "NOTHING"
    ad.action = None


def key_states(shell, heart, tails, heart_mat, frames):
    """Key every state on its own NLA track (see module docstring)."""
    key = shell.data.shape_keys
    bend = key.key_blocks["bend"]
    bsdf = next(n for n in heart_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for state in STATES:
        for f in range(1, frames + 2):  # frame frames+1 == frame 1: seamless
            t = ((f - 1) % frames) / frames
            v = state_curves(state, t)
            bend.value = v["bend"]
            bend.keyframe_insert("value", frame=f)
            heart.scale = (v["heart"],) * 3
            heart.keyframe_insert("scale", frame=f)
            bx, bz = v["body"]
            shell.scale = (bx, bx, bz)
            shell.keyframe_insert("scale", frame=f)
            bsdf.inputs["Emission Strength"].default_value = v["glow"]
            bsdf.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)
            for i, ob in enumerate(tails):
                x0, z0 = TAIL_BASE[i]
                ph = t - i * 0.08
                dx = 0.1 * math.sin(TAU * ph) * (1 + i * 0.4)
                dy = 0.0
                if v["swirl"]:
                    dx = 0.14 * math.cos(TAU * (t + i * 0.25))
                    dy = 0.14 * math.sin(TAU * (t + i * 0.25))
                ob.location = (x0 + dx, dy, 1.42 + (z0 - 1.42) * v["tail"])
                ob.keyframe_insert("location", frame=f)
        push_to_track(key, state)
        push_to_track(shell, state)
        push_to_track(heart, state)
        push_to_track(heart_mat.node_tree, state)
        for ob in tails:
            push_to_track(ob, state)


def solo_state(ids, state):
    for idb in ids:
        ad = idb.animation_data
        if not ad:
            continue
        for track in ad.nla_tracks:
            track.mute = track.name != state


# --- scene ------------------------------------------------------------------

def build(frames):
    reset()
    scene = bpy.context.scene
    verts, faces = revolve(flame_profile())
    shell = mesh_object("shell", verts, faces)
    add_bend_key(shell)
    heart = sphere_object("heart", 0.12)
    # A hair toward the camera so blended sorting always draws it over the shell.
    heart.location = (0.0, -0.02, -0.12)
    tails = []
    for i, (x, z) in enumerate(TAIL_BASE):
        ob = sphere_object(f"tail{i}", 0.06 - i * 0.011, ico=True)
        ob.location = (x, 0.0, z)
        tails.append(ob)
    # Render-only soft glow around the heart (not exported).
    halo = sphere_object("halo", 0.36)
    halo.location = (0.0, 0.0, -0.1)
    halo.parent = heart
    halo.location = (0.0, -0.01, 0.0)

    shell_mat = principled("shell", MID_L, GUIDE_L, 0.8, 0.38, True)
    heart_mat = principled("heart", HOT_L, HOT_L, 4.0, 1.0, False)
    # Render-only copy that carries the keyed glow; the exported heart keeps a
    # static emission (the glTF exporter drops animated emission entirely).
    heart_glow = heart_mat.copy()
    heart_glow.name = "heart.render"
    tail_mat = principled("tail", GUIDE_L, GUIDE_L, 1.5, 0.85, True)
    shell.data.materials.append(shell_mat)
    heart.data.materials.append(heart_mat)
    for ob in tails:
        ob.data.materials.append(tail_mat)
    halo.data.materials.append(halo_material())

    key_states(shell, heart, tails, heart_glow, frames)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 3.0
    cam = bpy.data.objects.new("cam", cam_data)
    cam.location = (0.0, -6.0, 0.7)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("world") if not scene.world else scene.world
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.0035, 0.0039, 0.0058, 1)
        bg.inputs["Strength"].default_value = 1.0
    scene.frame_start, scene.frame_end = 1, frames
    scene.render.fps = 24
    return dict(shell=shell, heart=heart, tails=tails, halo=halo,
                shell_mat=shell_mat, heart_mat=heart_mat, heart_glow=heart_glow)


def export_glb(parts, path):
    keep = {parts["shell"].name, parts["heart"].name} | {o.name for o in parts["tails"]}
    for ob in bpy.context.scene.objects:
        ob.select_set(ob.name in keep)
    for idb in nla_ids(parts):
        if idb.animation_data:
            for track in idb.animation_data.nla_tracks:
                track.mute = False
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True,
        export_animation_mode="NLA_TRACKS", export_morph=True,
        export_apply=False, export_yup=True, export_materials="EXPORT",
        export_force_sampling=True)


def nla_ids(parts):
    return [parts["shell"].data.shape_keys, parts["shell"], parts["heart"], parts["heart_glow"].node_tree, *parts["tails"]]


def set_engine(scene, size):
    for name in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = name
            break
        except TypeError:
            continue
    scene.render.film_transparent = True
    # AgX/Filmic desaturate bright emission toward white; keep the guide cyan.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 128


def render(parts, out, frames, size):
    scene = bpy.context.scene
    rim_shell_material(parts["shell_mat"])
    parts["heart"].data.materials[0] = parts["heart_glow"]
    set_engine(scene, size)
    for state in STATES:
        solo_state(nla_ids(parts), state)
        d = os.path.join(out, "frames", state)
        os.makedirs(d, exist_ok=True)
        scene.render.filepath = os.path.join(d, "")
        bpy.ops.render.render(animation=True)
    solo_state(nla_ids(parts), "idle")
    scene.frame_set(1)
    set_engine(scene, 512)
    scene.render.filepath = os.path.join(out, "still-512.png")
    bpy.ops.render.render(write_still=True)


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    parts = build(a.frames)
    export_glb(parts, os.path.join(a.out, "wisp-flame.glb"))
    if not a.no_render:
        render(parts, a.out, a.frames, a.size)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(a.out, "wisp-flame.blend"), compress=True)
    print("wisp-flame: done", a.out)


if __name__ == "__main__":
    main()
