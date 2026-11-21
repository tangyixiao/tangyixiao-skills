"""One review iteration, headless: build the model, check it, render it, save it.

    blender -b --factory-startup --python-exit-code 1 --python run_pipeline.py -- \
        --model model.py --out renders/iter_03 [--spec spec.json] [--mode clay|shaded|both] \
        [--res 512] [--final final.png] [--no-render] [--no-check] [--no-save]

Features on an existing model (open a COPY or the master read-only, build only
the new parts, check and render them against the host):

    ... -- --blend host.blend --model features.py --collection WIRING --spec spec.json \
        --context Body --color-by role --min-line-px 3 --no-save --out renders/v03

  A spec with a "channels" key also runs check_channels (or pass --channels spec.json);
  --verify spec.json runs verify_cuts on the result. --section y,0 renders a cutaway.

Run any script on a .blend (bmod.py --script wraps this):

    ... -- --blend in.blend --script assemble.py [--save-as out.blend] [--check] [--mode clay]
        [--script-args a b c]

  Script mode does no check, render or save unless asked. --save-as never
  overwrites the opened --blend.

Writes into --out:
    report.txt / report.json   check results (geometry, channels, cuts)
    clay_sheet.png             8-view contact sheet (and/or shaded_sheet.png)
    model.blend                the built scene, for opening in Blender
Exit code is 1 if the model script raised, 2 if a check found errors.
"""

import argparse
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy  # noqa: E402

import check_geometry  # noqa: E402
import modelkit  # noqa: E402
import render_views  # noqa: E402


def _write(out, name, text):
    if out:
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="model script (the source of truth)")
    ap.add_argument("--script", help="run this script on the scene (no reset, no check/render/save unless asked)")
    ap.add_argument("--script-args", nargs=argparse.REMAINDER, default=[])
    ap.add_argument("--blend", help="open this .blend first (never saved over)")
    ap.add_argument("--out")
    ap.add_argument("--spec")
    ap.add_argument("--mode", default=None, choices=["clay", "shaded", "both", "none"])
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--collection")
    ap.add_argument("--context", help="comma-separated objects/collections drawn as context (e.g. the host)")
    ap.add_argument("--no-ghost", action="store_true", help="draw context objects solid instead of ghosted")
    ap.add_argument("--focus", default="target", help="target | all | comma-separated names")
    ap.add_argument("--section", help="cutaway, e.g. y,0.0 (removes y < 0) or -x,0.1")
    ap.add_argument("--color-by", default="object", choices=["object", "material", "role"])
    ap.add_argument("--min-line-px", type=float, default=0)
    ap.add_argument("--final", help="also render a presentation image (Cycles) to this path")
    ap.add_argument("--channels", help="spec with a 'channels' key (default: --spec if it has one)")
    ap.add_argument("--verify", help="spec with a 'verify' key: run verify_cuts")
    ap.add_argument("--check", action="store_true", help="script mode: also run the checks")
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--save-as", help="save the resulting scene here (not over --blend)")
    a = ap.parse_args(argv)
    script_mode = bool(a.script)
    if not script_mode and not a.out:
        ap.error("--out is required (except with --script)")

    out = os.path.abspath(a.out) if a.out else None
    if out:
        os.makedirs(out, exist_ok=True)

    blend = os.path.abspath(a.blend) if a.blend else None
    if blend:
        bpy.ops.wm.open_mainfile(filepath=blend, load_ui=False, use_scripts=False)
    elif not script_mode:
        modelkit.reset_scene()
    src = a.script or a.model
    if src:
        path = os.path.abspath(src)
        sys.path.insert(0, os.path.dirname(path))
        ns = {"__name__": "__main__", "__file__": path}
        old_argv = sys.argv
        sys.argv = [path] + list(a.script_args or [])
        try:
            with open(path, "r", encoding="utf-8-sig") as f:  # tolerate BOMs from PowerShell
                exec(compile(f.read(), path, "exec"), ns)
        except SystemExit as ex:
            if ex.code not in (None, 0):
                msg = f"{'SCRIPT' if script_mode else 'MODEL SCRIPT'} FAILED\nsys.exit({ex.code})\n"
                _write(out, "report.txt", msg)
                print(msg)
                sys.exit(1)
        except Exception:
            tb = traceback.format_exc()
            msg = f"{'SCRIPT' if script_mode else 'MODEL SCRIPT'} FAILED\n" + tb
            _write(out, "report.txt", msg)
            print(msg)
            sys.exit(1)
        finally:
            sys.argv = old_argv

    spec_path = os.path.abspath(a.spec) if a.spec else None
    spec = {}
    if spec_path:
        with open(spec_path, encoding="utf-8-sig") as f:
            spec = json.load(f)
    texts, errors = [], 0
    do_check = (a.check or not script_mode) and not a.no_check
    if do_check:
        coll = a.collection or (None if spec.get("collection") else (spec.get("channels") or {}).get("collection"))
        report = check_geometry.run(spec=spec, collection=coll,
                                    out_path=os.path.join(out, "report.json") if out else None)
        texts.append(report["text"])
        errors += report["summary"]["errors"]
        ch_path = os.path.abspath(a.channels) if a.channels else (spec_path if "channels" in spec else None)
        if ch_path:
            import check_channels
            rep = check_channels.run(spec_path=ch_path,
                                     out_path=os.path.join(out, "channels_report.json") if out else None)
            texts.append(rep["text"])
            errors += rep["summary"]["errors"]
    if a.verify:
        import verify_cuts
        rep = verify_cuts.run(spec_path=os.path.abspath(a.verify),
                              out_path=os.path.join(out, "verify_report.json") if out else None)
        texts.append(rep["text"])
        errors += rep["summary"]["errors"]
    if script_mode:
        texts.insert(0, "SCRIPT OK")
    _write(out, "report.txt", "\n".join(texts) + "\n")

    mode = a.mode or ("none" if script_mode else "clay")
    if out and not a.no_render and mode != "none":
        ctx = a.context.split(",") if a.context else None
        focus = a.focus if a.focus in ("target", "all") else a.focus.split(",")
        section = None
        if a.section:
            ax, off = a.section.split(",")
            section = (ax.strip(), float(off))
        for m in (["clay", "shaded"] if mode == "both" else [mode]):
            render_views.run(out, mode=m, res=a.res, collection=a.collection, context=ctx,
                             ghost=not a.no_ghost, focus=focus, section=section,
                             color_by=a.color_by, min_line_px=a.min_line_px)

    if a.final:
        if bpy.context.scene.camera is None:
            modelkit.studio()
        modelkit.render_final(os.path.abspath(a.final))
        print(f"FINAL: {a.final}")

    if a.save_as:
        dst = os.path.abspath(a.save_as)
        if blend and os.path.normcase(dst) == os.path.normcase(blend):
            print("REFUSED: --save-as is the opened file; save under a new (versioned) name.")
            sys.exit(1)
        bpy.ops.wm.save_as_mainfile(filepath=dst, copy=True)
        print(f"SAVED: {dst}")
    elif out and not script_mode and not a.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "model.blend"), copy=True)

    if errors:
        sys.exit(2)


main()
