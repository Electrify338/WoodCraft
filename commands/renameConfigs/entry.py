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

"""Rename Configurations — name every configuration '<File>-<Width>-<Height>'.

Reads the active configured design's top table, resolves each row's Width and
Height (whether the column holds the parameter directly or references a theme
table), and renames the row to '<file name>-<width>-<height>' in the document's
default length units (e.g. 'WC_CL_S1-1000-720'). The dialog previews every
rename before anything is touched; OK applies them.
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

CMD_ID = f'{config.COMPANY_NAME}_renameConfigs'
CMD_NAME = 'Rename Configurations'
CMD_Description = ("Rename every configuration to '<File>-<Width>-<Height>' using the "
                   "Width and Height columns of the configuration table.")
IS_PROMOTED = True

PANEL_ID = config.DEV_PANEL_ID
PANEL_NAME = config.DEV_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

PREVIEW_ID = 'rc_preview'

local_handlers = []


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


# ---------------------------------------------------------------------------
# Plan building (pure reads — safe to run in the preview AND again on execute)
# ---------------------------------------------------------------------------

def _base_name(doc):
    """The file's name without Fusion's ' v12' version suffix."""
    name = None
    try:
        df = doc.dataFile
        if df:
            name = df.name
    except Exception:
        # Unsaved documents (and some offline states) have no dataFile.
        pass
    if not name:
        name = doc.name
    return re.sub(r'\s+v\d+$', '', name).strip()


def _fmt_len(des, db_value):
    """Database-units length (cm) as a bare number string in the design's
    default length units: 100.0 -> '1000' (mm), trailing zeros trimmed."""
    um = des.unitsManager
    v = um.convert(db_value, um.internalUnits, um.defaultLengthUnits)
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return ('%f' % v).rstrip('0').rstrip('.')


def _cell_length(des, cell, want_title):
    """Resolve a top-table Width/Height cell to a number string, or None.

    The column may hold the parameter directly, or (the common case) reference
    a row of a theme table whose parameter column carries the value.
    """
    ctype = cell.objectType.split('::')[-1]
    if ctype == 'ConfigurationParameterCell':
        return _fmt_len(des, cell.value)
    if ctype != 'ConfigurationThemeCell':
        return None
    theme_row = cell.referencedTableRow
    if not theme_row:
        return None
    theme_table = theme_row.parentTable
    # Prefer the theme column with the same title; else the first parameter cell.
    fallback = None
    for ci in range(theme_table.columns.count):
        col = theme_table.columns.item(ci)
        tcell = theme_table.getCell(ci, theme_row.index)  # getCell(column, row)!
        if tcell.objectType.split('::')[-1] != 'ConfigurationParameterCell':
            continue
        if (getattr(col, 'title', '') or '').strip().lower() == want_title:
            return _fmt_len(des, tcell.value)
        if fallback is None:
            fallback = _fmt_len(des, tcell.value)
    if fallback is not None:
        return fallback
    # Last resort: the theme row's own name is usually the size label ('1000').
    return theme_row.name or None


def _plan():
    """(base_name, [{'row', 'old', 'new'} ...], error_html_or_None)."""
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        return None, [], 'No active design.'
    if not getattr(des, 'isConfiguredDesign', False):
        return None, [], 'The active document is not a configured design.'

    table = des.configurationTopTable
    if not table:
        return None, [], 'No configuration table found.'

    width_ci = height_ci = None
    titles = []
    for ci in range(table.columns.count):
        title = (getattr(table.columns.item(ci), 'title', '') or '').strip()
        titles.append(title)
        if title.lower() == 'width':
            width_ci = ci
        elif title.lower() == 'height':
            height_ci = ci
    if width_ci is None or height_ci is None:
        return None, [], ('Could not find both a <b>Width</b> and a <b>Height</b> column '
                          f'in the configuration table. Columns found: {", ".join(titles)}.')

    base = _base_name(app.activeDocument)
    plan = []
    used = set()
    problems = []
    for ri in range(table.rows.count):
        row = table.rows.item(ri)
        w = _cell_length(des, table.getCell(width_ci, ri), 'width')
        h = _cell_length(des, table.getCell(height_ci, ri), 'height')
        if w is None or h is None:
            problems.append(f'<b>{row.name}</b>: could not read '
                            f'{"Width" if w is None else "Height"} — skipped.')
            continue
        new = f'{base}-{w}-{h}'
        # Two rows with the same W×H would collide on the same name.
        if new in used:
            n = 2
            while f'{new} ({n})' in used:
                n += 1
            new = f'{new} ({n})'
        used.add(new)
        plan.append({'row': ri, 'old': row.name, 'new': new})

    err = '<br>'.join(problems) if problems else None
    return base, plan, err


# ---------------------------------------------------------------------------
# Command events
# ---------------------------------------------------------------------------

def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    try:
        args.command.setDialogInitialSize(460, 320)
    except Exception:
        pass

    try:
        base, plan, err = _plan()
    except Exception as e:
        base, plan, err = None, [], f'Failed to read the configuration table:<br>{e}'

    lines = []
    if err:
        lines.append(err + '<br>')
    if plan:
        changing = [p for p in plan if p['old'] != p['new']]
        lines.append(f"File: <b>{base}</b> — {len(changing)} of {len(plan)} "
                     'configuration(s) will be renamed:<br>')
        for p in plan:
            if p['old'] == p['new']:
                lines.append(f"<b>{p['old']}</b> &nbsp;—&nbsp; <i>already correct</i>")
            else:
                lines.append(f"<b>{p['old']}</b> &nbsp;&rarr;&nbsp; <b>{p['new']}</b>")
    elif not err:
        lines.append('Nothing to rename.')

    box = inputs.addTextBoxCommandInput(PREVIEW_ID, '', '<br>'.join(lines), 12, True)
    try:
        box.isFullWidth = True
    except Exception:
        pass

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    # Recompute rather than trusting the preview — the table may have changed.
    base, plan, err = _plan()

    des = adsk.fusion.Design.cast(app.activeProduct)
    table = des.configurationTopTable if des else None
    renamed = 0
    skipped = 0
    failures = []
    for p in (plan or []):
        if p['old'] == p['new']:
            skipped += 1
            continue
        try:
            table.rows.item(p['row']).name = p['new']
            renamed += 1
        except Exception as e:
            # e.g. "Rename is unavailable because the Configured Design is
            # still being saved" while a cloud save is in flight.
            failures.append(f"{p['old']}: {e}")

    msg = f'Renamed {renamed} configuration(s).'
    if skipped:
        msg += f'\n{skipped} already had the correct name.'
    if err:
        msg += '\n\n' + re.sub(r'<[^>]+>', '', err.replace('<br>', '\n'))
    if failures:
        msg += '\n\nFailed:\n' + '\n'.join(failures)
        msg += '\n\nIf the design is still being saved, wait for the save to finish and run the command again.'
    ui.messageBox(msg, CMD_NAME)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
