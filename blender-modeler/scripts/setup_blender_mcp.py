"""Set up and diagnose the official Blender Lab MCP add-on (live mode).

    python setup_blender_mcp.py --check
    python setup_blender_mcp.py --install-addon PATH   # mcp-x.y.z.zip, or the add-on source folder
    python setup_blender_mcp.py --enable-online-access
    python setup_blender_mcp.py --package-addon [PATH] # zip the add-on to Downloads for Install from Disk

Why this exists: the add-on only tries to start its server once, when Blender
starts, and only if Online Access is already on. Turning Online Access on in a
running Blender does not start it, and the setting is lost unless preferences
are saved. Both lead to "the MCP tools time out" with no visible error.

Three ways to get the server running:
  1. Online Access saved on (--enable-online-access, or Preferences > System >
     Allow Online Access + Save Preferences), then start Blender.
  2. Launch Blender with --online-mode: on for that launch only, nothing saved.
  3. Already open with the server stopped: turn Online Access on, then
     Preferences > Add-ons > MCP > Start MCP Bridge Server. No reinstall needed.

Windows app sandbox: processes started by an MSIX-packaged app (the Claude
desktop app is one) see a virtualised %APPDATA%. Their writes land in
%LOCALAPPDATA%\\Packages\\<app>\\LocalCache\\Roaming\\..., so an add-on installed or a
preference saved from there is invisible to the Blender the user starts from the
Start menu. --check detects this (it writes and removes a marker file); in that
case use --package-addon and Blender's own Install from Disk.

--check also reports which process owns port 9876 (and its window title, i.e.
which file is open), using the OS connection table; it does not connect to it.

--install-addon and --enable-online-access change Blender's saved preferences,
so Blender must be closed (it would overwrite them on quit). A backup of
userpref.blend is made first. Runs with any Python 3.8+.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bmod import blender_version, find_blender  # noqa: E402

ADDON_ID = "mcp"
PORT = 9876

PROBE = r"""
import bpy, json, os, addon_utils
p = bpy.context.preferences
mods = [a.module for a in p.addons]
mod = next((m for m in mods if m == "mcp" or m.endswith(".mcp")), None)
found = [m for m in addon_utils.modules() if m.__name__.split(".")[-1] == "mcp"]
a = p.addons.get(mod) if mod else None
print("PROBE" + json.dumps({
    "installed": [m.__name__ for m in found],
    "paths": [os.path.dirname(m.__file__) for m in found],
    "enabled_module": mod,
    "online_access_saved": p.system.use_online_access,
    "autostart": getattr(a.preferences, "use_autostart", None) if a else None,
    "port": getattr(a.preferences, "port", None) if a else None,
    "userpref": bpy.utils.user_resource("CONFIG", path="userpref.blend"),
}))
"""

ENABLE_ONLINE = r"""
import bpy
bpy.context.preferences.system.use_online_access = True
bpy.ops.wm.save_userpref()
print("ONLINE_SAVED", bpy.context.preferences.system.use_online_access)
"""


def run_blender(exe, args, timeout=180):
    r = subprocess.run([exe] + args, capture_output=True, text=True, errors="replace", timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def probe(exe):
    # No --factory-startup: we want the user's real preferences. The add-on never
    # starts its server in background mode, so this can't clash with a running one.
    _, out = run_blender(exe, ["-b", "--python-expr", PROBE])
    for line in out.splitlines():
        if line.startswith("PROBE"):
            return json.loads(line[5:])
    raise RuntimeError("Could not read Blender preferences:\n" + out[-2000:])


def _ps(script, timeout=30):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=timeout).stdout


def blender_cmdlines():
    """Command lines of running Blender processes ([] if none or unknown)."""
    try:
        if os.name == "nt":
            out = _ps("(Get-CimInstance Win32_Process -Filter \"Name='blender.exe'\").CommandLine")
        else:
            out = subprocess.run(["pgrep", "-ifa", "blender"], capture_output=True, text=True).stdout
        return [l.strip() for l in out.splitlines() if l.strip() and "setup_blender_mcp" not in l]
    except Exception:  # noqa: BLE001
        return []


def blender_running():
    return bool(blender_cmdlines())


def port_owner(port=PORT):
    """{"pid", "name", "cmdline", "title"} of the process listening on port, None if
    nothing listens, "unknown" if the OS can't be asked. Never opens a connection."""
    try:
        if os.name == "nt":
            out = _ps(
                f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
                "Select-Object -First 1; if ($c) { $p = Get-CimInstance Win32_Process -Filter "
                "\"ProcessId=$($c.OwningProcess)\"; $g = Get-Process -Id $c.OwningProcess -ErrorAction "
                "SilentlyContinue; [pscustomobject]@{pid=$c.OwningProcess; name=$p.Name; cmdline=$p.CommandLine; "
                "title=$g.MainWindowTitle} | ConvertTo-Json -Compress } else { 'NONE' }")
            out = out.strip()
            if out == "NONE":
                return None
            if out.startswith("{"):
                return json.loads(out)
            # Get-NetTCPConnection missing: fall back to netstat
            ns = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=30).stdout
            for line in ns.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                    return {"pid": int(parts[4]), "name": None, "cmdline": None, "title": None}
            return None
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
                             capture_output=True, text=True, timeout=30).stdout
        pids = [l[1:] for l in out.splitlines() if l.startswith("p")]
        if not pids:
            return None
        cmd = subprocess.run(["ps", "-o", "command=", "-p", pids[0]], capture_output=True, text=True).stdout.strip()
        return {"pid": int(pids[0]), "name": os.path.basename(cmd.split()[0]) if cmd else None,
                "cmdline": cmd, "title": None}
    except FileNotFoundError:
        return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def port_listening(port=PORT):
    owner = port_owner(port)
    if owner != "unknown":
        return owner is not None
    with socket.socket() as s:            # last resort only: the OS table was not available
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------- Windows app sandbox

def msix_sandbox():
    """Name of the MSIX package whose AppData virtualisation this process runs under
    (e.g. 'Claude_pzs8sxrjxfjjc'), or None. Writes one marker file under %APPDATA%,
    looks for it under %LOCALAPPDATA%\\Packages\\*\\LocalCache\\Roaming, then removes it."""
    if os.name != "nt":
        return None
    appdata, local = os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")
    if not appdata or not local:
        return None
    name = f"blender_modeler_probe_{uuid.uuid4().hex}.tmp"
    marker = os.path.join(appdata, name)
    hits = []
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("sandbox probe; safe to delete\n")
        hits = glob.glob(os.path.join(local, "Packages", "*", "LocalCache", "Roaming", name))
    except OSError:
        return None
    finally:
        for p in [marker] + hits:
            try:
                os.remove(p)
            except OSError:
                pass
    return os.path.normpath(hits[0]).split(os.sep)[-4] if hits else None


def sandbox_addon_copies():
    """MCP add-on folders inside any app's virtualised AppData (Windows)."""
    local = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local:
        return []
    pat = os.path.join(local, "Packages", "*", "LocalCache", "Roaming", "Blender Foundation", "Blender",
                       "*", "extensions", "*", ADDON_ID)
    return [p for p in glob.glob(pat) if os.path.isdir(p)]


def downloads_dir():
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def package_addon(src=None, exe=None, to=None):
    """Zip the add-on (blender_manifest.toml at the zip root) to the Downloads folder
    (or `to`), for Edit > Preferences > Get Extensions > (menu) > Install from Disk."""
    if src is None:
        cands = []
        if exe:
            try:
                cands += probe(exe).get("paths", [])
            except Exception:  # noqa: BLE001
                pass
        cands += sandbox_addon_copies()
        src = next((c for c in cands if os.path.isfile(os.path.join(c, "blender_manifest.toml"))), None)
        if not src:
            print("No MCP add-on found to package; pass its folder or zip: --package-addon PATH")
            return 1
    src = os.path.abspath(src)
    dst = os.path.join(to or downloads_dir(), "blender_mcp_addon.zip")
    if os.path.isfile(src) and src.lower().endswith(".zip"):
        shutil.copy2(src, dst)
    elif os.path.isdir(src):
        if not os.path.isfile(os.path.join(src, "blender_manifest.toml")):
            print(f"{src} has no blender_manifest.toml; is it the add-on folder?")
            return 1
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith(".pyc"):
                        continue
                    p = os.path.join(root, f)
                    z.write(p, os.path.relpath(p, src))
    else:
        print(f"Not a zip or folder: {src}")
        return 1
    print(f"Packaged {src}\n     -> {dst}")
    print("In the Blender you normally use: Edit > Preferences > Get Extensions > (menu, top right) > "
          "Install from Disk > pick that zip. Then System > Allow Online Access, and Save Preferences "
          "(menu at bottom left). Restart Blender (or click Start MCP Bridge Server).")
    return 0


# ---------------------------------------------------------------- actions

def backup_prefs(path):
    if path and os.path.isfile(path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = f"{path}.bak-{stamp}"
        shutil.copy2(path, dst)
        print(f"Backed up preferences to {dst}")


def require_closed():
    if blender_running():
        print("Blender is running. Close it first (it would overwrite the saved preferences on quit).")
        sys.exit(1)


def warn_sandbox(pkg):
    print(f"WARNING: this process runs inside the '{pkg}' app sandbox. Its %APPDATA% is virtualised:\n"
          "  add-ons installed and preferences saved from here only affect Blenders launched from this\n"
          "  sandbox, not the Blender you start yourself. Use --package-addon and install the zip from\n"
          "  Blender's Preferences instead, and turn on Online Access there.")


def check(exe):
    v = blender_version(exe)
    print(f"Blender:        {exe} ({v})")
    pkg = msix_sandbox()
    info = probe(exe)
    ok = True

    def line(label, good, text, fix=None):
        nonlocal ok
        ok &= good
        print(f"{'OK ' if good else 'FIX'} {label:<15} {text}")
        if fix and not good:
            print(f"    -> {fix}")

    if pkg:
        copies = sandbox_addon_copies()
        print(f"!!  Sandbox         running inside the '{pkg}' app sandbox: %APPDATA% is virtualised, so the\n"
              "                    preferences/add-ons below are what a Blender started FROM HERE sees.")
        for c in copies:
            print(f"                    sandbox-only add-on copy: {c}")
        print("    -> if the Blender you open yourself doesn't list MCP in Preferences > Add-ons:\n"
              "       python setup_blender_mcp.py --package-addon, then Install from Disk in that Blender")
    else:
        print("OK  Sandbox         not sandboxed (writes to %APPDATA% are real)" if os.name == "nt"
              else "--  Sandbox         n/a on this OS")
    major_minor = tuple(int(x) for x in v.split(".")[:2]) if v[0].isdigit() else (0, 0)
    line("Blender 5.1+", major_minor >= (5, 1), v, "the official MCP add-on needs Blender 5.1 or newer")
    line("Add-on", bool(info["installed"]), ", ".join(info["installed"]) or "not installed",
         "python setup_blender_mcp.py --install-addon <mcp-x.y.z.zip or addon folder>"
         + (" (sandboxed: use --package-addon instead)" if pkg else ""))
    line("Add-on enabled", bool(info["enabled_module"]), info["enabled_module"] or "disabled",
         "Edit > Preferences > Add-ons > MCP: tick the checkbox, or re-run --install-addon")
    cmdlines = blender_cmdlines()
    running = bool(cmdlines)
    owner = port_owner(info["port"] or PORT)
    listening = owner is not None if owner != "unknown" else port_listening(info["port"] or PORT)
    online_flag = any("--online-mode" in c for c in cmdlines)
    if not info["online_access_saved"] and online_flag:
        print("--  Online Access   saved OFF, but the open Blender was launched with --online-mode "
              "(on for that launch only)")
    elif running and listening and not info["online_access_saved"]:
        line("Online Access", False, "on in the open Blender but NOT saved (off again next launch)",
             "in Blender: Edit > Preferences > (menu at bottom left) > Save Preferences")
    else:
        line("Online Access", bool(info["online_access_saved"]),
             "saved ON" if info["online_access_saved"] else "saved OFF (server will not start)",
             "python setup_blender_mcp.py --enable-online-access (with Blender closed), "
             "or turn it on in Edit > Preferences > System and Save Preferences")
    line("Auto Start", info["autostart"] is not False, str(info["autostart"]),
         "Edit > Preferences > Add-ons > MCP: tick Auto Start, then Save Preferences")
    if running:
        line("Server", listening, f"listening on {info['port'] or PORT}" if listening else "Blender open but server not running",
             "turn on Online Access, then Edit > Preferences > Add-ons > MCP > Start MCP Bridge Server "
             "(no reinstall needed), or restart Blender")
    else:
        print(f"--  Server          Blender is closed; the server starts with Blender"
              f"{' (port is busy: another MCP add-on?)' if listening else ''}")
    if isinstance(owner, dict):
        is_blender = "blender" in str(owner.get("name") or owner.get("cmdline") or "").lower()
        print(f"{'OK ' if is_blender else 'FIX'} Port owner      PID {owner['pid']} {owner.get('name') or ''}"
              f"{'  window: ' + repr(owner['title']) if owner.get('title') else ''}")
        if owner.get("cmdline"):
            print(f"                    {owner['cmdline']}")
        if not is_blender:
            ok = False
            print("    -> another program holds the port (e.g. the community blender-mcp); stop it or change the port")
        elif len(cmdlines) > 1:
            print(f"    -> {len(cmdlines)} Blenders are open; only this one serves MCP. Make sure it is the "
                  "window with your file (its title shows the open .blend).")
    elif owner == "unknown":
        print("--  Port owner      could not query the OS connection table")
    print("\nAll good." if ok else "\nFix the items marked FIX, then start Blender.")
    return 0 if ok else 1


def install_addon(exe, path):
    require_closed()
    pkg = msix_sandbox()
    if pkg:
        warn_sandbox(pkg)
    path = os.path.abspath(path)
    backup_prefs(probe(exe).get("userpref"))
    if os.path.isdir(path):
        out_dir = tempfile.mkdtemp(prefix="blmcp_")
        code, out = run_blender(exe, ["--factory-startup", "-c", "extension", "build",
                                      "--source-dir", path, "--output-dir", out_dir])
        zips = [f for f in os.listdir(out_dir) if f.endswith(".zip")]
        if code or not zips:
            print(out)
            return 1
        path = os.path.join(out_dir, zips[0])
    code, out = run_blender(exe, ["-c", "extension", "install-file", "-r", "user_default", "-e", path])
    print(out.strip())
    return code


def enable_online(exe):
    require_closed()
    pkg = msix_sandbox()
    if pkg:
        warn_sandbox(pkg)
    backup_prefs(probe(exe).get("userpref"))
    code, out = run_blender(exe, ["-b", "--python-expr", ENABLE_ONLINE])
    if "ONLINE_SAVED True" not in out:
        print(out[-2000:])
        return 1
    print("Online Access is now on and saved.")
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--install-addon", metavar="PATH")
    ap.add_argument("--enable-online-access", action="store_true")
    ap.add_argument("--package-addon", metavar="PATH", nargs="?", const="")
    ap.add_argument("--to", metavar="DIR", help="folder for --package-addon (default: Downloads)")
    ap.add_argument("--sandbox", action="store_true", help="only report the app-sandbox and port-owner status")
    ap.add_argument("--blender", metavar="PATH")
    a = ap.parse_args()
    if a.sandbox:
        pkg = msix_sandbox()
        print(f"sandbox: {pkg or 'none'}")
        for c in sandbox_addon_copies():
            print(f"sandbox add-on copy: {c}")
        print(f"port {PORT} owner: {json.dumps(port_owner())}")
        return 0
    exe = find_blender(a.blender)
    if not exe and a.package_addon is None:
        print("Blender not found; set BLENDER_EXE or pass --blender PATH.")
        return 3
    code = 0
    if a.package_addon is not None:
        code |= package_addon(a.package_addon or None, exe, a.to)
    if a.install_addon:
        code |= install_addon(exe, a.install_addon)
    if a.enable_online_access:
        code |= enable_online(exe)
    if a.check or not (a.install_addon or a.enable_online_access or a.package_addon is not None):
        code |= check(exe)
    return code


if __name__ == "__main__":
    sys.exit(main())
