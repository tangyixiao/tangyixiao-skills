"""Building blocks for model scripts, with good defaults baked in.

The point is to make the high-quality path the easy path:
- primitives are built at their true size (no object scale), so bevels and
  solidify stay even
- finish() adds the bevel + weighted-normal + smooth-shading stack that stops
  hard-surface parts looking like raw CG primitives
- material() adds subtle procedural colour/roughness variation and bump,
  because perfectly uniform surfaces read as fake

Units are metres, Z up, the model faces -Y (front view), origin at floor centre.
(tube/tube_mesh also take units="mm" for fabrication work.)

Nothing here uses bpy.ops except render_final(), so the builders are safe to
call from a live MCP session.

    import modelkit as mk
    mk.reset_scene()
    top = mk.box("Top", (1.2, 0.7, 0.04), (0, 0, 0.73))
    mk.finish(top, bevel=0.004)
    mk.assign(top, mk.material("Oak", (0.45, 0.28, 0.15), roughness=0.55, variation=0.25))
"""

import math
import time

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

_UNIT = {"m": 1.0, "cm": 0.01, "mm": 0.001}


# ---------------------------------------------------------------- scene

def reset_scene():
    """Delete all objects and orphaned data, leaving an empty scene."""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.images, bpy.data.node_groups):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    bpy.context.scene.unit_settings.system = "METRIC"


def collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _link(obj, coll):
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def _object_from_bmesh(name, bm, location, rotation, coll):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    obj.rotation_euler = Euler([math.radians(a) for a in rotation])
    return _link(obj, coll)


# ---------------------------------------------------------------- primitives
# rotation is in degrees (XYZ euler). All sizes are full sizes, not half sizes.

def box(name, size, location=(0, 0, 0), rotation=(0, 0, 0), coll=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return _object_from_bmesh(name, bm, location, rotation, coll)


def cylinder(name, radius, depth, location=(0, 0, 0), rotation=(0, 0, 0), segments=48,
             radius_top=None, coll=None):
    """Cylinder along local Z, centred on location. radius_top makes a cone/taper."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius if radius_top is None else radius_top,
                          depth=depth)
    return _object_from_bmesh(name, bm, location, rotation, coll)


def sphere(name, radius, location=(0, 0, 0), rotation=(0, 0, 0), segments=48, rings=24, coll=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    return _object_from_bmesh(name, bm, location, rotation, coll)


def lathe(name, profile, location=(0, 0, 0), rotation=(0, 0, 0), segments=64, coll=None):
    """Spin a profile [(radius, z), ...] around local Z. Bottom to top.

    Use for anything turned: vases, bottles, lamp bases, table legs, knobs.
    Start/end the profile at radius 0 to get closed caps.
    Built directly as rings (bmesh spin gets very slow above ~100k faces).
    """
    prof = []
    for r, z in profile:
        if not prof or abs(prof[-1][0] - r) > 1e-9 or abs(prof[-1][1] - z) > 1e-9:
            prof.append((float(r), float(z)))
    ang = np.linspace(0.0, math.tau, segments, endpoint=False)
    cs, sn = np.cos(ang), np.sin(ang)
    verts, rings = [], []
    for r, z in prof:
        if abs(r) < 1e-9:                       # on the axis: one pole vertex
            rings.append(np.full(segments, len(verts)))
            verts.append((0.0, 0.0, z))
        else:
            rings.append(np.arange(len(verts), len(verts) + segments))
            verts += list(zip(r * cs, r * sn, np.full(segments, z)))
    faces = []
    nxt = np.roll(np.arange(segments), -1)
    for a, b in zip(rings[:-1], rings[1:]):
        for q in np.stack([a, a[nxt], b[nxt], b], 1).tolist():
            f = [v for i, v in enumerate(q) if v != q[i - 1]]   # collapse pole duplicates
            if len(f) >= 3:
                faces.append(f)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _object_from_bmesh(name, bm, location, rotation, coll)


def extrude_profile(name, points, depth, location=(0, 0, 0), rotation=(0, 0, 0), coll=None):
    """Extrude a closed 2D outline [(x, y), ...] (counter-clockwise) along local Z by depth.

    Use for brackets, panels, side profiles of furniture, logos, cut-out shapes.
    """
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, 0.0)) for x, y in points]
    face = bm.faces.new(verts)
    res = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in res["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, depth), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _object_from_bmesh(name, bm, location, rotation, coll)


def tube(name, points, radius, location=(0, 0, 0), smooth=True, resolution=12,
         bevel_resolution=6, coll=None, to_mesh=True, kind=None, units="m"):
    """Sweep a round section along a path of 3D points (offsets from location).

    Use for handles, pipes, cables, wire frames, bent rods. Make the first and last
    points sit inside the parts they connect to, or check_geometry will flag a gap.

    kind: "bezier" (smooth, AUTO handles; the default via smooth=True) or "poly"
    (straight between points). Use "poly" for dense routed paths: AUTO handles
    overshoot between closely spaced points. units: "m" or "mm" for points/radius.
    The object stores its centre line and diameter (custom props "centerline",
    "dia", metres, object space) for check_channels / verify_cuts.
    """
    k = _UNIT[units]
    pts = [tuple(c * k for c in p) for p in points]
    radius = radius * k
    kind = kind or ("bezier" if smooth else "poly")
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_depth = radius
    cd.bevel_resolution = bevel_resolution
    cd.use_fill_caps = True
    cd.resolution_u = resolution
    if kind == "bezier":
        sp = cd.splines.new("BEZIER")
        sp.bezier_points.add(len(pts) - 1)
        for bp, p in zip(sp.bezier_points, pts):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = "AUTO"
    elif kind == "poly":
        sp = cd.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for pt, p in zip(sp.points, pts):
            pt.co = (*p, 1.0)
    else:
        raise ValueError("kind must be 'bezier' or 'poly'")
    obj = _link(bpy.data.objects.new(name, cd), coll)
    obj.location = [c * k for c in location]
    if to_mesh:
        obj = convert_to_mesh(obj)
        weld(obj)  # curve caps come out as separate islands
    _tag_tube(obj, pts, radius * 2)
    return obj


def _tag_tube(obj, pts_local, dia):
    obj["centerline"] = [float(c) for p in pts_local for c in p]
    obj["dia"] = float(dia)


def tube_mesh(name, points, dia, segments=16, end_ext=0.0, units="m", coll=None):
    """Watertight tube mesh along a polyline: parallel-transport rings, fan-capped ends.

    Closed and consistently wound, so it works as a MANIFOLD boolean cutter (curve
    tubes converted to mesh are not reliably closed). end_ext extends both ends along
    their tangents so a channel breaks cleanly into the pocket/cavity it joins
    (1-1.5 mm for print channels). points/dia/end_ext are in `units`; the object is in
    metres with identity transform. Stores "centerline"/"dia" props (metres).
    """
    k = _UNIT[units]
    P = np.asarray(points, float) * k
    keep = np.r_[True, np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-9]
    P = P[keep]
    if len(P) < 2:
        raise ValueError(f"{name}: tube_mesh needs at least two distinct points")
    centre = P.copy()
    e = end_ext * k
    if e > 0:
        d0 = P[0] - P[1]
        d1 = P[-1] - P[-2]
        P = np.vstack([P[0] + d0 / np.linalg.norm(d0) * e, P, P[-1] + d1 / np.linalg.norm(d1) * e])
    r = dia * k / 2
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    n = np.cross(T[0], [0, 0, 1.0])
    if np.linalg.norm(n) < 1e-3:
        n = np.cross(T[0], [1.0, 0, 0])
    n /= np.linalg.norm(n)
    ang = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    rings = []
    for p, t in zip(P, T):
        n = n - np.dot(n, t) * t                  # parallel transport: no twisting
        n /= np.linalg.norm(n)
        b = np.cross(t, n)
        rings.append(p + r * (np.cos(ang)[:, None] * n + np.sin(ang)[:, None] * b))
    verts = np.vstack(rings).tolist()
    L, sg = len(P), segments
    faces = [(i * sg + j, i * sg + (j + 1) % sg, (i + 1) * sg + (j + 1) % sg, (i + 1) * sg + j)
             for i in range(L - 1) for j in range(sg)]
    c0, c1 = len(verts), len(verts) + 1
    verts += [P[0].tolist(), P[-1].tolist()]
    faces += [(c0, (j + 1) % sg, j) for j in range(sg)]
    faces += [(c1, (L - 1) * sg + j, (L - 1) * sg + (j + 1) % sg) for j in range(sg)]
    obj = mesh_from_data(name, verts, faces, coll)
    _tag_tube(obj, centre.tolist(), dia * k)
    return obj


def mesh_from_data(name, verts, faces, coll=None, recalc_normals=True):
    """Mesh object from vertex/face lists (metres, world = object space), validated and
    with consistent outward normals (what the MANIFOLD solver needs)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate()
    if recalc_normals:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    return _link(bpy.data.objects.new(name, me), coll)


def offset_copy(obj, dist, name=None, coll=None):
    """Copy of a mesh with every vertex pushed dist (metres, world) along its normal
    (grow > 0, shrink < 0).

    For clearance gaps on doors and lids (cut the grown copy from the body). Faces move
    by exactly dist (shell-factor offset, like Solidify's even thickness); fine for
    convex or gently curved shapes, but concave corners can fold, so check the result.
    Modifiers are baked; the copy keeps the original's world matrix.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    sc = obj.matrix_world.to_scale()
    shift = [(v, v.normal.copy(), v.calc_shell_factor()) for v in bm.verts]
    for v, n, k in shift:                 # shell factor: flat faces move exactly dist (even offset)
        v.co += Vector(n[i] / sc[i] for i in range(3)) * dist * k
    bm.to_mesh(me)
    bm.free()
    o = _link(bpy.data.objects.new(name or f"{obj.name}_offset", me),
              coll or (obj.users_collection[0] if obj.users_collection else None))
    o.matrix_world = obj.matrix_world.copy()
    return o


def weld(obj, dist=1e-5):
    """Merge coincident vertices so separately generated pieces form one closed mesh."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def convert_to_mesh(obj):
    """Bake a curve/text object (or modifiers) into a plain mesh object of the same name."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    me = bpy.data.meshes.new_from_object(ev)
    name, loc, rot, colls = obj.name, obj.location.copy(), obj.rotation_euler.copy(), list(obj.users_collection)
    mats = [s.material for s in obj.material_slots]
    bpy.data.objects.remove(obj, do_unlink=True)
    new = bpy.data.objects.new(name, me)
    new.location, new.rotation_euler = loc, rot
    for c in colls:
        c.objects.link(new)
    for m in mats:
        if m:
            new.data.materials.append(m)
    return new


# ---------------------------------------------------------------- finishing

def finish(obj, bevel=0.003, segments=3, angle=30, weighted_normals=True):
    """Hard-surface finish: angle-limited bevel, weighted normals, smooth shading.

    bevel is the edge radius in metres. Real objects almost never have perfectly
    sharp edges; 1-5 mm for furniture/products, 0.5 mm for small electronics.
    """
    if bevel and bevel > 0:
        m = obj.modifiers.new("Bevel", "BEVEL")
        m.width = bevel
        m.segments = segments
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(angle)
        m.use_clamp_overlap = True
        m.harden_normals = True
    if weighted_normals:
        w = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        w.keep_sharp = True
    shade_smooth(obj)
    return obj


def shade_smooth(obj):
    if obj.type == "MESH":
        obj.data.shade_smooth()
    return obj


def subsurf(obj, levels=2, render_levels=None):
    """Subdivision surface. Only on clean quad cages; add support loops to keep edges crisp."""
    m = obj.modifiers.new("Subdivision", "SUBSURF")
    m.levels = levels
    m.render_levels = levels if render_levels is None else render_levels
    shade_smooth(obj)
    return obj


def solidify(obj, thickness, offset=-1.0):
    m = obj.modifiers.new("Solidify", "SOLIDIFY")
    m.thickness = thickness
    m.offset = offset
    m.use_even_offset = True
    return obj


def array(obj, count, offset, relative=False):
    """Repeat obj count times. offset is a vector in metres (or relative factors)."""
    m = obj.modifiers.new("Array", "ARRAY")
    m.count = count
    m.use_relative_offset = relative
    m.use_constant_offset = not relative
    if relative:
        m.relative_offset_displace = offset
    else:
        m.constant_offset_displace = offset
    return obj


def mirror(obj, x=True, y=False, z=False, mirror_object=None):
    m = obj.modifiers.new("Mirror", "MIRROR")
    m.use_axis = (x, y, z)
    m.use_clip = True
    if mirror_object:
        m.mirror_object = mirror_object
    return obj


def available_solvers():
    """Boolean solvers this Blender has, e.g. ['FLOAT', 'EXACT', 'MANIFOLD'] in 5.x
    (FAST was renamed FLOAT in 5.0; MANIFOLD arrived in 4.5)."""
    return [e.identifier for e in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items]


def is_closed(obj):
    """True if the object's base mesh is watertight: every edge has exactly two faces."""
    if obj.type != "MESH" or not obj.data.polygons:
        return False
    me = obj.data
    le = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("edge_index", le)
    return bool(np.all(np.bincount(le, minlength=len(me.edges)) == 2))


def winding_consistent(obj):
    """True if every edge is used once in each direction, i.e. no face is flipped
    against its neighbours. MANIFOLD silently returns the input unchanged otherwise."""
    me = obj.data
    nl, npoly = len(me.loops), len(me.polygons)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(npoly, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(npoly, np.int64)
    me.polygons.foreach_get("loop_total", lt)
    nxt = np.arange(nl) + 1
    nxt[ls + lt - 1] = ls
    key = lv * len(me.vertices) + lv[nxt]
    return len(np.unique(key)) == nl


def pick_solver(*objs, solver="AUTO"):
    """MANIFOLD when available and every input is closed, else EXACT."""
    if solver != "AUTO":
        return solver
    ok = "MANIFOLD" in available_solvers() and all(is_closed(o) for o in objs)
    return "MANIFOLD" if ok else "EXACT"


def boolean(obj, cutter, operation="DIFFERENCE", solver="AUTO"):
    """Boolean with a hidden helper cutter. Cutter is renamed with a '_' prefix so checks ignore it.

    cutter may be an object or a collection of cutters (one modifier for all of them,
    which is much faster with MANIFOLD). solver "AUTO" picks MANIFOLD when available
    and all inputs are closed meshes, else EXACT.
    """
    m = obj.modifiers.new("Boolean", "BOOLEAN")
    m.operation = operation
    if isinstance(cutter, bpy.types.Collection):
        m.operand_type = "COLLECTION"
        m.collection = cutter
        inputs = [o for o in cutter.all_objects if o.type == "MESH"]
        for o in inputs:
            o.display_type = "WIRE"
            o.hide_render = True
    else:
        if not cutter.name.startswith("_"):
            cutter.name = "_" + cutter.name
        cutter.display_type = "WIRE"
        cutter.hide_render = True
        m.object = cutter
        inputs = [cutter]
    m.solver = pick_solver(obj, *inputs, solver=solver)
    return obj


def apply_cuts(target, cutters, op="DIFFERENCE", solver="AUTO", overshoot=0.001, fix_cutters=True,
               fix_target=True):
    """Apply one boolean of target against many cutters and bake it (no bpy.ops).

    The scalable recipe from a 4.9M-triangle print job (about 1 min for 80+ cutters):
    - cutters must be closed meshes (tube_mesh, box, mesh_from_data); with fix_cutters
      their normals are recalculated so MANIFOLD accepts them. With fix_target, a target
      with flipped faces gets its normals recalculated too (MANIFOLD otherwise returns
      it unchanged). Only ever run this on a working copy, never the frozen master.
    - solver "AUTO": MANIFOLD when available and every input is closed, else EXACT
    - display-only WeightedNormal modifiers on target are switched off while baking;
      the rest of target's modifier stack is baked in
    - overshoot (metres; None skips): cutter vertices closer to target's skin than this
      are reported. A cutter face that stops at (or 0.01 mm past) the skin leaves a
      paper-thin skin that seals the pocket; end every cutter >= 1 mm through.
    Order a full assembly as: union/ADD -> splits (doors, lids) -> body cuts -> part cuts.
    Then run verify_cuts (shells, skin openings, tunnels open).

    Returns {"solver", "faces_before", "faces_after", "seconds", "warnings"}.
    """
    t0 = time.time()
    cutters = [c for c in cutters if c is not None]
    warnings = []
    if fix_cutters:
        for c in cutters:
            if c.type == "MESH":
                bm = bmesh.new()
                bm.from_mesh(c.data)
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                bm.to_mesh(c.data)
                bm.free()
    if fix_target and target.type == "MESH" and not winding_consistent(target):
        if target.data.users > 1:
            target.data = target.data.copy()
        bm = bmesh.new()
        bm.from_mesh(target.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(target.data)
        bm.free()
        warnings.append(f"target '{target.name}' had flipped faces; recalculated its normals on this copy "
                        "(MANIFOLD needs consistent winding)")
    open_ = [c.name for c in cutters if not is_closed(c)]
    if open_:
        warnings.append(f"open (non-watertight) cutters: {', '.join(open_[:8])}{' ...' if len(open_) > 8 else ''}")
    if overshoot:
        warnings += _overshoot_warnings(target, cutters, overshoot)
    s = pick_solver(target, *cutters, solver=solver)
    faces_before = len(target.data.polygons)
    verts_before = len(target.data.vertices)
    col = bpy.data.collections.new("_cuts_tmp")
    bpy.context.scene.collection.children.link(col)
    for c in cutters:
        col.objects.link(c)
    saved = [(m, m.show_viewport, m.show_render) for m in target.modifiers if m.type == "WEIGHTED_NORMAL"]
    for m, _, _ in saved:
        m.show_viewport = m.show_render = False
    m = target.modifiers.new("_cuts", "BOOLEAN")
    m.operation = op
    m.operand_type = "COLLECTION"
    m.collection = col
    m.solver = s
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me = bpy.data.meshes.new_from_object(target.evaluated_get(dg))
    finally:
        target.modifiers.remove(m)
        for c in cutters:
            col.objects.unlink(c)
        bpy.data.collections.remove(col)
    old = target.data
    for mm in [mm for mm in target.modifiers if mm.type != "WEIGHTED_NORMAL"]:
        target.modifiers.remove(mm)
    for mm, v, r in saved:
        mm.show_viewport, mm.show_render = v, r
    name = old.name
    target.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    me.name = name
    out = {"solver": s, "op": op, "cutters": len(cutters), "faces_before": faces_before,
           "faces_after": len(me.polygons), "seconds": round(time.time() - t0, 2), "warnings": warnings}
    if not me.polygons:
        out["warnings"].append("boolean result is EMPTY (check cutter normals/closure, or try solver='EXACT')")
    elif len(me.polygons) == faces_before and len(me.vertices) == verts_before and cutters:
        out["warnings"].append("boolean changed nothing: cutters miss the target, or the solver rejected "
                               "the input (non-manifold / flipped faces); try solver='EXACT' to compare")
    import sys
    if "hostkit" in sys.modules:
        sys.modules["hostkit"].clear_cache(target)
    return out


def _overshoot_warnings(target, cutters, overshoot, max_verts=4000):
    import hostkit
    saved = hostkit.UNITS
    hostkit.set_units("m")
    try:
        H = hostkit.host_bvh(target)
        warn = []
        for c in cutters:
            V = hostkit.world_verts(c)
            if len(V) > max_verts:
                V = V[np.linspace(0, len(V) - 1, max_verts).astype(int)]
            _, d = hostkit.nearest(V, H)
            near = d < overshoot
            if near.any():
                i = int(np.argmin(np.where(near, d, np.inf)))
                warn.append(f"OVERSHOOT: cutter '{c.name}' has {int(near.sum())} vertices within "
                            f"{overshoot * 1000:.2f} mm of the skin (closest {d[i] * 1000:.3f} mm at "
                            f"({V[i][0]:.4f}, {V[i][1]:.4f}, {V[i][2]:.4f})); extend it at least "
                            f"{overshoot * 1000:.1f} mm through or it may leave a sealing skin")
        return warn
    finally:
        hostkit.set_units(saved)


def scale_scene(factor, pivot=(0, 0, 0), objects=None, roots_only=True):
    """Scale objects about pivot by changing world matrices.

    roots_only (default): only objects without a parent are scaled; children follow
    their parents. Scaling every object double-scales children (a parented lid ended
    up 860 mm out of place). Keep purchased hardware at real size: scale the body,
    then rebuild hardware from real dimensions. Verify bounds afterwards.
    Returns the scaled objects.
    """
    objs = list(objects) if objects is not None else list(bpy.context.scene.objects)
    p = Vector(pivot)
    S = Matrix.Translation(p) @ Matrix.Scale(factor, 4) @ Matrix.Translation(-p)
    done = []
    for o in objs:
        if roots_only and o.parent is not None:
            continue
        o.matrix_world = S @ o.matrix_world
        done.append(o)
    bpy.context.view_layer.update()
    return done


def apply_modifiers(obj):
    """Bake the modifier stack into the mesh (use before exporting to games/printing)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    bpy.data.meshes.remove(old)
    return obj


# ---------------------------------------------------------------- materials

def material(name, color, roughness=0.5, metallic=0.0, variation=0.15, bump=0.15,
             scale=8.0, specular=0.5, transmission=0.0, coat=0.0, emission=None):
    """Principled material with subtle procedural break-up.

    variation: 0-1, how much colour value and roughness wander across the surface.
    bump: bump strength (0 disables). scale: noise frequency (higher = finer).
    Colours are linear RGB in 0-1.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    _set(bsdf, ("Specular IOR Level", "Specular"), specular)
    _set(bsdf, ("Transmission Weight", "Transmission"), transmission)
    _set(bsdf, ("Coat Weight", "Clearcoat"), coat)
    if emission:
        _set(bsdf, ("Emission Color", "Emission"), (*emission[:3], 1.0))
        _set(bsdf, ("Emission Strength",), emission[3] if len(emission) > 3 else 1.0)

    if variation <= 0 and bump <= 0:
        return mat
    coord = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 6.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])

    if variation > 0:
        hsv = nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Color"].default_value = (*color, 1.0)
        val = nodes.new("ShaderNodeMapRange")
        val.inputs["To Min"].default_value = 1.0 - variation * 0.5
        val.inputs["To Max"].default_value = 1.0 + variation * 0.5
        links.new(noise.outputs["Fac"], val.inputs["Value"])
        links.new(val.outputs["Result"], hsv.inputs["Value"])
        links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
        rough = nodes.new("ShaderNodeMapRange")
        rough.inputs["To Min"].default_value = max(0.0, roughness * (1 - variation))
        rough.inputs["To Max"].default_value = min(1.0, roughness * (1 + variation))
        links.new(noise.outputs["Fac"], rough.inputs["Value"])
        links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    if bump > 0:
        fine = nodes.new("ShaderNodeTexNoise")
        fine.inputs["Scale"].default_value = scale * 12
        fine.inputs["Detail"].default_value = 4.0
        links.new(coord.outputs["Object"], fine.inputs["Vector"])
        bn = nodes.new("ShaderNodeBump")
        bn.inputs["Strength"].default_value = bump
        bn.inputs["Distance"].default_value = 0.002
        links.new(fine.outputs["Fac"], bn.inputs["Height"])
        links.new(bn.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def wood(name, light=(0.30, 0.15, 0.06), dark=(0.11, 0.05, 0.018), roughness=0.5,
         grain_density=40.0, grain_axis="X", bump=0.15):
    """Procedural wood: noise stretched into fine streaks along grain_axis.

    grain_density: streaks per metre across the grain (higher = finer). Colours
    are linear RGB; the defaults are a mid oak. Walnut: light (0.12, 0.06, 0.03),
    dark (0.035, 0.017, 0.008). Pale birch: light (0.55, 0.38, 0.22), dark (0.32, 0.2, 0.1).

    grain_axis must follow each part's long axis in object space (legs: "Z",
    a board lying along X: "X"), so make one material per grain direction.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")
    coord = nodes.new("ShaderNodeTexCoord")

    # Squash space across the grain so noise turns into long thin streaks.
    across = grain_density
    stretch = {"X": (1, across, across), "Y": (across, 1, across), "Z": (across, across, 1)}[grain_axis]
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = stretch
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    # Wobble the streaks a little with a large, unstretched noise.
    warp = nodes.new("ShaderNodeTexNoise")
    warp.inputs["Scale"].default_value = 3.0
    warp_amt = nodes.new("ShaderNodeVectorMath")
    warp_amt.operation = "SCALE"
    warp_amt.inputs["Scale"].default_value = 0.6
    links.new(coord.outputs["Object"], warp.inputs["Vector"])
    links.new(warp.outputs["Color"], warp_amt.inputs[0])
    warped = nodes.new("ShaderNodeVectorMath")
    warped.operation = "ADD"
    links.new(mapping.outputs["Vector"], warped.inputs[0])
    links.new(warp_amt.outputs["Vector"], warped.inputs[1])

    grain = nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 1.5
    grain.inputs["Detail"].default_value = 10.0
    grain.inputs["Roughness"].default_value = 0.65
    links.new(warped.outputs["Vector"], grain.inputs["Vector"])

    ramp = nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.35, (*dark, 1)
    els[1].position, els[1].color = 0.65, (*light, 1)
    links.new(grain.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    rough = nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = roughness + 0.1
    rough.inputs["To Max"].default_value = roughness - 0.1
    links.new(grain.outputs["Fac"], rough.inputs["Value"])
    links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    if bump > 0:
        bn = nodes.new("ShaderNodeBump")
        bn.inputs["Strength"].default_value = bump
        bn.inputs["Distance"].default_value = 0.0005
        bn.invert = True  # dark latewood sits slightly lower
        links.new(grain.outputs["Fac"], bn.inputs["Height"])
        links.new(bn.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def assign_wood(obj, name="Wood", **kw):
    """Assign wood with the grain along the object's longest local axis.

    Reuses one material per (name, axis), e.g. "Oak_X", "Oak_Z". Getting this
    wrong shows blotchy end-grain on big faces, so prefer this over wood().
    """
    dims = obj.dimensions
    axis = "XYZ"[max(range(3), key=lambda i: dims[i])]
    key = f"{name}_{axis}"
    mat = bpy.data.materials.get(key) or wood(key, grain_axis=axis, **kw)
    return assign(obj, mat)


def _set(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


def assign(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return obj


# ---------------------------------------------------------------- presentation

def object_corners(obj, depsgraph=None):
    """8 world-space corners of the object's local box, from its EVALUATED vertices.

    Don't use obj.bound_box: for curves Blender 5.2 pads it by about 1 m, so any
    scene with tubes or cables gets framed 2-3x too wide. Falls back to bound_box only
    when there is no mesh data (empties, an empty boolean result).
    """
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    co = None
    if obj.type == "MESH" and not obj.modifiers and not obj.data.shape_keys:
        me = obj.data
        if len(me.vertices):
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
    else:
        try:
            me = ev.to_mesh()
        except RuntimeError:
            me = None
        if me is not None:
            if len(me.vertices):
                co = np.empty(len(me.vertices) * 3)
                me.vertices.foreach_get("co", co)
            ev.to_mesh_clear()
    if co is None:
        local = [Vector(c) for c in ev.bound_box]
    else:
        co = co.reshape(-1, 3)
        lo, hi = co.min(0), co.max(0)
        local = [Vector((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return [ev.matrix_world @ c for c in local]


def bounds(objs=None):
    """World (lo, hi) of the objects' evaluated geometry (default: visible meshes and curves)."""
    objs = objs or [o for o in bpy.context.scene.objects
                    if o.type in {"MESH", "CURVE", "SURFACE", "FONT", "META"} and not o.name.startswith("_")]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        pts += object_corners(o, depsgraph)
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    return lo, hi


def studio(objs=None, azimuth=-35, elevation=18, lens=65, floor=True, floor_color=(0.5, 0.5, 0.5),
           world_strength=0.25):
    """Hero camera + soft three-light rig + floor for a presentation render.

    Sets scene.camera. Objects created here are named with a leading '_' so the
    geometry check ignores them.
    """
    scene = bpy.context.scene
    lo, hi = bounds(objs)
    center = (lo + hi) / 2
    radius = (hi - lo).length / 2
    coll = collection("_Studio")

    cam = bpy.data.objects.new("_Camera", bpy.data.cameras.new("_Camera"))
    coll.objects.link(cam)
    cam.data.lens = lens
    a, e = math.radians(azimuth), math.radians(elevation)
    d = Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))
    half = math.atan(cam.data.sensor_width / 2 / lens)
    cam.location = center + d * (radius / math.sin(half) * 1.15)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    # Power scales with radius^2 because the lights sit at 4x radius.
    for name, az, el, power, size in (("Key", -50, 45, 250, 1.2), ("Fill", 65, 20, 70, 2.0),
                                      ("Rim", 165, 55, 180, 0.8)):
        ld = bpy.data.lights.new(f"_{name}", "AREA")
        ld.energy = power * radius * radius
        ld.size = size * radius
        lo_ = bpy.data.objects.new(f"_{name}", ld)
        coll.objects.link(lo_)
        a, e = math.radians(az), math.radians(el)
        dd = Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))
        lo_.location = center + dd * radius * 4
        lo_.rotation_euler = (-dd).to_track_quat("-Z", "Y").to_euler()

    if floor:
        f = box("_Floor", (radius * 40, radius * 40, 0.001), (center.x, center.y, lo.z - 0.0005), coll=coll)
        assign(f, material("_FloorMat", floor_color, roughness=0.8, variation=0, bump=0))

    w = bpy.data.worlds.new("_World")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.6, 0.62, 0.65, 1)
    bg.inputs["Strength"].default_value = world_strength
    scene.world = w
    return cam


def render_final(path, engine="CYCLES", samples=128, res=(1600, 1200), denoise=True):
    scene = bpy.context.scene
    r = scene.render
    if engine == "CYCLES":
        r.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        try:
            scene.cycles.device = "GPU"
        except Exception:
            pass
    else:
        for ident in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
            try:
                r.engine = ident
                break
            except TypeError:
                continue
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.filepath = path
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        pass
    bpy.ops.render.render(write_still=True)
    return path
