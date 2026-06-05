"""Convert to Panel — tag selected components as WoodCraft panels.

WoodCraft's output commands (cut list, BOM, labels) find "the panels" by an
invisible custom attribute (config.PANEL_ATTR_*). Carcass Maker and Shelf Creator
stamp it automatically; this command stamps panels that were modelled by hand or
imported, so they show up in those reports too. The tag lives on the component
and is saved with the document.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_convertPanel'
CMD_NAME = 'Convert to Panel'
CMD_Description = (
    'Tag selected components as WoodCraft panels so they are picked up by the cut '
    'list, BOM and label commands. Use this for panels not made by WoodCraft.'
)
IS_PROMOTED = True

PANEL_ID = config.DRESSUP_PANEL_ID
PANEL_NAME = config.DRESSUP_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SEL_ID = 'cp_selection'

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

    sel = inputs.addSelectionInput(
        SEL_ID, 'Components', 'Select the components (or their bodies) to tag as panels')
    sel.addSelectionFilter('Occurrences')
    sel.addSelectionFilter('SolidBodies')
    sel.setSelectionLimits(1, 0)

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _component_of(entity):
    """Resolve a selection (an Occurrence or a body) to its owning Component."""
    if entity.objectType == adsk.fusion.Occurrence.classType():
        return adsk.fusion.Occurrence.cast(entity).component
    if entity.objectType == adsk.fusion.BRepBody.classType():
        return adsk.fusion.BRepBody.cast(entity).parentComponent
    return None


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs
    sel: adsk.core.SelectionCommandInput = inputs.itemById(SEL_ID)

    seen_tokens = set()
    tagged = 0
    skipped = 0
    for i in range(sel.selectionCount):
        comp = _component_of(sel.selection(i).entity)
        if not comp:
            continue
        # De-dup: selecting several instances/bodies of one component tags it once.
        try:
            token = comp.entityToken
        except Exception:
            token = None
        if token is not None:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)

        if ui_helpers.tag_as_panel(comp):
            tagged += 1
        else:
            skipped += 1
            futil.log(f'Convert to Panel: could not tag "{getattr(comp, "name", "?")}" (referenced/read-only?)')

    msg = f'Tagged {tagged} component(s) as WoodCraft panels.'
    if skipped:
        msg += (f'\n{skipped} could not be tagged — likely referenced/read-only. '
                f'Open the source design to tag those.')
    ui.messageBox(msg)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    sel = inputs.itemById(SEL_ID)
    args.areInputsValid = sel.selectionCount > 0


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
