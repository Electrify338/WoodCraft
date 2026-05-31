"""Dress Up — convert selected faces of a skeleton body into panel components.

Workflow:
  1. The user selects one or more planar faces of a solid "skeleton" body
     (typically a box representing the outer shell of a piece of furniture). With
     "Collect Flat Faces Automatically" on, picking one face grabs every planar
     face of that body.
  2. They set global defaults: thickness, direction (Inside / Outside /
     Symmetric) and offset. These seed every new panel.
  3. The Advanced Control table lists one row per selected face and lets each
     panel be renamed and given its own thickness / direction / offset.
  4. On OK each panel becomes its own component containing a single body,
     extruded from its face.

Panels are intentionally left overlapping at the corners — the Trim command is
what resolves those overlaps afterwards.

State model: `_panels` is the source of truth — a list of dicts, one per panel,
each holding the BRepFace plus its name/thickness/direction/offset and the ids
of the table cell inputs currently representing it. It is kept in sync with the
face selection on every change, preserving edits by matching faces on tempId.
"""

import os
import re

import adsk.core
import adsk.fusion

from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_dressUp'
CMD_NAME = 'Carcass Maker'
CMD_Description = (
    'Convert selected faces of a solid body into individual panel components, '
    'each with its own thickness, direction and offset.'
)
IS_PROMOTED = True

PANEL_ID = config.DRESSUP_PANEL_ID
PANEL_NAME = config.DRESSUP_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# Input ids.
COLLECT_BTN_ID = 'dressup_collect'
FACES_INPUT_ID = 'dressup_faces'
THICKNESS_INPUT_ID = 'dressup_thickness'
DIRECTION_INPUT_ID = 'dressup_direction'
OFFSET_INPUT_ID = 'dressup_offset'
ADV_GROUP_ID = 'dressup_adv_group'
TABLE_ID = 'dressup_table'
DEFAULTS_BTN_ID = 'dressup_defaults'
DELETE_BTN_ID = 'dressup_delete'

DIRECTIONS = ['Inside', 'Outside', 'Symmetric']

# Defaults in Fusion internal units (centimetres). 18 mm is the most common
# sheet-good thickness in cabinetmaking.
DEFAULT_THICKNESS_CM = 1.8
DEFAULT_OFFSET_CM = 0.0
DEFAULT_DIRECTION = 'Inside'

local_handlers = []

# --- Command state (reset on every command_created) -------------------------
_panels = []            # list of {tempId, face, name, thickness, direction, offset, ids:{}}
_cell_ids = []          # ids of all table cell inputs, so they can be torn down
_uid = 0                # monotonic counter for unique cell input ids
_syncing = False        # guard against re-entrant selection changes during bursts
_graphics_group = None  # CustomGraphicsGroup holding the panel labels/arrows
_dimmed_bodies = []     # skeleton bodies whose opacity we lowered, to restore later


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

    # Fresh state for each invocation of the dialog.
    global _panels, _cell_ids, _uid, _syncing, _graphics_group, _dimmed_bodies
    _panels = []
    _cell_ids = []
    _uid = 0
    _syncing = False
    _graphics_group = None
    _dimmed_bodies = []

    inputs = args.command.commandInputs
    length_units = app.activeProduct.unitsManager.defaultLengthUnits

    faces_input = inputs.addSelectionInput(FACES_INPUT_ID, 'Face(s)', 'Select faces to convert into panels')
    faces_input.addSelectionFilter('PlanarFaces')
    faces_input.setSelectionLimits(1, 0)

    # One-shot helper: pick a face, then press this to add every other flat face
    # of the same body. Done as an explicit button (not reactive) so it never
    # fights the user clicking faces on/off.
    collect_btn = inputs.addBoolValueInput(COLLECT_BTN_ID, 'Collect all flat faces', True, '', False)
    collect_btn.tooltip = 'Add every flat face of the bodies you have already picked a face from.'

    inputs.addValueInput(
        THICKNESS_INPUT_ID, 'Thickness', length_units,
        adsk.core.ValueInput.createByReal(DEFAULT_THICKNESS_CM),
    )

    direction_input = inputs.addDropDownCommandInput(
        DIRECTION_INPUT_ID, 'Direction', adsk.core.DropDownStyles.TextListDropDownStyle)
    for d in DIRECTIONS:
        direction_input.listItems.add(d, d == DEFAULT_DIRECTION)

    offset_input = inputs.addValueInput(
        OFFSET_INPUT_ID, 'Offset', length_units,
        adsk.core.ValueInput.createByReal(DEFAULT_OFFSET_CM),
    )
    offset_input.tooltip = 'Distance the panel is shifted from the selected face along its direction.'

    # Advanced Control: per-panel override table.
    group = inputs.addGroupCommandInput(ADV_GROUP_ID, 'Advanced Control')
    group.isExpanded = True
    table = group.children.addTableCommandInput(TABLE_ID, 'Panels', 4, '3:2:2:2')
    table.minimumVisibleRows = 1
    table.maximumVisibleRows = 10

    # Action "buttons" implemented as checkbox-style inputs that reset
    # themselves after firing. (A non-checkbox BoolValueInput needs a real icon
    # folder; checkbox style works with no resources and won't break the dialog.)
    defaults_btn = group.children.addBoolValueInput(DEFAULTS_BTN_ID, 'Reset rows to defaults', True, '', False)
    defaults_btn.tooltip = 'Reset every panel row back to the global thickness, direction and offset.'
    delete_btn = group.children.addBoolValueInput(DELETE_BTN_ID, 'Delete selected row', True, '', False)
    delete_btn.tooltip = 'Select a row in the table, then check this to remove it.'

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.executePreview, command_preview, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------
def command_input_changed(args: adsk.core.InputChangedEventArgs):
    changed = args.input
    # Always work from the command's root inputs. args.inputs is only the
    # collection the changed input lives in (e.g. the group's children for the
    # Defaults/Delete checkboxes), and its itemById can't see top-level inputs.
    # The root collection's itemById searches the whole tree.
    inputs = changed.parentCommand.commandInputs

    if changed.id == FACES_INPUT_ID:
        # Plain selection: just mirror it into the panel table. No selection
        # mutation here, so native click-to-toggle works cleanly.
        if not _syncing:
            _rebuild_panels(inputs)
    elif changed.id == COLLECT_BTN_ID:
        if changed.value:
            _on_collect(inputs)
            changed.value = False
    elif changed.id == DEFAULTS_BTN_ID:
        if changed.value:
            _on_defaults(inputs)
            changed.value = False  # re-arm; fires inputChanged again, guarded above
    elif changed.id == DELETE_BTN_ID:
        if changed.value:
            _on_delete(inputs)
            changed.value = False
    # Renames / per-row direction changes are reflected by executePreview, which
    # re-snapshots the cells and redraws the labels — nothing to do here.


def _on_collect(inputs: adsk.core.CommandInputs):
    """Add every flat face of each already-selected face's body to the selection."""
    global _syncing
    faces_input: adsk.core.SelectionCommandInput = inputs.itemById(FACES_INPUT_ID)

    selected = [faces_input.selection(i).entity for i in range(faces_input.selectionCount)]
    if not selected:
        return

    present_ids = {face.tempId for face in selected}
    bodies = []  # de-duped while preserving order
    for face in selected:
        if all(b is not face.body for b in bodies):
            bodies.append(face.body)

    # Guard the burst so the selection events it spawns don't each rebuild the
    # table; we rebuild once at the end. (This is a one-shot button, so there's
    # no oscillation risk regardless.)
    _syncing = True
    try:
        for body in bodies:
            for f in body.faces:
                if (f.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType
                        and f.tempId not in present_ids):
                    faces_input.addSelection(f)
                    present_ids.add(f.tempId)
    finally:
        _syncing = False

    _rebuild_panels(inputs)


def _on_defaults(inputs: adsk.core.CommandInputs):
    """Reset every panel row to the current global thickness/direction/offset."""
    g_thickness, g_direction, g_offset = _read_globals(inputs)
    _snapshot_cells(inputs)
    for p in _panels:
        p['thickness'] = g_thickness
        p['direction'] = g_direction
        p['offset'] = g_offset
    _rebuild_table(inputs)


def _on_delete(inputs: adsk.core.CommandInputs):
    """Drop the selected table row (and its face from the selection)."""
    global _syncing
    table: adsk.core.TableCommandInput = inputs.itemById(TABLE_ID)
    row = table.selectedRow
    panel_index = row - 1  # row 0 is the header
    if panel_index < 0 or panel_index >= len(_panels):
        return

    _snapshot_cells(inputs)
    _panels.pop(panel_index)

    # Re-sync the selection to the surviving faces, guarded so the burst of
    # selection events doesn't rebuild the table mid-way.
    faces_input: adsk.core.SelectionCommandInput = inputs.itemById(FACES_INPUT_ID)
    _syncing = True
    try:
        faces_input.clearSelection()
        for p in _panels:
            faces_input.addSelection(p['face'])
    finally:
        _syncing = False

    _rebuild_table(inputs)


def _rebuild_panels(inputs: adsk.core.CommandInputs):
    """Rebuild `_panels` from the live selection, preserving edits by tempId."""
    global _panels
    _snapshot_cells(inputs)

    faces_input: adsk.core.SelectionCommandInput = inputs.itemById(FACES_INPUT_ID)
    g_thickness, g_direction, g_offset = _read_globals(inputs)

    old_by_tempid = {p['tempId']: p for p in _panels}
    new_panels = []
    for idx in range(faces_input.selectionCount):
        face = faces_input.selection(idx).entity
        existing = old_by_tempid.get(face.tempId)
        if existing:
            existing['face'] = face  # refresh the (possibly new) proxy
            new_panels.append(existing)
        else:
            new_panels.append({
                'tempId': face.tempId,
                'face': face,
                'name': _next_panel_name(new_panels),
                'thickness': g_thickness,
                'direction': g_direction,
                'offset': g_offset,
                'ids': {},
            })
    _panels = new_panels
    _rebuild_table(inputs)


def _next_panel_name(panels: list) -> str:
    """Smallest 'Panel N' name not already used, so re-added faces reuse freed
    numbers instead of jumping to the end (e.g. deselect Panel 3, reselect it,
    and it becomes Panel 3 again rather than Panel 6)."""
    used = set()
    for p in panels:
        match = re.match(r'^Panel (\d+)$', p['name'])
        if match:
            used.add(int(match.group(1)))
    n = 1
    while n in used:
        n += 1
    return f'Panel {n}'


def _read_globals(inputs: adsk.core.CommandInputs):
    thickness = inputs.itemById(THICKNESS_INPUT_ID).value
    direction = inputs.itemById(DIRECTION_INPUT_ID).selectedItem.name
    offset = inputs.itemById(OFFSET_INPUT_ID).value
    return thickness, direction, offset


def _snapshot_cells(inputs: adsk.core.CommandInputs):
    """Pull the latest values out of the table cells back into `_panels`."""
    for p in _panels:
        ids = p.get('ids') or {}
        name_in = inputs.itemById(ids.get('name', ''))
        th_in = inputs.itemById(ids.get('thickness', ''))
        dir_in = inputs.itemById(ids.get('direction', ''))
        off_in = inputs.itemById(ids.get('offset', ''))
        if name_in:
            p['name'] = name_in.value
        if th_in:
            p['thickness'] = th_in.value
        if dir_in:
            p['direction'] = dir_in.selectedItem.name
        if off_in:
            p['offset'] = off_in.value


def _new_id(prefix: str) -> str:
    global _uid
    _uid += 1
    return f'{prefix}_{_uid}'


def _rebuild_table(inputs: adsk.core.CommandInputs):
    """Tear down and re-create the table rows to match `_panels`."""
    global _cell_ids
    table: adsk.core.TableCommandInput = inputs.itemById(TABLE_ID)
    length_units = app.activeProduct.unitsManager.defaultLengthUnits

    table.clear()
    for cid in _cell_ids:
        leftover = inputs.itemById(cid)
        if leftover:
            try:
                leftover.deleteMe()
            except Exception:
                pass
    _cell_ids = []

    def add_cell(cmd_input, row, column):
        table.addCommandInput(cmd_input, row, column)
        _cell_ids.append(cmd_input.id)

    # Header row.
    headers = ['Panel Name', 'Thickness', 'Direction', 'Offset']
    for col, text in enumerate(headers):
        hdr = inputs.addTextBoxCommandInput(_new_id('hdr'), '', f'<b>{text}</b>', 1, True)
        add_cell(hdr, 0, col)

    # Data rows.
    for i, p in enumerate(_panels):
        row = i + 1

        name_in = inputs.addStringValueInput(_new_id('name'), '', p['name'])
        p['ids']['name'] = name_in.id
        add_cell(name_in, row, 0)

        th_in = inputs.addValueInput(
            _new_id('th'), '', length_units, adsk.core.ValueInput.createByReal(p['thickness']))
        p['ids']['thickness'] = th_in.id
        add_cell(th_in, row, 1)

        dir_in = inputs.addDropDownCommandInput(
            _new_id('dir'), '', adsk.core.DropDownStyles.TextListDropDownStyle)
        for d in DIRECTIONS:
            dir_in.listItems.add(d, d == p['direction'])
        p['ids']['direction'] = dir_in.id
        add_cell(dir_in, row, 2)

        off_in = inputs.addValueInput(
            _new_id('off'), '', length_units, adsk.core.ValueInput.createByReal(p['offset']))
        p['ids']['offset'] = off_in.id
        add_cell(off_in, row, 3)


def command_preview(args: adsk.core.CommandEventArgs):
    """Draw labels/arrows and dim the bodies here, NOT in inputChanged. Touching
    body opacity (or anything that triggers a graphics refresh) inside the
    selection's inputChanged clears the in-progress selection; executePreview
    runs after the selection has settled, so it's safe."""
    inputs = args.command.commandInputs
    _snapshot_cells(inputs)
    _update_graphics()


def _update_graphics():
    """Draw a floating name label and build-direction arrow at each panel face,
    and dim the skeleton bodies so the labels read clearly through them."""
    global _graphics_group, _dimmed_bodies
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent

        if _graphics_group:
            try:
                _graphics_group.deleteMe()
            except Exception:
                pass
            _graphics_group = None

        if not _panels:
            app.activeViewport.refresh()
            return

        # Dim each skeleton body once so the labels are visible through it. We
        # only touch bodies still at (near) full opacity, which both avoids
        # re-dimming and dedupes the restore list.
        for p in _panels:
            body = p['face'].body
            try:
                if body.opacity > 0.9:
                    body.opacity = 0.3
                    _dimmed_bodies.append(body)
            except Exception:
                pass

        group = root.customGraphicsGroups.add()
        label_color = adsk.fusion.CustomGraphicsSolidColorEffect.create(
            adsk.core.Color.create(255, 90, 90, 255))
        arrow_color = adsk.fusion.CustomGraphicsSolidColorEffect.create(
            adsk.core.Color.create(255, 200, 0, 255))

        for p in _panels:
            face = p['face']
            try:
                base = face.centroid
            except Exception:
                base = face.pointOnFace

            _, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
            normal.normalize()

            # The arrow points the way the panel will be built.
            if p['direction'] == 'Outside':
                arrow_dir = normal.copy()
            else:  # Inside / Symmetric point into the body
                arrow_dir = normal.copy()
                arrow_dir.scaleBy(-1.0)

            # Label floats off the face, billboarded so it always faces us.
            label_offset = normal.copy()
            label_offset.scaleBy(0.6)
            label_pt = base.copy()
            label_pt.translateBy(label_offset)

            transform = adsk.core.Matrix3D.create()
            transform.translation = label_pt.asVector()
            text = group.addText(p['name'], 'Arial', 2.0, transform)
            text.billBoarding = adsk.fusion.CustomGraphicsBillBoard.create(label_pt)
            text.color = label_color

            # Short arrow line from the face in the build direction.
            tip_vec = arrow_dir.copy()
            tip_vec.scaleBy(1.5)
            tip = base.copy()
            tip.translateBy(tip_vec)
            coords = adsk.fusion.CustomGraphicsCoordinates.create(
                [base.x, base.y, base.z, tip.x, tip.y, tip.z])
            line = group.addLines(coords, [], True)
            line.color = arrow_color
            line.weight = 3

        _graphics_group = group
        app.activeViewport.refresh()
    except Exception:
        futil.handle_error('Dress Up: update graphics')


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs

    # Defensive fallback: if the table never got populated (e.g. the
    # inputChanged path didn't run), build panels straight from the selection
    # using the global defaults so OK still works.
    if not _panels:
        _rebuild_panels(inputs)
    _snapshot_cells(inputs)

    created = 0
    skeleton_bodies = []
    for p in _panels:
        body = p['face'].body
        if all(b is not body for b in skeleton_bodies):
            skeleton_bodies.append(body)
        try:
            _build_panel(p)
            created += 1
        except Exception:
            futil.handle_error(f'Dress Up: failed to create "{p.get("name", "?")}"')

    # Hide the skeleton bodies now that the panels exist — the carcass is the
    # set of panel components, the skeleton was just the input shape.
    for body in skeleton_bodies:
        try:
            body.isLightBulbOn = False
        except Exception:
            pass

    if created < len(_panels):
        ui.messageBox(
            f'Created {created} of {len(_panels)} panels. '
            f'See the Text Commands window for details on the rest.'
        )


def _build_panel(p: dict):
    """Extrude the skeleton face itself into a panel body, in its own component.

    Extruding the BRepFace directly (rather than a projected sketch profile)
    keeps the panel associatively linked to the skeleton: when the skeleton
    body's parameters change, the face changes and every panel follows. The
    extrude is created inside a new component but references the external face,
    which Fusion tracks as a cross-component dependency."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    face: adsk.fusion.BRepFace = p['face']
    thickness = p['thickness']
    offset = p['offset']
    direction = p['direction']

    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    panel_comp = occ.component
    panel_comp.name = p['name']

    extrudes = panel_comp.features.extrudeFeatures
    # The face is the profile. A positive extrude follows the face's outward
    # normal, so "Inside" (into the body) is the negative direction.
    ext_input = extrudes.createInput(face, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)

    if direction == 'Symmetric':
        # Symmetric distance is measured per side, so half the thickness each way.
        ext_input.setDistanceExtent(True, adsk.core.ValueInput.createByReal(thickness / 2.0))
        build_sign = -1.0
    else:
        build_sign = -1.0 if direction == 'Inside' else 1.0
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(build_sign * thickness))

    if abs(offset) > 1e-9:
        ext_input.startExtent = adsk.fusion.OffsetStartDefinition.create(
            adsk.core.ValueInput.createByReal(build_sign * offset))

    extrudes.add(ext_input)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    faces_input: adsk.core.SelectionCommandInput = inputs.itemById(FACES_INPUT_ID)
    thickness = inputs.itemById(THICKNESS_INPUT_ID).value
    args.areInputsValid = faces_input.selectionCount > 0 and thickness > 0


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers, _panels, _cell_ids, _graphics_group, _dimmed_bodies
    if _graphics_group:
        try:
            _graphics_group.deleteMe()
        except Exception:
            pass
        _graphics_group = None
    # Restore the opacity of any skeleton bodies we dimmed.
    for body in _dimmed_bodies:
        try:
            body.opacity = 1.0
        except Exception:
            pass
    _dimmed_bodies = []
    app.activeViewport.refresh()
    local_handlers = []
    _panels = []
    _cell_ids = []
