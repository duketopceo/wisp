"""Clickable parts of a small 3D model (B13), from a glTF or GLB file.

A `::model[url=...]` card shows a model whose parts can be clicked to ask
about. The card needs only each part's name and bounding box, so this reads
no mesh data: the glTF JSON names every node and its mesh, and the spec
requires a POSITION accessor to carry `min` and `max`. The bytes of the
binary buffer are never opened, which keeps a hostile file harmless: the
worst it can do is fail to parse.

Limits: JSON of at most `MAX_JSON` bytes, `MAX_NODES` nodes, `MAX_PARTS`
parts reported; a buffer or image that points outside the file (anything
but a `data:` URI) is refused, so a model cannot name a second fetch.
"""
from __future__ import annotations

import json
import math
import struct

MAX_JSON = 2 * 1024 * 1024
MAX_NODES = 2000
MAX_PARTS = 48
MAX_DEPTH = 32
_GLB_MAGIC = 0x46546C67          # "glTF"
_CHUNK_JSON = 0x4E4F534A         # "JSON"


class ModelError(Exception):
    """The file is not a model this card can show. `str(e)` is speakable."""


def _json_of(data: bytes) -> dict:
    if len(data) >= 12 and struct.unpack_from("<I", data, 0)[0] == _GLB_MAGIC:
        pos = 12
        while pos + 8 <= len(data):
            n, kind = struct.unpack_from("<II", data, pos)
            pos += 8
            if kind == _CHUNK_JSON:
                if n > MAX_JSON or pos + n > len(data):
                    raise ModelError("That 3D file is malformed.")
                data = data[pos:pos + n]
                break
            pos += n + (-n % 4)
        else:
            raise ModelError("That 3D file has no model description.")
    elif len(data) > MAX_JSON:
        raise ModelError("That 3D file is too large to show.")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ModelError("That file isn't a 3D model I can show.")
    if not isinstance(doc, dict) or not isinstance(doc.get("asset"), dict):
        raise ModelError("That file isn't a 3D model I can show.")
    return doc


def _num(v, default=0.0) -> float:
    return float(v) if isinstance(v, (int, float)) \
        and not isinstance(v, bool) and math.isfinite(v) else default


def _vec(v, n, default):
    if isinstance(v, list) and len(v) == n:
        return [_num(x, d) for x, d in zip(v, default)]
    return list(default)


def _matmul(a, b):
    """4x4 column-major product a·b."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
            for c in range(4) for r in range(4)]


def _local(node: dict):
    m = node.get("matrix")
    if isinstance(m, list) and len(m) == 16:
        return [_num(x) for x in m]
    t = _vec(node.get("translation"), 3, (0, 0, 0))
    q = _vec(node.get("rotation"), 4, (0, 0, 0, 1))
    s = _vec(node.get("scale"), 3, (1, 1, 1))
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    x, y, z, w = (c / n for c in q)
    return [
        (1 - 2 * (y * y + z * z)) * s[0], (2 * (x * y + z * w)) * s[0],
        (2 * (x * z - y * w)) * s[0], 0,
        (2 * (x * y - z * w)) * s[1], (1 - 2 * (x * x + z * z)) * s[1],
        (2 * (y * z + x * w)) * s[1], 0,
        (2 * (x * z + y * w)) * s[2], (2 * (y * z - x * w)) * s[2],
        (1 - 2 * (x * x + y * y)) * s[2], 0,
        t[0], t[1], t[2], 1]


def _corners(lo, hi, m):
    out = []
    for i in range(8):
        p = (hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1],
             hi[2] if i & 4 else lo[2])
        out.append([m[0 + r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2]
                    + m[12 + r] for r in range(3)])
    return out


def _check_uris(doc: dict) -> None:
    for key in ("buffers", "images"):
        for item in doc.get(key) or []:
            uri = item.get("uri") if isinstance(item, dict) else None
            if uri and not str(uri).startswith("data:"):
                raise ModelError("That 3D file points at other files, so "
                                 "I won't show it.")


def _mesh_box(doc: dict, mesh_idx):
    meshes, accs = doc.get("meshes") or [], doc.get("accessors") or []
    if not isinstance(mesh_idx, int) or not 0 <= mesh_idx < len(meshes):
        return None, ""
    mesh = meshes[mesh_idx] if isinstance(meshes[mesh_idx], dict) else {}
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for prim in mesh.get("primitives") or []:
        a = ((prim or {}).get("attributes") or {}).get("POSITION")
        if not isinstance(a, int) or not 0 <= a < len(accs):
            continue
        acc = accs[a] if isinstance(accs[a], dict) else {}
        amin, amax = acc.get("min"), acc.get("max")
        if not (isinstance(amin, list) and isinstance(amax, list)
                and len(amin) == len(amax) == 3):
            continue
        for i in range(3):
            lo[i] = min(lo[i], _num(amin[i]))
            hi[i] = max(hi[i], _num(amax[i]))
    if lo[0] > hi[0]:
        return None, str(mesh.get("name") or "")
    return (lo, hi), str(mesh.get("name") or "")


def parse(data: bytes) -> dict:
    """{title, parts: [{name, box: [x0,y0,z0,x1,y1,z1]}]}: boxes are in the
    model's own space, scaled so the largest side is 1 and centred at the
    origin. Raises ModelError for anything that is not a showable model."""
    doc = _json_of(data)
    _check_uris(doc)
    nodes = doc.get("nodes") or []
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ModelError("That 3D model is too complex to show.")
    scenes = doc.get("scenes") or []
    si = doc.get("scene", 0)
    if scenes and isinstance(si, int) and 0 <= si < len(scenes) \
            and isinstance(scenes[si], dict):
        roots = scenes[si].get("nodes") or []
    else:
        child = {c for n in nodes if isinstance(n, dict)
                 for c in n.get("children") or [] if isinstance(c, int)}
        roots = [i for i in range(len(nodes)) if i not in child]
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    found, seen = [], set()

    def walk(i, parent, depth):
        if (not isinstance(i, int) or not 0 <= i < len(nodes)
                or i in seen or depth > MAX_DEPTH
                or not isinstance(nodes[i], dict)):
            return
        seen.add(i)
        node = nodes[i]
        world = _matmul(parent, _local(node))
        box, mesh_name = _mesh_box(doc, node.get("mesh"))
        if box:
            pts = _corners(box[0], box[1], world)
            found.append((str(node.get("name") or mesh_name or ""), pts))
        for c in node.get("children") or []:
            walk(c, world, depth + 1)

    for r in roots:
        walk(r, ident, 0)
    if not found:
        raise ModelError("That 3D file has no parts I can show.")
    allpts = [p for _, pts in found for p in pts]
    lo = [min(p[i] for p in allpts) for i in range(3)]
    hi = [max(p[i] for p in allpts) for i in range(3)]
    span = max(hi[i] - lo[i] for i in range(3)) or 1.0
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    parts, used = [], {}
    for k, (name, pts) in enumerate(found[:MAX_PARTS]):
        name = " ".join(name.replace("_", " ").split())[:40] \
            or f"part {k + 1}"
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = f"{name} {used[name]}"
        box = [round((min(p[i] for p in pts) - mid[i]) / span, 4)
               for i in range(3)]
        box += [round((max(p[i] for p in pts) - mid[i]) / span, 4)
                for i in range(3)]
        parts.append({"name": name, "box": box})
    title = ""
    if scenes and isinstance(si, int) and 0 <= si < len(scenes) \
            and isinstance(scenes[si], dict):
        title = str(scenes[si].get("name") or "")[:60]
    return {"title": title, "parts": parts}
