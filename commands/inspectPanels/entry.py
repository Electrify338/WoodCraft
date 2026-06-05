"""Inspect Panels (DEV) — list every component tagged as a WoodCraft panel.

Temporary debugging aid: opens a dialog listing the count and each tagged panel's
name + cut size (L x W x T, mm), so you can verify tagging while the cut list is
being built. It also previews exactly what the cut list will collect: it walks
root.allOccurrences and reads each component's panel attribute (works across
referenced cabinets), and cross-checks against design.findAttributes.

Safe to remove later: delete this folder and its two lines in commands/__init__.py.
It lives in its own Dev panel (segment) at the end of the WoodCraft tab.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import panels
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_inspectPanels'
CMD_NAME = 'Inspect Panels (dev)'
CMD_Description = 'DEV: list all components tagged as WoodCraft panels, with cut sizes.'
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
    """(findAttributes_count, [(name, dims_mm, qty), ...]) for tagged panels.

    Uses the shared collector so this dev view matches exactly what Cut List sees.
    """
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None, []

    agg = {}
    order = []
    for it in panels.collect_panel_instances(design):
        key = it['comp_name']
        if key not in agg:
            agg[key] = {'name': key, 'dims': (it['L'], it['W'], it['T']), 'qty': 0}
            order.append(key)
        agg[key]['qty'] += 1
    rows = [(agg[k]['name'], agg[k]['dims'], agg[k]['qty']) for k in order]

    try:
        fa_count = design.findAttributes(
            config.PANEL_ATTR_GROUP, config.PANEL_ATTR_NAME).count
    except Exception:
        fa_count = -1
    return fa_count, rows


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
        html = f'No tagged panels found. (findAttributes count: {fa_count})'
    else:
        pieces = sum(q for _, _, q in rows)
        lines = [f'<b>{pieces}</b> panel(s) in <b>{len(rows)}</b> unique size(s) '
                 f'&nbsp;<i>(findAttributes: {fa_count})</i><br>']
        for nm, dims, qty in rows:
            q = f'{qty}&times; ' if qty > 1 else ''
            lines.append(f'{q}{nm}: &nbsp; {dims[0]:.1f} &times; {dims[1]:.1f} &times; {dims[2]:.1f} mm')
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
