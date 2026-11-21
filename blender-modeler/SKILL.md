---
name: blender-modeler
description: Build higher-quality 3D models in Blender with a spec → blockout → measured-check → multi-view-critique loop, and add measured features (channels, wiring, cavities, pockets, mounts) inside or on existing meshes. Use whenever the user asks to model, build, make or improve a 3D object, prop, piece of furniture, product, building or scene in Blender (via a Blender MCP connection or headless Blender), to add internal features to an existing model, or asks for a Blender render of something that has to be modelled first.
---

# Blender modeler

One-shot generated Blender scripts look like cheap CG: wrong proportions, parts
floating a centimetre off the body, razor-sharp edges, flat colours. This skill
replaces that with a loop that research (LL3M, VIGA, SEIG, BlenderAlchemy)
showed works: plan the parts, build from one editable script, **measure** the
result, look at it from fixed views, fix specific things, verify the fixes, and
work in stages.

Two rules matter most:
1. **The numbers beat your eyes.** Vision models miss floating parts and
   gaps. `check_geometry` measures them. Never call a stage done while it
   reports errors, however good the render looks.
2. **Edit the script; never regenerate it.** Rewriting from scratch makes the
   model drift. Each iteration makes targeted edits to `model.py`.

There are two modes. **New object** (below) builds something from primitives
on an empty scene. **Features inside or on an existing model** (channels,
wiring, cavities, vaults, pockets, mounts added to a frozen, often huge mesh)
uses the same rules with different tools; see § Existing models.

Below, `<skill>` means the folder that contains this SKILL.md. Use its real
absolute path in every command.

## Tools

| file in `<skill>/scripts/` | what it does |
|---|---|
| `bmod.py` | **entry point.** Finds Blender, runs one iteration headless, prints a short summary. `--script` runs any script on a .blend in the background |
| `modelkit.py` | build helpers with good defaults: `box`, `cylinder`, `sphere`, `lathe`, `extrude_profile`, `tube`, `tube_mesh` (watertight, for cutters), `finish` (bevel + weighted normals + smooth), `subsurf`, `solidify`, `array`, `mirror`, `boolean`/`apply_cuts` (MANIFOLD when possible), `offset_copy`, `scale_scene`, `material`, `wood`/`assign_wood`, `studio`, `render_final` |
| `check_geometry.py` | floating parts, gaps, contacts (flush vs embedded depth), mesh health, spec dimensions and required attachments |
| `render_views.py` | 8 fixed views tiled into one sheet; `clay` (Workbench, random colour per part) or `shaded` (EEVEE); context/ghost, cutaway and close-up options; `live_view()` for the user's viewport |
| `run_pipeline.py` | runs inside Blender: reset scene → run model.py → check → render → save model.blend |
| `hostkit.py` | measure an existing mesh: world vertices, ray-parity inside/outside, wall thickness, voxel clearance field, pocket finder, ray scans |
| `routekit.py` | route channels through a host: clearance-weighted shortest paths, smoothing, bend radii, junction snapping |
| `check_channels.py` | channels vs host: wall to skin, bend radius, keep-out clearance, loose ends, hub connectivity, fill % |
| `verify_cuts.py` | after booleans: watertight shells, skin openings (intended vs not), tunnels open, cavities empty, fused parts |
| `portkit.py` | dump a collection to JSON live, rebuild it as a port .blend headless |

Read `<skill>/references/techniques.md` before writing a model script. It has
the craft rules and Blender API gotchas.

### Running an iteration (headless, always available)

```
python <skill>/scripts/bmod.py --model model.py --spec spec.json --out renders/iter_01 --mode clay
```
Use `python3` where `python` isn't available. Run `bmod.py --where` once to
confirm which Blender it found. If none is found, ask the user for the path and
pass `--blender PATH` (or set `BLENDER_EXE`).

Options: `--mode clay|shaded|both|none`, `--res 512`, `--final path.png` (Cycles
presentation render, using `modelkit.studio()` if the scene has no camera),
`--no-render`, `--no-check`, `--verbose` (full Blender log, also saved as
`<out>/blender.log`), `--timeout SECONDS`. It takes about 5–15 s for clay and a
minute or more for a final render.

Background jobs on a file (heavy booleans, port files, rescaling a master):
```
python <skill>/scripts/bmod.py --script assemble.py --blend master.blend --save-as final_v01.blend [-- script args]
```
Script mode does no check, render or save unless you add `--check`, `--mode` or
`--save-as`; `--save-as` refuses to overwrite the opened file; `--addons` loads
the user's add-ons. Auto-run scripts inside .blend files are always disabled.

Exit codes: 0 ok, 1 the model script raised (traceback printed), 2 a check
found errors, 3 Blender not found. The summary prints the check reports and
the paths of the sheets. **Look at every sheet image** before critiquing.

On Windows, write files with your file-writing tool rather than PowerShell
`Set-Content`/`Out-File`, which add a byte-order mark (the scripts tolerate it,
but other tools may not). Don't mix your edit tool with `sed -i` or patch
scripts on the same file in one turn; re-read before editing.

### Live mode (Blender MCP connected)

If the official Blender Lab MCP is connected (its tools include
`execute_blender_code`, `get_objects_summary` and `get_screenshot_of_window_as_image`),
you can run the same code inside the user's open Blender so they can watch:

```python
import sys, importlib
S = r"<skill>/scripts"
sys.path.insert(0, S)
import modelkit, check_geometry, render_views
for m in (modelkit, check_geometry, render_views): importlib.reload(m)
modelkit.reset_scene()   # only when the user agreed to replace the scene
exec(compile(open(r"<project>/model.py", encoding="utf-8-sig").read(), "model.py", "exec"), {"__name__": "__main__"})
r = check_geometry.run(spec_path=r"<project>/spec.json")
render_views.run(r"<project>/renders/iter_03", mode="clay")
result = {"errors": r["summary"]["errors"]}
```

Live rules (details, tool quirks and recovery: `references/live_mode.md`):
- Every code call ends with `result = {...}` (a dict, never a string).
- Keep each live call under ~30–60 s; the UI freezes while it runs. Voxelising,
  booleans on big meshes and pure-Python loops over >1M elements go headless in
  the background (`bmod.py --script`). Tell the user before a heavy live call.
- Never write .blend files (`save_as_mainfile`, `libraries.write`) from the live
  session, and don't use `bpy.ops` in scripts that run live. Dump to JSON
  (`portkit.dump`) and rebuild headless.
- First call: confirm the right file is open (`get_objects_summary`; an empty
  file path means the wrong window).
- If Blender stops responding, tell the user and **ask** before killing it, even
  if you launched it. After a relaunch, re-run the generator.
- Keep the user's file clean: generated objects in their own collection,
  reference imports in a `REF … (do not port)` collection, never save their
  master.

Never call `reset_scene()` on a user's existing scene without asking. For
editing their scene, inspect it first and work on named objects. Headless runs
stay the default for the critique loop because they are reproducible. Use live
mode to show progress and for scene/lighting work on the user's own files.

If the MCP tools fail ("Cannot connect to Blender"), run
`python <skill>/scripts/setup_blender_mcp.py --check` and follow what it
says. The usual cause is that the add-on only starts its server at Blender
launch, and only when Online Access is on. The fix is *Preferences → Add-ons →
MCP → Start MCP Bridge Server* after enabling Online Access, not a reinstall.
`--check` also says which process owns port 9876 (and which file it has open)
and whether you run inside an app sandbox that hides installs from the user's
Blender (then use `--package-addon`). `--install-addon`/`--enable-online-access`
change the user's Blender preferences: ask first, and Blender must be closed.
Never close the user's Blender yourself without asking; they may have unsaved work.

## Project layout

Put each model in its own folder: the user's named location, else
`~/Documents/BlenderAI/<model-name>/`. Never use the current directory when it
is a system folder.

```
spec.json        parts, real dimensions, attachments (the contract)
notes.md         brief, reference notes, critique log per iteration
model.py         the single source of truth; parameters at the top
renders/iter_NN/ report.txt, clay_sheet.png, shaded_sheet.png, model.blend
```

`model.py` starts with `import modelkit as mk`. bmod.py puts the scripts
folder on the import path and starts from an empty scene.

## Workflow

### 0. Intake
- Pin down the object, style, and purpose (still render, game asset, 3D print,
  or a part that must fit an existing model). Ask for reference images. If the
  user supplies them, look at them and note proportions in `notes.md`.
- For fabrication (3D print, CNC), ask about the output: print size and split
  lines, wall thickness, and the hardware to buy. Use real purchased-part sizes
  (magnets, LEDs, cable OD, boards) and keep them at real size if the model is
  rescaled.
- Mechanisms (doors, locks, lids, hinges): design them with the user first
  (a short plan with sizes and the alternatives), then build.
- Be honest about fit. This works well for hard-surface objects (furniture,
  products, props, architecture, mechanical parts, cables/wiring, vehicles at
  low detail). Characters, faces, animals and realistic plants come out poorly
  from code. For those, suggest an asset (Poly Haven, BlenderKit, Sketchfab) or
  image-to-3D, and offer to handle placement, materials, lighting and
  rendering.
- **Working on an existing model?** Ask which file is the master; don't search
  the disk for it (opening an autosave needs an explicit OK). Then follow
  § Existing models.

### 1. Spec (`spec.json` + `notes.md`)
- Use real-world dimensions in metres (or set `"units": "mm"` and give every
  spec number in mm; the report then uses mm). Use known standards when the
  user gives none (seat height 0.45, desk 0.75, door 2.0 × 0.9, mug Ø0.08 ×
  0.095). State the assumptions you used.
- Break the object into named parts. For each, list its size, what it attaches
  to, its build method (box + bevel, lathe profile, extruded outline, tube
  sweep, subsurf cage) and its material.
- Coordinates: Z up, front faces -Y, object resting on z = 0, centred on X/Y.

```json
{
  "name": "side table",
  "overall": {"dims": [0.5, 0.5, 0.55], "tol": 0.02},
  "parts": {
    "Top":   {"dims": [0.5, 0.5, 0.03], "attached_to": ["Leg_FL", "Leg_FR", "Leg_BL", "Leg_BR"]},
    "Shelf": {"attached_to": ["Leg_FL", "Leg_BR"]}
  }
}
```
`dims` are the object's own (unrotated) X/Y/Z size; use `null` to skip an
axis. `tol` defaults to 5% (min 2 mm). Optional: `"ground": false` for things
that hang or fly, `"contact_tolerance"`, `"collection"` to check only one
collection, `"expect_embedded": [["Leg_*", "Top"]]` for intended overlaps.

### 2. Blockout (clay)
Write `model.py` with primitives at the spec's sizes and positions, with
named parameters at the top. No bevels or materials yet. Run with
`--mode clay`.
**Gate:** 0 errors, and the overall silhouette and proportions match the
reference in the orthographic views.

### 3. Form and detail (clay)
Add the shapes that make it read as a real object: lathe profiles instead of
plain cylinders, tapered legs, chamfers and bevels (`mk.finish`), aprons and
rails, panel gaps, handles, screws and feet. Secondary detail is where quality
comes from. Look at `techniques.md` § Detail.
**Gate:** 0 errors, and the critique checklist passes.

### 4. Materials (shaded)
Assign materials with `mk.material(...)` / `mk.assign_wood(...)`, with
variation and bump > 0. Never leave flat colours. Run `--mode shaded`.

### 5. Presentation
Run `mk.studio()` (or a custom camera and lights), then `--final final.png`.
Show the user the final image and `model.blend`. In live mode, build it in
their Blender.

### The critique loop (every iteration)
1. Run bmod.py. Read the report, then look at the sheet image.
2. Write up to 5 numbered critiques in `notes.md` under `## iter_NN`. Each
   names the part, the view, the problem and the concrete fix in numbers
   (e.g. "Backrest, RIGHT view: tilt reads too upright; rotate X -8° → -14°").
   Report errors always come first.
3. Make targeted edits to `model.py` (small edits, not a rewrite).
4. Re-run into `iter_NN+1`. Mark each previous critique ✅ fixed or ❌ not fixed
   from the new report or sheet. Carry ❌ items forward.
5. Move to the next stage when the gate passes. Stop a stage after about 6
   iterations without progress and tell the user what is stuck.

For design-iteration work (features on an existing model), `notes.md` can be a
per-version change log instead: what changed, the check deltas, open questions.

Sheet layout: row 1 is orthographic FRONT | RIGHT | BACK | TOP; row 2 is
perspective 3/4 LEFT | 3/4 RIGHT | 3/4 BACK | LOW HERO. In clay mode each
object gets its own random colour, so one colour means one object.

### Critique checklist
- **Proportions:** compare ortho views against the reference or spec ratios,
  not your memory. Is anything too thick or thin? (A common failure is
  everything too chunky.)
- **Connections:** does every joint look plausible (legs meet the top,
  handles meet bodies)? The report proves contact. You judge whether the
  contact makes physical sense.
- **Silhouette:** is it recognisable from the 3/4 views alone? Is anything
  missing that a real one has?
- **Edges:** no perfectly sharp box edges. Bevels are visible but small.
- **Detail density:** big flat areas need a reason (a panel line, inset, trim
  or texture).
- **Symmetry and alignment:** mirrored parts match, and things line up in TOP.
- **Materials:** do they have variation? Does wood grain follow each part's
  long axis? Are metals metallic = 1 with roughness 0.2–0.5?

## Existing models: features inside or on a frozen host

Use this mode when the user wants channels, wiring, cavities, vaults, pockets
or mounts added to a model that already exists (a sculpt, scan or finished
print master, often millions of triangles, with unapplied transforms). Full
recipe, spec keys and code: `<skill>/references/existing_models.md`.

1. **Master file:** ask for it, open it with auto-run off, never save over it.
2. **Transforms and units:** record the host's location/rotation/scale and the
   unit you'll work in (mm for print work); measure in world space
   (`hostkit` goes through `matrix_world`). Say which unit every report uses.
3. **Measure:** write `measured.json` (pocket floors, normals, depths) with
   `hostkit`. List **every** detected feature to the user and ask which count.
4. **Keep-outs first:** agree the large cavities and keep-out volumes before
   routing anything through the body.
5. **Generator:** one `model.py` builds only the new features, in their own
   collection, re-runnable; hardware at real size; a `role` prop per object.
6. **Check:** `check_channels` (wall to skin, bends, keep-outs, loose ends, hub
   connectivity, fill). Never run `check_geometry`/`render_views` on the host
   itself; scope them with `collection=`/`names=` (huge objects are skipped).
7. **Review:** context renders (`--context <host>`: host ghosted, features
   coloured by role), a close-up per changed area, a cutaway (`--section`)
   when the user asks whether it is really hollow or connected.
8. **Port files:** versioned .blend files at the host's world coordinates
   (`portkit`), with a README text that gives the boolean order.
9. **Final assembly** only when the user says so: headless
   (`bmod.py --script`), `apply_cuts` in order (union → splits → body cuts →
   part cuts), every cutter ≥ 1 mm through the skin, then `verify_cuts`.

Before anything goes to fabrication, do an **audit pass**: list every
requirement (fits, walls, capacities, magnets vs springs, connectivity) and
verify each with a measurement. Verify connectivity end-to-end, not by
sampled joints. Place real items (stacks, boards) one by one rather than
dividing volumes.

## Reporting to the user
After each stage, show the user the latest sheet (or the final render). Attach
the image if your app can, otherwise give its path. Add one or two lines on what
changed and what's next, and mention `model.blend` so they can open it. For
context renders, say what each colour means. Exploded or preview transforms
must not intersect other parts, or must be labelled as previews.

## Improving this skill
If you hit a bug or a missing helper while using this skill, tell the user
what you found and propose the fix. Don't silently patch the installed copy:
it is a git checkout and changes should go upstream (see `README.md` §
Contributing). At the end of a long session, list the helpers you had to write
that the skill lacked (name and file) and offer to upstream them.
