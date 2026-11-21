"""End-to-end "features inside an existing model" test on a synthetic host.

Builds a 1.2 m lathe figure (~380k triangles) with three pockets, flips 1% of its
faces and gives it an unapplied rotation + scale (like a real sculpted master).
Then: find the pockets (hostkit), route channels to a hub bay around a keep-out
(routekit), check them (check_channels: clean run, then deliberate faults), cut
everything with MANIFOLD (apply_cuts, with one cutter deliberately stopping
0.2 mm short of the skin), verify (verify_cuts), fix the cutter and re-verify,
and render context/ghost and section sheets to look at.

    blender -b --factory-startup --python tests/test_host_pipeline.py -- --out DIR
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import check, done, out_dir  # noqa: E402

import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix  # noqa: E402

import check_channels  # noqa: E402
import check_geometry  # noqa: E402
import hostkit as hk  # noqa: E402
import modelkit as mk  # noqa: E402
import render_views  # noqa: E402
import routekit as rk  # noqa: E402
import verify_cuts  # noqa: E402

OUT = out_dir()
mk.reset_scene()
T = {}


def tic(k):
    T[k] = time.time()


def toc(k):
    T[k] = round(time.time() - T[k], 2)
    print(f"INFO time {k}: {T[k]} s", flush=True)


def box_obj(name, lo_mm, hi_mm, coll=None, role=None):
    lo, hi = np.asarray(lo_mm) / 1000, np.asarray(hi_mm) / 1000
    V = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    F = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    o = mk.mesh_from_data(name, V, F, coll)
    if role:
        o["role"] = role
    return o


# ---------------------------------------------------------------- 1. the host
ctrl = [(0.0, 0.0), (0.16, 0.0), (0.16, 0.06), (0.13, 0.2), (0.11, 0.36), (0.13, 0.5), (0.17, 0.68),
        (0.15, 0.86), (0.08, 0.95), (0.09, 1.0), (0.13, 1.08), (0.1, 1.17), (0.0, 1.2)]
prof = rk.chaikin(np.array([(r, 0.0, z) for r, z in ctrl]), 5)
prof = rk.resample(prof, 0.003)
profile = [(float(p[0]), float(p[2])) for p in prof]


def R(z):
    side = prof[(prof[:, 2] > 0.03) & (prof[:, 2] < 1.15)]
    return float(np.interp(z, side[:, 2], side[:, 0]))


tic("build host")
body = mk.lathe("Body", profile, segments=480)
pockets = {"A": ("head front", 1.08, "-y"), "B": ("chest side", 0.72, "+x"), "C": ("leg front", 0.16, "-y")}
pk_cut = []
for k, (_, z, side) in pockets.items():
    r = R(z) * 1000
    zc = z * 1000
    if side == "-y":
        pk_cut.append(box_obj(f"_pocket {k}", (-15, -r - 20, zc - 15), (15, -r + 15, zc + 15)))
    else:
        pk_cut.append(box_obj(f"_pocket {k}", (r - 15, -15, zc - 15), (r + 20, 15, zc + 15)))
res = mk.apply_cuts(body, pk_cut, overshoot=None)
for c in pk_cut:
    bpy.data.objects.remove(c)
bm = bmesh.new()
bm.from_mesh(body.data)
bm.faces.ensure_lookup_table()
rng = np.random.default_rng(7)
flip = [bm.faces[i] for i in rng.choice(len(bm.faces), len(bm.faces) // 100, replace=False)]
bmesh.ops.reverse_faces(bm, faces=flip)
bm.to_mesh(body.data)
bm.free()
M = Matrix.Translation((0.05, -0.02, 0.0)) @ Matrix.Rotation(math.radians(37), 4, "Z") @ Matrix.Scale(1.25, 4)
body.data.transform(M.inverted())           # world shape unchanged, transform left unapplied
body.matrix_world = M
body.data.calc_loop_triangles()
bpy.context.view_layer.update()
toc("build host")
ntri = len(body.data.loop_triangles)
check("host is big, flipped, unapplied", ntri > 300_000 and len(flip) > 1000 and abs(body.scale[0] - 1.25) < 1e-6,
      f"{ntri:,} tris, {len(flip):,} flipped faces, scale {tuple(round(s, 3) for s in body.scale)}, "
      f"rot z {math.degrees(body.rotation_euler.z):.0f} deg, pocket cuts {res['solver']} {res['seconds']} s")

# inside/outside: face-normal sign vs ray parity
hk.set_units("mm")
rng = np.random.default_rng(3)
zs = rng.uniform(0.1, 1.1, 3000)
th = rng.uniform(0, 2 * np.pi, 3000)
rad_in = np.array([R(z) for z in zs]) * rng.uniform(0.0, 0.6, 3000)
rad_out = np.array([R(z) for z in zs]) * rng.uniform(1.15, 1.6, 3000)
P_in = np.stack([rad_in * np.cos(th), rad_in * np.sin(th), zs], 1) * 1000
P_out = np.stack([rad_out * np.cos(th), rad_out * np.sin(th), zs], 1) * 1000
H = hk.host_bvh(body)
wrong_n = 0
for P, want in ((P_in, True), (P_out, False)):
    for p in H.local(P / 1000):
        loc, nrm, _, _ = H.tree.find_nearest(p)
        wrong_n += ((p - loc).dot(nrm) < 0) != want
tic("parity 6000 pts")
wrong_p = int((~hk.inside(P_in, body)).sum() + hk.inside(P_out, body).sum())
toc("parity 6000 pts")
check("ray parity beats face normals on flipped faces", wrong_p == 0 and wrong_n > 0,
      f"normal-sign test wrong on {wrong_n}/6000 points, ray parity wrong on {wrong_p}/6000")
cl = hk.clearance([(0, 0, 600)], body)[0]              # on the figure's axis (world)
check("clearance on the axis <= local radius", 0.9 * R(0.6) * 1000 < cl <= R(0.6) * 1000 + 0.5,
      f"{cl:.1f} mm vs radial {R(0.6) * 1000:.1f} mm")

# pockets
tic("pocket finder")
clusters = hk.sharp_edge_clusters(body, link=6.0)
toc("pocket finder")
design = {}
for k, (_, z, side) in pockets.items():
    r = R(z) * 1000
    design[k] = np.array([0, -r, z * 1000]) if side == "-y" else np.array([r, 0, z * 1000])
found = {}
for c in clusters:
    k = min(design, key=lambda q: np.linalg.norm(design[q] - c["center"]))
    if np.linalg.norm(design[k] - c["center"]) < 30:
        fl = hk.ray_floor(c["center"], c["normal"], body, start=5.0)
        found[k] = {"center": c["center"], "normal": c["normal"], "floor": fl, "edges": c["n_edges"]}
check("sharp_edge_clusters finds exactly the 3 pockets", len(clusters) == 3 and len(found) == 3,
      f"{len(clusters)} clusters: " + ", ".join(f"{k} ({v['edges']} edges)" for k, v in sorted(found.items())))
depths = {k: v["floor"]["depth"] for k, v in found.items() if v["floor"]}
check("ray_floor depths ~15 mm", len(depths) == 3 and all(12 < d < 17 for d in depths.values()),
      ", ".join(f"{k} {d:.1f} mm" for k, d in sorted(depths.items())))

# ---------------------------------------------------------------- 2. routing (mm)
feat = mk.collection("FEATURES")
wiring = bpy.data.collections.new("WIRING")
feat.children.link(wiring)
bay_lo, bay_hi = np.array([-30, -25, 580]), np.array([30, 25, 620])
bay = box_obj("CUT bay", bay_lo, bay_hi, feat, "cut")
vault = box_obj("KEEP vault", (-80, -10, 680), (80, 90, 850), feat, "keepout")
hub = (bay_lo + bay_hi) / 2

tic("voxelize 10 mm")
g = hk.voxelize(body, step=10.0)
toc("voxelize 10 mm")
tic("keepouts")
blocked = rk.keepouts_from(g, [vault], margin=10.0)
toc("keepouts")
free = hk.box_mask(g, [(bay_lo, bay_hi)])
tic("dijkstra tree")
tree = rk.clearance_tree(g, hub, min_clear=12.0, pref_clear=40.0, blocked=blocked, free=free)
toc("dijkstra tree")
check("voxel grid + tree", g["inside"].sum() > 50_000 and np.isfinite(tree["dist"]).sum() > 10_000,
      f"grid {tuple(g['shape'])}, {int(g['inside'].sum()):,} inside, {int(np.isfinite(tree['dist']).sum()):,} reached, "
      f"{int(blocked.sum()):,} blocked")

leaves, drops = {}, {}
for k, v in found.items():
    f, n = v["floor"]["point"], v["normal"]
    entry = f - n * 12.0
    leaves[k] = (entry, 1)
    drops[k] = (f + n * 2.0, entry)
exit_pt = np.array([0.0, 0.0, 40.0])
leaves["exit"] = (exit_pt, 3)
segs = rk.merge_tree(tree, leaves)


def ok(p):
    i = hk.to_idx(g, p)
    return (g["clear"][i] >= 10.0 or free[i]) and not blocked[i]


tubes = {}
for s in segs:
    P = rk.resample(rk.smooth(s["points"], 30, ok=ok), 4.0)
    power = "exit" in s["leaves"]
    dia = 10.0 if power else (6.0 if s["weight"] <= 1 else 8.0)
    name = "ch " + "+".join(s["leaves"])
    o = mk.tube_mesh(name, P, dia, end_ext=1.5, units="mm", coll=wiring)
    o["role"] = "power" if power else "channel"
    tubes[name] = o
for k, (a, b) in drops.items():
    o = mk.tube_mesh(f"drop {k}", [a, b], 6.0, end_ext=1.5, units="mm", coll=wiring)
    o["role"] = "channel"
o = mk.tube_mesh("drop exit", [exit_pt, (0, 0, -5.0)], 10.0, end_ext=1.5, units="mm", coll=wiring)
o["role"] = "power"
check("merge_tree segments", len(segs) >= 4, ", ".join(f"{'+'.join(s['leaves'])} ({len(s['points'])} vox)" for s in segs))

spec = {"units": "mm", "channels": {
    "units": "mm", "host": "Body", "collection": "WIRING", "wall_min": 3.0, "bend_min": 15.0,
    "keepouts": ["KEEP vault"], "keepout_min": 3.0, "hub": "bay", "exits": ["drop exit"],
    "terminals": {**{f"pocket_{k}": {"point": v["floor"]["point"].tolist(), "radius": 4.0} for k, v in found.items()},
                  "bay": {"object": "CUT bay"}},
    "wires": {"ch *bad*": 12, "*": 2}, "wire_od": 1.5, "fill_max": 0.6}}
tic("check_channels")
rep = check_channels.run(spec=spec, out_path=os.path.join(OUT, "host_channels_clean.json"), verbose=False)
toc("check_channels")
walls = [e["min_wall"] for e in rep["channels"].values() if "min_wall" in e]
bends = [e["min_bend"] for e in rep["channels"].values() if e.get("min_bend")]
check("check_channels: routed network is clean", rep["summary"]["errors"] == 0,
      f"{rep['summary']['channels']} channels, {rep['total_length']:.0f} mm, min wall {min(walls):.1f} mm, "
      f"min bend R{min(bends):.1f} mm, errors: {rep['errors'][:3]}")
with open(os.path.join(OUT, "host_channels_clean.txt"), "w", encoding="utf-8") as f:
    f.write(rep["text"])

# deliberate faults: a branch that stops 8 mm short of the trunk, a run 1.5 mm under the skin
trunk = max(tubes.values(), key=lambda o: len(o["centerline"]))
TP = np.asarray(list(trunk["centerline"])).reshape(-1, 3) * 1000
q = TP[len(TP) // 2]
t = TP[len(TP) // 2 + 1] - TP[len(TP) // 2 - 1]
d = np.cross(t, (0, 0, 1.0))
d /= np.linalg.norm(d)
rt = trunk["dia"] * 1000 / 2
bad = mk.tube_mesh("ch bad_branch", [q + d * 50, q + d * (rt + 8)], 6.0, units="mm", coll=wiring)
z = 0.45
ang = np.radians(np.linspace(200, 230, 16))
rr = R(z) * 1000 - 3.0 - 1.5
thin = mk.tube_mesh("ch thin_run", np.stack([rr * np.cos(ang), rr * np.sin(ang), np.full(16, z * 1000)], 1),
                    6.0, units="mm", coll=wiring)
spec_bad = {"units": "mm", "channels": dict(spec["channels"], terminals=dict(
    spec["channels"]["terminals"], sensor={"point": (q + d * 50).tolist(), "radius": 2.0},
    thin_a={"point": [rr * np.cos(ang[0]), rr * np.sin(ang[0]), z * 1000], "radius": 1.0},
    thin_b={"point": [rr * np.cos(ang[-1]), rr * np.sin(ang[-1]), z * 1000], "radius": 1.0}))}
rep2 = check_channels.run(spec=spec_bad, out_path=os.path.join(OUT, "host_channels_faults.json"), verbose=False)
with open(os.path.join(OUT, "host_channels_faults.txt"), "w", encoding="utf-8") as f:
    f.write(rep2["text"])
E = rep2["errors"]
kinds = {"loose": any(e.startswith("LOOSE END: ch bad_branch end") for e in E),
         "hub": sum(e.startswith("NOT CONNECTED TO HUB") for e in E) == 2,
         "thin": any(e.startswith("THIN WALL: ch thin_run") for e in E),
         "fill": any(e.startswith("OVERFULL: ch bad_branch") for e in E)}
innocent = [e for e in E if "bad_branch" not in e and "thin_run" not in e]
thin_wall = rep2["channels"]["ch thin_run"].get("min_wall")
check("check_channels catches loose end, hub gap, thin wall, overfill", all(kinds.values()) and not innocent,
      f"{kinds}; thin_run wall {thin_wall} mm; {len(E)} errors; false alarms {innocent[:2]}")
gr = check_geometry.run(spec={"host": "Body", "units": "mm"}, collection="WIRING", verbose=False)
check("check_geometry scoped to channels: no ground warning, mm units",
      not any("ground" in w for w in gr["warnings"]) and gr["units"] == "mm",
      f"{gr['summary']}; first error: {(gr['errors'] or ['-'])[0][:90]}")
gs = check_geometry.run(names=["Body"], verbose=False, max_verts=100_000)
check("check_geometry skips a huge host", any("skipped" in i for i in gs["info"]), gs["info"][0][:80])
for o in (bad, thin):
    bpy.data.objects.remove(o)

# context / ghost render (before cutting)
# stops 0.2 mm short of the floor skin (MANIFOLD happens to drop a 0.01 mm sliver, but don't rely on it)
pocket_d = box_obj("CUT pocket D (short)", (70, -10, 0.2), (90, 10, 20), feat, "cut")
tic("context render")
sheet = render_views.run(OUT, mode="clay", res=448, collection="FEATURES", context=["Body"], color_by="role",
                         min_line_px=3, sheet_name="host_context_sheet.png")
toc("context render")
check("context/ghost sheet rendered", os.path.isfile(sheet), sheet)

# ---------------------------------------------------------------- 3. cuts
def final_copy(name):
    o = bpy.data.objects.new(name, body.data.copy())
    o.matrix_world = body.matrix_world.copy()
    bpy.context.scene.collection.objects.link(o)
    return o


cutters = list(wiring.objects) + [bay, pocket_d]
final = final_copy("Body (final)")
tic("MANIFOLD cuts")
cr = mk.apply_cuts(final, cutters, overshoot=0.001)
toc("MANIFOLD cuts")
short = [w for w in cr["warnings"] if "OVERSHOOT" in w]
check("apply_cuts: MANIFOLD on the big host, short cutter flagged",
      cr["solver"] == "MANIFOLD" and cr["faces_after"] > 0 and len(short) == 1 and "pocket D" in short[0],
      f"{cr['solver']} {cr['cutters']} cutters {cr['seconds']} s, {cr['faces_before']:,} -> {cr['faces_after']:,} faces; "
      f"warnings: {[w[:70] for w in cr['warnings']]}")

lid = box_obj("PART lid", (-15, -R(1.08) * 1000 - 30, 1065), (15, -R(1.08) * 1000 - 25, 1095), feat, "part")
magnet = box_obj("PART magnet", (6, -R(1.08) * 1000 + 13, 1077), (12, -R(1.08) * 1000 + 16, 1083), feat, "magnet")
vspec = {"units": "mm", "verify": {
    "final": "Body (final)", "original": "Body", "samples": 60000, "tol": 0.5, "cell": 25.0,
    "openings": [{"name": f"pocket {k} drop", "point": v["floor"]["point"].tolist(), "radius": 8.0} for k, v in found.items()]
    + [{"name": "power exit", "point": [0, 0, 0], "radius": 12.0},
       {"name": "pocket D", "point": [80, 0, 0], "radius": 15.0}],
    "tunnels": {"collection": "WIRING"}, "cavities": ["CUT bay"], "apart": [["PART lid", "Body (final)"]],
    "shells": {"Body (final)": 1}}}
tic("verify")
vr = verify_cuts.run(spec=vspec, out_path=os.path.join(OUT, "host_verify_short.json"), verbose=False)
toc("verify")
with open(os.path.join(OUT, "host_verify_short.txt"), "w", encoding="utf-8") as f:
    f.write(vr["text"])
E = vr["errors"]
check("verify_cuts catches the sealed pocket (missing opening + void shell)",
      any(e.startswith("MISSING OPENING 'pocket D'") for e in E) and any("shells, expected 1" in e for e in E)
      and len(E) == 2,
      f"{len(E)} errors: {[e[:60] for e in E]}")
tun = vr.get("tunnels", {})
check("tunnels open, bay empty, lid apart", all(r["blocked_pct"] <= 1.0 for r in tun.values())
      and vr["cavities"]["CUT bay"]["solid_pct"] == 0 and not vr["apart"][0]["touching"],
      f"{len(tun)} tunnels max blocked {max(r['blocked_pct'] for r in tun.values())}%, "
      f"bay {vr['cavities']['CUT bay']['solid_pct']}% solid, skin {vr['skin_openings']['gone']} gone in "
      f"{len(vr['skin_openings']['clusters'])} openings")
hk.set_units("mm")
ve = verify_cuts.cavity_empty(final, vault)
tp = verify_cuts.touching_parts(magnet, final)
check("negative controls: uncut vault is solid, magnet touches body", ve["solid_pct"] > 95 and tp["touching"],
      f"vault {ve['solid_pct']}% solid; magnet {tp}")

# fix: the pocket cutter goes 1 mm through, cut again, verify again
bpy.data.objects.remove(final)
bpy.data.objects.remove(pocket_d)
pocket_d = box_obj("CUT pocket D", (70, -10, -1.0), (90, 10, 20), feat, "cut")
final = final_copy("Body (final)")
cr2 = mk.apply_cuts(final, list(wiring.objects) + [bay, pocket_d], overshoot=0.001)
vr2 = verify_cuts.run(spec=vspec, out_path=os.path.join(OUT, "host_verify_fixed.json"), verbose=False)
with open(os.path.join(OUT, "host_verify_fixed.txt"), "w", encoding="utf-8") as f:
    f.write(vr2["text"])
check("after the fix: no overshoot warning, verify clean",
      not any("OVERSHOOT" in w for w in cr2["warnings"]) and vr2["summary"]["errors"] == 0,
      f"{cr2['seconds']} s; verify errors {vr2['errors'][:2]}; shells {len(vr2['shells']['Body (final)'])}")

# section render of the cut body: front half removed, tunnels visible
body.hide_render = True
for o in feat.all_objects:
    o.hide_render = True
tic("section render")
sec = render_views.run(OUT, mode="clay", res=448, names=["Body (final)"], section=("y", 0.0),
                       views=["front", "three_quarter_left", "right", ("close_up", -20, 10, False)],
                       sheet_name="host_section_sheet.png")
toc("section render")
check("section sheet rendered", os.path.isfile(sec), sec)
zoom = ((-0.17, -0.05, 0.45), (0.17, 0.12, 0.78))        # bay, trunk and the pocket-B branch (metres)
sec2 = render_views.run(OUT, mode="clay", res=512, names=["Body (final)"], section=("y", 0.0), focus=zoom,
                        views=["front", ("front_low", 0, 15, False)], sheet_name="host_section_closeup.png")
check("section close-up rendered", os.path.isfile(sec2), sec2)
print("INFO timings " + ", ".join(f"{k} {v}s" for k, v in T.items()))
# scene + spec for the command-line test (run_tests.py "hostcli")
import json  # noqa: E402
body.hide_render = False
for o in feat.all_objects:
    o.hide_render = False
spec_all = {"units": "mm", "host": "Body", "channels": spec["channels"], "verify": vspec["verify"]}
with open(os.path.join(OUT, "host_spec.json"), "w", encoding="utf-8") as f:
    json.dump(spec_all, f, indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "host_scene.blend"), copy=True)
done()
