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

"""Generate Configurations — build the geometry for rows that have none.

The second half of the job Create Configurations starts, and a separate button
for one reason: a row cannot be built until the document has been SAVED. Ask
Fusion to build a row created moments ago in an unsaved document and it answers
"Select failed because Configuration was temporarily unavailable" — the row is
not yet real to it.

So the order is: Create Configurations, save, then this.

The dialog refuses to start while the document has unsaved changes, which is the
whole guard. It also says how many rows are waiting and roughly how long they
will take, because this is the slow half — the first few rows cost about ten
seconds each while Fusion loads every referenced part, and it settles to around a
second a row after that.

Fusion has no "generate all" of its own: the only thing that builds a
configuration in its UI is activating it, one row at a time.

Interrupting is safe. There is no way to ask a row whether it has geometry, and
generate() costs the same whether it needs to or not, so the record of what has
been built is kept on the design and written after every row. Run it again and it
carries on where it stopped.
"""

import os
import time

import adsk.core
import adsk.fusion

from .. import config_table
from .. import ui_helpers
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_configBuild'
CMD_NAME = 'Generate Configurations'
CMD_Description = (
    'Build the geometry for configuration rows that have none, so a kitchen never '
    'waits for one. Save the document first — a row created since the last save '
    'cannot be built.'
)
IS_PROMOTED = False

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

INFO_ID = 'cb_info'
REBUILD_ID = 'cb_rebuild'

# Minutes of work, so it cannot run inside the command: the dialog would be
# frozen throughout and Fusion does not settle a document mid-command anyway.
RUN_EVENT_ID = 'WoodCraftGenerateConfigurationsRun'

# What a row costs to build, measured: the first few are slow while Fusion loads
# every referenced part, then it settles.
FIRST_ROWS = 4
FIRST_ROW_SECONDS = 10.5
LATER_ROW_SECONDS = 1.2

local_handlers = []
_event_handlers = []
_run_event = None
_pending = None          # the regenerate flag, or None when idle


class _RunHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _pending
        job, _pending = _pending, None
        if job is None:
            return
        try:
            _generate(job)
        except Exception:
            futil.handle_error(CMD_NAME)


def _arm_event():
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
def _estimate(count):
    """Roughly how long `count` rows will take, in words."""
    slow = min(count, FIRST_ROWS)
    seconds = slow * FIRST_ROW_SECONDS + max(0, count - slow) * LATER_ROW_SECONDS
    if seconds < 90:
        return f'about {seconds:.0f} seconds'
    return f'about {seconds / 60.0:.0f} minutes'


def _state(regenerate=False):
    """(design, table, waiting rows, blocking message)."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None, None, [], 'Open a configured design first.'
    table = config_table.top_table(design)
    if table is None:
        return design, None, [], ('This document has no configuration table. '
                                  'Open the configured design itself, not an '
                                  'assembly that places one.')
    if app.activeDocument.isModified:
        return design, table, [], (
            'This document has unsaved changes.<br><br>'
            'A row cannot be built until it has been saved — asking anyway gives '
            '"Configuration was temporarily unavailable". <b>Save the document, '
            'then run this again.</b>')
    return design, table, config_table.unbuilt(design, regenerate), None


def _summary(inputs=None):
    regenerate = False
    if inputs is not None:
        box = inputs.itemById(REBUILD_ID)
        regenerate = bool(box.value) if box else False
    _design, table, waiting, blocked = _state(regenerate)
    if blocked:
        return blocked, False
    total = table.rows.count
    if not waiting:
        return ('All %d row(s) in this table have been built.<br><br>'
                'Tick "Build every row again" to rebuild them anyway.' % total), False
    lines = ['%d of %d row(s) still to build.' % (len(waiting), total),
             'This will take %s.' % _estimate(len(waiting)),
             '',
             'First few: ' + ', '.join(r.name for r in waiting[:3])]
    if len(waiting) > 3:
        lines.append('… and %d more.' % (len(waiting) - 3))
    lines.append('')
    lines.append('Progress is written after every row, so stopping part way '
                 'loses nothing — run it again to carry on.')
    return '<br>'.join(lines), True


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    text, can_run = _summary()
    info = inputs.addTextBoxCommandInput(INFO_ID, '', text, 12, True)
    info.isFullWidth = True
    inputs.addBoolValueInput(REBUILD_ID, 'Build every row again', True, '', False)

    args.command.okButtonText = 'Generate'
    args.command.isOKButtonVisible = can_run

    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    """Re-read the plan when the rebuild box is ticked — the count changes."""
    inputs = args.inputs
    box = inputs.itemById(INFO_ID)
    if box is None:
        return
    text, _can_run = _summary(inputs)
    try:
        box.formattedText = text
    except Exception:
        pass


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    global _pending
    box = args.command.commandInputs.itemById(REBUILD_ID)
    _pending = bool(box.value) if box else False
    _arm_event()
    app.fireCustomEvent(RUN_EVENT_ID)


def _generate(regenerate):
    """Runs after the dialog has closed, so Fusion is free to settle between rows."""
    design, _table, waiting, blocked = _state(regenerate)
    if blocked or not waiting:
        if blocked:
            ui.messageBox(blocked.replace('<br>', '\n').replace('<b>', '')
                          .replace('</b>', ''), CMD_NAME)
        return

    futil.log(f'{CMD_NAME}: building {len(waiting)} row(s)…')
    started = time.perf_counter()
    built, skipped, problems = config_table.build(
        design, waiting, futil.log, regenerate=regenerate)
    elapsed = time.perf_counter() - started

    lines = [f'Built {built} configuration(s) in {elapsed:.0f} s.']
    if skipped:
        lines.append(f'{skipped} were already built and were skipped.')
    if problems:
        lines.append('')
        lines.append('Problems:')
        lines.extend(f'  {p}' for p in problems[:10])
        if len(problems) > 10:
            lines.append(f'  … and {len(problems) - 10} more '
                         f'(see the Text Command window)')
    lines.append('')
    lines.append('Save the document to keep the record of what has been built.')
    ui.messageBox('\n'.join(lines), CMD_NAME)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
