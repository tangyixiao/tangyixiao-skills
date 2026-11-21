"""Verify the result of a boolean assembly (cut channels, cavities, splits).

Booleans fail quietly: a cutter that stops 0.01 mm short leaves a paper-thin skin
that seals a magnet well, a cut that grazes the surface opens a hole nobody
wanted, a split leaves the lid in 4 pieces, two parts fuse. After every final
assembly, measure:

- shells(obj): watertight connected components, with boundary / non-manifold
  edge counts and signed volume (< 0 = an enclosed void shell)
- skin_openings(original, finals): sample the ORIGINAL outer skin; points that
  are no longer on any final part are openings. They are clustered and matched
  against your list of intended openings; unexpected ones are errors, and
  intended ones that are missing (sealed!) are errors too
- tunnels_open(channels, final): % of each channel centre line that is still
  inside solid material (should be 0)
- cavity_empty(final, cavity): % of a cavity's volume that is solid (should be 0)
- touching_parts(a, b): parts that should be separate but touch or overlap

Spec (key "verify"; numbers in "units", default the spec's units, else metres):

    "verify": {
      "units": "mm",
      "final": "Body (final)",  "parts": ["Lid (print)"],      # final objects
      "original": "Body",                                      # the pre-cut host (hidden copy)
      "samples": 60000, "tol": 0.5, "cell": 25,
      "openings": [{"name": "eye pocket", "point": [x, y, z], "radius": 12},
                   {"name": "power exit", "object": "CUT power", "required": true}],
      "ignore": [{"box": [[x0, y0, z0], [x1, y1, z1]]}],          # e.g. a flattened sole
      "tunnels": {"collection": "WIRING"},                     # or "names": [...]
      "cavities": ["CUT bay"],                                 # objects or {"name", "box"}
      "apart": [["Lid (print)", "Body (final)"]],
      "shells": {"Body (final)": 1}
    }

Runs inside Blender: verify_cuts.run(spec_path=...), or headless:
blender -b final.blend --python verify_cuts.py -- --spec spec.json [--out dir]
(exit code 2 on errors).
"""

import fnmatch
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostkit  # noqa: E402
import routekit  # noqa: E402

_PER = {"m": 1.0, "cm": 0.01, "mm": 0.001}


def _obj(o):
    return bpy.data.objects[o] if isinstance(o, str) else o


def _mesh_np(obj):
    """World verts (UNITS), edges, triangles of the evaluated mesh."""
    obj = _obj(obj)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        ed = np.empty(len(me.edges) * 2, np.int64)
        me.edges.foreach_get("vertices", ed)
        le = np.empty(len(me.loops), np.int64)
        me.loops.foreach_get("edge_index", le)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        M = np.array(ev.matrix_world)
    finally:
        ev.to_mesh_clear()
    co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    return co / hostkit.unit_scale(), ed.reshape(-1, 2), le, tri.reshape(-1, 3)


def _labels(nv, edges):
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
    return lab


def shells(obj):
    """Connected shells of a mesh, largest first: [{"verts", "faces", "boundary_edges",
    "nonmanifold_edges", "volume" (UNITS^3, signed; < 0 = enclosed void), "center", "size"}]."""
    co, ed, le, tri = _mesh_np(obj)
    lab = _labels(len(co), ed)
    ecount = np.bincount(le, minlength=len(ed))
    elab = lab[ed[:, 0]] if len(ed) else np.zeros(0, np.int64)
    tlab = lab[tri[:, 0]] if len(tri) else np.zeros(0, np.int64)
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    out = []
    for r in np.unique(lab):
        vm = lab == r
        P = co[vm]
        em = elab == r
        out.append({"verts": int(vm.sum()), "faces": int((tlab == r).sum()),
                    "boundary_edges": int((ecount[em] == 1).sum()),
                    "nonmanifold_edges": int((ecount[em] > 2).sum()),
                    "volume": float(vol[tlab == r].sum()),
                    "center": P.mean(0).round(4).tolist(), "size": np.ptp(P, axis=0).round(4).tolist()})
    out.sort(key=lambda s: -s["verts"])
    return out


def _tris(obj):
    co, _, _, tri = _mesh_np(obj)
    return co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]


def _sample(a, b, c, n, rng, mask=None):
    if mask is not None:
        a, b, c = a[mask], b[mask], c[mask]
    if not len(a) or n <= 0:
        return np.zeros((0, 3)), 0.0
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    k = rng.choice(len(a), size=n, p=area / area.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    return a[k] + (b[k] - a[k]) * u[:, None] + (c[k] - a[k]) * v[:, None], float(area.sum())


def surface_samples(obj, n, seed=1):
    """n area-weighted random points on the object's surface (world, UNITS), and its area."""
    return _sample(*_tris(obj), n, np.random.default_rng(seed))


def _region_sphere(reg):
    if "point" in reg:
        return np.asarray(reg["point"], float), float(reg.get("radius", 0))
    if "box" in reg:
        lo, hi = np.asarray(reg["box"][0], float), np.asarray(reg["box"][1], float)
        return (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 + reg.get("radius", 0)
    if "object" in reg:
        W = hostkit.world_verts(reg["object"])
        lo, hi = W.min(0), W.max(0)
        return (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 + reg.get("radius", 0)
    return None, 0.0


def _in_region(p, reg):
    if "box" in reg:
        lo, hi = np.asarray(reg["box"][0], float), np.asarray(reg["box"][1], float)
        return bool(np.all(p >= lo - reg.get("radius", 0)) and np.all(p <= hi + reg.get("radius", 0)))
    if "point" in reg:
        return float(np.linalg.norm(p - np.asarray(reg["point"], float))) <= reg.get("radius", 0)
    if "object" in reg:
        return float(hostkit.clearance([p], reg["object"])[0]) >= -reg.get("radius", 0)
    return False


def skin_openings(original, finals, samples=60000, tol=None, cell=None, openings=(), ignore=(), local=400):
    """Where did the original skin disappear? Returns {"samples", "gone", "clusters",
    "unexpected", "missing"}. A cluster matches an opening when any of its points lies
    in the opening's region (point+radius, box, or object). Openings are required
    unless "required": false. Besides the uniform samples, `local` extra samples are
    taken around every declared opening, so small holes (a 6 mm drop on a 1 m body)
    are not missed for lack of samples. Cluster "area" counts uniform samples only."""
    s = hostkit.unit_scale()
    tol = tol if tol is not None else 0.0005 / s
    rng = np.random.default_rng(1)
    A, B, C = _tris(original)
    P, area = _sample(A, B, C, samples, rng)
    w = np.full(len(P), area / max(samples, 1))
    cen = (A + B + C) / 3
    for o in openings:
        c, rad = _region_sphere(o)
        if c is None:
            continue
        Q, _ = _sample(A, B, C, local, rng, np.linalg.norm(cen - c, axis=1) <= rad * 1.5 + tol)
        P = np.vstack([P, Q])
        w = np.concatenate([w, np.zeros(len(Q))])
    if ignore:
        keep = np.array([not any(_in_region(p, g) for g in ignore) for p in P])
        P, w = P[keep], w[keep]
    best = np.full(len(P), np.inf)
    for f in finals:
        _, d = hostkit.nearest(P, f)
        best = np.minimum(best, d)
    gm = best > tol
    gone, gw = P[gm], w[gm]
    clusters = []
    if len(gone):
        cell = cell if cell is not None else 0.025 / s
        lab = hostkit.cluster_points(gone, cell)
        for r in np.unique(lab):
            G = gone[lab == r]
            clusters.append({"n": int(len(G)), "center": G.mean(0).round(3).tolist(),
                             "size": np.ptp(G, axis=0).round(3).tolist(),
                             "area": round(float(gw[lab == r].sum()), 6), "pts": G})
        clusters.sort(key=lambda c: -c["n"])
    hit = set()
    for c in clusters:
        c["matches"] = [o["name"] for o in openings if any(_in_region(p, o) for p in c["pts"][:400])]
        hit |= set(c["matches"])
    unexpected = [c for c in clusters if not c["matches"]]
    missing = [o["name"] for o in openings if o.get("required", True) and o["name"] not in hit]
    for c in clusters:
        del c["pts"]
    return {"samples": int(len(P)), "gone": int(len(gone)), "clusters": clusters,
            "unexpected": unexpected, "missing": missing}


def tunnels_open(channels, final, spacing=None):
    """{name: {"blocked_pct", "blocked_at"}} for channel objects (curves, tube/tube_mesh
    objects with a stored centre line) or {name: points} polylines, against the final solid."""
    import check_channels
    s = hostkit.unit_scale()
    polys = {}
    if isinstance(channels, dict):
        polys = {k: (np.asarray(v, float), None) for k, v in channels.items()}
    else:
        for o in channels:
            for label, P, dia in check_channels.centerlines(_obj(o)):
                polys[label] = (P / s, None if dia is None else dia / s)
    out = {}
    for name, (P, dia) in polys.items():
        sp = spacing or ((dia / 2) if dia else routekit.length(P) / 50)
        S = routekit.resample(P, max(sp, 1e-9))
        solid = hostkit.inside(S, final)
        i = np.nonzero(solid)[0]
        out[name] = {"samples": int(len(S)), "blocked_pct": round(100.0 * solid.mean(), 2),
                     "blocked_at": S[i[0]].round(3).tolist() if len(i) else None}
    return out


def cavity_empty(final, cavity, step=None, margin=None):
    """% of the cavity (object or {"box": [lo, hi]}) that is still solid in final.
    Samples a grid inside the cavity, staying `margin` away from its walls."""
    s = hostkit.unit_scale()
    if isinstance(cavity, dict):
        lo, hi = np.asarray(cavity["box"][0], float), np.asarray(cavity["box"][1], float)
        ob = None
    else:
        ob = _obj(cavity)
        W = hostkit.world_verts(ob)
        lo, hi = W.min(0), W.max(0)
    step = step or float(np.min(hi - lo)) / 6
    margin = margin if margin is not None else 0.0003 / s
    axes = [np.arange(lo[k] + step / 2, hi[k], step) for k in range(3)]
    G = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    if ob is not None:
        G = G[hostkit.clearance(G, ob) > margin]
    else:
        G = G[np.all((G > lo + margin) & (G < hi - margin), axis=1)]
    if not len(G):
        return {"samples": 0, "solid_pct": None}
    solid = hostkit.inside(G, final)
    return {"samples": int(len(G)), "solid_pct": round(100.0 * solid.mean(), 2),
            "solid_at": G[np.argmax(solid)].round(3).tolist() if solid.any() else None}


def touching_parts(a, b, tol=None, max_verts=5000):
    """Do two parts touch or overlap? {"touching", "min_gap", "overlap"} (UNITS)."""
    s = hostkit.unit_scale()
    tol = tol if tol is not None else 0.0001 / s
    best, overlap = np.inf, False
    for x, y in ((a, b), (b, a)):
        V = hostkit.world_verts(_obj(x))
        if len(V) > max_verts:
            V = V[np.linspace(0, len(V) - 1, max_verts).astype(int)]
        _, d = hostkit.nearest(V, _obj(y))
        best = min(best, float(d.min()))
        if hostkit.inside(V[np.argsort(d)[:200]], _obj(y)).any():
            overlap = True
    return {"touching": bool(overlap or best <= tol), "min_gap": round(best, 6), "overlap": overlap}


def run(spec_path=None, spec=None, out_path=None, verbose=True):
    if spec is None:
        with open(spec_path, "r", encoding="utf-8-sig") as f:
            spec = json.load(f)
    v = spec.get("verify", spec)
    units = v.get("units", spec.get("units", "m"))
    saved = hostkit.UNITS
    hostkit.set_units(units)
    try:
        return _run(v, units, out_path, verbose)
    finally:
        hostkit.set_units(saved)


def _run(v, units, out_path, verbose):
    errors, warnings, info = [], [], []
    rep = {"units": units, "errors": errors, "warnings": warnings, "info": info}
    finals = [n for n in ([v["final"]] if isinstance(v.get("final"), str) else v.get("final", [])) + v.get("parts", [])]
    missing = [n for n in finals if n not in bpy.data.objects]
    if missing:
        errors.append("Final objects not found: " + ", ".join(missing))
        return _finish(rep, out_path, verbose)
    main = finals[0] if finals else None

    rep["shells"] = {}
    for n in finals:
        sh = shells(n)
        rep["shells"][n] = sh[:10]
        nm = sum(x["nonmanifold_edges"] for x in sh)
        bd = sum(x["boundary_edges"] for x in sh)
        voids = [x for x in sh[1:] if x["volume"] < 0]
        want = (v.get("shells") or {}).get(n)
        if bd or nm:
            errors.append(f"{n}: not watertight ({bd} boundary, {nm} non-manifold edges).")
        if want is not None and len(sh) != want:
            errors.append(f"{n}: {len(sh)} shells, expected {want} "
                          f"(extra: {', '.join(str(x['center']) for x in sh[1:6])}).")
        elif len(sh) > 1:
            info.append(f"{n}: {len(sh)} shells ({len(voids)} enclosed voids).")

    if v.get("original"):
        so = skin_openings(v["original"], finals, v.get("samples", 60000), v.get("tol"), v.get("cell"),
                           v.get("openings", []), v.get("ignore", []))
        rep["skin_openings"] = so
        for c in so["unexpected"]:
            errors.append(f"UNEXPECTED OPENING in the skin at {c['center']} (size {c['size']} {units}, "
                          f"{c['n']} samples).")
        for name in so["missing"]:
            errors.append(f"MISSING OPENING '{name}': the skin is still there (cutter short of the "
                          "surface? extend it >= 1 mm through).")
        info.append(f"skin: {so['gone']} of {so['samples']} samples gone, {len(so['clusters'])} openings.")

    tv = v.get("tunnels")
    if tv and main:
        if tv.get("names"):
            objs = [o for o in bpy.data.objects if any(fnmatch.fnmatchcase(o.name, p) for p in tv["names"])]
        else:
            objs = list(bpy.data.collections[tv["collection"]].all_objects)
        objs = [o for o in objs if o.type in ("CURVE", "MESH")]
        t = tunnels_open(objs, main, tv.get("spacing"))
        rep["tunnels"] = t
        mx = tv.get("max_blocked_pct", 1.0)
        for n, r in t.items():
            if r["blocked_pct"] > mx:
                errors.append(f"BLOCKED TUNNEL: {n} is {r['blocked_pct']}% inside solid (first at {r['blocked_at']}).")
        info.append(f"tunnels: {sum(r['blocked_pct'] <= mx for r in t.values())}/{len(t)} open.")

    rep["cavities"] = {}
    for c in v.get("cavities", []):
        name = c if isinstance(c, str) else c.get("name", "box")
        r = cavity_empty(main, c if isinstance(c, str) else c)
        rep["cavities"][name] = r
        if r["solid_pct"] is None:
            warnings.append(f"cavity {name}: no sample points (too small for the grid).")
        elif r["solid_pct"] > v.get("max_solid_pct", 0.5):
            errors.append(f"CAVITY NOT EMPTY: {name} is {r['solid_pct']}% solid (at {r['solid_at']}).")

    rep["apart"] = []
    for a, b in v.get("apart", []):
        r = touching_parts(a, b)
        rep["apart"].append({"a": a, "b": b, **r})
        if r["touching"]:
            errors.append(f"FUSED/TOUCHING: {a} and {b} {'overlap' if r['overlap'] else 'touch'} "
                          f"(gap {r['min_gap']} {units}).")
    return _finish(rep, out_path, verbose)


def _finish(rep, out_path, verbose):
    rep["summary"] = {"errors": len(rep["errors"]), "warnings": len(rep["warnings"])}
    lines = [f"CUT VERIFY: {rep['summary']['errors']} errors, {rep['summary']['warnings']} warnings ({rep['units']})"]
    for key in ("errors", "warnings", "info"):
        for msg in rep[key]:
            lines.append(f"  [{key[:-1].upper() if key != 'info' else 'INFO'}] {msg}")
    for name, sh in rep.get("shells", {}).items():
        lines.append(f"  {name}: {len(sh)} shell(s), main {sh[0]['faces'] if sh else 0} tris")
    for name, c in rep.get("cavities", {}).items():
        lines.append(f"  cavity {name}: {c['solid_pct']}% solid ({c['samples']} samples)")
    rep["text"] = "\n".join(lines)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in rep.items() if k != "text"}, f, indent=1, default=float)
    if verbose:
        print(rep["text"])
    return rep


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = None
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        out = os.path.join(a.out, "verify_report.json")
    rep = run(spec_path=a.spec, out_path=out)
    if a.out:
        with open(os.path.join(a.out, "verify_report.txt"), "w", encoding="utf-8") as f:
            f.write(rep["text"] + "\n")
    sys.exit(2 if rep["summary"]["errors"] else 0)


if __name__ == "__main__":
    _cli()
