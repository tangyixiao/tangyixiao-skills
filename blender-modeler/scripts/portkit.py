"""Port generated features to other .blend files as plain data ("port files").

Writing .blend files from a live MCP session can crash the user's Blender
(bpy.data.libraries.write after linking collections did, mid-session). The safe
route: dump the generated collection to JSON from the live session, then
rebuild it in a NEW .blend headless, at the same world coordinates, with a
README text block that says how to port it (boolean order etc.).

Live (writes only a JSON file):

    import portkit
    portkit.dump("WIRING", r"<project>/wiring_parts.json")

Headless (version in the file name from the command line, not by editing the script):

    python bmod.py --script <skill>/scripts/portkit.py -- --rebuild wiring_parts.json \
        --out "wiring_{version}.blend" --version v07 --readme README_port.txt

Curves are stored as world-space centre lines with their diameter (rebuilt as POLY
curves, or closed tube meshes with --as-mesh); meshes as world-space vertices and
faces. Materials keep their viewport colour; custom props (role, dia, ...) survive.
"""

import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _props(o):
    out = {}
    for k in o.keys():
        if k.startswith("_") or k == "centerline":
            continue
        v = o[k]
        if isinstance(v, (int, float, str, bool)):
            out[k] = v
    return out


def dump(collection, path=None, version=None):
    """Collection tree -> plain dict (and JSON file if path). World space, metres."""
    import check_channels
    root = bpy.data.collections[collection] if isinstance(collection, str) else collection
    mats = {}

    def mat(o):
        m = o.active_material
        if m:
            mats[m.name] = list(m.diffuse_color)
            return m.name
        return None

    def walk(c):
        tubes, meshes = [], []
        for o in c.objects:
            if o.type == "CURVE" or (o.type == "MESH" and "centerline" in o and o.get("port_as") == "tube"):
                for label, P, dia in check_channels.centerlines(o):
                    tubes.append({"name": label, "dia": dia, "pts": P.round(7).tolist(), "mat": mat(o),
                                  "props": _props(o)})
            elif o.type == "MESH":
                me = o.data
                co = np.empty(len(me.vertices) * 3)
                me.vertices.foreach_get("co", co)
                M = np.array(o.matrix_world)
                W = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
                props = _props(o)
                if "centerline" in o:
                    cl = np.asarray(list(o["centerline"]), float).reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
                    props["centerline"] = cl.round(7).ravel().tolist()
                meshes.append({"name": o.name, "mat": mat(o), "props": props, "verts": W.round(7).tolist(),
                               "faces": [list(p.vertices) for p in me.polygons]})
        return {"name": c.name, "tubes": tubes, "meshes": meshes, "children": [walk(ch) for ch in c.children]}

    data = {"version": version, "units": "m", "collections": walk(root), "materials": mats}
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return data


def rebuild(data, out_blend=None, readme=None, as_mesh=False, clear=True):
    """Build the dumped collections into the current scene (cleared first when clear)
    and save to out_blend. Returns the root collection."""
    import modelkit
    if isinstance(data, str):
        with open(data, encoding="utf-8-sig") as f:
            data = json.load(f)
    if clear:
        modelkit.reset_scene()
    sc = bpy.context.scene
    mats = {}
    for n, col in data.get("materials", {}).items():
        m = bpy.data.materials.new(n)
        m.diffuse_color = col
        mats[n] = m

    def make(cd, parent):
        c = bpy.data.collections.new(cd["name"])
        parent.children.link(c)
        for t in cd["tubes"]:
            if as_mesh:
                o = modelkit.tube_mesh(t["name"], t["pts"], t["dia"], coll=c)
            else:
                o = modelkit.tube(t["name"], t["pts"], t["dia"] / 2, kind="poly", to_mesh=False,
                                  bevel_resolution=4, coll=c)
            if t.get("mat"):
                o.data.materials.append(mats[t["mat"]])
            for k, v in t.get("props", {}).items():
                o[k] = v
        for s in cd["meshes"]:
            me = bpy.data.meshes.new(s["name"])
            me.from_pydata(s["verts"], [], s["faces"])
            me.validate()
            if s.get("mat"):
                me.materials.append(mats[s["mat"]])
            o = bpy.data.objects.new(s["name"], me)
            for k, v in s.get("props", {}).items():
                o[k] = v
            c.objects.link(o)
        for ch in cd["children"]:
            make(ch, c)
        return c

    root = make(data["collections"], sc.collection)
    if readme:
        text = open(readme, encoding="utf-8-sig").read() if os.path.isfile(readme) else readme
        t = bpy.data.texts.get("README") or bpy.data.texts.new("README")
        t.clear()
        t.write(text)
    if out_blend:
        cur = bpy.data.filepath
        if cur and os.path.normcase(os.path.abspath(out_blend)) == os.path.normcase(cur):
            raise RuntimeError("refusing to save the port file over the opened .blend")
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_blend), compress=True, copy=True)
        print(f"WROTE {os.path.abspath(out_blend)}")
    return root


def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", help="JSON written by dump()")
    ap.add_argument("--dump", help="collection to dump (with --json)")
    ap.add_argument("--json")
    ap.add_argument("--out", help="output .blend; '{version}' is replaced by --version")
    ap.add_argument("--version", default="")
    ap.add_argument("--readme", help="README text or a text file")
    ap.add_argument("--as-mesh", action="store_true")
    a = ap.parse_args(sys.argv[1:] if "--" not in sys.argv else sys.argv[sys.argv.index("--") + 1:])
    if a.dump:
        dump(a.dump, a.json, a.version or None)
        print(f"WROTE {a.json}")
    if a.rebuild:
        rebuild(a.rebuild, a.out.format(version=a.version) if a.out else None, a.readme, a.as_mesh)


if __name__ == "__main__":
    _cli()
