# WoodCraft — a Fusion add-in for cabinetmaking.
# Copyright (C) 2026 Abdelrahman Youssry
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.

"""Create Configurations — one row for every combination of the theme tables.

Run it on a configured design (the cabinet itself, not a kitchen that places
one). It reads that design's own theme tables, works out every combination, and
adds a row for each one not already there.

The dialog IS the dry run: opening it shows exactly what would be created and
changes nothing, so OK is only ever pressed on a plan you have read.

It creates rows and stops. It does not build them and it does not save — that is
the other half of the job, and the two cannot be done in one pass:

    1. Create Configurations   (this command)
    2. SAVE the document
    3. Generate Configurations

Skipping step 2 is what produces "Select failed because Configuration was
temporarily unavailable": a row created moments ago in an unsaved document is not
yet real enough to build.

Safe to run again — it skips combinations that already exist, so adding a value
to a theme table and re-running only creates the rows that value made possible.
"""

import os

import adsk.core
import adsk.fusion

from .. import config_table
from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_configRows'
CMD_NAME = 'Create Configurations'
CMD_Description = (
    'Add a configuration row for every combination of this configured design\'s '
    'theme tables. Creates the rows only — save the document, then use Generate '
    'Configurations to build them.'
)
IS_PROMOTED = False

# Cabinet Builder: this shapes a cabinet's own library file, not a kitchen.
PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

INFO_ID = 'cr_info'

# Row creation is quick, but it is still table surgery, and the same rule that
# bit Fit Handles applies: Fusion does not settle a document mid-command. The
# work runs from a custom event, after the dialog has closed.
RUN_EVENT_ID = 'WoodCraftCreateConfigurationsRun'

local_handlers = []
_event_handlers = []
_run_event = None
_pending = False


class _RunHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _pending
        go, _pending = _pending, False
        if not go:
            return
        try:
            _create()
        except Exception:
            futil.handle_error(CMD_NAME)


def _arm_event():
    """Register the run event with a live handler, replacing any stale one."""
    global _run_event
    try:
        app.unregisterCustomEvent(RUN_EVENT_ID)
    except Exception:
        pass
    _run_event = app.registerCustomEvent(RUN_EVENT_ID)
    handler = _RunHandler()
    _run_event.add(handler)
    _event_handlers.append(handler)
    del _event_handlers[:-2]


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    _arm_event()

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    global _run_event
    _run_event = None
    _event_handlers.clear()
    try:
        app.unregisterCustomEvent(RUN_EVENT_ID)
    except Exception:
        pass
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def _current_plan():
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None, None
    return design, config_table.plan(design, app.activeDocument.name)


def _summary(result):
    if result is None:
        return 'Open a configured design first.'
    if result.error:
        return result.error

    lines = ['<b>%d combinations</b> of %s.' % (
        result.total,
        ', '.join('%s (%d)' % (t, len(a))
                  for t, a in zip(result.vary, result.axes)))]
    lines.append('%d already in the table, <b>%d to create</b>.'
                 % (result.present, len(result.to_create)))
    if result.untouched:
        lines.append('')
        lines.append('Not varied — inherited from "%s": %s' % (
            result.base.name,
            ', '.join('%s = %s' % (t, v)
                      for t, v in sorted(result.untouched.items()))))
    if result.clashes:
        lines.append('')
        lines.append('<b>%d name(s) would collide</b> and Fusion would append '
                     '"(1)": %s' % (len(result.clashes),
                                    ', '.join(result.clashes[:4])))
    if result.to_create:
        lines.append('')
        lines.append('First few: ' +
                     ', '.join(n for n, _c in result.to_create[:3]))
        if len(result.to_create) > 3:
            lines.append('… and %d more.' % (len(result.to_create) - 3))
        lines.append('')
        lines.append('Rows only — nothing is built and nothing is saved. '
                     'Save the document, then run Generate Configurations.')
    else:
        lines.append('')
        lines.append('Nothing to do.')
    return '<br>'.join(lines)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs
    _design, result = _current_plan()

    info = inputs.addTextBoxCommandInput(INFO_ID, '', _summary(result), 12, True)
    info.isFullWidth = True

    args.command.okButtonText = 'Create'
    if result is None or result.error or not result.to_create:
        args.command.isOKButtonVisible = False

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    global _pending
    _pending = True
    _arm_event()
    app.fireCustomEvent(RUN_EVENT_ID)


def _create():
    """Runs after the dialog has closed, where the document settles normally."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return
    result = config_table.plan(design, app.activeDocument.name)
    if result.error or not result.to_create:
        return

    made, problems = config_table.create(design, result)
    table = config_table.top_table(design)

    lines = [f'Created {made} configuration row(s).',
             f'The table now has {table.rows.count} rows.']
    if problems:
        lines.append('')
        lines.append('Problems:')
        lines.extend(f'  {p}' for p in problems[:10])
        if len(problems) > 10:
            lines.append(f'  … and {len(problems) - 10} more')
    lines.append('')
    lines.append('Nothing has been built and nothing has been saved.')
    lines.append('SAVE the document, then run Generate Configurations — building '
                 'a row before the save fails with "Configuration was '
                 'temporarily unavailable".')
    ui.messageBox('\n'.join(lines), CMD_NAME)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
