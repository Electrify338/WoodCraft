"""BOM — hierarchical Bill of Materials, as an HTML palette with Excel export.

Unlike Cut List & Nest (a cutting/nesting sheet), the BOM is the *structural* bill:
the assembly tree (root → components → sub-components), one row per component with
its Type, Dimensions, Material, Quantity and native Fusion **Part number**
(Component.partNumber). Fusion has no BOM API object, so we walk the occurrence
tree ourselves (panels.build_tree) and read native component properties.

The tree UI lives in resources/html/ (vanilla HTML/CSS/JS). Python here is just:
  - a launcher button (Output panel) that shows the palette, and
  - a thin bridge (incomingFromHTML): serve the tree, and export it to .xlsx
    (commands/xlsx_writer.py — pure stdlib, no openpyxl).

Bridge actions (JS -> Python via adsk.fusionSendData; reply via args.returnData):
  ready  -> {tree:[...], design:"...", config:"...", rows:N}
  export -> file Save dialog, writes a native .xlsx; {ok, path|cancelled}
"""

import json
import os
import pathlib

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import panels
from .. import report_utils
from .. import xlsx_writer
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_bom'
CMD_NAME = 'BOM'
CMD_Description = (
    'Open the Bill of Materials: the assembly hierarchy (component, type, '
    'dimensions, material, quantity, part number) with Export to Excel. Opens a '
    'docked panel.'
)
IS_PROMOTED = True

PANEL_ID = config.OUTPUT_PANEL_ID
PANEL_NAME = config.OUTPUT_PANEL_NAME
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

PALETTE_ID = f'{config.COMPANY_NAME}_bom_palette'
PALETTE_NAME = 'BOM — Bill of Materials'
# A proper file:// URI (forward slashes); a raw Windows path makes a broken URL.
PALETTE_URL = pathlib.Path(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'resources', 'html', 'index.html')).as_uri()

# Excel columns (header, width). Numbers stay numeric in the sheet. Panel costs
# are sheet-library estimates (raw area × avg cost/m² + waste factor); hardware
# costs are the values entered in Set Type.
XLSX_HEADERS = ['No.', 'Name', 'Type', 'Length (mm)', 'Width (mm)', 'Thickness (mm)',
                'Qty', 'Material', 'Part #', 'Unit cost', 'Total cost']
XLSX_WIDTHS = [10, 42, 12, 13, 13, 15, 6, 28, 18, 11, 12]

local_handlers = []
palette_handlers = []


def start():
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if not cmd_def:
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    global palette_handlers
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette:
        try:
            palette.deleteMe()
        except Exception:
            pass
    palette_handlers = []
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    # Launcher: open the palette and add NO inputs, so the command auto-executes
    # with no command dialog (clicking the button only opens the side panel).
    _show_palette()
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _show_palette():
    palette = ui.palettes.itemById(PALETTE_ID)
    if not palette:
        palette = ui.palettes.add(
            PALETTE_ID, PALETTE_NAME, PALETTE_URL,
            True,    # isVisible
            True,    # showCloseButton
            True,    # isResizable
            760, 620)
        try:
            palette.setMinimumSize(520, 360)
        except Exception:
            pass
        try:
            palette.dockingOption = adsk.core.PaletteDockOptions.PaletteDockOptionsToVerticalAndHorizontal
            palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        except Exception:
            pass
        futil.add_handler(palette.incomingFromHTML, palette_incoming,
                          local_handlers=palette_handlers)
    else:
        try:
            if palette.htmlFileURL != PALETTE_URL:
                palette.htmlFileURL = PALETTE_URL
        except Exception:
            pass
    palette.isVisible = True


# ---------------------------------------------------------------------------
# JS <-> Python bridge
# ---------------------------------------------------------------------------
def _active_design():
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design:
        return design
    try:
        doc = app.activeDocument
        if doc:
            return adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    except Exception:
        pass
    return None


def _design_name(design):
    try:
        return design.parentDocument.name
    except Exception:
        return 'WoodCraft'


def _active_config_name(design):
    """Active configuration name, or '' if the design isn't configured."""
    try:
        topt = design.configurationTopTable
        if topt and topt.activeRow:
            return topt.activeRow.name or ''
    except Exception:
        pass
    return ''


def _count_rows(tree):
    return sum(1 + _count_rows(n['children']) for n in tree)


def _payload():
    design = _active_design()
    tree = panels.build_tree(design) if design else []
    return {
        'tree': tree,
        'design': _design_name(design) if design else '',
        'config': _active_config_name(design) if design else '',
        'rows': _count_rows(tree),
        'totals': panels.tree_cost_totals(tree),
    }


def _xlsx_rows(tree):
    """Flatten the tree into (cells, outline_level) rows for xlsx_writer. Leaf dims
    are numeric; assemblies leave dims blank. The name is space-indented by depth so
    the hierarchy reads even with grouping collapsed. Ends with the billed-BOM
    totals block (panels estimate / hardware / grand total)."""
    rows = []
    for node, level in panels.flatten_tree(tree):
        has_dims = node['type'] != 'Assembly' and node['L'] > 0
        unit = node.get('unit_cost')
        cost = node.get('cost')
        rows.append(([
            node.get('no', ''),
            ('    ' * level) + node['name'],
            node['type'],
            round(node['L'], 1) if has_dims else '',
            round(node['W'], 1) if has_dims else '',
            round(node['T'], 1) if has_dims else '',
            node['qty'],
            node['material'] or '',
            node['part_number'] or '',
            round(unit, 2) if unit is not None else '',
            round(cost, 2) if cost is not None else '',
        ], level))

    totals = panels.tree_cost_totals(tree)
    if totals['grand'] or totals['unpriced_panels']:
        blank = [''] * len(XLSX_HEADERS)
        def total_row(label, value):
            cells = list(blank)
            cells[1] = label
            cells[-1] = round(value, 2)
            return (cells, 0)
        rows.append((blank, 0))
        rows.append(total_row('Panels (estimated)', totals['panels_est']))
        rows.append(total_row('Hardware', totals['hardware']))
        rows.append(total_row('TOTAL', totals['grand']))
        if totals['unpriced_panels']:
            cells = list(blank)
            cells[1] = (f"{totals['unpriced_panels']} panel(s) unpriced — no sheet "
                        f"cost for their material in the Sheets library")
            rows.append((cells, 0))
    return rows


def _export():
    design = _active_design()
    if not design:
        return {'ok': False, 'error': 'No active design.'}
    tree = panels.build_tree(design)
    if not tree:
        return {'ok': False, 'error': 'This design has no components to export.'}

    dlg = ui.createFileDialog()
    dlg.title = 'Export WoodCraft BOM'
    dlg.filter = 'Excel files (*.xlsx)'
    dlg.initialFilename = report_utils.safe_filename(_design_name(design)) + '_BOM.xlsx'
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:
        return {'ok': False, 'cancelled': True}

    xlsx_writer.write_xlsx(dlg.filename, XLSX_HEADERS, _xlsx_rows(tree),
                           sheet_name='BOM', col_widths=XLSX_WIDTHS)
    return {'ok': True, 'path': dlg.filename}


def palette_incoming(args: adsk.core.HTMLEventArgs):
    action = args.action
    try:
        data = json.loads(args.data) if args.data else {}
    except Exception:
        data = {}

    try:
        if action == 'ready':
            result = _payload()
        elif action == 'export':
            result = _export()
        else:
            result = {'ok': False, 'error': f'unknown action: {action}'}
    except Exception as e:
        futil.handle_error('BOM palette bridge')
        result = {'ok': False, 'error': str(e)}

    args.returnData = json.dumps(result)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
