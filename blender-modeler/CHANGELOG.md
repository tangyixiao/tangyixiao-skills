# Changelog

## 0.3.0 (2026-10-22)
From a review of a 7-hour session that added LED wiring, vaults and ballast to
a 4.9M-triangle figure. Most of the helpers that session had to write are now
part of the skill.
- **Fix:** review sheets and `studio()` framed scenes with curves 2–3x too
  wide. Blender 5.2 pads an evaluated curve's `bound_box` by ~1 m; bounds now
  come from evaluated vertices (`modelkit.object_corners`/`bounds`).
- New mode in SKILL.md, "features inside or on an existing model" (frozen
  host, measured.json, keep-outs before routing, context renders, port files,
  final assembly on the user's go, verification), with
  `references/existing_models.md`. Intake asks about output intent, every
  detected feature, mechanisms and real hardware sizes; audit pass before
  fabrication; end-of-session "helpers I had to write" nudge.
- Live-mode rules and `references/live_mode.md`: `result` dict, a 30–60 s
  budget with heavy work headless, no file writes or `bpy.ops` live, ask before
  killing Blender, MCP tool quirks (CLI tool timeout, scene-camera render,
  black screenshots), keeping the user's file clean.
- New `scripts/hostkit.py`: numpy world vertices/normals, cached BVH,
  ray-parity inside test (3-ray majority), clearance/signed distance, voxel
  clearance field, sharp-edge pocket finder, PCA axes, ray floor, height-map
  scans, voxel diff. Units "m" or "mm".
- New `scripts/routekit.py`: clearance-weighted Dijkstra tree, route/trace,
  keep-out masks, merge_tree (shared junctions), smooth, Chaikin, resample,
  bend radii, junction snapping.
- New `scripts/check_channels.py`: wall to skin, bend radius, keep-out
  clearance, loose ends, hub connectivity, fill %, length; runs from
  `run_pipeline`/`bmod` when the spec has a `"channels"` key (exit 2 on errors).
- New `scripts/verify_cuts.py`: shells, skin openings vs declared openings
  (sealed pockets are errors), tunnels open, cavities empty, touching parts.
- New `scripts/portkit.py`: dump a collection to JSON (safe live), rebuild a
  versioned port .blend headless with a README.
- `modelkit`: `tube(kind="poly"|"bezier", units=)`, watertight `tube_mesh`,
  `mesh_from_data`, `offset_copy` (even offset), `boolean(solver="AUTO")`
  (MANIFOLD when inputs are closed), `apply_cuts` (one MANIFOLD op for many
  cutters, fixes flipped targets, overshoot and no-op warnings),
  `scale_scene(roots_only=True)`; `lathe` builds rings directly (28 s → 1 s
  on a 250k-face profile).
- `render_views`: `context=` + `ghost=` (host ghosted under the features),
  `focus=`, `section=` cutaways, `min_line_px`, `color_by="material"|"role"`,
  custom close-up views, `live_view()`/`restore_view()` for the user's viewport.
- `check_geometry`: ray-parity penetration depth (flipped faces no longer fake
  it), numpy mesh health and islands, huge objects skipped (`max_verts`),
  `expect_embedded`, `"units": "mm"`, ground check off when a host is named.
- `bmod.py --script x.py --blend f.blend [--save-as out.blend] [-- args]`
  runs any script in the background (refuses to save over the opened file;
  `--addons`, `--timeout`); auto-run in .blend files is always disabled.
- `setup_blender_mcp.py`: detects the Claude desktop app's MSIX sandbox
  (virtualised AppData hides installs from the user's Blender), new
  `--package-addon` (zip to Downloads, or `--to DIR`, for Install from Disk),
  reports which process owns port 9876 (PID, command line, window title) from
  the OS connection table without connecting to it.
- New `tests/run_tests.py`: unit checks, a synthetic 461k-triangle host
  pipeline (route, check, MANIFOLD cuts, verify, renders), the chair regression
  through bmod, script mode and the setup diagnostics.

## 0.2.0 (2026-10-21)
- New `scripts/setup_blender_mcp.py`: installs the official MCP add-on (from
  zip or source folder), saves *Allow Online Access* (with a prefs backup), and
  `--check` diagnoses live-mode problems with a fix for each.
- Documented the real cause of "MCP installed but not connecting": the add-on
  starts its server only at Blender launch and only if Online Access is
  already on, so turning it on later (or not saving preferences) leaves the
  server stopped. Use *Start MCP Bridge Server* or restart; no reinstall needed.
  `--online-mode` is the no-settings-change alternative.

## 0.1.0 (2026-10-21)
- First public version.
- Spec → blockout → detail → materials → presentation workflow with a
  measured-check + 8-view critique loop.
- `check_geometry`: floating parts (island-level), gaps, flush/embedded
  contacts, mesh health, spec dimensions and required attachments.
- `render_views`: clay (Workbench, random colour per part) and shaded (EEVEE)
  contact sheets.
- `modelkit`: true-size builders (box, cylinder, sphere, lathe, extrude_profile,
  tube), bevel/weighted-normal finishing, procedural materials and wood with
  automatic grain direction, studio lighting, Cycles final render.
- `bmod.py`: cross-platform launcher that finds Blender and summarises results.
- Tested on Blender 5.2.1 (Windows).
