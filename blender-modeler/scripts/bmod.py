"""Launcher: find Blender, run one review iteration headless, print a short summary.

Runs with any Python 3.8+ (stdlib only); Blender itself does the work.

    python bmod.py --model model.py --spec spec.json --out renders/iter_01 --mode clay
    python bmod.py --where          # show which Blender will be used

Run any script on a .blend in the background (heavy or risky work: booleans on
millions of triangles, writing port files, rescaling a master):

    python bmod.py --script assemble.py --blend master.blend --save-as final_v01.blend
    python bmod.py --script verify_cuts.py --blend final_v01.blend -- --spec spec.json

  Everything after a bare `--` goes to the script's sys.argv. Script mode skips the
  check, render and save unless you pass --check, --mode or --save-as. --save-as
  refuses to overwrite the opened --blend. Add --addons to load the user's add-ons
  (no --factory-startup). Auto-run scripts in .blend files are always disabled.

All other arguments are passed to run_pipeline.py (--model, --blend, --out,
--spec, --mode, --res, --collection, --context, --focus, --section, --color-by,
--min-line-px, --channels, --verify, --final, --no-render, --no-check, --no-save).

Blender is found from, in order: --blender PATH, $BLENDER_EXE, $BLENDER_PATH,
`blender` on PATH, then the standard install locations (newest version wins).

Options for this launcher: --blender PATH, --verbose (full log), --where,
--addons, --timeout SECONDS.

Exit codes: 0 ok, 1 model/script failed or Blender error (or timeout), 2 a check
found errors, 3 Blender not found.
"""

import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "run_pipeline.py")
KEEP = re.compile(r"Traceback|Error|FAILED|GEOMETRY|CHANNEL|CUT VERIFY|RENDER:|FINAL:|SAVED:|REFUSED|^\s+File |^\s+\[")
CHECKS = re.compile(r"(?:GEOMETRY CHECK|CHANNEL CHECK|CUT VERIFY): (\d+) errors")


def _version_key(path):
    m = re.search(r"(\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def candidates():
    for env in ("BLENDER_EXE", "BLENDER_PATH"):
        if os.environ.get(env):
            yield os.environ[env]
    on_path = shutil.which("blender")
    if on_path:
        yield on_path
    system = platform.system()
    found = []
    if system == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.expandvars(r"%LOCALAPPDATA%\Programs")):
            found += glob.glob(os.path.join(root, "Blender Foundation", "Blender*", "blender.exe"))
        found += glob.glob(os.path.expandvars(
            r"%ProgramFiles(x86)%\Steam\steamapps\common\Blender\blender.exe"))
    elif system == "Darwin":
        found += glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
        found += glob.glob(os.path.expanduser("~/Applications/Blender*.app/Contents/MacOS/Blender"))
    else:
        found += ["/snap/bin/blender", "/usr/bin/blender", "/usr/local/bin/blender"]
        found += glob.glob(os.path.expanduser("~/blender*/blender"))
        found += glob.glob("/opt/blender*/blender")
    yield from sorted(found, key=_version_key, reverse=True)


def find_blender(explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for c in candidates():
        if c and os.path.isfile(c):
            return c
    return None


def blender_version(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"Blender (\d+\.\d+(\.\d+)?)", out)
        return m.group(1) if m else "unknown"
    except Exception as ex:  # noqa: BLE001
        return f"unknown ({ex})"


def _pop(args, flag, has_value=False):
    if flag not in args:
        return None
    i = args.index(flag)
    if has_value:
        v = args[i + 1]
        del args[i:i + 2]
        return v
    del args[i]
    return True


def main():
    args = sys.argv[1:]
    script_args = []
    if "--" in args:
        i = args.index("--")
        args, script_args = args[:i], args[i + 1:]
    verbose = bool(_pop(args, "--verbose"))
    where = bool(_pop(args, "--where"))
    addons = bool(_pop(args, "--addons"))
    explicit = _pop(args, "--blender", True)
    timeout = _pop(args, "--timeout", True)

    exe = find_blender(explicit)
    if not exe:
        print("Blender not found. Install Blender 4.2+ (5.1+ recommended) or set BLENDER_EXE "
              "to the blender executable.")
        return 3
    if where:
        print(f"{exe}\nBlender {blender_version(exe)}")
        return 0

    script_mode = "--script" in args
    out_dir = None
    if "--out" in args:
        out_dir = os.path.abspath(args[args.index("--out") + 1])
    elif script_mode:
        out_dir = tempfile.mkdtemp(prefix="bmod_")
        args += ["--out", out_dir]
    if script_args:
        args += ["--script-args"] + script_args
    cmd = [exe, "-b"] + ([] if addons else ["--factory-startup"]) + [
        "--disable-autoexec", "--python-exit-code", "1", "--python", PIPELINE, "--"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=float(timeout) if timeout else None)
        log, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as ex:
        log = (ex.stdout or b"").decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else (ex.stdout or "")
        log += f"\nTIMEOUT after {timeout} s: the Blender process was stopped."
        code = None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "blender.log"), "w", encoding="utf-8") as f:
            f.write(log)
    if code is None:
        print("\n".join(log.splitlines()[-30:]))
        return 1

    report = os.path.join(out_dir, "report.txt") if out_dir else None
    if verbose or not report or not os.path.isfile(report):
        print(log if verbose else "\n".join(l for l in log.splitlines() if KEEP.search(l)))
    elif script_mode:
        tail = [l for l in log.splitlines() if l.strip() and not l.startswith(("Blender ", "Read blend", "Blender quit"))]
        print("\n".join(tail[-25:]))
    if report and os.path.isfile(report):
        with open(report, encoding="utf-8") as f:
            text = f.read()
        print(text)
        if text.startswith(("MODEL SCRIPT FAILED", "SCRIPT FAILED")):
            return 1
        code = 2 if sum(int(n) for n in CHECKS.findall(text)) > 0 else 0
        for s in sorted(glob.glob(os.path.join(out_dir, "*_sheet.png"))):
            print(f"SHEET: {s}")
        if "--final" in args:
            print(f"FINAL: {os.path.abspath(args[args.index('--final') + 1])}")
        if out_dir and os.path.isfile(os.path.join(out_dir, "model.blend")) and not script_mode:
            print(f"BLEND: {os.path.join(out_dir, 'model.blend')}")
        if script_mode:
            print(f"LOG: {os.path.join(out_dir, 'blender.log')}")
            if "REFUSED:" in log:
                return 1
        return code
    print(f"Blender exited with code {code}; see {out_dir}/blender.log" if out_dir
          else f"Blender exited with code {code}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
