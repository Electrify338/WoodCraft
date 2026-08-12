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

"""Inspect Panels (DEV) — list every classified WoodCraft component.

Temporary debugging aid: opens a dialog listing the count and each classified
component's category + name + cut size (L x W x T, mm), so you can verify
classification while the reports are being built. It previews exactly what the
reports collect — the shared category-driven collector (works across referenced
cabinets) — and cross-checks against design.findAttributes.

Safe to remove later: delete this folder and its two lines in commands/__init__.py.
It lives in its own Dev panel (segment) at the end of the WoodCraft tab.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import panels
from .. import wc_attrs
from .. import sheets_store
from .. import settings_store
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_inspectPanels'
CMD_NAME = 'Inspect Panels (dev)'
CMD_Description = 'DEV: list all classified WoodCraft components (panel/hardware), with cut sizes.'
IS_PROMOTED = True

PANEL_ID = config.DEV_PANEL_ID
PANEL_NAME = config.DEV_PANEL_NAME
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

RESULT_ID = 'ip_result'

local_handlers = []


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


def _dims_mm(component):
    """Sorted L, W, T in mm from the component's bounding box, or None."""
    try:
        bb = component.boundingBox
        ext = [(bb.maxPoint.x - bb.minPoint.x) * 10.0,
               (bb.maxPoint.y - bb.minPoint.y) * 10.0,
               (bb.maxPoint.z - bb.minPoint.z) * 10.0]
        ext.sort(reverse=True)
        return ext
    except Exception:
        return None


def _collect():
    """(findAttributes_count, [row dicts]) for every classified component, priced
    the same way the billed BOM prices them: hardware shows its billed unit cost
    (0 for a separate-parts assembly — its children carry the prices), panels show
    the sheet-derived estimate (None = unpriced material).

    Uses the shared collector so this dev view matches exactly what the reports see.
    """
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None, []

    materials = sheets_store.load()['materials']
    waste_mult = 1.0 + settings_store.get_waste_percent() / 100.0

    agg = {}
    order = []
    for it in panels.collect_instances(design):
        key = (it['comp_name'], it['category'])
        if key not in agg:
            if it['category'] in config.WC_SHEET_LIKE:
                unit = panels.estimate_panel_unit_cost(
                    it['material'], it['T'], it['L'], it['W'],
                    materials=materials, waste_mult=waste_mult)
                mode = ''
            else:
                unit = it['cost']    # 0 when bought as separate parts
                mode = wc_attrs.get_purchase_mode(it['component'])
            agg[key] = {'name': it['comp_name'], 'category': it['category'],
                        'dims': (it['L'], it['W'], it['T']), 'qty': 0,
                        'unit': unit, 'mode': mode}
            order.append(key)
        agg[key]['qty'] += 1

    try:
        # findAttributes returns a plain list of Attribute, not an API collection.
        fa_count = len(design.findAttributes(config.WC_GROUP, config.WC_CATEGORY))
    except Exception:
        fa_count = -1
    return fa_count, [agg[k] for k in order]


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    try:
        args.command.setDialogInitialSize(420, 460)
    except Exception:
        pass

    fa_count, rows = _collect()
    if fa_count is None:
        html = 'No active design.'
    elif not rows:
        html = f'No classified components found. (findAttributes count: {fa_count})'
    else:
        pieces = sum(r['qty'] for r in rows)
        lines = [f'<b>{pieces}</b> classified item(s) in <b>{len(rows)}</b> group(s) '
                 f'&nbsp;<i>(findAttributes: {fa_count})</i><br>']
        hw_total = 0.0
        panel_total = 0.0
        unpriced = 0
        for r in rows:
            dims = r['dims']
            q = f"{r['qty']}&times; " if r['qty'] > 1 else ''
            line = (f"<b>[{r['category']}]</b> {q}{r['name']}: &nbsp; "
                    f"{dims[0]:.1f} &times; {dims[1]:.1f} &times; {dims[2]:.1f} mm")
            if r['category'] in config.WC_SHEET_LIKE:
                if r['unit'] is None:
                    line += ' &nbsp;—&nbsp; <i>unpriced (no sheet cost)</i>'
                    unpriced += r['qty']
                else:
                    line += (f" &nbsp;—&nbsp; &asymp;{r['unit']:.2f} each = "
                             f"<b>&asymp;{r['unit'] * r['qty']:.2f}</b>")
                    panel_total += r['unit'] * r['qty']
            else:
                if r['mode'] == config.WC_PURCHASE_SEPARATE:
                    line += ' &nbsp;—&nbsp; <i>separate parts (children priced)</i>'
                elif r['unit'] > 0:
                    line += (f" &nbsp;—&nbsp; {r['unit']:.2f} each = "
                             f"<b>{r['unit'] * r['qty']:.2f}</b>")
                    hw_total += r['unit'] * r['qty']
                else:
                    line += ' &nbsp;—&nbsp; <i>no cost set</i>'
            lines.append(line)
        lines.append(f'<br><b>Panels &asymp;{panel_total:.2f} &nbsp;+&nbsp; '
                     f'hardware {hw_total:.2f} &nbsp;=&nbsp; '
                     f'&asymp;{panel_total + hw_total:.2f}</b>'
                     + (f' &nbsp;<i>({unpriced} panel(s) unpriced)</i>' if unpriced else ''))
        html = '<br>'.join(lines)

    box = inputs.addTextBoxCommandInput(RESULT_ID, '', html, 18, True)
    try:
        box.isFullWidth = True
    except Exception:
        pass

    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
