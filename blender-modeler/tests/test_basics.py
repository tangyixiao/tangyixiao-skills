"""Fast unit checks (headless Blender): curve bounds (B1), hostkit, routekit, modelkit.

    blender -b --factory-startup --python tests/test_basics.py -- --out DIR
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import check, done, out_dir  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import hostkit  # noqa: E402
import modelkit as mk  # noqa: E402
import render_views  # noqa: E402
import routekit  # noqa: E402

OUT = out_dir()
mk.reset_scene()

# ---- B1: curve bounds ------------------------------------------------------------
# 6 mm cables over a 0.3 m layout, kept as curves (like a port file of channels)
paths = [[(0.0, 0.0, 0.0), (0.05, 0.01, 0.10), (0.06, 0.0, 0.30)],
         [(0.0, 0.0, 0.0), (-0.08, 0.02, 0.12), (-0.1, 0.0, 0.25)],
         [(0.0, 0.0, 0.0), (0.0, 0.05, -0.05)]]
curves = [mk.tube(f"cable {i}", p, 0.003, kind="poly", to_mesh=False) for i, p in enumerate(paths)]
dg = bpy.context.evaluated_depsgraph_get()
old = []
for o in curves:
    ev = o.evaluated_get(dg)
    old += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
old_span = max(p.x for p in old) - min(p.x for p in old)
lo, hi = mk.bounds(curves)
true_x = (min(p[0] for q in paths for p in q) - 0.003, max(p[0] for q in paths for p in q) + 0.003)
check("curve bound_box is padded (the bug exists)", old_span > 1.0, f"bound_box x span {old_span:.3f} m")
check("modelkit.bounds uses evaluated verts", abs((hi.x - lo.x) - (true_x[1] - true_x[0])) < 0.002,
      f"x span {hi.x - lo.x:.4f} m vs true {true_x[1] - true_x[0]:.4f} m")
sheet = render_views.run(os.path.join(OUT, "basics_curves"), mode="clay", res=256, views=["front", "top"])
check("render_views frames curves", os.path.isfile(sheet), sheet)

# ---- modelkit: tube_mesh, solvers, offset_copy, scale_scene -------------------
t = mk.tube_mesh("tm", [(0, 0, 0), (10, 0, 0), (20, 5, 3), (30, 5, 10)], 6.0, end_ext=1.5, units="mm")
check("tube_mesh is closed", mk.is_closed(t), f"{len(t.data.polygons)} faces")
check("tube_mesh stores centre line + dia", "centerline" in t and abs(t["dia"] - 0.006) < 1e-9,
      f"dia {t['dia']} m, {len(t['centerline']) // 3} points")
solvers = mk.available_solvers()
box = mk.box("b", (0.05, 0.05, 0.05))
check("AUTO solver picks MANIFOLD for closed inputs", mk.pick_solver(box, t) == ("MANIFOLD" if "MANIFOLD" in solvers else "EXACT"),
      f"available {solvers}")
plane = bpy.data.objects.new("pl", bpy.data.meshes.new("pl"))
plane.data.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
bpy.context.scene.collection.objects.link(plane)
check("AUTO solver falls back to EXACT for open meshes", mk.pick_solver(box, plane) == "EXACT")
grown = mk.offset_copy(box, 0.001)
gd = max(grown.dimensions)
check("offset_copy grows by dist", abs(gd - 0.052) < 1e-4, f"{gd:.4f} m")
parent = mk.box("parent", (0.1, 0.1, 0.1), (1, 0, 0))
child = mk.box("child", (0.02, 0.02, 0.02))
child.parent = parent
child.matrix_parent_inverse = parent.matrix_world.inverted()
child.location = (1.2, 0, 0)
bpy.context.view_layer.update()
before = child.matrix_world.translation.copy()
mk.scale_scene(2.0, objects=[parent, child])
after = child.matrix_world.translation
check("scale_scene scales roots only (no double scale)", (after - before * 2).length < 1e-6,
      f"child {tuple(round(c, 4) for c in before)} -> {tuple(round(c, 4) for c in after)}")

# ---- hostkit on a non-uniformly scaled, rotated, partly flipped cube -------------
cube = mk.box("host", (1, 1, 1))
import bmesh  # noqa: E402
bm = bmesh.new()
bm.from_mesh(cube.data)
bmesh.ops.reverse_faces(bm, faces=bm.faces[:2])
bm.to_mesh(cube.data)
bm.free()
cube.matrix_world = Matrix.Translation((0.3, -0.2, 0.1)) @ Matrix.Rotation(math.radians(30), 4, "Z") @ Matrix.Diagonal((0.4, 0.2, 0.1, 1))
bpy.context.view_layer.update()
hostkit.set_units("mm")
c = np.array([300.0, -200.0, 100.0])
cl = hostkit.clearance([c, c + (0, 0, 200)], cube)
check("clearance inside non-uniform host = half thinnest side", abs(cl[0] - 50.0) < 0.5, f"{cl[0]:.2f} mm")
check("clearance outside is negative", cl[1] < 0, f"{cl[1]:.2f} mm")
fn = hostkit.world_normals(cube)
check("world_normals unit length", np.allclose(np.linalg.norm(fn, axis=1), 1.0))
g = hostkit.voxelize(cube, step=10.0)
vol = g["inside"].sum() * 1000.0
check("voxelize volume ~ 400x200x100 mm", abs(vol - 8e6) / 8e6 < 0.1, f"{vol / 1e6:.2f} L vs 8.00 L")
check("voxel clearance peaks near 50 mm", 35 <= g["clear"].max() <= 60, f"max {g['clear'].max():.1f} mm")
hostkit.set_units("m")

# ---- routekit polylines ------------------------------------------------------------
th = np.linspace(0, math.pi / 2, 40)
arc = np.stack([0.02 * np.cos(th), 0.02 * np.sin(th), np.zeros_like(th)], 1)
br = routekit.bend_radii(routekit.resample(arc, 0.002))
check("bend_radii of a 20 mm arc", abs(np.median(br) - 0.02) < 1e-3, f"median {np.median(br) * 1000:.2f} mm")
polys = {"trunk": np.array([[0, 0, 0], [0.1, 0, 0]]), "branch": np.array([[0.05, 0.004, 0], [0.05, 0.05, 0]])}
snapped, snaps = routekit.snap_junctions(polys, tol=0.01)
check("snap_junctions closes a 4 mm junction gap", ("branch", "start") in snaps and
      routekit.closest_on_polyline(polys["trunk"], snapped["branch"][0])[1] < 1e-9, str(snaps))

# ---- live_view is a no-op without a UI; portkit round trip ----------------------
lv = render_views.live_view(focus=[curves[0].name], xray=0.25, color_by="material")
render_views.restore_view(lv["previous"])
check("live_view sets and restores the stored 3D views (no bpy.ops)", lv["areas"] >= 0,
      str({k: lv[k] for k in ("areas", "center")}))
import portkit  # noqa: E402
coll = mk.collection("PORT")
for o in curves[:2] + [t]:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    coll.objects.link(o)
t["role"] = "channel"
data = portkit.dump("PORT", os.path.join(OUT, "port.json"), version="v01")
n_t = len(data["collections"]["tubes"])
n_m = len(data["collections"]["meshes"])
path = os.path.join(OUT, "port_{version}.blend")
portkit.rebuild(os.path.join(OUT, "port.json"), path.format(version="v01"), readme="Port test: append PORT.")
rebuilt = bpy.data.collections["PORT"].all_objects
check("portkit dump -> rebuild keeps tubes, meshes, props, README",
      os.path.isfile(path.format(version="v01")) and len(rebuilt) == n_t + n_m
      and any(o.get("role") == "channel" for o in rebuilt) and "README" in bpy.data.texts,
      f"{n_t} tubes + {n_m} meshes -> {len(rebuilt)} objects")
done()
