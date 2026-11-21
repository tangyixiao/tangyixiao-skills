# Features inside or on an existing model

The recipe for adding channels, wiring, cavities, vaults, pockets and mounts to
a model that already exists: a sculpt, scan or finished print master. It came
from a 7-hour session on a 4.9M-triangle figure where the measured,
script-driven approach worked and screenshot-driven iteration hadn't.

The new-object workflow (spec dims, ground contact, blockout → materials, the
8-view sheet) mostly doesn't apply here. The rules do: measure, one editable
generator, check after every change, version every output.

## The frozen-host contract

- The host is **read-only context**: something to measure, draw as a ghost in
  renders, and verify cuts against. Never edit it in place, never save over the
  master. Save new masters under new names (`_v56`, `_v57_FINAL`).
- The new features live in their own collection(s), built by a generator
  script you can re-run any time; re-running replaces only that collection.
- Everything is exchanged at the host's **world coordinates**, so the features
  drop into the master without moving anything.

## 1. Find and open the master

Ask which file is the master if the user hasn't named it. Don't scan the disk
for .blend files. Opening an autosave from a temp folder needs an explicit OK.

- Headless: `bmod.py --blend <master> --script ...` (auto-run scripts are
  always disabled). Work on the master read-only, or on a copy.
- Live: `bpy.ops.wm.open_mainfile(filepath=..., load_ui=False, use_scripts=False)`,
  or launch Blender with `--online-mode --disable-autoexec "<file>"`.

## 2. Transforms and units

Print the host's `location`, `rotation_euler`, `scale` and vertex/face count.
Scanned and sculpted hosts often carry an unapplied rotation and a scale like
1.27; everything has to go through `matrix_world`. `hostkit` does that for you.

Pick one working unit. For print/fabrication work use mm: `hostkit.set_units("mm")`,
`"units": "mm"` in the spec, `units="mm"` for `tube`/`tube_mesh`. Convert once,
at the bpy boundary, and state the unit in every number you report.

## 3. Measure: `measured.json`

```python
import hostkit as hk
hk.set_units("mm")
host = bpy.data.objects["Body"]
for i, c in enumerate(hk.sharp_edge_clusters(host, link=6.0)):
    fl = hk.ray_floor(c["center"], c["normal"], host, start=5.0)
    print(i, c["center"].round(1), c["normal"].round(3), c["n_edges"], fl and round(fl["depth"], 1))
```

- `sharp_edge_clusters` uses the mesh's `sharp_edge` attribute, else the face
  angle; flipped faces don't create false edges. It finds pockets, rims and
  cut-outs. **List every cluster to the user and ask which ones are features**
  (in the session, two nostril pockets were measured and then forgotten).
- `ray_floor` gives a pocket's floor point and depth along its axis;
  `pca_axes(points)` gives a cluster's axes; `scan_heightmap` maps the surface
  around a point (rim straightness, depth spread) with rays.
- Inside/outside: `hk.inside(pts, host)` (ray parity, 3-ray majority) and
  `hk.clearance(pts, host)` (distance to the skin, + inside, − outside).
  Never use the face-normal sign: on real meshes it flips for points deep
  inside (it reported "−20.6 mm, outside" for a point in the chest).
- Save the facts (floors, normals, depths, transforms) to `measured.json`, and
  load them in the generator. Positions measured on one version scale with the
  body if it is rescaled; directions and hardware sizes don't.

## 4. Keep-outs and cavities before routing

Agree the large volumes first: vaults, battery bays, controller bays, ballast,
door swings, magnet pins. Build them as closed cutter meshes (`CUT …` names).
Routing done before the keep-outs were known ran straight through where the
vault had to go. Design mechanisms (doors, locks, lids) with the user before
building them: a short plan with sizes, forces and alternatives.

## 5. The generator

One script (`model.py`, plus e.g. `vaults.py`) with parameters at the top:
walls, bend limits, diameters by wire count, hardware sizes. It builds only the
new features into its own collection and writes its report JSON. Rules:
- data API and bmesh only; no `bpy.ops` (it runs live too)
- give every object a `role` custom prop (`channel`, `power`, `cut`, `split`,
  `part`, `magnet`, `keepout`, `ballast`) for colour-coded renders
- name objects by what to do with them when porting: `ADD …`, `SPLIT door …`,
  `CUT body …`, `CUT door …`, `PART …`
- channels: `mk.tube_mesh(name, pts_mm, dia_mm, end_ext=1.5, units="mm")`
  (watertight, stores its centre line and diameter for the checks), or
  `mk.tube(..., kind="poly")` for a light curve preview

Routing through the host (`routekit`):

```python
import routekit as rk
g = hk.voxelize(host, step=5.0)                       # inside + clearance (mm); ~1 s at 5 mm on 4.9M tris
blocked = rk.keepouts_from(g, ["CUT vault", "CUT bay door"], margin=10.0)
free = hk.box_mask(g, [(bay_lo, bay_hi)])             # the hub chamber itself
tree = rk.clearance_tree(g, hub, min_clear=7.0, pref_clear=25.0, blocked=blocked, free=free)
segs = rk.merge_tree(tree, {"eye_R": (entry_pt, 1), "power": (exit_pt, 4)})
for s in segs:                                        # shared junctions stay exact
    P = rk.resample(rk.smooth(s["points"], 40, ok=lambda p: g["clear"][hk.to_idx(g, p)] >= 7), 3.0)
    mk.tube_mesh("ch " + "+".join(s["leaves"]), P, dia_for(s["weight"]), end_ext=1.5, units="mm", coll=wiring)
```
Drop holes go straight from each pocket floor to the network (`entry = floor -
n * drop_len`). If you edit paths by hand, re-snap junctions
(`rk.snap_junctions`) so every branch starts exactly on its trunk.

## 6. Check

`check_channels` (spec key `"channels"`, see its docstring):
```json
{"units": "mm", "host": "Body",
 "channels": {"units": "mm", "host": "Body", "collection": "WIRING",
   "wall_min": 3, "bend_min": 15, "bend_exempt": ["ch elbow*"],
   "keepouts": ["CUT vault"], "keepout_min": 3,
   "terminals": {"bay": {"object": "CUT bay"}, "eye_R": {"point": [-15.7, -131.1, 1044.6], "radius": 4}},
   "hub": "bay", "exits": ["drop power*"],
   "wires": {"ch *": 3, "trunk*": 8}, "wire_od": 1.6, "fill_max": 0.6}}
```
`bmod.py --blend host.blend --model model.py --spec spec.json --collection WIRING --no-save --out renders/v03`
runs the generator, `check_geometry` scoped to the collection (ground check off,
because the spec names a host) and `check_channels`, and exits 2 on errors.

What the errors mean:
- `LOOSE END`: an end lands on no channel centre line, terminal or declared exit.
  A trunk starting 35 mm past its branch still *overlaps* the cash it sits in,
  so contact checks pass; this one doesn't.
- `NOT CONNECTED TO HUB`: a whole network doesn't reach the hub terminal.
- `OFF-CENTRE JUNCTION` (warning): a branch meets its trunk more than half a
  radius off-centre. Snap it.
- `THIN WALL`, `TIGHT BEND`, `KEEP-OUT`, `OVERFULL`: with the location and the
  needed value.

## 7. Review: context renders, close-ups, cutaways

The 8-view sheet of the features alone shows floating sticks; with the host
opaque, the features are hidden. Use a context render instead:

```
bmod.py --blend host.blend --model model.py --collection FEATURES --context Body --color-by role --min-line-px 3 --no-save --out renders/v03
```
- the host is drawn as a faint ghost, the features on top, coloured by role
- `--focus all` frames the whole host; in Python, `focus=(lo, hi)` (metres)
  plus `views=[("close", -20, 15, False)]` gives a close-up of a changed area
- `--section y,0.0` removes everything in front of y = 0: the cut body shows
  its tunnels as half-pipes. Offer this when the user asks "is it really
  hollow / connected?"
- live: `render_views.live_view(az, el, focus="FEATURES", xray=0.2, color_by="role")`,
  then take a viewport screenshot (see `live_mode.md`)

Say what each colour means when you send the image.

## 8. Port files

Write versioned .blend files with the features at the host's world
coordinates, plus a README text block with the porting order, built headless:

```python
portkit.dump("WIRING", r"<project>/wiring_parts.json")           # live: only writes JSON
```
```
bmod.py --script <skill>/scripts/portkit.py -- --rebuild wiring_parts.json --out "wiring_{version}.blend" --version v07 --readme README_port.txt
```
Pass the version on the command line; don't text-patch `VER = "v12"` in a script.
Generate the README numbers from the report JSON, not by hand.

## 9. Final assembly (only on the user's go) and verification

Run it headless in the background on the master (read-only) with
`--save-as <new name>`:

```python
def copy_of(o, name):                             # never cut the master object itself
    c = bpy.data.objects.new(name, o.data.copy())
    c.matrix_world = o.matrix_world.copy()
    bpy.context.scene.collection.objects.link(c)
    return c

fin = copy_of(host, "Body (final)")
mk.apply_cuts(fin, adds, op="UNION")                          # 1. ADD: merge parts into the body
door = copy_of(fin, "Door (print)")
mk.apply_cuts(door, [door_split], op="INTERSECT")             # 2. splits: the part ...
mk.apply_cuts(fin, [mk.offset_copy(door_split, 0.0003)])      #    ... and the body, 0.3 mm gap
mk.apply_cuts(fin, body_cuts)                                 # 3. every body cut in one MANIFOLD op
mk.apply_cuts(door, door_cuts)                                # 4. part cuts
```
- `apply_cuts` picks MANIFOLD when every input is closed (about 1 min for 80+
  cutters on 4.9M triangles), recalculates cutter normals, fixes a target with
  flipped faces (on the copy), and warns when a cutter ends within `overshoot`
  (1 mm) of the skin or when the boolean changed nothing.
- Every cutter that opens the skin goes ≥ 1 mm through it. A cut 0.01 mm past
  the surface left paper-thin skins sealing magnet wells.

Then `verify_cuts` (spec key `"verify"`):
```json
{"verify": {"units": "mm", "final": "Body (final)", "parts": ["Door (print)"], "original": "Body",
  "openings": [{"name": "eye_R pocket", "point": [-15.7, -131.1, 1044.6], "radius": 12},
               {"name": "power exit", "object": "CUT power exit"}],
  "tunnels": {"collection": "WIRING"}, "cavities": ["CUT bay"],
  "apart": [["Door (print)", "Body (final)"]], "shells": {"Body (final)": 1, "Door (print)": 1}}}
```
`bmod.py --script <skill>/scripts/verify_cuts.py --blend final_v01.blend -- --spec spec.json`
- skin openings: samples the original skin, clusters what vanished, and
  matches it to the declared openings. Unexpected openings are errors, and so
  are declared openings that are still sealed.
- shells: watertight parts; an extra negative-volume shell is a sealed void.
- tunnels open, cavities empty, parts apart (unintended fusions).

## Audit pass before fabrication

List every requirement and verify each with a number: walls and bends
(`check_channels`), capacity (place real items one by one: 156 × 66 × 5.6 mm
stacks, not volume ÷ volume), magnet pull vs spring force, connectivity of
every run end-to-end, every intended opening present, every part watertight.
The session's audit found 6 real problems, including an overstated capacity
and a check that gave false alarms.

## Performance reference

| step | 4.9M-triangle figure (session) | 461k-triangle test host |
|---|---|---|
| voxelize | 0.9 s at 5 mm | 0.04 s at 10 mm |
| clearance tree (Dijkstra) | 14 s | 0.2 s |
| full live regeneration | 18 s | – |
| MANIFOLD assembly | ~53 s, 82 cutters in one op | 1.5 s, 11 cutters |
| verify (60k skin samples) | ~1 min | 1–1.5 s |
