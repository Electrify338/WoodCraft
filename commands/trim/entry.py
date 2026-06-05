"""Trim — cut panels so they fit against other panels, with an optional gap.

Carcass Maker leaves panels overlapping at the corners. Trim resolves those overlaps
using Fusion's Combine (cut): the user picks the panels to trim and the panels
to trim them *with*, and each target has the tool panels subtracted from it.

The gap grows each tool panel outward by a uniform distance before the cut, so
the trimmed panel ends up standing off from the tool by that amount — e.g. a
2 mm reveal around a door, or clearance so a bottom panel doesn't bind between
two sides.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_trim'
CMD_NAME = 'Trim'
CMD_Description = (
    'Trim selected panels against other panels using a cut, with an optional '
    'uniform gap between them.'
)
IS_PROMOTED = True

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

TARGETS_INPUT_ID = 'trim_targets'
TOOLS_INPUT_ID = 'trim_tools'
GAP_INPUT_ID = 'trim_gap'

DEFAULT_GAP_CM = 0.0

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

    targets_input = inputs.addSelectionInput(TARGETS_INPUT_ID, 'Panels to trim', 'Select the panels to be cut')
    targets_input.addSelectionFilter('SolidBodies')
    targets_input.setSelectionLimits(1, 0)

    tools_input = inputs.addSelectionInput(TOOLS_INPUT_ID, 'Trim with', 'Select the panels that do the cutting')
    tools_input.addSelectionFilter('SolidBodies')
    tools_input.setSelectionLimits(1, 0)

    length_units = app.activeProduct.unitsManager.defaultLengthUnits
    gap_input = inputs.addValueInput(
        GAP_INPUT_ID, 'Gap', length_units,
        adsk.core.ValueInput.createByReal(DEFAULT_GAP_CM),
    )
    gap_input.tooltip = 'Clearance left between each trimmed panel and the panel that trims it. 0 is a flush cut.'

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs

    targets_input: adsk.core.SelectionCommandInput = inputs.itemById(TARGETS_INPUT_ID)
    tools_input: adsk.core.SelectionCommandInput = inputs.itemById(TOOLS_INPUT_ID)
    gap: float = inputs.itemById(GAP_INPUT_ID).value

    targets = [targets_input.selection(i).entity for i in range(targets_input.selectionCount)]
    tools = [tools_input.selection(i).entity for i in range(tools_input.selectionCount)]

    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    trimmed = 0
    for target in targets:
        try:
            if _trim_target(root, target, tools, gap):
                trimmed += 1
        except Exception:
            futil.handle_error(f'Trim: failed to trim "{target.name}"')

    if trimmed == 0:
        ui.messageBox('No panels were trimmed. Make sure the trim panels actually overlap the targets.')


def _trim_target(root: adsk.fusion.Component, target: adsk.fusion.BRepBody,
                 tools: list, gap: float) -> bool:
    """Cut `target` by every tool (other than itself). Returns True if a cut ran."""
    tool_bodies = adsk.core.ObjectCollection.create()

    for tool in tools:
        if tool == target:
            continue
        if gap > 1e-9:
            # Grow a throwaway copy of the tool outward by `gap` so the cut
            # leaves clearance. The copy is consumed by the combine below.
            grown = tool.copyToComponent(root)
            _offset_body_faces(root, grown, gap)
            tool_bodies.add(grown)
        else:
            tool_bodies.add(tool)

    if tool_bodies.count == 0:
        return False

    combines = root.features.combineFeatures
    combine_input = combines.createInput(target, tool_bodies)
    combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    # When gap > 0 the tools are disposable grown copies, so let the combine
    # consume them. With no gap the tools are the user's real panels — keep them.
    combine_input.isKeepToolBodies = gap <= 1e-9
    combines.add(combine_input)
    return True


def _offset_body_faces(root: adsk.fusion.Component, body: adsk.fusion.BRepBody, distance: float):
    """Offset every face of `body` outward by `distance`, growing the solid."""
    faces = [body.faces.item(i) for i in range(body.faces.count)]
    offset_faces = root.features.offsetFacesFeatures
    offset_input = offset_faces.createInput(faces, adsk.core.ValueInput.createByReal(distance))
    offset_faces.add(offset_input)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    targets_input: adsk.core.SelectionCommandInput = inputs.itemById(TARGETS_INPUT_ID)
    tools_input: adsk.core.SelectionCommandInput = inputs.itemById(TOOLS_INPUT_ID)
    args.areInputsValid = targets_input.selectionCount > 0 and tools_input.selectionCount > 0


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
