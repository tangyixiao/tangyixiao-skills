"""Check channels (wire runs, pipes, conduits, drop holes) inside a host mesh.

For every channel (a curve with a bevel, or a mesh made by modelkit.tube /
tube_mesh, which store their centre line and diameter) this measures:
- min_wall: distance from the channel surface to the host skin (ray-parity
  signed clearance minus the radius), with where it is thinnest
- min_bend: tightest bend radius of the centre line
- keep-out clearance: wall between the channel and each keep-out volume
- loose ends: every end must land on another channel's centre line (within that
  channel's radius), on a declared terminal, or be a declared exit through the
  skin. Contact checks don't catch a trunk that starts 35 mm past its branch:
  the tubes still overlap. This does.
- connectivity: with a "hub" terminal, every channel must connect to it
- fill: wire bundle area / channel area, from wire counts
- length per channel and in total

Spec (spec.json, key "channels"); numbers are in "units" (default the spec's
"units", else metres):

    "channels": {
      "units": "mm",
      "host": "Body",                       # the host object (frozen master or a copy)
      "collection": "WIRING",               # or "names": ["ch *", "drop *"] (fnmatch)
      "wall_min": 3.0, "bend_min": 15.0,
      "bend_exempt": ["ch elbow*"],          # e.g. V-turns that sit on a print split
      "keepouts": ["CUT vault"],             # objects (closed meshes) or {"name", "box": [lo, hi]}
      "keepout_min": 3.0,                    # default wall_min
      "terminals": {"bay": {"object": "CUT bay"}, "eye_R": {"point": [x, y, z], "radius": 4}},
      "hub": "bay",                          # optional: everything must connect to this terminal
      "exits": ["drop power*"],              # channels allowed to end through the host skin
      "wires": {"ch *": 2, "trunk*": 6}, "wire_od": 1.6, "fill_max": 0.6,
      "open_len": null                       # wall check skips this far from open ends (default 2*(r+wall_min))
    }

Runs inside Blender:

    import check_channels
    rep = check_channels.run(spec_path="spec.json")         # rep["summary"]["errors"]

or headless: blender -b host.blend --python check_channels.py -- --spec spec.json [--out dir]
(exit code 2 when there are errors, like bmod.py).
"""

import fnmatch
import json
import os
import sys

import bpy
import numpy as np
from mathutils.geometry import interpolate_bezier

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostkit  # noqa: E402
import routekit  # noqa: E402

_PER = {"m": 1.0, "cm": 0.01, "mm": 0.001}


def _match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in (patterns or []))


def centerlines(obj):
    """[(label, points (N, 3) world metres, diameter metres)] for one channel object."""
    M = np.array(obj.matrix_world)
    sc = float(np.mean([obj.matrix_world.col[i].xyz.length for i in range(3)]))
    out = []

    def world(P):
        P = np.asarray(P, float).reshape(-1, 3)
        return P @ M[:3, :3].T + M[:3, 3]

    dia = None
    if "dia" in obj:
        dia = float(obj["dia"]) * sc
    elif "dia_mm" in obj:
        dia = float(obj["dia_mm"]) / 1000 * sc
    if "centerline" in obj:
        out.append((obj.name, world(list(obj["centerline"])), dia))
        return out
    if obj.type == "CURVE":
        cd = obj.data
        if dia is None:
            dia = 2 * cd.bevel_depth * sc
        for k, sp in enumerate(cd.splines):
            if sp.type == "BEZIER":
                bp = sp.bezier_points
                pts = []
                segs = list(zip(bp[:-1], bp[1:])) + ([(bp[-1], bp[0])] if sp.use_cyclic_u else [])
                for a, b in segs:
                    seg = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, max(2, cd.resolution_u + 1))
                    pts += [tuple(v) for v in (seg if not pts else seg[1:])]
            else:
                pts = [tuple(p.co[:3]) for p in sp.points]
            if len(pts) >= 2:
                out.append((obj.name if len(cd.splines) == 1 else f"{obj.name}[{k}]", world(pts), dia))
    return out


def _channels(ch):
    if ch.get("names"):
        objs = [o for o in bpy.data.objects if _match(o.name, ch["names"])]
    elif ch.get("collection"):
        objs = list(bpy.data.collections[ch["collection"]].all_objects)
    else:
        objs = [o for o in bpy.context.scene.objects if "centerline" in o or "dia_mm" in o]
    return [o for o in objs if o.type in ("CURVE", "MESH") and not o.name.startswith("_")]


def _box_clearance(P, lo, hi):
    """Distance from points to an axis-aligned box: >0 outside, <0 inside (approx)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    d = np.maximum(lo - P, P - hi)
    out = np.linalg.norm(np.maximum(d, 0), axis=1)
    inside = np.all(d < 0, axis=1)
    out[inside] = d[inside].max(1)
    return out


def _arclen(P):
    return np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])


def run(spec_path=None, spec=None, out_path=None, verbose=True):
    if spec is None:
        with open(spec_path, "r", encoding="utf-8-sig") as f:
            spec = json.load(f)
    ch = spec.get("channels", spec)
    units = ch.get("units", spec.get("units", "m"))
    k = _PER[units]                                   # metres per unit
    saved_units = hostkit.UNITS
    hostkit.set_units(units)
    try:
        return _run(ch, units, k, out_path, verbose)
    finally:
        hostkit.set_units(saved_units)


def _run(ch, units, k, out_path, verbose):
    errors, warnings, info = [], [], []
    rep = {"units": units, "channels": {}, "errors": errors, "warnings": warnings, "info": info}
    host = bpy.data.objects.get(ch["host"]) if ch.get("host") else None
    if ch.get("host") and host is None:
        errors.append(f"Host object '{ch['host']}' not found.")
    wall_min = ch.get("wall_min")
    bend_min = ch.get("bend_min")
    keep_min = ch.get("keepout_min", wall_min if wall_min is not None else 0.0)
    fill_max = ch.get("fill_max", 0.6)
    tol = ch.get("tol", 0.00005 / k)                   # junction slack: 0.05 mm

    chans = []
    for o in _channels(ch):
        for label, P, dia in centerlines(o):
            if dia is None or dia <= 0:
                warnings.append(f"{label}: no diameter (bevel_depth or 'dia' prop); skipped.")
                continue
            chans.append({"name": label, "obj": o.name, "P": P / k, "r": dia / k / 2})
    if not chans:
        errors.append("No channels found (curves with a bevel, or modelkit.tube/tube_mesh objects).")
        return _finish(rep, out_path, verbose)

    # terminals
    terms = {}
    for tname, t in (ch.get("terminals") or {}).items():
        if "object" in t:
            ob = bpy.data.objects.get(t["object"])
            if ob is None:
                errors.append(f"Terminal '{tname}': object '{t['object']}' not found.")
                continue
            terms[tname] = {"object": ob, "radius": t.get("radius", 0.0)}
        else:
            terms[tname] = {"point": np.asarray(t["point"], float), "radius": float(t.get("radius", 0.0))}

    def terminal_of(e, r):
        best = None
        for tname, t in terms.items():
            if "object" in t:
                c = float(hostkit.clearance([e], t["object"])[0])     # >0 inside the terminal
                ok = c >= -(t["radius"] + r)
                d = max(0.0, -c)
            else:
                d = float(np.linalg.norm(e - t["point"]))
                ok = d <= t["radius"] + r
            if ok and (best is None or d < best[1]):
                best = (tname, d)
        return best

    # ends and connectivity
    edges = {c["name"]: set() for c in chans}
    hub = ch.get("hub")
    loose = []
    for c in chans:
        ends = {}
        for end, e in (("start", c["P"][0]), ("end", c["P"][-1])):
            best = None
            for o in chans:
                if o is c:
                    continue
                q, d, _ = routekit.closest_on_polyline(o["P"], e)
                if d <= o["r"] + tol and (best is None or d < best[1]):
                    best = (o["name"], d, o["r"])
            t = terminal_of(e, c["r"])
            skin = None
            if host is not None:
                skin = float(hostkit.clearance([e], host)[0])
            if best:
                ends[end] = {"joins": best[0], "offset": round(best[1], 4)}
                edges[c["name"]].add(best[0])
                edges[best[0]].add(c["name"])
                if best[1] > 0.5 * best[2]:
                    warnings.append(f"OFF-CENTRE JUNCTION: {c['name']} {end} meets {best[0]} "
                                    f"{best[1]:.2f} {units} off its centre line (r {best[2]:.2f}); snap it "
                                    "(routekit.snap_junctions).")
                if t:
                    ends[end]["terminal"] = t[0]
                    edges[c["name"]].add("@" + t[0])
            elif t:
                ends[end] = {"terminal": t[0], "offset": round(t[1], 4)}
                edges[c["name"]].add("@" + t[0])
            elif skin is not None and skin < c["r"] and _match(c["name"], ch.get("exits")):
                ends[end] = {"exit": True, "skin_clearance": round(skin, 4)}
                edges[c["name"]].add("@outside")
            else:
                near = min(((o["name"], routekit.closest_on_polyline(o["P"], e)[1]) for o in chans if o is not c),
                           key=lambda x: x[1], default=(None, float("inf")))
                ends[end] = {"loose": True, "nearest": near[0], "gap": round(near[1], 4)}
                loose.append(c["name"])
                where = "(" + ", ".join(f"{x:.2f}" for x in e) + ")"
                errors.append(f"LOOSE END: {c['name']} {end} at {where} {units} lands on nothing "
                              f"(nearest channel {near[0]}: {near[1]:.2f} {units} from its centre line; "
                              + ("ends through the skin but is not listed in 'exits'" if skin is not None and skin < c["r"]
                                 else "not a declared terminal") + ").")
        c["ends"] = ends

    # graph components
    seen, comps = set(), []
    for c in chans:
        if c["name"] in seen:
            continue
        stack, comp = [c["name"]], set()
        while stack:
            u = stack.pop()
            if u in comp:
                continue
            comp.add(u)
            for v in edges.get(u, ()):
                if not v.startswith("@"):
                    stack.append(v)
        seen |= comp
        anchors = {v for u in comp for v in edges[u] if v.startswith("@")}
        comps.append((sorted(comp), sorted(anchors)))
    rep["networks"] = [{"channels": a, "anchors": b} for a, b in comps]
    if hub:
        for comp, anchors in comps:
            if "@" + hub not in anchors:
                errors.append(f"NOT CONNECTED TO HUB '{hub}': {', '.join(comp)} "
                              f"(their network reaches: {', '.join(anchors) or 'nothing'}).")
    if len(comps) > 1 and not hub:
        info.append(f"{len(comps)} separate channel networks (add a 'hub' terminal to require one).")

    # per-channel measurements
    keeps = []
    for kk in ch.get("keepouts") or []:
        if isinstance(kk, dict) and "box" in kk:
            keeps.append((kk.get("name", "box"), None, kk["box"]))
        else:
            ob = bpy.data.objects.get(kk if isinstance(kk, str) else kk.get("name"))
            if ob is None:
                errors.append(f"Keep-out '{kk}' not found.")
            else:
                keeps.append((ob.name, ob, None))
    wires = ch.get("wires") or {}
    wire_od = ch.get("wire_od")
    total = 0.0
    for c in chans:
        P, r = c["P"], c["r"]
        L = routekit.length(P)
        total += L
        e = {"dia": round(2 * r, 4), "length": round(L, 3), "ends": c["ends"]}
        S = routekit.resample(P, max(r / 2, 1e-9))
        s = _arclen(S)
        skip = np.zeros(len(S), bool)
        open_len = ch.get("open_len") or 2 * (r + (wall_min or 0))
        for end, info_ in c["ends"].items():
            if info_.get("terminal") or info_.get("exit"):
                skip |= (s <= open_len) if end == "start" else (s >= s[-1] - open_len)
        if host is not None:
            wall = hostkit.clearance(S, host) - r
            w = np.where(skip, np.inf, wall)
            i = int(np.argmin(w))
            if np.isfinite(w[i]):
                e["min_wall"] = round(float(w[i]), 3)
                e["min_wall_at"] = [round(float(x), 3) for x in S[i]]
                if wall_min is not None and w[i] < wall_min:
                    errors.append(f"THIN WALL: {c['name']} has {w[i]:.2f} {units} to the skin at "
                                  f"({', '.join(f'{x:.2f}' for x in S[i])}) (needs {wall_min}).")
        if len(P) >= 3:
            B = routekit.resample(P, max(2 * r, 1e-9))
            br = routekit.bend_radii(B)
            if len(br):
                i = int(np.argmin(br))
                e["min_bend"] = round(float(br[i]), 3) if np.isfinite(br[i]) else None
                if bend_min is not None and br[i] < bend_min:
                    msg = (f"{c['name']} bends at radius {br[i]:.1f} {units} at "
                           f"({', '.join(f'{x:.2f}' for x in B[i + 1])}) (min {bend_min})")
                    if _match(c["name"], ch.get("bend_exempt")):
                        info.append("BEND (exempt): " + msg)
                    else:
                        errors.append("TIGHT BEND: " + msg + ".")
        for kname, kob, box in keeps:
            own = {v.get("terminal") for v in c["ends"].values()}
            if kob is not None and any(terms.get(t, {}).get("object") is kob for t in own if t):
                continue                                     # the channel ends in this cavity on purpose
            cl = (-hostkit.clearance(S, kob) if kob is not None else _box_clearance(S, *box)) - r
            i = int(np.argmin(cl))
            e.setdefault("keepout_wall", {})[kname] = round(float(cl[i]), 3)
            if cl[i] < keep_min:
                errors.append(f"KEEP-OUT: {c['name']} is {cl[i]:.2f} {units} from '{kname}' at "
                              f"({', '.join(f'{x:.2f}' for x in S[i])}) (needs {keep_min}).")
        n_w = next((v for pat, v in wires.items() if fnmatch.fnmatchcase(c["name"], pat)), None)
        if n_w is not None and wire_od:
            fill = n_w * wire_od ** 2 / (2 * r) ** 2
            e["fill_pct"] = round(100 * fill, 1)
            if fill > fill_max:
                errors.append(f"OVERFULL: {c['name']} carries {n_w} x {wire_od} {units} wires = "
                              f"{100 * fill:.0f}% fill (max {100 * fill_max:.0f}%); widen it to "
                              f"{wire_od * (n_w / fill_max) ** 0.5:.1f} {units}.")
        rep["channels"][c["name"]] = e
    rep["total_length"] = round(total, 3)
    return _finish(rep, out_path, verbose)


def _finish(rep, out_path, verbose):
    rep["summary"] = {"errors": len(rep["errors"]), "warnings": len(rep["warnings"]),
                      "channels": len(rep["channels"])}
    rep["text"] = format_report(rep)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in rep.items() if k != "text"}, f, indent=1, default=float)
    if verbose:
        print(rep["text"])
    return rep


def format_report(rep):
    u = rep["units"]
    s = rep["summary"]
    lines = [f"CHANNEL CHECK: {s['errors']} errors, {s['warnings']} warnings, {s['channels']} channels, "
             f"total length {rep.get('total_length', 0):.1f} {u}"]
    for key in ("errors", "warnings", "info"):
        for msg in rep[key]:
            lines.append(f"  [{key[:-1].upper() if key != 'info' else 'INFO'}] {msg}")
    lines.append(f"  channels ({u}):")
    for name, e in rep["channels"].items():
        bits = [f"dia {e['dia']:g}", f"len {e['length']:.1f}"]
        if "min_wall" in e:
            bits.append(f"wall {e['min_wall']:.2f}")
        if e.get("min_bend") is not None:
            bits.append(f"bend R{e['min_bend']:.1f}")
        if "fill_pct" in e:
            bits.append(f"fill {e['fill_pct']:.0f}%")
        ends = []
        for end, v in e["ends"].items():
            ends.append(f"{end}->" + (v.get("joins") or (("@" + v["terminal"]) if v.get("terminal") else None)
                                       or ("exit" if v.get("exit") else "LOOSE")))
        lines.append(f"    {name}: " + ", ".join(bits) + "  [" + " ".join(ends) + "]")
    return "\n".join(lines)


def _cli():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = None
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        out = os.path.join(a.out, "channels_report.json")
    rep = run(spec_path=a.spec, out_path=out)
    if a.out:
        with open(os.path.join(a.out, "channels_report.txt"), "w", encoding="utf-8") as f:
            f.write(rep["text"] + "\n")
    sys.exit(2 if rep["summary"]["errors"] else 0)


if __name__ == "__main__":
    _cli()
