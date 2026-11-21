"""Tiny assertion helper shared by the Blender-side tests (stdlib only).

Each test script prints one line per check ("PASS name: detail" / "FAIL ...")
and ends with "RESULT n_pass n_fail"; run_tests.py collects those lines.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

_results = []


def out_dir():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    d = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(HERE, "_out")
    os.makedirs(d, exist_ok=True)
    return d


def check(name, ok, detail=""):
    _results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    return ok


def done():
    n_fail = _results.count(False)
    print(f"RESULT {_results.count(True)} {n_fail}", flush=True)
    sys.exit(1 if n_fail else 0)
