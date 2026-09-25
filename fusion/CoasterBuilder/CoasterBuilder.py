"""CoasterBuilder: turns coaster_gen.py DXF files into 3D maze coasters.

Pick one or more DXFs. For each, the OUTLINE loop is extruded to base + wall
height, then the CHANNELS loops are cut down to the base, leaving the maze
walls standing on a solid floor. Coasters are laid out in a row along X, each
in its own component when the design allows it (Part designs only have one).

The DXF is read here and drawn with the sketch API rather than imported, so
the geometry always lands in millimetres whatever the design's units are.
"""
import math
import os
import time
import traceback

import adsk.core
import adsk.fusion

DEFAULT_HEIGHTS = "2, 2"  # base thickness, wall height in mm
SPACING = 10.0            # mm between coasters
MIN_SAGITTA = 1e-3        # mm; flatter arcs are drawn as lines (Fusion rejects near-straight arcs)


def read_dxf_loops(path):
    """Return {LAYER: [loop, ...]} in mm. A loop is [(x, y, bulge), ...] or ("circle", cx, cy, r).

    Reads the LWPOLYLINE and CIRCLE entities that coaster_gen.py writes.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [ln.strip() for ln in f]
    pairs = list(zip(lines[0::2], lines[1::2]))
    layers = {}
    in_entities = False
    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        i += 1
        if code == "2" and value == "ENTITIES":
            in_entities = True
        elif code == "0" and value == "ENDSEC":
            in_entities = False
        elif in_entities and code == "0" and value in ("LWPOLYLINE", "CIRCLE"):
            layer, verts, circle = "0", [], {}
            while i < len(pairs) and pairs[i][0] != "0":
                c, v = pairs[i]
                i += 1
                if c == "8":
                    layer = v.upper()
                elif value == "CIRCLE" and c in ("10", "20", "40"):
                    circle[c] = float(v)
                elif c == "10":
                    verts.append([float(v), 0.0, 0.0])
                elif c == "20" and verts:
                    verts[-1][1] = float(v)
                elif c == "42" and verts:
                    verts[-1][2] = float(v)
            if value == "CIRCLE":
                loop = ("circle", circle["10"], circle["20"], circle["40"])
            else:
                loop = [tuple(v) for v in verts]
            layers.setdefault(layer, []).append(loop)
    return layers


def pt(x, y):
    return adsk.core.Point3D.create(x / 10, y / 10, 0)  # mm -> cm (Fusion's internal unit)


def arc_point(x0, y0, x1, y1, b, t=0.5):
    """Point a fraction t along the arc from (x0, y0) to (x1, y1) with DXF bulge b."""
    sweep = 4 * math.atan(b)
    dx, dy = x1 - x0, y1 - y0
    chord = math.hypot(dx, dy)
    r = chord / (2 * math.sin(sweep / 2))
    h = r * math.cos(sweep / 2)
    cx = (x0 + x1) / 2 - dy / chord * h
    cy = (y0 + y1) / 2 + dx / chord * h
    a = math.atan2(y0 - cy, x0 - cx) + sweep * t
    return cx + abs(r) * math.cos(a), cy + abs(r) * math.sin(a)


def shifted(loop, dx):
    if loop[0] == "circle":
        return ("circle", loop[1] + dx, loop[2], loop[3])
    return [(x + dx, y, b) for x, y, b in loop]


def x_range(loop):
    """Smallest and largest x of a loop in mm (arcs sampled)."""
    if loop[0] == "circle":
        return loop[1] - loop[3], loop[1] + loop[3]
    xs = []
    for i, (x0, y0, b) in enumerate(loop):
        xs.append(x0)
        if b:
            x1, y1, _ = loop[(i + 1) % len(loop)]
            xs += [arc_point(x0, y0, x1, y1, b, t / 16)[0] for t in range(1, 16)]
    return min(xs), max(xs)


def point_at(curve, x, y):
    """The end of curve that sits at (x, y) mm; arcs are always stored counter-clockwise."""
    g = curve.startSketchPoint.geometry
    if (g.x - x / 10) ** 2 + (g.y - y / 10) ** 2 < 1e-10:
        return curve.startSketchPoint
    return curve.endSketchPoint


def draw_loop(sketch, loop):
    curves = sketch.sketchCurves
    if loop[0] == "circle":
        _, cx, cy, r = loop
        curves.sketchCircles.addByCenterRadius(pt(cx, cy), r / 10)
        return
    n = len(loop)
    first = prev = None
    for i in range(n):
        x0, y0, b = loop[i]
        x1, y1, _ = loop[(i + 1) % n]
        start = prev or pt(x0, y0)
        end = first if i == n - 1 else pt(x1, y1)
        curve = None
        if abs(b) * math.hypot(x1 - x0, y1 - y0) / 2 >= MIN_SAGITTA:
            try:
                curve = curves.sketchArcs.addByThreePoints(start, pt(*arc_point(x0, y0, x1, y1, b)), end)
            except RuntimeError:
                curve = None  # too flat for Fusion; a line is within microns of it
        if curve is None:
            curve = curves.sketchLines.addByTwoPoints(start, end)
        if first is None:
            first = point_at(curve, x0, y0)
        prev = point_at(curve, x1, y1)


def sketch_from_loops(comp, name, loops):
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = name
    sketch.isComputeDeferred = True
    for loop in loops:
        draw_loop(sketch, loop)
    sketch.isComputeDeferred = False
    return sketch


def distance(mm):
    return adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByReal(mm / 10))


def target_component(root, name):
    """A new component for this coaster, or the root when the design is a Part (one component only)."""
    try:
        comp = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    except RuntimeError:
        return root
    comp.name = name
    return comp


def build_coaster(root, name, layers, base, wall, dx):
    """One coaster, shifted dx mm along X."""
    comp = target_component(root, name)
    outline = sketch_from_loops(comp, f"{name} OUTLINE", [shifted(lp, dx) for lp in layers["OUTLINE"]])
    channels = sketch_from_loops(comp, f"{name} CHANNELS", [shifted(lp, dx) for lp in layers["CHANNELS"]])
    extrudes = comp.features.extrudeFeatures
    ops = adsk.fusion.FeatureOperations
    up = adsk.fusion.ExtentDirections.PositiveExtentDirection

    profile = max(outline.profiles, key=lambda p: p.areaProperties().area)
    body_input = extrudes.createInput(profile, ops.NewBodyFeatureOperation)
    body_input.setOneSideExtent(distance(base + wall), up)
    body = extrudes.add(body_input).bodies.item(0)
    body.name = name

    cut_profiles = adsk.core.ObjectCollection.create()
    for p in channels.profiles:
        cut_profiles.add(p)
    cut_input = extrudes.createInput(cut_profiles, ops.CutFeatureOperation)
    cut_input.startExtent = adsk.fusion.OffsetStartDefinition.create(adsk.core.ValueInput.createByReal(base / 10))
    cut_input.setOneSideExtent(distance(wall + 0.1), up)
    cut_input.participantBodies = [body]
    extrudes.add(cut_input)


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox("Open a design in the Design workspace first.")
            return

        dialog = ui.createFileDialog()
        dialog.title = "Choose coaster DXF files"
        dialog.filter = "DXF files (*.dxf)"
        dialog.isMultiSelectEnabled = True
        if dialog.showOpen() != adsk.core.DialogResults.DialogOK:
            return

        text, cancelled = ui.inputBox("Base thickness, wall height (mm):", "Coaster heights", DEFAULT_HEIGHTS)
        if cancelled:
            return
        try:
            base, wall = [float(v) for v in text.replace(";", ",").split(",")]
            assert base > 0 and wall > 0
        except (ValueError, AssertionError):
            ui.messageBox(f'Expected two positive numbers like "{DEFAULT_HEIGHTS}", got "{text}".')
            return

        root = design.rootComponent
        cursor, built, started = None, [], time.time()  # cursor: x (mm) where the next coaster may start
        for path in dialog.filenames:
            name = os.path.splitext(os.path.basename(path))[0]
            layers = read_dxf_loops(path)
            missing = [layer for layer in ("OUTLINE", "CHANNELS") if layer not in layers]
            if missing:
                ui.messageBox(f"{name}: skipped, no {' or '.join(missing)} layer in the DXF.")
                continue
            lo, hi = x_range(layers["OUTLINE"][0])
            dx = 0.0 if cursor is None else cursor - lo
            build_coaster(root, name, layers, base, wall, dx)
            cursor = dx + hi + SPACING
            built.append(name)
            adsk.doEvents()

        if built:
            ui.messageBox(f"Built {len(built)} coaster(s) in {time.time() - started:.0f} s:\n" + "\n".join(built))
    except Exception:
        if ui:
            ui.messageBox("CoasterBuilder failed:\n" + traceback.format_exc())
