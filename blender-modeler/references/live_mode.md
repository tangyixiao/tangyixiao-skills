# Live mode: working in the user's open Blender

Live mode runs code inside the Blender window the user is looking at, through
the official Blender Lab MCP server. It is the right place for measuring,
quick regeneration loops and showing work. It is the wrong place for anything
heavy or anything that writes files.

| live (MCP) | headless (`bmod.py`, background) |
|---|---|
| measuring the host, routing loops, regenerating your collection | booleans on big meshes, voxel work over ~1M elements |
| viewport screenshots for the user | writing .blend files (port files, new masters) |
| scene/lighting tweaks on the user's file | rescaling a master, final assembly, verify_cuts |

## Connecting

1. Run `python <skill>/scripts/setup_blender_mcp.py --check`. It reports the
   add-on, Online Access, Auto Start, whether port 9876 listens, and **which
   process owns the port** (PID, command line, window title, so you can see
   which file that Blender has open). It reads the OS connection table and
   never connects to the port.
2. Not listening: Online Access is off. *Preferences → System → Allow Online
   Access*, then *Preferences → Add-ons → MCP → Start MCP Bridge Server* (no
   reinstall), or relaunch with `--online-mode`.
3. The port owner is a Blender with the default scene while the user's file is
   in another window: only one Blender can own 9876. Ask the user to close the
   other one, or open their file in the serving one.
4. The add-on is missing from the user's Preferences although you installed
   it: you are probably inside an app sandbox (see below).

### App sandbox on Windows (Claude desktop app)

Processes started by an MSIX-packaged app see a virtualised `%APPDATA%`:
their writes land in `%LOCALAPPDATA%\Packages\<app>\LocalCache\Roaming\...`.
An add-on installed (or preferences saved) from inside the sandbox is visible
only to Blenders launched from the sandbox, not to the Blender the user starts
from the Start menu. `--check` detects this by writing a marker file under
`%APPDATA%` and looking for it in the package folders (then deletes it), and
lists sandbox-only add-on copies.

Fix: `setup_blender_mcp.py --package-addon` zips the add-on into the user's
Downloads folder (`--to DIR` for elsewhere). The user installs it in their own
Blender: *Edit → Preferences → Get Extensions → ⌄ → Install from Disk*, then
turns on Online Access and saves preferences. `--install-addon` and
`--enable-online-access` print a warning when sandboxed.

## Tool behaviour (Blender Lab MCP 1.0.x)

| tool | behaviour |
|---|---|
| `execute_blender_code` | runs in Blender's UI thread and blocks the UI while it runs. Must set `result` to a **dict** ("The result variable must be a dict, not str"). Captures stdout. |
| `execute_blender_code_for_cli` | spawns a separate Blender with a 120 s cap. Timed out even listing objects of a 151 MB file. For big files use your own `bmod.py --script` instead. |
| `get_objects_summary` / blend-file info | cheap. Use it first to confirm the right file is open (an empty file path means the wrong window). |
| `get_screenshot_of_area_as_image` (`VIEW_3D`) | the viewport as the user sees it. Can come back **black** right after heavy work: check, force a redraw (`area.tag_redraw()`), retry once. |
| `render_viewport_to_path` | renders the **scene camera**, not the viewport. Don't use it to show the viewport. |

## Rules

- End every code call with `result = {...}`.
- Budget: keep each call under ~30–60 s. Anything that may run longer goes
  headless in the background (`bmod.py --script x.py --blend <file>` with
  `--timeout`), with progress prints. Tell the user before a heavy live call
  that Blender will freeze.
- Cache heavy structures between calls in `bpy.app.driver_namespace`
  (`hostkit` caches BVH trees and voxel grids there; `hostkit.clear_cache()`
  after editing the host).
- No `bpy.ops` in scripts that run live (a live `primitive_uv_sphere_add`
  showed up in a crash log); use the data API and bmesh (`modelkit` does).
- Never write .blend files from the live session (`bpy.data.libraries.write`
  after linking collections crashed the user's Blender). Dump to JSON with
  `portkit.dump()` and rebuild headless.
- Open files live with `bpy.ops.wm.open_mainfile(filepath=..., load_ui=False,
  use_scripts=False)`; launch with `--online-mode --disable-autoexec "<file>"`
  and wait until port 9876 listens (about 5 s).

## Hangs and recovery

1. The MCP call times out ("Blender connection timed out"): the UI thread is
   probably still working. Tell the user.
2. Poll whether the process responds (Windows: `(Get-Process -Id <pid>).Responding`)
   for up to 2–3 min.
3. Still hung: **ask** before force-killing it, even if you launched it. It
   may hold the user's unsaved work.
4. After a relaunch, re-run the generator: `model.py` rebuilds the features
   identically, which is why everything lives in scripts.

## Keep the user's file clean

- Generated objects go in their own collection, so re-running replaces only them.
- Reference objects you load (an older version's parts, measuring helpers) go in
  a collection named `REF … (do not port)`.
- Never save the user's master. Tell them to close without saving, or to save
  scratch work under a new name.

## Showing work

```python
import render_views
v = render_views.live_view(az=-35, el=20, focus="FEATURES", xray=0.2, color_by="role")
result = {"areas": v["areas"]}
```
Then take a `VIEW_3D` screenshot, copy it to `renders/<name>_vNN.png`, and send
it with a one-line caption saying what each colour means.
`render_views.restore_view()` (in a later call) puts the view back. `focus` can be a
collection, object names or a `(lo, hi)` box for a close-up. When the user asks
whether something is really hollow or connected, offer a cutaway
(`render_views.run(..., section=("y", 0.0))`, headless) as well as the numbers.
