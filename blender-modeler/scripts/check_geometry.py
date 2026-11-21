"""Numeric geometry checks for a Blender scene.

Vision models are bad at spotting floating parts, gaps and wrong proportions in
renders, so this measures them instead:

- floating parts: every connected mesh island is a "part"; parts are linked when
  they touch or intersect, and anything not linked to the grounded group is
  reported with its distance to the nearest neighbour
- mesh health: non-manifold edges, loose geometry, degenerate faces, inverted
  normals, unapplied/negative object scale, n-gons
- spec checks (optional spec.json): overall size, per-part size, required
  attachments, missing parts

Runs inside Blender. From an MCP code tool or the Python console:

    import sys; sys.path.insert(0, r"<skill>/scripts")
    import check_geometry
    report = check_geometry.run(spec_path="spec.json")

Objects whose name starts with "_" (cutters, helpers) and objects hidden from
render are ignored. Objects with more than max_verts vertices (default 250k: a
scanned or sculpted host) are skipped with a note; scope the check to your new
parts with collection=/names= instead. Inside/outside tests use ray parity, not
face normals, so flipped faces don't fake penetration depths.

Spec keys used here: overall, parts, ground, contact_tolerance, collection,
units ("m" default, or "mm": spec numbers and the report are in mm),
expect_embedded ([[a, b], ...], fnmatch patterns: intended overlaps reported
only as a count), max_verts, host (a host object name: ground defaults to off).
"""

import fnmatch
import json
import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

GEOM_TYPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}
MAX_ISLANDS_PER_OBJECT = 64   # above this an object counts as one part (arrays, text)
MAX_SAMPLES = 3000            # vertices sampled per part for distance queries
MAX_VERTS = 250_000           # larger objects are skipped unless max_verts is raised
RAY_DIRS = [Vector(d).normalized() for d in ((0.0123, 0.0071, 1.0), (-0.0093, 0.0157, -1.0),
                                             (0.577, 0.5953, 0.5587))]
_UNITS = {"m": (1.0, "m"), "mm": (1000.0, "mm"), "cm": (100.0, "cm")}


def target_objects(collection=None, names=None):
    if names:
        objs = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
    elif collection:
        objs = list(bpy.data.collections[collection].all_objects)
    else:
        objs = list(bpy.context.scene.objects)
    out = []
    for o in objs:
        if o.type not in GEOM_TYPES or o.name.startswith("_"):
            continue
        if o.hide_render or not o.visible_get():
            continue
        out.append(o)
    return out


def _world_arrays(obj, depsgraph):
    """Evaluated mesh as numpy arrays in world space."""
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        nv, ne, nl, npoly = len(me.vertices), len(me.edges), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3)
        me.vertices.foreach_get("co", co)
        M = np.array(ev.matrix_world)
        co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        edges = np.empty(ne * 2, np.int64)
        me.edges.foreach_get("vertices", edges)
        lv = np.empty(nl, np.int64)
        me.loops.foreach_get("vertex_index", lv)
        le = np.empty(nl, np.int64)
        me.loops.foreach_get("edge_index", le)
        ls = np.empty(npoly, np.int64)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(npoly, np.int64)
        me.polygons.foreach_get("loop_total", lt)
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        tp = np.empty(nt, np.int64)
        me.loop_triangles.foreach_get("polygon_index", tp)
    finally:
        ev.to_mesh_clear()
    return {"co": co, "edges": edges.reshape(-1, 2), "lv": lv, "le": le, "ls": ls, "lt": lt,
            "tri": tri.reshape(-1, 3), "tri_poly": tp}


def _labels(nv, edges):
    """Connected-component label per vertex (numpy label propagation)."""
    lab = np.arange(nv)
    if len(edges):
        a, b = edges[:, 0], edges[:, 1]
        for _ in range(10000):
            la, lb = lab[a], lab[b]
            if np.array_equal(la, lb):
                break
            m = np.minimum(la, lb)
            np.minimum.at(lab, la, m)
            np.minimum.at(lab, lb, m)
            while True:
                nxt = lab[lab]
                if np.array_equal(nxt, lab):
                    break
                lab = nxt
    _, inv = np.unique(lab, return_inverse=True)
    return inv, int(inv.max()) + 1 if nv else 0


def _health(obj, m):
    co, tri = m["co"], m["tri"]
    nv, ne, npoly = len(co), len(m["edges"]), len(m["ls"])
    ecount = np.bincount(m["le"], minlength=ne)
    used = np.zeros(nv, bool)
    used[m["edges"].ravel()] = True
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.bincount(m["tri_poly"], weights=np.linalg.norm(cr, axis=1) / 2, minlength=npoly)
    boundary = int((ecount == 1).sum())
    multi = int((ecount > 2).sum())
    closed = boundary == 0 and multi == 0 and npoly > 0
    volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0) if closed else None
    return {
        "verts": nv,
        "faces": npoly,
        "open_boundary_edges": boundary,
        "nonmanifold_edges": multi,
        "loose_verts": int((~used).sum()),
        "loose_edges": int((ecount == 0).sum()),
        "degenerate_faces": int((area < 1e-12).sum()),
        "ngons": int((m["lt"] > 4).sum()),
        "closed": closed,
        "volume": round(volume, 9) if volume is not None else None,
        "scale": [round(s, 4) for s in obj.scale],
        "dimensions": [round(d, 4) for d in obj.dimensions],
    }


def _bbox_gap(a, b):
    d = 0.0
    for i in range(3):
        g = max(b["min"][i] - a["max"][i], a["min"][i] - b["max"][i], 0.0)
        d += g * g
    return math.sqrt(d)


def _min_distance(a, b, tol):
    """Smallest vertex-to-surface distance between two parts (both directions)."""
    if a["tree"].overlap(b["tree"]):
        return 0.0, True
    best = math.inf
    for src, dst in ((a, b), (b, a)):
        for p in src["samples"]:
            hit = dst["tree"].find_nearest(p)
            if hit[0] is not None and hit[3] < best:
                best = hit[3]
                if best <= tol:
                    return best, False
    return best, False


def _inside(part, p):
    """Ray-parity inside test against one part (majority of 3 rays). Face normals are
    not used: on real meshes some are flipped."""
    votes = 0
    eps = part["eps"]
    for k, d in enumerate(RAY_DIRS):
        n, q = 0, p
        for _ in range(256):
            h = part["tree"].ray_cast(q, d)[0]
            if h is None:
                break
            n += 1
            q = h + d * eps
        votes += n % 2
        if votes >= 2 or (k == 1 and votes == 0):
            break
    return votes >= 2


def _penetration(a, b):
    """Approximate how deep the two parts sink into each other (0 = just touching)."""
    depth = 0.0
    for src, dst in ((a, b), (b, a)):
        for p in src["samples"]:
            loc, _, _, dist = dst["tree"].find_nearest(p)
            if loc is not None and dist > depth and _inside(dst, p):
                depth = dist
    return depth


class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _fmt(v, fac=1.0):
    return "(" + ", ".join(f"{x * fac:.3f}" for x in v) + ")"


def _len(x, units, prec=4):
    fac, name = _UNITS[units]
    return f"{x * fac:.{max(prec - 3, 1) if fac > 1 else prec}f} {name}"


def _make_parts(obj, m, info):
    co = m["co"]
    island_of, n_islands = _labels(len(co), m["edges"])
    if n_islands > MAX_ISLANDS_PER_OBJECT:
        info.append(f"{obj.name}: {n_islands} islands, treated as one part.")
        island_of = np.zeros(len(co), np.int64)
    lv, ls, lt = m["lv"], m["ls"], m["lt"]
    pisl = island_of[lv[ls]]
    groups = np.unique(pisl)
    parts = []
    for k in groups:
        pidx = np.nonzero(pisl == k)[0]
        vidx = np.unique(np.concatenate([lv[ls[p]:ls[p] + lt[p]] for p in pidx]))
        remap = np.full(len(co), -1, np.int64)
        remap[vidx] = np.arange(len(vidx))
        coords = co[vidx]
        polys = [remap[lv[ls[p]:ls[p] + lt[p]]].tolist() for p in pidx]
        mn, mx = coords.min(0), coords.max(0)
        step = max(1, len(coords) // MAX_SAMPLES)
        label = obj.name if len(groups) == 1 else f"{obj.name}[island {k}]"
        parts.append({"label": label, "obj": obj.name,
                      "samples": [Vector(c) for c in coords[::step]],
                      "tree": BVHTree.FromPolygons(coords.tolist(), polys, epsilon=0.0),
                      "min": Vector(mn), "max": Vector(mx), "nverts": len(coords),
                      "eps": max(float(np.linalg.norm(mx - mn)) * 1e-6, 1e-9)})
    return parts, n_islands


def run(spec_path=None, spec=None, collection=None, names=None, tol=None,
        out_path=None, verbose=True, max_verts=None):
    if spec is None and spec_path:
        with open(spec_path, "r", encoding="utf-8-sig") as f:
            spec = json.load(f)
    spec = spec or {}
    units = spec.get("units", "m")
    if units not in _UNITS:
        units = "m"
    sf = 1.0 / _UNITS[units][0]                  # spec numbers -> metres
    max_verts = max_verts or spec.get("max_verts", MAX_VERTS)
    host_scoped = bool(spec.get("host") or (spec.get("channels") or {}).get("host"))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objs = target_objects(collection or spec.get("collection"), names)

    errors, warnings, info = [], [], []
    report = {"objects": {}, "errors": errors, "warnings": warnings, "info": info, "units": units}
    if not objs:
        errors.append("No visible geometry objects found.")
        return _finish(report, out_path, verbose)

    # Build parts (mesh islands) and per-object health.
    parts = []
    for obj in objs:
        n0 = len(obj.data.vertices) if obj.type == "MESH" else 0
        if n0 > max_verts:
            info.append(f"{obj.name}: {n0:,} verts > max_verts {max_verts:,}, skipped. Scope the check to your "
                        "new parts (collection=/names=), or raise max_verts.")
            continue
        m = _world_arrays(obj, depsgraph)
        h = _health(obj, m)
        report["objects"][obj.name] = h
        if not h["faces"]:
            errors.append(f"{obj.name}: no faces after modifiers (empty boolean result or bad curve?).")
            continue
        p, h["islands"] = _make_parts(obj, m, info)
        parts += p

        # Per-object health findings.
        if h["nonmanifold_edges"]:
            warnings.append(f"{obj.name}: {h['nonmanifold_edges']} edges shared by >2 faces (non-manifold).")
        if h["loose_verts"] or h["loose_edges"]:
            warnings.append(f"{obj.name}: loose geometry ({h['loose_verts']} verts, {h['loose_edges']} edges).")
        if h["degenerate_faces"]:
            warnings.append(f"{obj.name}: {h['degenerate_faces']} zero-area faces.")
        if h["volume"] is not None and h["volume"] < 0:
            errors.append(f"{obj.name}: closed mesh with inverted normals (negative volume).")
        if any(s < 0 for s in obj.scale):
            warnings.append(f"{obj.name}: negative scale {h['scale']} (flips normals, breaks bevels).")
        elif max(obj.scale) - min(obj.scale) > 1e-4 and obj.modifiers:
            warnings.append(f"{obj.name}: non-uniform scale {h['scale']} with modifiers; bevel/solidify will be uneven. Apply scale.")
        if h["open_boundary_edges"] and obj.type == "MESH":
            info.append(f"{obj.name}: open mesh ({h['open_boundary_edges']} boundary edges); fine for planes/cloth, bad for solids and 3D printing.")
        if h["ngons"]:
            info.append(f"{obj.name}: {h['ngons']} n-gons (matters only before subdivision).")
    if not parts:
        if not errors:
            errors.append("No checkable geometry (every object was skipped or empty).")
        return _finish(report, out_path, verbose)

    lo = Vector((min(p["min"][i] for p in parts) for i in range(3)))
    hi = Vector((max(p["max"][i] for p in parts) for i in range(3)))
    diag = (hi - lo).length
    if tol is None:
        tol = spec["contact_tolerance"] * sf if "contact_tolerance" in spec else max(1e-4, diag * 1e-3)
    report["overall"] = {"min": list(lo), "max": list(hi), "size": list(hi - lo),
                         "contact_tolerance": tol, "parts": len(parts)}

    expected = [tuple(pair) for pair in spec.get("expect_embedded", [])]

    def is_expected(a, b):
        return any((fnmatch.fnmatchcase(a, x) and fnmatch.fnmatchcase(b, y)) or
                   (fnmatch.fnmatchcase(a, y) and fnmatch.fnmatchcase(b, x)) for x, y in expected)

    # Contact graph between parts.
    n = len(parts)
    dsu = _DSU(n)
    contact = {}
    intersections = []
    for i in range(n):
        for j in range(i + 1, n):
            if _bbox_gap(parts[i], parts[j]) > tol:
                continue
            d, overlapping = _min_distance(parts[i], parts[j], tol)
            if d <= tol:
                dsu.union(i, j)
                contact[(i, j)] = True
                depth = _penetration(parts[i], parts[j]) if overlapping else 0.0
                intersections.append((parts[i]["label"], parts[j]["label"], depth,
                                      is_expected(parts[i]["obj"], parts[j]["obj"])))

    # Grounded group = the one containing the lowest part.
    lowest = min(range(n), key=lambda k: parts[k]["min"].z)
    root = dsu.find(lowest)
    want_ground = spec.get("ground", not host_scoped)
    if want_ground and abs(lo.z) > tol:
        warnings.append(f"Asset does not sit on the ground: lowest point z = {_len(lo.z, units)} (expected 0).")

    floating = [k for k in range(n) if dsu.find(k) != root]
    if floating:
        root_parts = [k for k in range(n) if dsu.find(k) == root]
        groups = {}
        for k in floating:
            groups.setdefault(dsu.find(k), []).append(k)
        for members in groups.values():
            best, best_k, best_r = math.inf, None, None
            for k in members:
                # exact distance only for the closest candidates by bbox gap
                cands = sorted(root_parts, key=lambda r: _bbox_gap(parts[k], parts[r]))[:4]
                for r in cands:
                    d, _ = _min_distance(parts[k], parts[r], 0.0)
                    if d < best:
                        best, best_k, best_r = d, k, r
            names_ = ", ".join(parts[k]["label"] for k in members)
            c = (parts[best_k]["min"] + parts[best_k]["max"]) / 2
            errors.append(
                f"FLOATING: [{names_}] is not connected to the main body. "
                f"Closest gap {_len(best, units)} between {parts[best_k]['label']} (center {_fmt(c)}) "
                f"and {parts[best_r]['label']}.")

    shown = [x for x in intersections if not x[3]]
    if shown:
        desc = [f"{a}-{b} " + (f"embedded {_len(d, units, 3)}" if d > tol * 2 else "flush")
                for a, b, d, _ in shown]
        info.append("Contacts: " + "; ".join(desc))
    if len(shown) < len(intersections):
        info.append(f"{len(intersections) - len(shown)} expected embedded contacts (expect_embedded).")
    report["contacts"] = [{"a": a, "b": b, "depth": d, "expected": e} for a, b, d, e in intersections]

    # Object-level contact lookup for spec checks.
    def objects_touch(a_name, b_name):
        for (i, j) in contact:
            if {parts[i]["obj"], parts[j]["obj"]} == {a_name, b_name}:
                return True
        return False

    def objects_gap(a_name, b_name):
        pa = [p for p in parts if p["obj"] == a_name]
        pb = [p for p in parts if p["obj"] == b_name]
        return min((_min_distance(x, y, 0.0)[0] for x in pa for y in pb), default=math.inf)

    # Spec checks.
    if "overall" in spec:
        _check_dims("Overall size", list(hi - lo), spec["overall"], errors, units)
    for pname, pspec in spec.get("parts", {}).items():
        obj = bpy.data.objects.get(pname)
        if obj is None or obj.name not in report["objects"]:
            errors.append(f"Missing part from spec: '{pname}'.")
            continue
        if "dims" in pspec:
            _check_dims(f"{pname} dimensions", list(obj.dimensions), pspec, errors, units)
        for other in pspec.get("attached_to", []):
            if other not in report["objects"]:
                continue
            if not objects_touch(pname, other):
                errors.append(f"NOT ATTACHED: {pname} should touch {other}; gap {_len(objects_gap(pname, other), units)}.")

    return _finish(report, out_path, verbose)


def _check_dims(label, actual, pspec, errors, units="m"):
    want = pspec.get("dims") or pspec.get("size")
    if not want:
        return
    fac, uname = _UNITS[units]
    tol = pspec.get("tol")
    bad = []
    for axis, a, w in zip("XYZ", actual, want):
        if w is None:
            continue
        a = a * fac                      # compare in spec units
        t = tol if tol is not None else max(0.002 * fac, abs(w) * 0.05)
        if abs(a - w) > t:
            bad.append(f"{axis} {a:.3f} vs {w:.3f}")
    if bad:
        errors.append(f"{label} off spec: " + "; ".join(bad) + f" ({uname}).")


def _finish(report, out_path, verbose):
    report["summary"] = {"errors": len(report["errors"]), "warnings": len(report["warnings"])}
    text = format_report(report)
    report["text"] = text
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in report.items() if k != "text"}, f, indent=2, default=list)
    if verbose:
        print(text)
    return report


def format_report(report):
    lines = []
    s = report.get("summary", {})
    ov = report.get("overall")
    fac, uname = _UNITS[report.get("units", "m")]
    lines.append(f"GEOMETRY CHECK: {s.get('errors', 0)} errors, {s.get('warnings', 0)} warnings")
    if ov:
        lines.append(f"  overall size ({uname}): {_fmt(ov['size'], fac)}  parts: {ov['parts']}  "
                     f"contact tol: {ov['contact_tolerance'] * fac:.4f}")
    for key in ("errors", "warnings", "info"):
        for msg in report[key]:
            lines.append(f"  [{key[:-1].upper() if key != 'info' else 'INFO'}] {msg}")
    lines.append("  objects:")
    for name, h in report["objects"].items():
        lines.append(f"    {name}: dims {_fmt(h['dimensions'], fac)} verts {h['verts']} faces {h['faces']} islands {h.get('islands', '-')}")
    return "\n".join(lines)
