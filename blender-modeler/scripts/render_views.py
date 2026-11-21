"""Render a model from fixed review views and tile them into one contact sheet.

Sheet layout (4 x 2), always the same so critiques can name views:

    row 1 (orthographic):  FRONT   | RIGHT   | BACK    | TOP
    row 2 (perspective):   3/4 L   | 3/4 R   | 3/4 BACK| LOW HERO

Front looks from -Y toward +Y (Blender's numpad 1), Z is up.

Modes:
    clay    Workbench, studio light, cavity + outline, random colour per object.
            Fast; shows form, part boundaries and proportions.
    shaded  EEVEE with the scene's own materials (adds a temporary light rig and
            grey world if the scene has no lights).

Context renders (features inside or on an existing model):
    context=  objects/collections drawn around the targets but not used for framing
              (the host). ghost=True draws them as a faint see-through layer under the
              targets, so internal channels and cavities stay visible.
    focus=    "target" (default), "all", a (lo, hi) box, or object names: what to frame.
    section=  ("y", 0.0) removes everything with world y < 0 (the front half, for the
              FRONT view); ("-x", 0.1) removes x > 0.1. Answers "is it really hollow?".
    min_line_px  thicken thin tubes for display only (curves and tube_mesh objects).
    color_by  "object" (random per object), "material", or "role" (custom prop "role"
              on each object: channel, cut, part, magnet, keepout, ballast, ...).
    views=    names from VIEWS, or your own (name, azimuth, elevation, ortho) tuples for
              close-ups; combine with focus=(lo, hi) on the changed area.

Runs inside Blender:

    import render_views
    sheet = render_views.run(out_dir, mode="clay", res=512)
    sheet = render_views.run(out, collection="WIRING", context=["Body"], color_by="role",
                             min_line_px=3, sheet_name="wiring_context.png")

Everything it changes (camera, engine, resolution, visibility, colours, world,
temporary modifiers) is put back afterwards, so it is safe on a live scene. For
showing the user's own viewport instead, see live_view().
"""

import math
import os
import zlib

import bpy
import numpy as np
from mathutils import Quaternion, Vector

import check_geometry
import modelkit

VIEWS = [
    # name, azimuth deg (0 = front, 90 = right), elevation deg, orthographic
    ("front", 0, 0, True),
    ("right", 90, 0, True),
    ("back", 180, 0, True),
    ("top", 0, 90, True),
    ("three_quarter_left", -35, 22, False),
    ("three_quarter_right", 35, 22, False),
    ("three_quarter_back", 150, 28, False),
    ("low_hero", 20, 6, False),
]
COLS = 4
BG = (0.32, 0.32, 0.34)
GHOST_COLOR = (0.85, 0.85, 0.88)
ROLE_COLORS = {
    "channel": (1.0, 0.45, 0.05), "power": (0.9, 0.08, 0.06), "cut": (0.2, 0.55, 1.0),
    "cavity": (0.2, 0.55, 1.0), "split": (0.2, 0.85, 0.45), "part": (0.95, 0.95, 0.95),
    "magnet": (0.55, 0.55, 0.62), "keepout": (0.85, 0.2, 0.85), "ballast": (0.55, 0.38, 0.2),
    "add": (1.0, 0.85, 0.15), "light": (1.0, 1.0, 0.4), "host": GHOST_COLOR,
}


def _role_color(role):
    if role in ROLE_COLORS:
        return ROLE_COLORS[role]
    h = zlib.crc32(role.encode()) & 0xFFFFFF
    return tuple(0.25 + 0.7 * ((h >> s) & 0xFF) / 255 for s in (16, 8, 0))


def _bounds(objs):
    """World (lo, hi, corners) from evaluated vertices (curve bound_box is padded ~1 m)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        pts += modelkit.object_corners(o, depsgraph)
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    return lo, hi, pts


def _resolve(spec):
    """Objects from a collection name, object names, or a mix (None -> [])."""
    if not spec:
        return []
    items = [spec] if isinstance(spec, (str, bpy.types.Object)) else list(spec)
    out = []
    for it in items:
        if isinstance(it, bpy.types.Object):
            out.append(it)
        elif it in bpy.data.collections:
            out += list(bpy.data.collections[it].all_objects)
        elif it in bpy.data.objects:
            out.append(bpy.data.objects[it])
    seen = set()
    return [o for o in out if o.type in check_geometry.GEOM_TYPES and not (o.name in seen or seen.add(o.name))]


def _is_box(v):
    try:
        return len(v) == 2 and all(len(c) == 3 and not isinstance(c, str) for c in v)
    except TypeError:
        return False


def _eevee_id():
    for ident in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            bpy.context.scene.render.engine = ident
            return ident
        except TypeError:
            continue
    raise RuntimeError("No EEVEE engine found")


def _direction(az, el):
    a, e = math.radians(az), math.radians(el)
    return Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))


def _place_camera(cam, center, radius, corners, az, el, ortho):
    direction = _direction(az, el)
    top = el >= 89.9
    if top:
        direction = Vector((0, 0, 1))
    cd = cam.data
    cd.sensor_fit = "AUTO"
    if ortho:
        cd.type = "ORTHO"
        dist = radius * 3
    else:
        cd.type = "PERSP"
        cd.lens = 50
        half_fov = math.atan(cd.sensor_width / 2 / cd.lens)
        dist = radius / math.sin(half_fov) * 1.08
    cam.location = center + direction * dist
    # Top view: identity rotation looks down -Z with +Y up, like Blender's numpad 7.
    rot = Quaternion() if top else (-direction).to_track_quat("-Z", "Y")
    cam.rotation_euler = rot.to_euler()
    cd.clip_start = max(1e-4, dist - radius * 2) if ortho else max(1e-4, dist * 0.01)
    cd.clip_end = dist + radius * 4
    if ortho:
        # Frame the projected bounding box tightly in the view plane.
        right = rot @ Vector((1, 0, 0))
        up = rot @ Vector((0, 1, 0))
        xs = [(p - center).dot(right) for p in corners]
        ys = [(p - center).dot(up) for p in corners]
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        cam.location = cam.location + right * cx + up * cy
        cd.ortho_scale = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.12


def _temp_lights(center, radius):
    made = []
    for name, az, el, energy, size in (("key", -45, 40, 250, 1.0), ("fill", 60, 15, 80, 1.5),
                                       ("rim", 170, 50, 160, 0.8)):
        ld = bpy.data.lights.new(f"_review_{name}", "AREA")
        ld.energy = energy * radius * radius
        ld.size = size * radius
        lo = bpy.data.objects.new(f"_review_{name}", ld)
        bpy.context.scene.collection.objects.link(lo)
        d = _direction(az, el)
        lo.location = center + d * radius * 4
        lo.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        made.append(lo)
    return made


def _load_rgba(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def _composite(target_png, ghost_png=None, ghost_alpha=0.25):
    """Background, then the ghost layer at ghost_alpha, then the targets on top."""
    t = _load_rgba(target_png)
    out = np.empty(t.shape[:2] + (3,), dtype=np.float32)
    out[:] = BG
    if ghost_png:
        g = _load_rgba(ghost_png)
        a = g[..., 3:4] * ghost_alpha
        out = out * (1 - a) + g[..., :3] * a
    a = t[..., 3:4]
    return out * (1 - a) + t[..., :3] * a


def _save_rgb(arr, path):
    H, W = arr.shape[:2]
    rgba = np.concatenate([arr, np.ones((H, W, 1), dtype=np.float32)], axis=2)
    img = bpy.data.images.new("_review_img", W, H, alpha=False)
    img.pixels.foreach_set(rgba.astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def _write_sheet(tiles, res, out_path):
    cols = min(COLS, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    pad = 4
    W, H = cols * res + (cols + 1) * pad, rows * res + (rows + 1) * pad
    sheet = np.full((H, W, 3), 0.12, dtype=np.float32)
    for k, tile in enumerate(tiles):
        r, c = divmod(k, cols)
        y0 = H - (r + 1) * (res + pad)  # pixel rows are stored bottom-up
        x0 = pad + c * (res + pad)
        sheet[y0:y0 + res, x0:x0 + res] = tile
    _save_rgb(sheet, out_path)


# ---------------------------------------------------------------- section cut

def _section_group(normal, offset):
    """Node group deleting points with dot(position, normal) < offset (object space).
    Constants live in the nodes: modifier input ID-props changed in Blender 5."""
    ng = bpy.data.node_groups.new("_review_section", "GeometryNodeTree")
    it = ng.interface
    it.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    it.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    pos = n.new("GeometryNodeInputPosition")
    dot = n.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    cmp = n.new("FunctionNodeCompare")
    cmp.data_type = "FLOAT"
    cmp.operation = "LESS_THAN"
    dele = n.new("GeometryNodeDeleteGeometry")
    dele.domain = "POINT"
    dot.inputs[1].default_value = normal
    cmp.inputs[1].default_value = offset
    L = ng.links
    L.new(pos.outputs["Position"], dot.inputs[0])
    L.new(dot.outputs["Value"], cmp.inputs[0])
    L.new(gi.outputs["Geometry"], dele.inputs["Geometry"])
    L.new(cmp.outputs["Result"], dele.inputs["Selection"])
    L.new(dele.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def _add_section(objs, section):
    """Temporary GN modifier on each object deleting the geometry on the removed side."""
    axis, offset = section[0], float(section[1])
    sign = -1.0 if axis.startswith("-") else 1.0
    nw = Vector((0.0, 0.0, 0.0))
    nw["xyz".index(axis[-1].lower())] = sign
    off = offset * sign
    made = []
    for o in objs:
        try:
            m = o.modifiers.new("_review_section", "NODES")
        except (RuntimeError, TypeError):
            continue
        if m is None:
            continue
        A = o.matrix_world.to_3x3()
        t = o.matrix_world.translation
        m.node_group = _section_group(tuple(A.transposed() @ nw), off - nw.dot(t))
        made.append((o, m))
    return made


# ---------------------------------------------------------------- main entry

def run(out_dir, mode="clay", res=512, collection=None, names=None, views=None,
        samples=32, sheet_name=None, context=None, ghost=True, ghost_alpha=0.25,
        focus="target", section=None, min_line_px=0, color_by="object"):
    scene = bpy.context.scene
    r = scene.render
    os.makedirs(out_dir, exist_ok=True)
    objs = check_geometry.target_objects(collection, names)
    if not objs:
        raise RuntimeError("Nothing to render: no visible geometry objects.")
    targets = {o.name for o in objs}
    ctx = [o for o in _resolve(context) if o.name not in targets]
    if focus == "all":
        lo, hi, corners = _bounds(objs + ctx)
    elif _is_box(focus):
        lo, hi = Vector(focus[0]), Vector(focus[1])
        corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    elif focus not in (None, "target"):
        lo, hi, corners = _bounds(_resolve(focus) or objs)
    else:
        lo, hi, corners = _bounds(objs)
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-4)
    shown = targets | {o.name for o in ctx}
    two_pass = bool(ctx) and ghost

    saved = {
        "camera": scene.camera, "engine": r.engine, "rx": r.resolution_x, "ry": r.resolution_y,
        "pct": r.resolution_percentage, "path": r.filepath, "transp": r.film_transparent,
        "fmt": r.image_settings.file_format, "cmode": r.image_settings.color_mode,
        "world": scene.world,
    }
    shading = scene.display.shading
    saved_shading = {k: getattr(shading, k) for k in (
        "light", "color_type", "single_color", "show_cavity", "show_object_outline", "show_shadows")}
    hidden, shown_tmp, temp, mods, colors, bevels = [], [], [], [], [], []
    try:
        for o in scene.objects:
            if o.type in check_geometry.GEOM_TYPES and o.name not in shown and not o.hide_render:
                o.hide_render = True
                hidden.append(o)
        for o in ctx:
            if o.hide_render:
                o.hide_render = False
                shown_tmp.append(o)
        cam_data = bpy.data.cameras.new("_review_cam")
        cam = bpy.data.objects.new("_review_cam", cam_data)
        scene.collection.objects.link(cam)
        temp.append(cam)
        scene.camera = cam

        r.resolution_x = r.resolution_y = res
        r.resolution_percentage = 100
        r.film_transparent = True
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"

        if section:
            mods += _add_section(objs + ctx, section)
        if min_line_px:
            want = min_line_px * (2 * radius * 1.12 / res) / 2      # radius for min_line_px on screen
            for o in objs:
                sc = sum(o.matrix_world.to_scale()) / 3
                if o.type == "CURVE" and 0 < o.data.bevel_depth * sc < want:
                    bevels.append((o.data, o.data.bevel_depth))
                    o.data.bevel_depth = want / sc
                elif o.type == "MESH" and "dia" in o and o["dia"] / 2 < want:
                    m = o.modifiers.new("_review_thicken", "DISPLACE")
                    m.direction = "NORMAL"
                    m.mid_level = 0.0
                    m.strength = (want - o["dia"] / 2) / sc
                    mods.append((o, m))
        roles = {}
        if color_by == "role":
            for o in objs + ctx:
                colors.append((o, tuple(o.color)))
                role = str(o.get("role", "host" if o in ctx else "part"))
                roles[role] = _role_color(role)
                o.color = (*roles[role], 1.0)

        if mode == "clay":
            r.engine = "BLENDER_WORKBENCH"
            shading.light = "STUDIO"
            shading.color_type = {"object": "RANDOM", "material": "MATERIAL", "role": "OBJECT"}[color_by]
            shading.show_cavity = True
            shading.cavity_type = "BOTH"
            shading.show_object_outline = True
            shading.show_shadows = False
            scene.display.render_aa = "8"
        elif mode == "shaded":
            _eevee_id()
            try:
                scene.eevee.taa_render_samples = samples
            except AttributeError:
                pass
            has_lights = any(o.type == "LIGHT" and not o.hide_render for o in scene.objects)
            if not has_lights:
                temp += _temp_lights(center, radius)
            if scene.world is None or not has_lights:
                w = bpy.data.worlds.new("_review_world")
                w.use_nodes = True
                bgn = w.node_tree.nodes.get("Background")
                if bgn:
                    bgn.inputs["Color"].default_value = (0.4, 0.4, 0.42, 1)
                    bgn.inputs["Strength"].default_value = 0.6
                scene.world = w
        else:
            raise ValueError("mode must be 'clay' or 'shaded'")

        view_list = []
        for v in (views or [v[0] for v in VIEWS]):
            if isinstance(v, str):
                view_list += [x for x in VIEWS if x[0] == v]
            else:
                view_list.append(tuple(v))
        tiles = []
        for name, az, el, ortho in view_list:
            _place_camera(cam, center, radius, corners, az, el, ortho)
            p = os.path.join(out_dir, f"{mode}_{name}.png")
            gp = None
            if two_pass:
                # pass 1: the context alone (single light colour); pass 2: the targets alone
                for o in objs:
                    o.hide_render = True
                if mode == "clay":
                    ct = shading.color_type
                    shading.color_type = "SINGLE"
                    shading.single_color = GHOST_COLOR
                gp = os.path.join(out_dir, f"{mode}_{name}_context.png")
                r.filepath = gp
                bpy.ops.render.render(write_still=True)
                if mode == "clay":
                    shading.color_type = ct
                for o in objs:
                    o.hide_render = False
                for o in ctx:
                    o.hide_render = True
            r.filepath = p
            bpy.ops.render.render(write_still=True)
            if two_pass:
                for o in ctx:
                    o.hide_render = False
            tiles.append(_composite(p, gp, ghost_alpha))

        sheet = os.path.join(out_dir, sheet_name or f"{mode}_sheet.png")
        _write_sheet(tiles, res, sheet)
        if roles:
            print("ROLES: " + ", ".join(f"{k}=({', '.join(f'{c:.2f}' for c in v)})" for k, v in sorted(roles.items())))
        print(f"RENDER: {len(tiles)} views -> {sheet}")
        return sheet
    finally:
        scene.camera = saved["camera"]
        r.engine = saved["engine"]
        r.resolution_x, r.resolution_y = saved["rx"], saved["ry"]
        r.resolution_percentage = saved["pct"]
        r.filepath = saved["path"]
        r.film_transparent = saved["transp"]
        r.image_settings.file_format = saved["fmt"]
        r.image_settings.color_mode = saved["cmode"]
        for k, v in saved_shading.items():
            setattr(shading, k, v)
        tmp_world = scene.world if scene.world is not saved["world"] else None
        scene.world = saved["world"]
        if tmp_world:
            bpy.data.worlds.remove(tmp_world)
        for o in hidden:
            o.hide_render = False
        for o in shown_tmp:
            o.hide_render = True
        for o, m in mods:
            ng = m.node_group if m.type == "NODES" else None
            o.modifiers.remove(m)
            if ng is not None and ng.users == 0:
                bpy.data.node_groups.remove(ng)
        for cd, b in bevels:
            cd.bevel_depth = b
        for o, c in colors:
            o.color = c
        for o in temp:
            data = o.data
            bpy.data.objects.remove(o)
            if isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)


# ---------------------------------------------------------------- live viewport

def live_view(az=-35, el=22, focus=None, xray=0.2, ortho=False, color_by=None, lens=None):
    """Point the user's 3D viewport(s) at the focus objects (live MCP sessions).

    focus: collection name, object names or a (lo, hi) box (default: all visible
    geometry). xray: 0 for solid, else the X-ray alpha (0.15-0.3 shows internal
    channels through a host). color_by: None (keep), "object", "material", or "role"
    (sets the object colour of objects that have a "role" prop, i.e. generated ones).
    No bpy.ops and no rendering: take the screenshot with your viewport-screenshot
    tool afterwards (retry once if it comes back black right after heavy work).
    Returns {"areas", "center", "previous"}; restore_view() undoes it (the previous
    state is also kept in bpy.app.driver_namespace, so a later MCP call can restore).
    """
    if _is_box(focus):
        lo, hi = Vector(focus[0]), Vector(focus[1])
    else:
        objs = _resolve(focus) if focus else check_geometry.target_objects()
        lo, hi, _ = _bounds(objs)
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-4)
    rot = Quaternion() if el >= 89.9 else (-_direction(az, el)).to_track_quat("-Z", "Y")
    if color_by == "role":
        for o in bpy.context.scene.objects:
            if "role" in o:
                o.color = (*_role_color(str(o["role"])), 1.0)
    previous = []
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            sp = area.spaces.active
            r3d = sp.region_3d
            sh = sp.shading
            previous.append({"area": area.as_pointer(), "location": tuple(r3d.view_location),
                             "rotation": tuple(r3d.view_rotation), "distance": r3d.view_distance,
                             "perspective": r3d.view_perspective, "type": sh.type, "xray": sh.show_xray,
                             "xray_alpha": sh.xray_alpha, "color_type": sh.color_type})
            if lens:
                sp.lens = lens
            r3d.view_location = center
            r3d.view_rotation = rot
            r3d.view_distance = radius / math.sin(math.atan(36 / 2 / sp.lens)) * 1.15
            r3d.view_perspective = "ORTHO" if ortho else "PERSP"
            sh.type = "SOLID"
            sh.show_xray = xray > 0
            if xray > 0:
                sh.xray_alpha = xray
            if color_by:
                sh.color_type = {"object": "RANDOM", "material": "MATERIAL", "role": "OBJECT"}[color_by]
            area.tag_redraw()
    bpy.app.driver_namespace.setdefault("render_views_previous", previous)
    return {"areas": len(previous), "center": tuple(round(c, 5) for c in center), "previous": previous}


def restore_view(previous=None):
    """Undo live_view(): pass its result's "previous" list, or nothing to restore the
    state from before the first live_view() call."""
    if previous is None:
        previous = bpy.app.driver_namespace.pop("render_views_previous", [])
    by_ptr = {p["area"]: p for p in previous}
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            p = by_ptr.get(area.as_pointer())
            if not p:
                continue
            sp = area.spaces.active
            r3d = sp.region_3d
            r3d.view_location = p["location"]
            r3d.view_rotation = p["rotation"]
            r3d.view_distance = p["distance"]
            r3d.view_perspective = p["perspective"]
            sp.shading.type = p["type"]
            sp.shading.show_xray = p["xray"]
            sp.shading.xray_alpha = p["xray_alpha"]
            sp.shading.color_type = p["color_type"]
            area.tag_redraw()
