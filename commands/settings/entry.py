"""Settings — add-on-wide options for WoodCraft (commands/settings_store.py).

Today that is one number: the panel-cost WASTE FACTOR. The BOM estimates a
panel's cost as raw area × the average sheet cost/m² of its material (Sheets
library); real nesting never uses a whole sheet, so the estimate is topped up
by this percentage. New options should be added here (and to settings_store's
DEFAULTS) rather than growing per-command dialogs.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import settings_store
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_settings'
CMD_NAME = 'Settings'
CMD_Description = (
    'WoodCraft options shared by every design. Waste factor: the percentage added '
    'on top of a panel\'s raw area when the BOM estimates panel costs from the '
    'Sheets library prices (offcuts and trim mean nesting never uses 100% of a '
    'sheet).'
)
IS_PROMOTED = False

PANEL_ID = config.OUTPUT_PANEL_ID
PANEL_NAME = config.OUTPUT_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

WASTE_ID = 'st_waste'

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

    waste = settings_store.get_waste_percent()
    # Plain-text field (command textboxes render HTML-free plain text anyway) —
    # same parse-at-execute pattern as Set Type's cost field.
    box = inputs.addStringValueInput(WASTE_ID, 'Panel waste factor (%)', f'{waste:g}')
    box.tooltip = ('Added to every panel-cost estimate in the BOM. Example: 10 '
                   'means a 1.00 m² panel is billed as 1.10 m² of sheet stock.')

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _parse_percent(text):
    """Float ≥ 0 from the waste field, or None if not a usable percentage."""
    try:
        value = float(str(text).strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    args.areInputsValid = _parse_percent(args.inputs.itemById(WASTE_ID).value) is not None


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    value = _parse_percent(args.command.commandInputs.itemById(WASTE_ID).value)
    if value is None:
        return
    saved = settings_store.set_waste_percent(value)
    ui.messageBox(f'Panel waste factor set to {saved:g}%.\n'
                  f'BOM panel-cost estimates will use it from the next refresh.')


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
