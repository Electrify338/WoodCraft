"""Edit Thickness — change the thickness of an existing panel.

Select one or more panels (the bodies Carcass Maker created) and enter a new
thickness. Instead of building anything new, this edits the panel's existing
extrude feature in the timeline — it scales the extrude's extent distance to the
new thickness, which keeps the original direction (Inside / Outside / Symmetric)
and any offset intact. The change recomputes parametrically like any manual
timeline edit.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_editThickness'
CMD_NAME = 'Edit Thickness'
CMD_Description = (
    'Change the thickness of selected panels by editing their extrude feature '
    'in place, rather than creating new geometry.'
)
IS_PROMOTED = True

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

PANEL_INPUT_ID = 'editthk_panel'
THICKNESS_INPUT_ID = 'editthk_thickness'

DEFAULT_THICKNESS_CM = 1.8

local_handlers = []


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
    inputs = args.command.commandInputs

    panel_input = inputs.addSelectionInput(PANEL_INPUT_ID, 'Panel(s)', 'Select the panel(s) to edit')
    panel_input.addSelectionFilter('SolidBodies')
    panel_input.setSelectionLimits(1, 0)

    length_units = app.activeProduct.unitsManager.defaultLengthUnits
    thickness_input = inputs.addValueInput(
        THICKNESS_INPUT_ID, 'New thickness', length_units,
        adsk.core.ValueInput.createByReal(DEFAULT_THICKNESS_CM),
    )
    thickness_input.tooltip = 'The thickness to apply. The selected panel\'s current thickness is shown when you pick it.'

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    changed = args.input
    inputs = changed.parentCommand.commandInputs

    # When a panel is picked, prefill the field with its current thickness so the
    # user can see what they're changing from.
    if changed.id == PANEL_INPUT_ID:
        panel_input: adsk.core.SelectionCommandInput = inputs.itemById(PANEL_INPUT_ID)
        if panel_input.selectionCount > 0:
            ext = _find_panel_extrude(panel_input.selection(0).entity)
            current = _panel_thickness(ext) if ext else None
            if current:
                inputs.itemById(THICKNESS_INPUT_ID).value = current


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs

    panel_input: adsk.core.SelectionCommandInput = inputs.itemById(PANEL_INPUT_ID)
    new_thickness: float = inputs.itemById(THICKNESS_INPUT_ID).value

    bodies = [panel_input.selection(i).entity for i in range(panel_input.selectionCount)]

    edited = 0
    for body in bodies:
        try:
            ext = _find_panel_extrude(body)
            if ext and _set_panel_thickness(ext, new_thickness):
                edited += 1
        except Exception:
            futil.handle_error(f'Edit Thickness: failed on "{body.name}"')

    if edited == 0:
        ui.messageBox(
            'Could not change thickness. Select panels created by Carcass Maker '
            '(a body made by a single extrude).'
        )


def _find_panel_extrude(body: adsk.fusion.BRepBody):
    """Return the extrude feature that created `body`, or the component's single
    extrude as a fallback (Carcass Maker panels have exactly one)."""
    comp = body.parentComponent
    extrudes = comp.features.extrudeFeatures
    for i in range(extrudes.count):
        ext = extrudes.item(i)
        for j in range(ext.bodies.count):
            try:
                if ext.bodies.item(j) == body:
                    return ext
            except Exception:
                pass
    return extrudes.item(0) if extrudes.count >= 1 else None


def _panel_thickness(ext: adsk.fusion.ExtrudeFeature):
    """Current panel thickness (cm), accounting for a symmetric extrude storing a
    per-side distance. Returns None if the extent isn't a distance/symmetric one."""
    ext_def = ext.extentOne
    try:
        distance = abs(ext_def.distance.value)
    except Exception:
        return None
    if ext_def.objectType == adsk.fusion.SymmetricExtentDefinition.classType():
        try:
            if not ext_def.isFullLength:
                distance *= 2.0
        except Exception:
            distance *= 2.0
    return distance


def _set_panel_thickness(ext: adsk.fusion.ExtrudeFeature, new_thickness: float) -> bool:
    """Scale the extrude's extent distance so the panel becomes `new_thickness`
    thick. Scaling (rather than reassigning) preserves the sign — i.e. the
    Inside/Outside/Symmetric direction — and the per-side vs full convention."""
    current = _panel_thickness(ext)
    if not current or current < 1e-9:
        return False
    param = ext.extentOne.distance
    param.value = param.value * (new_thickness / current)
    return True


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    panel_input: adsk.core.SelectionCommandInput = inputs.itemById(PANEL_INPUT_ID)
    thickness = inputs.itemById(THICKNESS_INPUT_ID).value
    args.areInputsValid = panel_input.selectionCount > 0 and thickness > 0


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
