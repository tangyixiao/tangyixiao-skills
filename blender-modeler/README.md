# blender-modeler

An agent skill that makes AI coding agents (Claude Code, OpenAI Codex, and
other tools that read `SKILL.md`) build noticeably better 3D models in Blender.

| Review sheet the agent critiques each round | Final render |
|---|---|
| ![8-view review sheet](docs/example_review_sheet.png) | ![final render](docs/example_final.png) |

Ask an agent to "model a chair in Blender" and it usually writes one script and
calls it done: wrong proportions, parts floating off the body, sharp CG edges,
flat colours. This skill gives the agent a process and tools instead:

1. **Spec first:** named parts, real-world dimensions, what attaches to what.
2. **One editable model script:** improved round by round, never regenerated.
3. **Measured checks:** a geometry checker finds floating parts, gaps, broken
   meshes and wrong sizes. Vision models are bad at spotting these, so the
   agent gets numbers instead of guessing from pictures.
4. **Fixed review views:** 8 views (4 orthographic, 4 perspective) tiled into
   one sheet, so the agent critiques the same angles every round.
5. **Stages:** blockout → detail → materials → final render, with a gate at
   each stage.
6. **Quality defaults:** builder helpers bevel edges, add subtle material
   variation and run wood grain along each part's length.
7. **Features inside existing models:** a second mode for adding channels,
   wiring, cavities and mounts to a big frozen mesh (a sculpt or print
   master): ray-parity measurement of the host, clearance-based channel
   routing, a channel check (wall to skin, bend radius, loose ends, keep-outs,
   fill), MANIFOLD booleans at scale, post-cut verification (sealed pockets,
   unexpected openings, blocked tunnels) and ghosted context / cutaway renders.

The approach follows published research on LLM-driven Blender modelling
(LL3M, VIGA, SEIG, BlenderAlchemy). The common finding is that write → render →
inspect → fix loops, done in stages, beat one-shot generation by a wide margin.

## Requirements

- **Blender 4.2 or newer** (developed and tested on 5.2). 5.1+ is needed for
  the optional live MCP mode.
- **Python 3.8+** on PATH (`python` or `python3`), used only by the launcher.
- An agent that can run commands on your computer: Claude Code, Codex
  CLI/app, or similar. A plain web chat can't run Blender.

## Install

Clone this repo into your agent's skills folder. The folder must be named
`blender-modeler`.

**Claude Code**
```bash
git clone https://github.com/calebrisc/blender-modeler.git ~/.claude/skills/blender-modeler
```

**OpenAI Codex**
```bash
git clone https://github.com/calebrisc/blender-modeler.git ~/.agents/skills/blender-modeler
```

On Windows, `~` is `C:\Users\<you>`. Git Bash and PowerShell both accept `~`
in these commands.

Then check that Blender is found:
```bash
python ~/.claude/skills/blender-modeler/scripts/bmod.py --where
```
If it isn't found, set the `BLENDER_EXE` environment variable to your Blender
executable.

**Update** to the latest version at any time:
```bash
git -C ~/.claude/skills/blender-modeler pull
```
(Use the `~/.agents/...` path for Codex.) Start a new agent session after
installing or updating.

## Use

Just ask, e.g.:

> Model a mid-century walnut side table in Blender, about 50 cm tall, and give me a final render.

The agent writes a spec, builds a blockout, then loops on the check report and
review sheets through each stage. It saves everything under
`~/Documents/BlenderAI/<model-name>/`, including a `model.blend` you can open.

It is strongest on hard-surface subjects: furniture, products, props,
architecture, mechanical parts and cables. It also handles "add internal
features to my existing model" jobs, e.g.:

> Route LED wire channels from the eye pockets to a battery bay inside this figure, 3 mm walls, and give me port files.

The agent measures the host without modifying it, builds the features in their
own collection, checks them, and only cuts them into a copy of the master when
you say so. Characters, faces, animals and
realistic plants don't come out well from code. For those, the skill tells
the agent to suggest an existing asset and handle the scene around it.

## Optional: live mode (watch it build in your open Blender)

Without this the agent runs Blender in the background, which is all the loop
needs. With it, the agent can also drive the Blender window you have open.
This uses Blender's official MCP server
([Blender Lab](https://www.blender.org/lab/mcp-server/)). You can ask your agent
to do these steps for you.

1. **Get the server** (needs git and Python 3.10+):
   ```bash
   git clone --depth 1 --branch v1.0.3 https://projects.blender.org/lab/blender_mcp.git ~/Tools/blender_mcp
   python -m venv ~/Tools/blender_mcp/venv
   ~/Tools/blender_mcp/venv/bin/pip install ~/Tools/blender_mcp/mcp        # Windows: venv\Scripts\pip
   ```
2. **Install the add-on and turn on Online Access.** Close Blender first, then
   run:
   ```bash
   python <skill>/scripts/setup_blender_mcp.py --install-addon ~/Tools/blender_mcp/addon/blender_mcp_addon --enable-online-access --check
   ```
   (`<skill>` is where you cloned this repo.) This builds and installs the
   add-on, saves *Allow Online Access* in your Blender preferences (backing them
   up first), and checks everything. To do it by hand instead: *Edit →
   Preferences → Get Extensions → ⌄ → Install from Disk* with the zip from the
   [Blender Lab page](https://www.blender.org/lab/mcp-server/), then *System →
   Allow Online Access*, then *☰ (bottom left) → Save Preferences*.

   > **Why Online Access matters:** the add-on starts its server **only once,
   > when Blender launches**, and only if Online Access is already on. Turning
   > it on later does nothing until you restart Blender or click *Start MCP
   > Bridge Server* in the add-on's preferences. If you don't save
   > preferences, it's off again next launch. Reinstalling the add-on is not
   > needed.
   >
   > Don't want to change the setting? Launch Blender with `--online-mode`
   > instead. That turns it on for that launch only.
3. Open Blender. The add-on auto-starts on `localhost:9876`. You can confirm it
   in *Preferences → Add-ons → MCP* ("Server is running").
4. **Register the server with your agent.** The server command is
   `~/Tools/blender_mcp/venv/bin/blender-mcp` (Windows:
   `venv\Scripts\blender-mcp.exe`). Use the full absolute path.
   - Claude Code:
     ```bash
     claude mcp add blender --scope user --env BLENDER_PATH=/path/to/blender -- /full/path/to/blender-mcp
     ```
   - Codex:
     ```bash
     codex mcp add blender --env BLENDER_PATH=/path/to/blender -- /full/path/to/blender-mcp
     ```
     or add this to `~/.codex/config.toml`:
     ```toml
     [mcp_servers.blender]
     command = "/full/path/to/blender-mcp"
     env = { BLENDER_PATH = "/path/to/blender" }
     ```
5. Open Blender first, then start a new agent session.

**Security note from Blender:** the MCP server runs AI-generated code inside
Blender with no sandbox. Save your work before handing over control, and don't
use it on machines with sensitive data.

## Troubleshooting

Start with `python <skill>/scripts/setup_blender_mcp.py --check`. It reports
what's wrong with the live-mode setup and how to fix each item.

| Problem | Fix |
|---|---|
| `Blender not found` | set `BLENDER_EXE` to the executable, or pass `--blender PATH` |
| MCP tools missing | start a new session after registering; check the server path is absolute |
| MCP tools time out / "Cannot connect to Blender" | the add-on server isn't running. Turn on Online Access, then *Preferences → Add-ons → MCP → Start MCP Bridge Server* (no reinstall needed), or restart Blender |
| Works once, broken after restarting Blender | Online Access was turned on but preferences weren't saved: *☰ → Save Preferences*, or `setup_blender_mcp.py --enable-online-access` with Blender closed |
| Port 9876 in use | another Blender MCP add-on (e.g. the community `blender-mcp`) is running; disable one. `--check` shows the PID, command line and window title of the owner |
| MCP talks to the wrong Blender (default cube scene) | only one Blender can own port 9876; `--check` shows which window owns it. Close the other one or open your file in that one |
| MCP missing from Preferences after the agent installed it (Windows, Claude desktop app) | the agent ran inside the app's sandbox, so the install went to a virtualised AppData that your Blender can't see. `--check` says so. Run `setup_blender_mcp.py --package-addon` and use *Get Extensions → ⌄ → Install from Disk* with the zip it puts in Downloads |
| MCP calls time out on a big file | the call is still running in Blender's UI thread. Heavy work belongs in the background (`bmod.py --script`); the skill tells the agent to ask before killing a hung Blender |
| Viewport screenshot is black | taken right after heavy work; force a redraw and retry once |
| Strange script errors on old Blender | upgrade to 4.2+; the helpers target the 4.2+/5.x API |

## What's in here

```
SKILL.md                        instructions the agent follows
references/techniques.md        modelling craft rules and Blender API gotchas
references/existing_models.md   adding features inside/on an existing (frozen) model
references/live_mode.md         live MCP rules, tool quirks, sandbox, recovery
scripts/bmod.py                 launcher: finds Blender, runs one iteration or any script, summarises
scripts/setup_blender_mcp.py    live-mode setup and diagnostics (add-on, Online Access, server, sandbox)
scripts/run_pipeline.py         runs inside Blender: build → check → render → save
scripts/check_geometry.py       floating parts, gaps, contacts, mesh health, spec checks
scripts/render_views.py         8-view clay/shaded sheet, context/ghost, cutaway, live viewport
scripts/modelkit.py             builders, finishing, booleans at scale, materials, studio lighting
scripts/hostkit.py              measure an existing mesh (ray parity, wall, voxels, pockets)
scripts/routekit.py             route channels through a host
scripts/check_channels.py       wall, bend, keep-out, loose-end, connectivity and fill checks
scripts/verify_cuts.py          post-boolean verification
scripts/portkit.py              port files: dump a collection live, rebuild headless
tests/run_tests.py              regression tests (drives Blender headless)
```

The scripts also work without an agent:
`python scripts/bmod.py --model your_model.py --out out --mode both`.

## Contributing

Improvements are expected. If you or your agent finds a bug or a missing
helper, open an issue or a pull request. Please:
- run `python tests/run_tests.py` (about 30 s; it drives Blender headless and
  prints the review images to look at), and include the review sheet if the
  change affects visuals,
- add a line to `CHANGELOG.md`,
- keep `SKILL.md` tool-neutral (no app-specific tool names or personal paths).

## License

MIT. See [LICENSE](LICENSE). The optional Blender MCP server is a separate
project by the Blender Foundation (GPL-3.0) and isn't included here.
