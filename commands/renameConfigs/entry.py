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
default length units (e.g. 'WC_CL_S1-1000-720').

Column titles vary across the library — wall cabinets say 'Width'/'Height',
base cabinets say 'Cabinet Width' and have no overall height at all (only
'Legs Height' / 'Countertop Height') — so the dialog carries two dropdowns,
pre-selected by a fuzzy title match, letting the user point Width/Height at any
column or skip Height entirely. The preview updates live; OK applies.
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
WIDTH_COL_ID = 'rc_width_col'
HEIGHT_COL_ID = 'rc_height_col'
NONE_LABEL = '— none —'

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


def _get_table():
    """(design, top_table, error_or_None) for the active document."""
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        return None, None, 'No active design.'
    if not getattr(des, 'isConfiguredDesign', False):
        return None, None, 'The active document is not a configured design.'
    table = des.configurationTopTable
    if not table:
        return None, None, 'No configuration table found.'
    return des, table, None


def _candidate_columns(table):
    """[(index, title)] of every value-bearing column (theme/parameter — skips
    property columns like Part Number, whose reads can hit the cloud)."""
    out = []
    for ci in range(table.columns.count):
        col = table.columns.item(ci)
        ctype = col.objectType.split('::')[-1]
        if ctype in ('ConfigurationThemeColumn', 'ConfigurationParameterColumn'):
            out.append((ci, (getattr(col, 'title', '') or '').strip()))
    return out


def _guess_column(candidates, word):
    """Best title match for 'width'/'height': exact title beats a title that
    contains the word as its LAST word ('Cabinet Width') beats any title merely
    containing it ('Legs Height'). Returns the title or None."""
    best, best_score = None, 0
    for _, title in candidates:
        t = title.lower()
        if t == word:
            score = 3
        elif t.endswith(' ' + word):
            score = 2
        elif word in t:
            score = 1
        else:
            continue
        if score > best_score:
            best, best_score = title, score
    return best


def _plan(width_title, height_title):
    """(base_name, [{'row', 'old', 'new'} ...], error_html_or_None) for the
    chosen columns. height_title may be None → names are '<File>-<Width>'."""
    des, table, err = _get_table()
    if err:
        return None, [], err

    lookup = {t: ci for ci, t in _candidate_columns(table)}
    width_ci = lookup.get(width_title)
    height_ci = lookup.get(height_title) if height_title else None
    if width_ci is None:
        return None, [], 'Pick the column that holds the cabinet width.'

    base = _base_name(app.activeDocument)
    plan = []
    used = set()
    problems = []
    for ri in range(table.rows.count):
        row = table.rows.item(ri)
        w = _cell_length(des, table.getCell(width_ci, ri), width_title.lower())
        h = (_cell_length(des, table.getCell(height_ci, ri), height_title.lower())
             if height_ci is not None else '')
        if w is None or h is None:
            problems.append(f'<b>{row.name}</b>: could not read '
                            f'{width_title if w is None else height_title} — skipped.')
            continue
        new = f'{base}-{w}-{h}' if h else f'{base}-{w}'
        # Two rows with the same size would collide on the same name.
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

def _selected_titles(inputs):
    """(width_title_or_None, height_title_or_None) from the two dropdowns."""
    def sel(input_id):
        dd = inputs.itemById(input_id)
        item = dd.selectedItem if dd else None
        name = item.name if item else None
        return None if (not name or name == NONE_LABEL) else name
    return sel(WIDTH_COL_ID), sel(HEIGHT_COL_ID)


def _preview_html(width_title, height_title):
    try:
        base, plan, err = _plan(width_title, height_title) if width_title else \
            (None, [], 'Pick the column that holds the cabinet width.')
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
    return '<br>'.join(lines)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    try:
        args.command.setDialogInitialSize(460, 380)
    except Exception:
        pass

    try:
        _, table, err = _get_table()
        candidates = _candidate_columns(table) if table else []
    except Exception:
        candidates, err = [], 'Failed to read the configuration table.'

    width_guess = _guess_column(candidates, 'width')
    height_guess = _guess_column(candidates, 'height')

    dd_w = inputs.addDropDownCommandInput(
        WIDTH_COL_ID, 'Width column', adsk.core.DropDownStyles.TextListDropDownStyle)
    for _, title in candidates:
        dd_w.listItems.add(title, title == width_guess)

    dd_h = inputs.addDropDownCommandInput(
        HEIGHT_COL_ID, 'Height column', adsk.core.DropDownStyles.TextListDropDownStyle)
    dd_h.listItems.add(NONE_LABEL, height_guess is None)
    for _, title in candidates:
        dd_h.listItems.add(title, title == height_guess)

    box = inputs.addTextBoxCommandInput(
        PREVIEW_ID, '', err or _preview_html(width_guess, height_guess), 12, True)
    try:
        box.isFullWidth = True
    except Exception:
        pass

    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    if args.input.id not in (WIDTH_COL_ID, HEIGHT_COL_ID):
        return
    # args.inputs may hold only the changed input's group — go via the command.
    inputs = args.firingEvent.sender.commandInputs
    box = inputs.itemById(PREVIEW_ID)
    if box:
        box.formattedText = _preview_html(*_selected_titles(inputs))


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    width_title, height_title = _selected_titles(args.command.commandInputs)
    if not width_title:
        ui.messageBox('Pick the column that holds the cabinet width.', CMD_NAME)
        return
    # Recompute rather than trusting the preview — the table may have changed.
    base, plan, err = _plan(width_title, height_title)

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
