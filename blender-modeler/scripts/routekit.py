"""Route channels (wire runs, pipes, conduits) through the inside of a host mesh.

The recipe that worked on a 4.9M-triangle figure:
1. hostkit.voxelize(host, step) -> inside grid + clearance to the skin
2. clearance_tree(): one shortest-path tree from the hub through voxels with at
   least min_clear to the skin; cost per step = length * (1 + (pref_clear/clear)^2),
   so paths hug the thick middle of each limb. Keep-outs (vaults, cavities) are
   blocked voxels, made with keepouts_from() BEFORE routing.
3. merge_tree(): trace every leaf (pocket, terminal) back to the hub and split the
   result into segments wherever the set of leaves carried changes. Segments share
   their junction points exactly, so smoothing them with fixed ends keeps the
   network connected; size each segment by its leaf count/weight.
4. smooth()/chaikin() + resample(), then CHECK against the real mesh
   (check_channels: wall to skin, bend radius, loose ends), never just the grid.

All points and distances are in the grid's units (hostkit.UNITS when it was built).
Runs inside Blender (numpy; keepouts_from uses hostkit for objects).
"""

import heapq
import math

import numpy as np

_NB = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1) if (a, b, c) != (0, 0, 0)]


# ---------------------------------------------------------------- grid search

def _to_idx(g, p):
    return tuple(np.clip(np.floor((np.asarray(p, float) - g["lo"]) / g["step"]).astype(int), 0, g["shape"] - 1))


def _to_pt(g, ijk):
    return g["lo"] + (np.asarray(ijk, float) + 0.5) * g["step"]


def keepouts_from(g, items, margin=0.0):
    """Blocked-voxel mask from keep-out volumes, grown by margin (grid units).

    items: (lo, hi) boxes, or Blender objects / object names (closed meshes such as
    cavity cutters; tested with hostkit ray parity, so their transforms are respected).
    """
    import bpy
    import hostkit
    sh = g["shape"]
    mask = np.zeros(sh, bool)
    for it in items:
        if isinstance(it, (tuple, list)) and len(it) == 2 and np.ndim(it[0]) == 1:
            lo, hi = np.asarray(it[0], float) - margin, np.asarray(it[1], float) + margin
            ids = _box_ids(g, lo, hi)
            if ids is None:
                continue
            C = _to_pt(g, ids)
            d = np.linalg.norm(np.maximum(np.maximum(np.asarray(it[0]) - C, C - np.asarray(it[1])), 0), axis=1)
            sel = d <= margin
        else:
            ob = bpy.data.objects[it] if isinstance(it, str) else it
            W = hostkit.world_verts(ob)
            ids = _box_ids(g, W.min(0) - margin, W.max(0) + margin)
            if ids is None:
                continue
            C = _to_pt(g, ids)
            sel = hostkit.clearance(C, ob) > -margin
        mask[tuple(ids[sel].T)] = True
    return mask


def _box_ids(g, lo, hi):
    a = np.clip(np.floor((lo - g["lo"]) / g["step"]).astype(int), 0, g["shape"] - 1)
    b = np.clip(np.floor((hi - g["lo"]) / g["step"]).astype(int), 0, g["shape"] - 1)
    if np.any(b < a):
        return None
    r = [np.arange(a[k], b[k] + 1) for k in range(3)]
    return np.stack(np.meshgrid(*r, indexing="ij"), -1).reshape(-1, 3)


def clearance_tree(g, src, min_clear, pref_clear, blocked=None, free=None):
    """Shortest-cost tree from src (hub point) over voxels with clear >= min_clear.

    Cost per step = step length * (1 + (pref_clear / clear)^2).
    blocked: bool mask of voxels to avoid (keep-outs). free: voxels always allowed
    while inside the host (e.g. the hub chamber itself).
    Returns a tree dict for route()/merge_tree().
    """
    clear = g["clear"]
    ok = g["inside"] & (clear >= min_clear)
    if blocked is not None:
        ok &= ~blocked
    if free is not None:
        ok |= free & g["inside"]
    sh = tuple(int(x) for x in g["shape"])
    ps = (sh[0] + 2, sh[1] + 2, sh[2] + 2)            # padded: neighbours never leave the grid
    okp = np.zeros(ps, bool)
    okp[1:-1, 1:-1, 1:-1] = ok
    wp = np.ones(ps, np.float64)
    wp[1:-1, 1:-1, 1:-1] = 1.0 + (pref_clear / np.maximum(clear, g["step"] * 0.5)) ** 2
    s = _to_idx(g, src)
    if not ok[s]:
        cand = np.argwhere(ok)
        if not len(cand):
            raise RuntimeError("no voxel satisfies min_clear; lower it or refine the grid")
        s = tuple(cand[np.argmin(np.linalg.norm(cand - np.array(s), axis=1))])
    sx, sy = ps[1] * ps[2], ps[2]
    offs = [(a * sx + b * sy + c, g["step"] * math.sqrt(abs(a) + abs(b) + abs(c))) for a, b, c in _NB]
    okl = okp.ravel().tolist()
    wl = wp.ravel().tolist()
    N = len(okl)
    dist = [math.inf] * N
    par = [-1] * N
    s0 = (s[0] + 1) * sx + (s[1] + 1) * sy + (s[2] + 1)
    dist[s0] = 0.0
    pq = [(0.0, s0)]
    pop, push = heapq.heappop, heapq.heappush
    while pq:
        d, u = pop(pq)
        if d > dist[u]:
            continue
        for o, L in offs:
            v = u + o
            if not okl[v]:
                continue
            nd = d + L * wl[v]
            if nd < dist[v]:
                dist[v] = nd
                par[v] = u
                push(pq, (nd, v))
    D = np.array(dist).reshape(ps)[1:-1, 1:-1, 1:-1]
    return {"grid": g, "dist": D, "par": np.array(par, np.int64), "pshape": ps, "src": s,
            "src_pt": np.asarray(src, float), "reached": None}


def _unpad(tree, flat):
    ps = tree["pshape"]
    i, r = divmod(int(flat), ps[1] * ps[2])
    j, k = divmod(r, ps[2])
    return (i - 1, j - 1, k - 1)


def _pad(tree, ijk):
    ps = tree["pshape"]
    return (ijk[0] + 1) * ps[1] * ps[2] + (ijk[1] + 1) * ps[2] + (ijk[2] + 1)


def nearest_reached(tree, p):
    """(voxel index, distance) of the reached voxel closest to point p."""
    g = tree["grid"]
    if tree["reached"] is None:
        tree["reached"] = np.argwhere(np.isfinite(tree["dist"]))
    R = tree["reached"]
    C = _to_pt(g, R)
    d = np.linalg.norm(C - np.asarray(p, float), axis=1)
    k = int(np.argmin(d))
    return tuple(R[k]), float(d[k])


def _voxel_path(tree, v):
    out = []
    f = _pad(tree, v)
    par = tree["par"]
    while f >= 0:
        out.append(_unpad(tree, f))
        f = int(par[f])
    return out


def route(tree, p, max_snap=None, endpoints=True):
    """Polyline from point p to the hub (p first), following the tree.

    max_snap: refuse (return None) if the nearest reached voxel is further than this.
    endpoints: start exactly at p and end exactly at the hub point.
    """
    g = tree["grid"]
    v, gap = nearest_reached(tree, p)
    if max_snap is not None and gap > max_snap:
        return None
    pts = _to_pt(g, _voxel_path(tree, v))
    if endpoints:
        pts = np.vstack([np.asarray(p, float), pts[1:-1] if len(pts) > 2 else pts[:0], tree["src_pt"]])
    return pts


trace = route


def merge_tree(tree, leaves):
    """Route every leaf to the hub and split into shared segments.

    leaves: {name: point} or {name: (point, weight)} (weight = lights/wires carried).
    Returns a list of {"leaves": [...], "weight": total, "points": (N, 3)}. Each segment
    ends exactly on the first point of the segment downstream of it (or on the hub), so
    smoothing with fixed ends keeps every junction connected.
    """
    g = tree["grid"]
    paths, weight, pin = {}, {}, {}
    for name, val in leaves.items():
        pair = isinstance(val, (tuple, list)) and len(val) == 2 and np.ndim(val[0]) == 1
        p, w = (val[0], float(val[1])) if pair else (val, 1.0)
        v, _ = nearest_reached(tree, p)
        paths[name] = _voxel_path(tree, v)
        weight[name] = w
        pin[name] = np.asarray(p, float)
    through = {}
    for name, path in paths.items():
        for v in path:
            through.setdefault(v, set()).add(name)
    segs = {}
    for name, path in paths.items():
        cur = [path[0]]
        for u in path[1:]:
            cur.append(u)
            if through[u] != through[cur[-2]]:
                key = frozenset(through[cur[-2]])
                segs.setdefault(key, list(cur))
                cur = [u]
        if len(cur) > 1:
            segs.setdefault(frozenset(through[cur[0]]), list(cur))
    out = []
    for key, vs in segs.items():
        pts = _to_pt(g, vs)
        if len(key) == 1:
            (nm,) = key
            if vs[0] == paths[nm][0]:
                pts[0] = pin[nm]                      # the leaf's own segment starts exactly at its point
        if vs[-1] == tree["src"]:
            pts[-1] = tree["src_pt"]
        out.append({"leaves": sorted(key), "weight": sum(weight[n] for n in key), "points": pts})
    for nm, path in paths.items():
        if through[path[0]] != {nm}:                  # leaf voxel already on another leaf's path: lead-in
            out.append({"leaves": [nm], "weight": weight[nm], "points": np.vstack([pin[nm], _to_pt(g, path[0])])})
    out.sort(key=lambda s: (len(s["leaves"]), s["leaves"]))
    return out


# ---------------------------------------------------------------- polylines

def length(poly):
    p = np.asarray(poly, float)
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) if len(p) > 1 else 0.0


def resample(poly, spacing):
    """Evenly spaced points along the polyline (ends kept)."""
    p = np.asarray(poly, float)
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] <= 0:
        return p[:1].copy()
    n = max(2, int(np.ceil(s[-1] / spacing)) + 1)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, p[:, k]) for k in range(3)], 1)


def smooth(poly, iters=40, lam=0.5, ok=None):
    """Laplacian smoothing with fixed ends. ok(p) -> bool can veto a move (e.g. keep
    clearance); vetoed points stay where they are for that iteration."""
    p = np.array(poly, float)
    for _ in range(iters):
        q = p.copy()
        q[1:-1] = p[1:-1] + lam * ((p[:-2] + p[2:]) / 2 - p[1:-1])
        if ok is not None:
            for i in range(1, len(p) - 1):
                if not ok(q[i]):
                    q[i] = p[i]
        p = q
    return p


def chaikin(poly, iters=3):
    """Corner cutting (keeps the end points). Rounds a coarse hand-placed path."""
    P = np.array(poly, float)
    for _ in range(iters):
        Q = [P[0]]
        for a, b in zip(P[:-1], P[1:]):
            Q += [0.75 * a + 0.25 * b, 0.25 * a + 0.75 * b]
        Q.append(P[-1])
        P = np.array(Q)
    return P


def bend_radii(poly):
    """Radius of curvature at each interior point (circumradius of 3 consecutive points).
    Resample first at a spacing near the channel diameter: the value depends on spacing."""
    p = np.asarray(poly, float)
    if len(p) < 3:
        return np.array([])
    a, b, c = p[:-2], p[1:-1], p[2:]
    ab = np.linalg.norm(b - a, axis=1)
    bc = np.linalg.norm(c - b, axis=1)
    ca = np.linalg.norm(a - c, axis=1)
    area2 = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(area2 < 1e-12, np.inf, ab * bc * ca / (2 * area2))
    return r


def closest_on_polyline(poly, pt):
    """(closest point, distance, segment index) from pt to the polyline."""
    P = np.asarray(poly, float)
    pt = np.asarray(pt, float)
    if len(P) == 1:
        return P[0], float(np.linalg.norm(P[0] - pt)), 0
    a, b = P[:-1], P[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", pt - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    q = a + t[:, None] * ab
    d = np.linalg.norm(q - pt, axis=1)
    i = int(np.argmin(d))
    return q[i], float(d[i]), i


def snap_junctions(polys, tol, min_gap=0.0, skip=()):
    """Make channel ends land exactly on the centre line they join.

    polys: {name: points}. For each end (name, "start"/"end") not in skip, if the
    nearest other centre line is closer than tol (and further than min_gap), the end is
    extended onto it with a short lead-in. Returns (new polys, {(name, end): gap}).
    Smoothing moves branches slightly; without this, trunks start a few mm off their
    branches and the wire can't pass (contact checks don't notice: the tubes overlap).
    """
    out = {k: np.asarray(v, float).copy() for k, v in polys.items()}
    snaps = {}
    for name in list(out):
        for end in ("start", "end"):
            if (name, end) in skip:
                continue
            P = out[name]
            e = P[0] if end == "start" else P[-1]
            best = None
            for other, Q in out.items():
                if other == name:
                    continue
                q, d, _ = closest_on_polyline(Q, e)
                if best is None or d < best[1]:
                    best = (q, d)
            if best and min_gap < best[1] <= tol:
                out[name] = np.vstack([best[0], P]) if end == "start" else np.vstack([P, best[0]])
                snaps[(name, end)] = round(best[1], 6)
    return out, snaps
