"""Measure an existing ("host") mesh: world-space vertices, inside/outside,
wall thickness, a voxel clearance field, pocket finding and ray scans.

Built for adding features inside big, frozen meshes (a sculpted figure with
millions of triangles, flipped faces and unapplied rotation/scale), where face
normals can't be trusted and pure-Python loops over every vertex are too slow:
- everything is read with foreach_get into numpy and moved to world space
  through matrix_world, so unapplied transforms are handled
- inside/outside uses ray parity (majority of 3 rays), never the face normal
- BVH trees and voxel grids are cached in bpy.app.driver_namespace, so repeated
  calls through MCP don't rebuild them (clear_cache() after editing the host)

Units: every point you pass in and every distance you get back is in UNITS
(default "m"). Call set_units("mm") once for fabrication work; the grid dicts
record the units they were built in.

    import hostkit as hk
    hk.set_units("mm")
    body = bpy.data.objects["Body"]
    wall = hk.clearance(points_mm, body)          # >0 inside (wall left), <0 outside
    g = hk.voxelize(body, step=5.0)               # g["inside"], g["clear"] (mm to skin)
    for c in hk.sharp_edge_clusters(body, link=6.0):
        floor = hk.ray_floor(c["center"], c["normal"], body)

Runs inside Blender (bpy, mathutils, numpy).
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

UNITS = "m"
_PER = {"m": 1.0, "mm": 0.001, "cm": 0.01}
NS = bpy.app.driver_namespace
_KEY = "hostkit"
# Slightly skewed so a ray rarely runs exactly along an edge or through a vertex of
# an axis-aligned mesh; the third ray breaks ties when one of the others grazes.
RAY_DIRS = [(0.0123, 0.0071, 1.0), (-0.0093, 0.0157, -1.0), (0.577, 0.5953, 0.5587)]
MAX_HITS = 256


def set_units(units):
    """'m', 'cm' or 'mm': the unit of every point and distance in and out of this module."""
    global UNITS
    if units not in _PER:
        raise ValueError(f"units must be one of {sorted(_PER)}")
    UNITS = units
    return UNITS


def unit_scale():
    """Metres per UNIT."""
    return _PER[UNITS]


def _m(pts):
    return np.asarray(pts, float) * _PER[UNITS]


def _u(pts_m):
    return np.asarray(pts_m, float) / _PER[UNITS]


def clear_cache(obj=None):
    """Forget cached BVH trees / grids (all, or only those built from obj)."""
    for k in [k for k in NS.keys() if isinstance(k, str) and k.startswith(_KEY)]:
        if obj is None or f"|{_name(obj)}|" in k:
            del NS[k]


def _name(obj):
    return obj if isinstance(obj, str) else obj.name


def _obj(obj):
    return bpy.data.objects[obj] if isinstance(obj, str) else obj


# ---------------------------------------------------------------- mesh access

def _mesh_arrays(obj, evaluated=True):
    """Local vertex coords (N, 3) of the object's (evaluated) mesh, as float64."""
    obj = _obj(obj)
    plain = obj.type == "MESH" and not obj.modifiers and not (obj.data.shape_keys and evaluated)
    if plain or not evaluated:
        me = obj.data
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        return co.reshape(-1, 3)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
    finally:
        ev.to_mesh_clear()
    return co.reshape(-1, 3)


def _apply(M, co):
    M = np.array(M)
    return co @ M[:3, :3].T + M[:3, 3]


def world_verts(obj, evaluated=True):
    """World-space vertex positions (N, 3) in UNITS (modifiers included when evaluated)."""
    obj = _obj(obj)
    return _u(_apply(obj.matrix_world, _mesh_arrays(obj, evaluated)))


def world_normals(obj):
    """World-space unit vertex normals (N, 3) of the base mesh (not trustworthy on
    meshes with flipped faces; use inside()/clearance() for inside/outside)."""
    obj = _obj(obj)
    me = obj.data
    n = np.empty(len(me.vertices) * 3)
    if hasattr(me, "vertex_normals"):           # 4.1+
        me.vertex_normals.foreach_get("vector", n)
    else:
        me.vertices.foreach_get("normal", n)
    n = n.reshape(-1, 3) @ np.array(obj.matrix_world.to_3x3().inverted().transposed()).T
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]


def world_tris(obj):
    """(verts (N, 3) in UNITS, triangles (T, 3) int) of the base mesh in world space."""
    obj = _obj(obj)
    me = obj.data
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    return world_verts(obj, evaluated=False), tri.reshape(-1, 3)


# ---------------------------------------------------------------- BVH host

class Host:
    """A cached BVH of one object plus the matrices to use it from world space.

    Uniformly scaled objects keep the BVH in object space (fast to build); other
    objects get a world-space BVH so distances stay true.
    """

    def __init__(self, obj):
        obj = _obj(obj)
        dg = bpy.context.evaluated_depsgraph_get()
        Mw = obj.matrix_world.copy()
        cols = [Mw.col[i].xyz.length for i in range(3)]
        uniform = max(cols) - min(cols) <= 1e-6 * max(cols)
        if uniform:
            self.tree = BVHTree.FromObject(obj, dg)
            self.M, self.Mi, self.s = Mw, Mw.inverted(), cols[0]
        else:
            bm = bmesh.new()
            bm.from_object(obj, dg)
            bm.transform(Mw)
            self.tree = BVHTree.FromBMesh(bm)
            bm.free()
            self.M, self.Mi, self.s = Matrix.Identity(4), Matrix.Identity(4), 1.0
        # ray nudge past each hit, in tree space (~1e-6 of the object's size)
        self.eps = max(max(obj.dimensions) / self.s * 1e-6, 1e-9)
        self.name = obj.name
        self.M3i = self.Mi.to_3x3()

    def local(self, pts_m):
        P = _apply(self.Mi, np.atleast_2d(pts_m))
        return [Vector(p) for p in P]

    def dir_local(self, d):
        return (self.M3i @ Vector(d)).normalized()

    def parity(self, p, d):
        """True if a ray from p (tree space) along d crosses the surface an odd number of times."""
        k, q = 0, p
        cast = self.tree.ray_cast
        for _ in range(MAX_HITS):
            h = cast(q, d)[0]
            if h is None:
                break
            k += 1
            q = h + d * self.eps
        return k % 2 == 1


def host_bvh(obj, refresh=False):
    """Cached Host for obj (rebuilt when its vertex count or transform changes)."""
    obj = _obj(obj)
    n = len(obj.data.vertices) if obj.type == "MESH" else -1
    fp = (n, tuple(round(x, 9) for row in obj.matrix_world for x in row), len(obj.modifiers))
    key = f"{_KEY}|{obj.name}|bvh"
    hit = NS.get(key)
    if refresh or hit is None or hit[0] != fp:
        NS[key] = (fp, Host(obj))
    return NS[key][1]


def inside(pts, host, rays=3):
    """Bool array: is each point (UNITS, world) inside the closed host? Ray parity,
    majority vote of `rays` (1 or 3) rays, so flipped faces and one grazing ray don't matter."""
    H = host if isinstance(host, Host) else host_bvh(host)
    P = H.local(_m(pts))
    dirs = [H.dir_local(d) for d in RAY_DIRS[:max(1, rays)]]
    need = len(dirs) // 2 + 1
    out = np.zeros(len(P), bool)
    for i, p in enumerate(P):
        yes = no = 0
        for d in dirs:
            if H.parity(p, d):
                yes += 1
            else:
                no += 1
            if yes >= need or no >= need:
                break
        out[i] = yes >= need
    return out


def nearest(pts, host):
    """(closest surface points (N, 3), distances (N,)) in UNITS."""
    H = host if isinstance(host, Host) else host_bvh(host)
    P = H.local(_m(pts))
    loc = np.zeros((len(P), 3))
    dist = np.full(len(P), np.inf)
    M = H.M
    for i, p in enumerate(P):
        h = H.tree.find_nearest(p)
        if h[0] is not None:
            loc[i] = M @ h[0]
            dist[i] = h[3] * H.s
    return _u(loc), _u(dist)


def clearance(pts, host, rays=3):
    """Distance from each point to the host skin in UNITS: positive inside (the
    material you have to work with), negative outside. A channel of radius r at p
    leaves a wall of clearance(p) - r."""
    _, d = nearest(pts, host)
    return np.where(inside(pts, host, rays), d, -d)


def signed_distance(pts, host, rays=3):
    """Conventional SDF in UNITS: negative inside, positive outside (= -clearance)."""
    return -clearance(pts, host, rays)


# ---------------------------------------------------------------- voxel field

def voxelize(host, step, bounds=None, pad=None, refine_below=None):
    """Inside/outside grid of the host by ray parity along world +Z columns, plus a
    clearance field (distance to the skin) for routing. Cached per (host, step, bounds).

    step, bounds ((lo, hi) corners) and pad are in UNITS. Pass the same bounds to two
    voxelize() calls to compare them voxel for voxel (voxel_diff).
    refine_below: replace the voxel-count clearance with the exact BVH distance in
    voxels whose estimate is below this value (slower; makes min-clearance gating exact).

    Returns {"lo", "step", "shape", "inside" (bool), "clear" (float, UNITS; <=0 outside), "units"}.
    """
    obj = _obj(host)
    H = host_bvh(obj)
    if bounds is None:
        W = world_verts(obj)
        pad = step * 2 if pad is None else pad
        lo, hi = W.min(0) - pad, W.max(0) + pad
    else:
        lo, hi = np.asarray(bounds[0], float), np.asarray(bounds[1], float)
    key = f"{_KEY}|{obj.name}|vox|{UNITS}|{step:g}|{np.round(lo, 6).tolist()}|{np.round(hi, 6).tolist()}|{refine_below}"
    fp = NS[f"{_KEY}|{obj.name}|bvh"][0]
    if key in NS and NS[key][0] == fp:
        return NS[key][1]
    shape = np.maximum(np.ceil((hi - lo) / step).astype(int), 1)
    inside_ = np.zeros(shape, bool)
    zc = lo[2] + (np.arange(shape[2]) + 0.5) * step
    s = unit_scale()
    up = H.dir_local((0, 0, 1))
    z0 = (lo[2] - step) * s
    jitter = (0.0, 0.173, -0.291)            # retry offsets (fraction of a step) for odd hit counts
    for i in range(shape[0]):
        for j in range(shape[1]):
            for jx in jitter:
                x = (lo[0] + (i + 0.5 + jx) * step) * s
                y = (lo[1] + (j + 0.5 - jx * 0.7) * step) * s
                q = H.local([(x, y, z0)])[0]
                hits = []
                for _ in range(MAX_HITS):
                    h = H.tree.ray_cast(q, up)[0]
                    if h is None:
                        break
                    hits.append((H.M @ h).z / s)
                    q = h + up * H.eps
                if len(hits) % 2 == 0:
                    break
            if len(hits) % 2:
                hits = hits[:-1]
            for a, b in zip(hits[0::2], hits[1::2]):
                inside_[i, j, (zc > a) & (zc < b)] = True
    clear = _erosion_distance(inside_) * step - step / 2
    clear[~inside_] = 0.0
    if refine_below is not None:
        idx = np.argwhere(inside_ & (clear < refine_below))
        if len(idx):
            c = lo + (idx + 0.5) * step
            _, d = nearest(c, H)
            clear[tuple(idx.T)] = d
    g = {"lo": lo, "hi": lo + shape * step, "step": float(step), "shape": shape, "inside": inside_,
         "clear": clear.astype(np.float32), "units": UNITS, "host": obj.name}
    NS[key] = (fp, g)
    return g


def _erosion_distance(mask):
    """Layers of erosion per voxel (1 = on the boundary). Alternates 6- and 26-neighbour
    erosion, which is a cheap, fairly round approximation of Euclidean distance."""
    dist = np.zeros(mask.shape, np.float32)
    cur = mask.copy()
    k = 0
    while cur.any():
        k += 1
        dist[cur] = k
        nxt = cur.copy()
        if k % 2:                                      # cross (6-neighbour)
            for ax in range(3):
                nxt &= _shift(cur, 1, ax) & _shift(cur, -1, ax)
        else:                                          # cube (26-neighbour), separable
            for ax in range(3):
                nxt = nxt & _shift(nxt, 1, ax) & _shift(nxt, -1, ax)
        cur = nxt
    return dist


def _shift(a, k, ax):
    out = np.zeros_like(a)
    src = [slice(None)] * 3
    dst = [slice(None)] * 3
    if k > 0:
        src[ax], dst[ax] = slice(0, -k), slice(k, None)
    else:
        src[ax], dst[ax] = slice(-k, None), slice(0, k)
    out[tuple(dst)] = a[tuple(src)]
    return out


def to_idx(g, p):
    """Voxel index (i, j, k) containing point p (clamped to the grid)."""
    return tuple(np.clip(np.floor((np.asarray(p, float) - g["lo"]) / g["step"]).astype(int), 0, g["shape"] - 1))


def to_pt(g, ijk):
    """Centre(s) of voxel index/indices, in the grid's units."""
    return g["lo"] + (np.asarray(ijk, float) + 0.5) * g["step"]


def box_mask(g, boxes):
    """Voxels whose centre lies in any of the (lo, hi) boxes (grid units)."""
    sh = g["shape"]
    cx, cy, cz = (g["lo"][k] + (np.arange(sh[k]) + 0.5) * g["step"] for k in range(3))
    m = np.zeros(sh, bool)
    for lo, hi in boxes:
        m |= (((cx >= lo[0]) & (cx <= hi[0]))[:, None, None] & ((cy >= lo[1]) & (cy <= hi[1]))[None, :, None]
              & ((cz >= lo[2]) & (cz <= hi[2]))[None, None, :])
    return m


def voxel_diff(a, b):
    """What changed between two grids on the same bounds: {"removed": a & ~b (e.g. carved),
    "added": b & ~a, "removed_volume", "added_volume"} (volumes in UNITS^3)."""
    if not (np.allclose(a["lo"], b["lo"]) and tuple(a["shape"]) == tuple(b["shape"]) and a["step"] == b["step"]):
        raise ValueError("voxel_diff needs two grids built with the same step and bounds")
    rem = a["inside"] & ~b["inside"]
    add = b["inside"] & ~a["inside"]
    v = a["step"] ** 3
    return {"removed": rem, "added": add, "removed_volume": float(rem.sum() * v), "added_volume": float(add.sum() * v)}


# ---------------------------------------------------------------- features

def cluster_points(P, link):
    """Connected clusters of points closer than `link` (single linkage). Returns a label per point."""
    P = np.asarray(P, float)
    n = len(P)
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cells = {}
    keys = np.floor(P / link).astype(np.int64)
    for i, k in enumerate(map(tuple, keys)):
        cells.setdefault(k, []).append(i)
    for k, idx in cells.items():
        A = P[idx]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    k2 = (k[0] + dx, k[1] + dy, k[2] + dz)
                    if k2 < k or k2 not in cells:
                        continue
                    jdx = cells[k2]
                    D = np.linalg.norm(A[:, None, :] - P[jdx][None, :, :], axis=2)
                    for a, b in zip(*np.nonzero(D < link)):
                        ra, rb = find(idx[a]), find(jdx[b])
                        if ra != rb:
                            parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def pca_axes(points):
    """(centre, axes (3, 3) rows from largest to smallest spread, extents along each axis)."""
    P = np.asarray(points, float)
    c = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    Q = (P - c) @ Vt.T
    return c, Vt, np.ptp(Q, axis=0)


def sharp_edges(obj, angle=30.0, use_attribute=True):
    """World midpoints (UNITS) and vertex pairs of sharp edges: the mesh's 'sharp_edge'
    attribute when present, else edges whose faces meet at more than `angle` degrees.
    Uses |cos| so flipped faces don't turn smooth edges into sharp ones."""
    obj = _obj(obj)
    me = obj.data
    ne = len(me.edges)
    ev = np.empty(ne * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    attr = me.attributes.get("sharp_edge") if use_attribute else None
    if attr is not None and attr.domain == "EDGE":
        sharp = np.zeros(ne, bool)
        attr.data.foreach_get("value", sharp)
    else:
        nl, npoly = len(me.loops), len(me.polygons)
        le = np.empty(nl, np.int64)
        me.loops.foreach_get("edge_index", le)
        lt = np.empty(npoly, np.int64)
        me.polygons.foreach_get("loop_total", lt)
        fn = np.empty(npoly * 3)
        me.polygons.foreach_get("normal", fn)
        fn = fn.reshape(-1, 3)
        lp = np.repeat(np.arange(npoly), lt)
        order = np.argsort(le, kind="stable")
        le_s, lp_s = le[order], lp[order]
        cnt = np.bincount(le, minlength=ne)
        start = np.concatenate([[0], np.cumsum(cnt)[:-1]])
        two = np.nonzero(cnt == 2)[0]
        f0, f1 = lp_s[start[two]], lp_s[start[two] + 1]
        cos = np.abs(np.einsum("ij,ij->i", fn[f0], fn[f1]))
        sharp = np.zeros(ne, bool)
        sharp[two[cos < math.cos(math.radians(angle))]] = True
    V = world_verts(obj, evaluated=False)
    e = ev[sharp]
    return (V[e[:, 0]] + V[e[:, 1]]) / 2, e


def sharp_edge_clusters(obj, link=None, angle=30.0, min_edges=8, use_attribute=True):
    """Find pockets, rims and cut-outs on a host: sharp edges clustered by distance.

    link (UNITS): edges closer than this join one cluster (default ~0.5% of the host size).
    Returns clusters sorted by size, each {"center", "normal" (outward, from vertex normals),
    "axes", "extent", "n_edges", "points"}. List EVERY cluster to the user and ask which
    ones are features; don't silently keep the first few.
    """
    obj = _obj(obj)
    mids, e = sharp_edges(obj, angle, use_attribute)
    if not len(mids):
        return []
    if link is None:
        W = world_verts(obj, evaluated=False)
        link = float(np.linalg.norm(np.ptp(W, axis=0))) * 0.005
    lab = cluster_points(mids, link)
    N = world_normals(obj)
    out = []
    for r in np.unique(lab):
        sel = lab == r
        if sel.sum() < min_edges:
            continue
        P = mids[sel]
        c, axes, ext = pca_axes(P)
        n = axes[2]
        vn = N[e[sel].ravel()].sum(0)
        if np.dot(n, vn) < 0:
            n = -n
        out.append({"center": c, "normal": n, "axes": axes, "extent": ext, "n_edges": int(sel.sum()), "points": P})
    out.sort(key=lambda d: -d["n_edges"])
    return out


def ray_first(origin, direction, host):
    """First hit (point UNITS, distance UNITS, face normal) of a world ray, or None."""
    H = host if isinstance(host, Host) else host_bvh(host)
    o = H.local(_m([origin]))[0]
    d = H.dir_local(direction)
    h = H.tree.ray_cast(o, d)
    if h[0] is None:
        return None
    p = np.array(H.M @ h[0])
    n = np.array((H.M3i.transposed() @ h[1]).normalized())
    return _u(p), float(np.linalg.norm(_u(p) - np.asarray(origin, float))), n


def ray_floor(center, normal, host, start=0.0):
    """Floor of a pocket: cast from center + normal*start along -normal.
    Returns {"point", "depth" (below center), "normal"} or None (UNITS)."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    o = np.asarray(center, float) + n * start
    r = ray_first(o, -n, host)
    if r is None:
        return None
    p, d, fn = r
    return {"point": p, "depth": d - start, "normal": fn}


def scan_heightmap(center, normal, size, step, host, start=None, ceiling=None):
    """Height map of the surface around center, by a grid of rays cast along -normal.

    size: half-width of the square grid; step: grid spacing; start: how far above center
    the rays begin (default size). ceiling: ignore hits higher than this above center
    (overhangs). Returns {"g" (1D offsets), "H" (heights along normal, NaN = no hit), "u", "v"}.
    """
    H_ = host if isinstance(host, Host) else host_bvh(host)
    n = np.asarray(normal, float)
    n /= np.linalg.norm(n)
    u = np.cross(n, [0, 0, 1.0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, [1.0, 0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    start = size if start is None else start
    g = np.arange(-size, size + 1e-9, step)
    Hm = np.full((len(g), len(g)), np.nan)
    d = H_.dir_local(-n)
    c = np.asarray(center, float)
    for i, a in enumerate(g):
        for j, b in enumerate(g):
            q = H_.local(_m([c + u * a + v * b + n * start]))[0]
            for _ in range(32):
                h = H_.tree.ray_cast(q, d)[0]
                if h is None:
                    break
                ht = float((_u(np.array(H_.M @ h)) - c) @ n)
                if ceiling is None or ht <= ceiling:
                    Hm[i, j] = ht
                    break
                q = h + d * H_.eps
    return {"g": g, "H": Hm, "u": u, "v": v}
