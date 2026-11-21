"""Run the skill's regression tests (drives Blender headless; stdlib only).

    python tests/run_tests.py                 # all tests
    python tests/run_tests.py basics chair    # some of them
    python tests/run_tests.py --out DIR       # keep outputs somewhere specific

Tests:
    basics  curve bounds (the bound_box bug), hostkit, routekit, modelkit helpers
    host    synthetic 380k-triangle host with flipped faces and an unapplied
            rotation/scale: find pockets, route channels, check_channels (incl. a
            deliberate loose end, thin wall and overfull channel), MANIFOLD cuts
            with a deliberately short cutter, verify_cuts, context/section renders
    chair   the classic new-object loop through bmod.py (model.py + spec.json)
    script  bmod.py --script on a .blend with --save-as (and its refusal to
            overwrite the opened file)
    hostcli bmod.py on the host test's scene: scoped geometry check, channel
            check, cut verification and a context render from the command line
    setup   setup_blender_mcp sandbox detection and port-owner lookup (no Blender,
            never connects to the MCP port)

Prints each check and the review images to look at; exit code 1 if any failed.
"""

import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
from bmod import find_blender  # noqa: E402


def blender_test(exe, script, out, timeout=1200):
    cmd = [exe, "-b", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.join(HERE, script), "--", "--out", out]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    log = p.stdout + p.stderr
    with open(os.path.join(out, script.replace(".py", ".log")), "w", encoding="utf-8") as f:
        f.write(log)
    lines = [l for l in log.splitlines() if l.startswith(("PASS", "FAIL", "INFO", "RESULT", "Traceback")) or "Error" in l]
    return p.returncode == 0 and any(l.startswith("RESULT") for l in lines), lines


def bmod(args, timeout=900):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "bmod.py")] + args,
                       capture_output=True, text=True, errors="replace", timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def test_chair(exe, out):
    fx = os.path.join(HERE, "fixtures", "chair")
    d = os.path.join(out, "chair")
    code, log = bmod(["--model", os.path.join(fx, "model.py"), "--spec", os.path.join(fx, "spec.json"),
                      "--out", d, "--mode", "clay", "--res", "384"])
    lines = [l for l in log.splitlines() if "GEOMETRY CHECK" in l or l.startswith(("SHEET", "  [ERROR"))]
    ok = code == 0 and os.path.isfile(os.path.join(d, "clay_sheet.png")) and os.path.isfile(os.path.join(d, "model.blend"))
    lines.append(f"{'PASS' if ok else 'FAIL'} chair via bmod.py: exit {code}")
    return ok, lines


def test_script(exe, out):
    d = os.path.join(out, "script")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(out, "chair", "model.blend")
    if not os.path.isfile(src):
        return False, ["FAIL script: run the chair test first (needs chair/model.blend)"]
    s = os.path.join(d, "add_marker.py")
    with open(s, "w", encoding="utf-8") as f:
        f.write("import sys, bpy\nimport modelkit as mk\n"
                "mk.box('Marker ' + (sys.argv[1] if len(sys.argv) > 1 else 'x'), (0.1, 0.1, 0.1), (0, 0, 2))\n"
                "print('OBJECTS', len(bpy.data.objects))\n")
    dst = os.path.join(d, "chair_marked_v01.blend")
    code, log = bmod(["--script", s, "--blend", src, "--save-as", dst, "--", "A1"])
    lines = []
    ok1 = code == 0 and os.path.isfile(dst) and "OBJECTS" in log
    lines.append(f"{'PASS' if ok1 else 'FAIL'} bmod --script --save-as: exit {code}, saved {os.path.isfile(dst)}")
    code2, log2 = bmod(["--script", s, "--blend", dst, "--save-as", dst])
    ok2 = code2 == 1 and "REFUSED" in log2
    lines.append(f"{'PASS' if ok2 else 'FAIL'} --save-as refuses to overwrite the opened file: exit {code2}")
    s2 = os.path.join(d, "boom.py")
    with open(s2, "w", encoding="utf-8") as f:
        f.write("raise ValueError('deliberate')\n")
    code3, log3 = bmod(["--script", s2, "--blend", src])
    ok3 = code3 == 1 and "deliberate" in log3
    lines.append(f"{'PASS' if ok3 else 'FAIL'} failing script -> exit 1 with traceback: exit {code3}")
    return ok1 and ok2 and ok3, lines


def test_hostcli(exe, out):
    blend = os.path.join(out, "host_scene.blend")
    if not os.path.isfile(blend):
        return False, ["FAIL hostcli: run the host test first (needs host_scene.blend)"]
    d = os.path.join(out, "hostcli")
    spec = os.path.join(out, "host_spec.json")
    code, log = bmod(["--blend", blend, "--spec", spec, "--collection", "WIRING", "--verify", spec,
                      "--context", "Body", "--color-by", "role", "--min-line-px", "3", "--res", "256",
                      "--no-save", "--out", d])
    lines = [l for l in log.splitlines() if l.startswith(("GEOMETRY CHECK", "CHANNEL CHECK", "CUT VERIFY", "SHEET", "  [ERROR"))]
    ok = code == 0 and os.path.isfile(os.path.join(d, "clay_sheet.png")) and "CHANNEL CHECK: 0 errors" in log         and "CUT VERIFY: 0 errors" in log and not os.path.isfile(os.path.join(d, "model.blend"))
    lines.append(f"{'PASS' if ok else 'FAIL'} bmod host mode (--blend --spec channels --verify --context): exit {code}")
    return ok, lines


def test_setup(exe, out):
    import setup_blender_mcp as sb
    lines = []
    pkg = sb.msix_sandbox()
    appdata = os.environ.get("APPDATA", "")
    leftovers = [f for f in os.listdir(appdata) if f.startswith("blender_modeler_probe_")] if appdata else []
    ok1 = not leftovers
    lines.append(f"{'PASS' if ok1 else 'FAIL'} sandbox probe cleans up: sandbox={pkg!r}, leftover markers {len(leftovers)}")
    owner = sb.port_owner()
    ok2 = owner is None or owner == "unknown" or isinstance(owner, dict)
    desc = owner if not isinstance(owner, dict) else f"PID {owner['pid']} {owner.get('name')}"
    lines.append(f"{'PASS' if ok2 else 'FAIL'} port_owner(9876) via OS table: {desc}")
    copies = sb.sandbox_addon_copies()
    lines.append(f"INFO sandbox add-on copies: {len(copies)}")
    return ok1 and ok2, lines


TESTS = {
    "basics": lambda exe, out: blender_test(exe, "test_basics.py", out),
    "host": lambda exe, out: blender_test(exe, "test_host_pipeline.py", out),
    "chair": test_chair,
    "script": test_script,
    "hostcli": test_hostcli,
    "setup": test_setup,
}


def main():
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out")
        out = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    out = out or os.path.join(tempfile.gettempdir(), "blender_modeler_tests")
    os.makedirs(out, exist_ok=True)
    names = args or list(TESTS)
    exe = find_blender()
    if not exe:
        print("Blender not found (set BLENDER_EXE).")
        return 3
    print(f"Blender: {exe}\nOutputs: {out}\n")
    failed = []
    for n in names:
        t0 = time.time()
        try:
            ok, lines = TESTS[n](exe, out)
        except Exception as ex:  # noqa: BLE001
            ok, lines = False, [f"FAIL {n}: {ex!r}"]
        print(f"== {n} ({time.time() - t0:.0f} s): {'ok' if ok else 'FAILED'}")
        for l in lines:
            print("   " + l)
        if not ok:
            failed.append(n)
    print("\nAll tests passed." if not failed else f"\nFailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
