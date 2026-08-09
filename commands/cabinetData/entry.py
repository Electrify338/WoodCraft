"""Cabinet Data — spec a cabinet's carcass and door finish for the schedule.

Select one or more cabinets (the assembly components, not their panels) and set:

  - **Carcass Type** — Painted or Veneer
  - **Door Type**    — Painted or Veneer

Both are stamped on the cabinet COMPONENT as WoodCraft attributes, so they are
saved inside the .f3d, survive configuration changes, and are read straight back
out by **Kitchen Export**. Carcass and door are separate because a cabinet is
routinely built one way inside and the other way on the front.

Multi-select is the point: a kitchen usually has one spec for the base run and
another for the talls, so you set a whole group in one go.

Note this is a COMPONENT attribute, matching the rest of WoodCraft: every
occurrence of the same cabinet component reports the same spec. Two identical
boxes that need different finishes have to be different components (Fusion's
normal "Make Independent"), which is also what makes the export's one-row-per-
model schedule correct.

Material is NOT set here — it is read from the Fusion physical material you
assign to the panels, exactly as the cut list and BOM already do. This command
only records the things geometry can't tell you.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import wc_attrs
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_cabinetData'
CMD_NAME = 'Cabinet Data'
CMD_Description = (
    'Record the Carcass Type and Door Type (Painted or Veneer) on the selected '
    'cabinets. Stored on the component and saved with the design; Kitchen Export '
    'reads them back into the schedule. Select several cabinets to spec them at once.'
)
IS_PROMOTED = True

PANEL_ID = config.KITCHEN_PANEL_ID
PANEL_NAME = config.KITCHEN_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SEL_ID = 'cd_selection'
CARCASS_ID = 'cd_carcass'
DOOR_ID = 'cd_door'

# Dropdown order → stored value. Index 0 is the default.
FINISH_CHOICES = [(config.WC_FINISH_PAINTED, config.WC_FINISH_PAINTED),
                  (config.WC_FINISH_VENEER, config.WC_FINISH_VENEER)]

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
        SEL_ID, 'Cabinets', 'Select the cabinet components to spec')
    sel.addSelectionFilter('Occurrences')
    # Lets a PART document's own root component be picked from the browser (a
    # part file has no occurrences to select). Guarded because an unknown filter
    # name throws, and command_created swallowing that would kill the dialog.
    try:
        sel.addSelectionFilter('RootComponents')
    except Exception:
        futil.log('Cabinet Data: RootComponents selection filter unavailable')
    sel.setSelectionLimits(1, 0)
    sel.tooltip = ('Pick the cabinet assemblies from the browser or the canvas. '
                   'Everything selected gets the same spec, so group by finish.')

    carcass = inputs.addDropDownCommandInput(
        CARCASS_ID, 'Carcass Type', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(FINISH_CHOICES):
        carcass.listItems.add(label, i == 0)

    door = inputs.addDropDownCommandInput(
        DOOR_ID, 'Door Type', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(FINISH_CHOICES):
        door.listItems.add(label, i == 0)

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _component_of(entity):
    """Resolve a selection (an Occurrence or a root Component) to its Component."""
    if entity.objectType == adsk.fusion.Occurrence.classType():
        return adsk.fusion.Occurrence.cast(entity).component
    if entity.objectType == adsk.fusion.Component.classType():
        return adsk.fusion.Component.cast(entity)
    return None


def _choice(inputs, input_id):
    dd = inputs.itemById(input_id)
    index = dd.selectedItem.index if dd and dd.selectedItem else 0
    return FINISH_CHOICES[index][1]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    sel = args.inputs.itemById(SEL_ID)
    args.areInputsValid = bool(sel and sel.selectionCount > 0)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs
    sel: adsk.core.SelectionCommandInput = inputs.itemById(SEL_ID)

    carcass = _choice(inputs, CARCASS_ID)
    door = _choice(inputs, DOOR_ID)

    # Snapshot every selected component BEFORE writing anything: an attribute
    # write mutates the document, which invalidates the live selection list, and
    # the next sel.selection(i) then throws "invalid argument index" — only the
    # first cabinet would get stamped. Same two-pass shape as Set Type.
    comps = []
    for i in range(sel.selectionCount):
        comp = _component_of(sel.selection(i).entity)
        if comp:
            comps.append(comp)

    done, skipped = 0, 0
    for comp in comps:
        ok_carcass = wc_attrs.set_carcass_type(comp, carcass)
        ok_door = wc_attrs.set_door_type(comp, door)
        if ok_carcass and ok_door:
            done += 1
        else:
            skipped += 1
            futil.log(f'Cabinet Data: could not spec "{getattr(comp, "name", "?")}" '
                      f'(referenced/read-only?)')

    msg = f'Specced {done} cabinet(s):\n  Carcass: {carcass}\n  Door: {door}'
    if skipped:
        msg += (f'\n\n{skipped} could not be updated — likely referenced/read-only. '
                f'Open the source design to spec those.')
    ui.messageBox(msg)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
