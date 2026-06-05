"""Shelf Creator — build a parametric shelf panel bounded by four faces.

The user:
  1. Picks the face (or construction plane) the shelf sketch sits on — this is
     the shelf's plane.
  2. Picks four bounding faces (the surrounding walls) and gives each an offset.
  3. Sets the shelf thickness.

Each shelf edge is created by intersecting a wall face with the sketch plane
(`Sketch.intersectWithSketchPlane`) and offsetting that line inward by the wall's
offset. Because the intersection lines are associative to the walls, the shelf
tracks the surrounding panels when their parameters change. The four edges bound
a profile that is extruded by the thickness into its own component.
"""

import math
import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_shelf'
CMD_NAME = 'Shelf Creator'
CMD_Description = (
    'Create a shelf panel on a picked plane, bounded by four faces each with '
    'its own offset, extruded by a set thickness.'
)
IS_PROMOTED = True

PANEL_ID = config.DRESSUP_PANEL_ID
PANEL_NAME = config.DRESSUP_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SKETCH_FACE_ID = 'shelf_sketch_face'
WALLS_ID = 'shelf_walls'
THICKNESS_ID = 'shelf_thickness'
OFFSET_IDS = ['shelf_offset_1', 'shelf_offset_2', 'shelf_offset_3', 'shelf_offset_4']

DEFAULT_THICKNESS_CM = 1.8
DEFAULT_OFFSET_CM = 0.0

local_handlers = []
_graphics_group = None


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')

    global _graphics_group
    _graphics_group = None

    inputs = args.command.commandInputs
    length_units = app.activeProduct.unitsManager.defaultLengthUnits

    sketch_input = inputs.addSelectionInput(
        SKETCH_FACE_ID, 'Shelf plane', 'Pick the face or plane the shelf sits on')
    sketch_input.addSelectionFilter('PlanarFaces')
    sketch_input.addSelectionFilter('ConstructionPlanes')
    sketch_input.setSelectionLimits(1, 1)

    walls_input = inputs.addSelectionInput(
        WALLS_ID, 'Bounding faces', 'Pick the four faces that surround the shelf')
    walls_input.addSelectionFilter('PlanarFaces')
    walls_input.setSelectionLimits(4, 4)

    for i, oid in enumerate(OFFSET_IDS):
        off = inputs.addValueInput(
            oid, f'Offset {i + 1}', length_units,
            adsk.core.ValueInput.createByReal(DEFAULT_OFFSET_CM))
        off.tooltip = (
            f'Gap between the shelf and bounding face #{i + 1} (numbered in the '
            f'graphics). Positive insets the shelf away from that face.')

    inputs.addValueInput(
        THICKNESS_ID, 'Thickness', length_units,
        adsk.core.ValueInput.createByReal(DEFAULT_THICKNESS_CM))

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.executePreview, command_preview, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Preview: number the bounding faces so offsets are easy to map.
# ---------------------------------------------------------------------------
def command_preview(args: adsk.core.CommandEventArgs):
    global _graphics_group
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        inputs = args.command.commandInputs

        if _graphics_group:
            try:
                _graphics_group.deleteMe()
            except Exception:
                pass
            _graphics_group = None

        walls_input: adsk.core.SelectionCommandInput = inputs.itemById(WALLS_ID)
        if walls_input.selectionCount == 0:
            app.activeViewport.refresh()
            return

        group = root.customGraphicsGroups.add()
        color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(80, 200, 255, 255))
        for i in range(walls_input.selectionCount):
            face = walls_input.selection(i).entity
            try:
                base = face.centroid
            except Exception:
                base = face.pointOnFace

            # Float the label off the face along its normal so the opaque wall
            # doesn't hide it (same idea as Carcass Maker's labels).
            try:
                _, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
                normal.normalize()
                normal.scaleBy(1.0)
                label_pt = base.copy()
                label_pt.translateBy(normal)
            except Exception:
                label_pt = base

            transform = adsk.core.Matrix3D.create()
            transform.translation = label_pt.asVector()
            text = group.addText(str(i + 1), 'Arial', 2.0, transform)
            text.billBoarding = adsk.fusion.CustomGraphicsBillBoard.create(label_pt)
            text.color = color
        _graphics_group = group
        app.activeViewport.refresh()
    except Exception:
        futil.handle_error('Shelf: preview')


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs

    sketch_ref = inputs.itemById(SKETCH_FACE_ID).selection(0).entity
    walls_input: adsk.core.SelectionCommandInput = inputs.itemById(WALLS_ID)
    walls = [walls_input.selection(i).entity for i in range(walls_input.selectionCount)]
    offsets = [inputs.itemById(oid).value for oid in OFFSET_IDS]
    thickness = inputs.itemById(THICKNESS_ID).value

    try:
        _build_shelf(sketch_ref, walls, offsets, thickness)
    except Exception:
        futil.handle_error('Shelf: build failed', show_message_box=True)


def _build_shelf(sketch_ref, walls, offsets, thickness):
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    shelf_comp = occ.component
    shelf_comp.name = 'Shelf'
    ui_helpers.tag_as_panel(shelf_comp)

    sketch = shelf_comp.sketches.add(sketch_ref)

    # One edge per wall: the line where the wall meets the shelf plane.
    raw_lines = []
    for wall in walls:
        line = _intersection_line(sketch, wall)
        if line is None:
            raise RuntimeError('A bounding face does not cross the shelf plane.')
        line.isConstruction = True
        raw_lines.append(line)

    # Interior point (world) to offset the edges toward.
    centroid = _centroid_world(raw_lines)

    boundary = []
    for line, offset in zip(raw_lines, offsets):
        if abs(offset) < 1e-9:
            boundary.append(line)               # the wall-intersection line itself
            continue
        mid = _line_midpoint_world(line)
        if offset >= 0:
            direction_point = centroid          # inset toward the middle
        else:
            direction_point = adsk.core.Point3D.create(  # push away from the middle
                mid.x + (mid.x - centroid.x),
                mid.y + (mid.y - centroid.y),
                mid.z + (mid.z - centroid.z))
        coll = adsk.core.ObjectCollection.create()
        coll.add(line)
        offset_curves = list(_iter_vector(sketch.offset(coll, direction_point, abs(offset))))
        if not offset_curves:
            raise RuntimeError('Offsetting a bounding edge produced no curve.')
        boundary.append(offset_curves[0])

    # Build an explicit rectangle from the four edges' corner intersections so
    # that *any* offsets (positive, negative or uneven) still close into a clean
    # profile. Collinear constraints keep each rectangle edge on its associative
    # boundary line, so the shelf stays parametric.
    if _draw_bounded_rectangle(sketch, boundary) is None:
        raise RuntimeError('The four bounding faces must form two parallel pairs.')

    profile = _largest_profile(sketch)
    if profile is None:
        raise RuntimeError('Could not form the shelf outline from the bounding faces.')

    # Extrude toward the picked face's outward side.
    sketch_normal = sketch.xDirection.crossProduct(sketch.yDirection)
    sketch_normal.normalize()
    sign = 1.0
    if sketch_ref.objectType == adsk.fusion.BRepFace.classType():
        _, face_normal = sketch_ref.evaluator.getNormalAtPoint(sketch_ref.pointOnFace)
        sign = 1.0 if sketch_normal.dotProduct(face_normal) > 0 else -1.0

    extrudes = shelf_comp.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(sign * thickness))
    extrudes.add(ext_input)


def _intersection_line(sketch: adsk.fusion.Sketch, face):
    """The sketch line where `face` crosses the sketch plane (associative)."""
    created = sketch.intersectWithSketchPlane([face])
    for curve in _iter_vector(created):
        if curve.objectType == adsk.fusion.SketchLine.classType():
            return curve
    return None


def _iter_vector(vec):
    """Yield items from a Fusion return type whose count attribute varies
    (ObjectCollection uses .count, SketchEntityVector uses .length, some are
    directly iterable)."""
    count = None
    for attr in ('count', 'length'):
        if hasattr(vec, attr):
            count = getattr(vec, attr)
            break
    if count is not None:
        for i in range(count):
            yield vec.item(i)
        return
    for item in vec:  # already a Python-iterable type
        yield item


def _line_midpoint_world(line: adsk.fusion.SketchLine) -> adsk.core.Point3D:
    a = line.startSketchPoint.worldGeometry
    b = line.endSketchPoint.worldGeometry
    return adsk.core.Point3D.create((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)


def _centroid_world(lines) -> adsk.core.Point3D:
    mids = [_line_midpoint_world(line) for line in lines]
    n = len(mids)
    return adsk.core.Point3D.create(
        sum(m.x for m in mids) / n,
        sum(m.y for m in mids) / n,
        sum(m.z for m in mids) / n)


def _draw_bounded_rectangle(sketch: adsk.fusion.Sketch, boundary):
    """Turn the four (associative) boundary edges into a closed rectangle by
    intersecting their corners, then constrain each rectangle side collinear to
    its boundary edge so the result stays parametric. Returns the edges, or None
    if the four edges aren't two parallel pairs."""
    for edge in boundary:
        edge.isConstruction = True

    geoms = [_line_xy(edge) for edge in boundary]

    # Pair edge 0 with whichever other edge is parallel to it.
    pair_j = next((j for j in (1, 2, 3) if _parallel_xy(geoms[0], geoms[j])), None)
    if pair_j is None:
        return None
    a = [0, pair_j]
    b = [k for k in (1, 2, 3) if k != pair_j]

    # Corners walk the rectangle: A0∩B0 → A0∩B1 → A1∩B1 → A1∩B0. Each resulting
    # edge therefore lies on a known boundary line (for the collinear constraint).
    order = [(a[0], b[0]), (a[0], b[1]), (a[1], b[1]), (a[1], b[0])]
    edge_line = [a[0], b[1], a[1], b[0]]

    corners = []
    for ai, bi in order:
        pt = _intersect_xy(geoms[ai], geoms[bi])
        if pt is None:
            return None
        corners.append(pt)

    lines = sketch.sketchCurves.sketchLines
    p = [adsk.core.Point3D.create(c[0], c[1], 0) for c in corners]
    e0 = lines.addByTwoPoints(p[0], p[1])
    e1 = lines.addByTwoPoints(e0.endSketchPoint, p[2])      # share points so the
    e2 = lines.addByTwoPoints(e1.endSketchPoint, p[3])      # loop is actually
    e3 = lines.addByTwoPoints(e2.endSketchPoint, e0.startSketchPoint)  # closed
    edges = [e0, e1, e2, e3]

    for k in range(4):
        try:
            sketch.geometricConstraints.addCollinear(edges[k], boundary[edge_line[k]])
        except Exception:
            pass  # keep the geometry even if a constraint can't be added
    return edges


def _line_xy(line: adsk.fusion.SketchLine):
    s = line.startSketchPoint.geometry
    e = line.endSketchPoint.geometry
    return (s.x, s.y, e.x, e.y)


def _parallel_xy(l1, l2) -> bool:
    d1x, d1y = l1[2] - l1[0], l1[3] - l1[1]
    d2x, d2y = l2[2] - l2[0], l2[3] - l2[1]
    return abs(d1x * d2y - d1y * d2x) < 1e-6


def _intersect_xy(l1, l2):
    x1, y1, x2, y2 = l1
    x3, y3, x4, y4 = l2
    d1x, d1y = x2 - x1, y2 - y1
    d2x, d2y = x4 - x3, y4 - y3
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-12:
        return None
    t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / denom
    return (x1 + t * d1x, y1 + t * d1y)


def _largest_profile(sketch: adsk.fusion.Sketch):
    best = None
    best_area = -1.0
    for i in range(sketch.profiles.count):
        prof = sketch.profiles.item(i)
        try:
            area = prof.areaProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy).area
        except Exception:
            area = 0.0
        if area > best_area:
            best_area = area
            best = prof
    return best


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    sketch_ok = inputs.itemById(SKETCH_FACE_ID).selectionCount == 1
    walls_ok = inputs.itemById(WALLS_ID).selectionCount == 4
    thickness_ok = inputs.itemById(THICKNESS_ID).value > 0
    args.areInputsValid = sketch_ok and walls_ok and thickness_ok


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers, _graphics_group
    if _graphics_group:
        try:
            _graphics_group.deleteMe()
        except Exception:
            pass
        _graphics_group = None
        app.activeViewport.refresh()
    local_handlers = []
