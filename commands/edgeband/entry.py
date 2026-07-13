"""Edgeband — tag panel edge faces with an edgeband type for the BOM.

Pick the faces to band (a panel's thin edge faces — the 18 mm-wide strips) and
choose an edgeband from the Sheets library's band catalogue; each face is stamped
with a WC_EDGEBAND attribute holding the band's NAME. The BOM then sums the
tagged lengths per band type across the whole design (face area ÷ panel
thickness, so a curved edge counts its true arc length) and prices the metres
from the catalogue's cost per metre. Nothing but the name is stored on the face —
cost lives in the library, so re-pricing a band re-prices every past design.

Tagging also TINTS the face in the viewport: a design-local appearance named
after the band (colour = the band's library colour) is applied as a face
override, so banded edges read at a glance. Removing the tag clears the
override. The tint is cosmetic — the BOM reads only the attribute.

Bands are edited in the Sheets palette (same sheets.json file as the stock
sheets). The last dropdown entry removes an existing tag instead.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import wc_attrs
from .. import panels
from .. import sheets_store
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_edgeband'
CMD_NAME = 'Edgeband'
CMD_Description = (
    'Tag the selected panel edge faces with an edgeband type from the Sheets '
    'library. The BOM totals the tagged edge length per band type and prices it '
    'at the library\'s cost per metre. Pick the remove entry to strip a tag.'
)
IS_PROMOTED = True

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SEL_ID = 'eb_faces'
BAND_ID = 'eb_band'

REMOVE_LABEL = '— Remove edgeband —'

# Copied from an Appearance-library paint to make each band's tint (newer and
# older Fusion library names).
APPEARANCE_LIBS = ('Fusion Appearance Library', 'Fusion 360 Appearance Library')
BASE_APPEARANCE = 'Paint - Enamel Glossy (Yellow)'

# Rebuilt on every dialog open from the Sheets library: [(label, band dict|None)].
# None = the remove entry. Module state is safe: one command dialog at a time.
band_choices = []

local_handlers = []


def start():
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if not cmd_def:
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


def _band_label(band):
    """Dropdown label: name + the catalogue's size when present, e.g.
    'PVC Oak 2 mm  (22 × 2 mm)'."""
    width = band.get('width') or 0
    thickness = band.get('thickness') or 0
    if width and thickness:
        return f"{band['name']}  ({width:g} × {thickness:g} mm)"
    return band['name']


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    sel = inputs.addSelectionInput(
        SEL_ID, 'Edge faces',
        'Select the panel edge faces to band (the thin thickness-side strips)')
    sel.addSelectionFilter('Faces')
    sel.setSelectionLimits(1, 0)

    global band_choices
    band_choices = [(_band_label(b), b)
                    for b in sheets_store.load()['edgebands']]
    band_choices.append((REMOVE_LABEL, None))

    dd = inputs.addDropDownCommandInput(
        BAND_ID, 'Edgeband', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(band_choices):
        dd.listItems.add(label, i == 0)
    dd.tooltip = ('Band types come from the Sheets palette (Edgebands section), '
                  'where each carries its cost per metre for the BOM.')

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input,
                      local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _selected_band(inputs):
    """The chosen band dict, or None for the remove entry."""
    dd = inputs.itemById(BAND_ID)
    idx = dd.selectedItem.index if dd and dd.selectedItem else 0
    return band_choices[idx][1] if 0 <= idx < len(band_choices) else None


# ---------------------------------------------------------------------------
# Viewport tint (face appearance override in the band's library colour)
# ---------------------------------------------------------------------------
def _hex_to_rgb(hex_str):
    """(r, g, b) from '#RRGGBB', falling back to the library's default tan."""
    try:
        s = str(hex_str or '').lstrip('#')
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, IndexError):
        return 201, 168, 106      # sheets_store.DEFAULT_COLOR

def _band_appearance(design, band):
    """Get-or-create this band's design-local appearance ('WoodCraft Edgeband —
    <name>'), with its colour synced to the band's CURRENT library colour. None
    when no base appearance could be found (tint is then skipped — the tag still
    works; the tint is cosmetic only)."""
    name = f'WoodCraft Edgeband — {band["name"]}'
    appearance = None
    try:
        appearance = design.appearances.itemByName(name)
    except Exception:
        pass
    if not appearance:
        base = None
        for lib_name in APPEARANCE_LIBS:
            try:
                lib = app.materialLibraries.itemByName(lib_name)
                if lib:
                    base = lib.appearances.itemByName(BASE_APPEARANCE)
                    if base:
                        break
            except Exception:
                continue
        if not base:
            futil.log(f'{CMD_NAME}: no base appearance found — skipping face tint')
            return None
        try:
            appearance = design.appearances.addByCopy(base, name)
        except Exception:
            return None
    try:
        r, g, b = _hex_to_rgb(band.get('color'))
        prop = appearance.appearanceProperties.itemByName('Color')
        if prop:
            prop.value = adsk.core.Color.create(r, g, b, 255)
    except Exception:
        pass    # wrong colour is still a visible tint — keep going
    return appearance


def _native_face(entity):
    """Resolve a selected face to its NATIVE BRepFace. A face picked on an
    occurrence is a proxy; writing the attribute on the native face makes the
    band per-component (every occurrence of the panel gets it — matching how the
    BOM multiplies one instance's banding by the quantity)."""
    face = adsk.fusion.BRepFace.cast(entity)
    if not face:
        return None
    try:
        return face.nativeObject or face
    except Exception:
        return face


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    sel = args.inputs.itemById(SEL_ID)
    args.areInputsValid = bool(sel and sel.selectionCount > 0)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs
    sel: adsk.core.SelectionCommandInput = inputs.itemById(SEL_ID)
    band = _selected_band(inputs)
    band_name = band['name'] if band else None

    # Snapshot every selected face BEFORE writing: adding an attribute mutates the
    # document, which invalidates the selection input's list mid-loop (see the
    # Set Type command / project memory).
    faces = []
    for i in range(sel.selectionCount):
        face = _native_face(sel.selection(i).entity)
        if face:
            faces.append(face)

    # One appearance per band, resolved once against the active design.
    appearance = None
    if band is not None:
        try:
            design = adsk.fusion.Design.cast(app.activeProduct)
            if design:
                appearance = _band_appearance(design, band)
        except Exception:
            appearance = None

    done = 0
    skipped = 0
    length_mm = 0.0
    for face in faces:
        if band_name is None:
            if wc_attrs.remove_edgeband(face):
                done += 1
                try:
                    face.appearance = None      # drop the tint override too
                except Exception:
                    pass
            continue
        if not wc_attrs.set_edgeband(face, band_name):
            skipped += 1
            futil.log(f'{CMD_NAME}: could not tag a face (referenced/read-only?)')
            continue
        done += 1
        if appearance is not None:
            try:
                face.appearance = appearance    # tint the edge in the band colour
            except Exception:
                pass
        try:
            comp = face.body.parentComponent
            dims = panels.panel_dims_mm(comp)
            length_mm += panels.face_edgeband_length_mm(face, dims[2] if dims else None)
        except Exception:
            pass    # length is only for the message; the tag itself succeeded

    if band_name is None:
        msg = f'Removed the edgeband tag (and tint) from {done} face(s).'
    else:
        msg = (f'Tagged {done} face(s) with "{band_name}" — '
               f'≈ {length_mm / 1000.0:.2f} m of banding.\n'
               f'The BOM totals and prices all tagged edges per band type.')
    if skipped:
        msg += (f'\n{skipped} face(s) could not be tagged — likely a referenced/'
                f'read-only component. Open its source design to band those.')
    ui.messageBox(msg)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
