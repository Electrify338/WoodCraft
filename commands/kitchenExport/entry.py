"""Kitchen Export — the finished kitchen as a one-line-per-cabinet spreadsheet.

Run this on the completed kitchen assembly. It walks the TOP-LEVEL components
(the direct children of the root — one per cabinet placed in the kitchen) and
writes a native .xlsx with one row each:

    Cabinet model name | Cabinet width (mm) | Carcass material |
    Carcass Type | Door material | Door Type

Where each column comes from
----------------------------
- **Model name** — the Fusion component name of the cabinet.
- **Width** — the X extent of the component's OWN bounding box, i.e. measured in
  the cabinet's local frame. Local rather than world so a cabinet rotated onto
  the other leg of an L-shaped kitchen still reports its width and not its
  depth. If a cabinet reads as ~600 mm when you expect 400, that component was
  modelled with its width along Y — rotate the geometry, not the placement.
- **Carcass / Door material** — the Fusion physical material of the panels
  inside, split by name: a panel whose name contains 'door', 'drawer' or 'front'
  (config.DOOR_PANEL_KEYWORDS) feeds the Door column, everything else feeds the
  Carcass column. The rules live in commands/kitchen_schedule.py.
- **Carcass / Door Type** — Painted or Veneer, as recorded by the **Cabinet
  Data** command. Blank means that cabinet hasn't been specced yet; the dialog
  tells you how many are missing before you export.

What counts as a cabinet
------------------------
A direct child of the root that is an assembly (it has sub-components) or that
has been specced with Cabinet Data. Countertops, loose panels and purchased
hardware sitting at the top level are skipped — they are tagged as WoodCraft
panels/hardware and are not cabinets.

One row per placed cabinet, not per unique model: three identical base units
give three rows, so the sheet is a build list you can tick off. Group them in
Excel if you want quantities.
"""

import os

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import panels as panels_util
from .. import kitchen_schedule
from .. import report_utils
from .. import wc_attrs
from .. import xlsx_writer
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_kitchenExport'
CMD_NAME = 'Kitchen Export'
CMD_Description = (
    'Export the finished kitchen as a spreadsheet — one row per cabinet with its '
    'model name, width, carcass and door materials (read from the panels\' Fusion '
    'materials) and the Painted/Veneer types recorded by Cabinet Data.'
)
IS_PROMOTED = True

PANEL_ID = config.KITCHEN_PANEL_ID
PANEL_NAME = config.KITCHEN_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SUMMARY_ID = 'ke_summary'

XLSX_HEADERS = ['Cabinet model name', 'Cabinet width (mm)', 'Carcass material',
                'Carcass Type', 'Door material', 'Door Type']
XLSX_WIDTHS = [38, 18, 30, 14, 30, 12]

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

    # The command has nothing to configure, so the dialog is a preflight report:
    # what it found and what is missing, checked BEFORE you pick a filename.
    summary = inputs.addTextBoxCommandInput(SUMMARY_ID, '', _summary_html(), 8, True)
    summary.isFullWidth = True

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Reading the design
# ---------------------------------------------------------------------------
def _active_design():
    return adsk.fusion.Design.cast(app.activeProduct)


def _design_name(design):
    try:
        return design.parentDocument.name
    except Exception:
        return 'Kitchen'


def _is_cabinet(occurrence) -> bool:
    """A top-level occurrence that represents a cabinet.

    An assembly (it has sub-components) or anything already specced with Cabinet
    Data. Explicitly NOT anything tagged as a WoodCraft panel or hardware item —
    that rules out countertops, loose shelves and purchased parts dropped at the
    top level, which are parts of the kitchen but not cabinets in it.
    """
    comp = occurrence.component
    if wc_attrs.is_panel(comp) or wc_attrs.is_hardware(comp):
        return False
    if wc_attrs.has_cabinet_data(comp):
        return True
    try:
        return occurrence.childOccurrences.count > 0
    except Exception:
        return False


def _descendants(occurrence):
    """Every occurrence inside `occurrence`, at any depth."""
    out = []
    try:
        children = occurrence.childOccurrences
    except Exception:
        return out
    for i in range(children.count):
        child = children.item(i)
        out.append(child)
        out.extend(_descendants(child))
    return out


def _cabinet_panels(occurrence):
    """(component_name, material_name) for every panel inside a cabinet.

    Prefers WoodCraft's own classification; falls back to "a leaf component that
    owns bodies" so a cabinet modelled by hand — or imported — still reports its
    materials instead of coming back blank. Hardware is always excluded: a
    purchased hinge's material must not decide the carcass column.
    """
    found = []
    for occ in _descendants(occurrence):
        comp = occ.component
        if wc_attrs.is_hardware(comp):
            continue
        if not wc_attrs.is_panel(comp):
            try:
                is_leaf_solid = (comp.bRepBodies.count > 0
                                 and occ.childOccurrences.count == 0)
            except Exception:
                is_leaf_solid = False
            if not is_leaf_solid:
                continue
        found.append((comp.name, panels_util.panel_material(comp)))
    return found


def _width_mm(comp, cache):
    """Width in mm — the X extent of the component's own bounding box.

    Component.boundingBox spans the whole subtree and Fusion computes it by
    touching every body, so it costs real time on an assembly (panels.py says as
    much). Cached per component name — Fusion keeps those unique in a document —
    because a kitchen repeats the same models many times over.
    """
    key = comp.name
    if key in cache:
        return cache[key]
    width = None
    try:
        bb = comp.boundingBox
        width = (bb.maxPoint.x - bb.minPoint.x) * 10.0
    except Exception:
        futil.log(f'Kitchen Export: could not measure "{key}"')
    cache[key] = width
    return width


def _rows(design):
    """(rows, missing_spec) — the spreadsheet body plus a count of un-specced
    cabinets, so the dialog can warn before anything is written."""
    root = design.rootComponent
    cache = {}
    rows = []
    missing = 0

    occurrences = root.occurrences
    for i in range(occurrences.count):
        occ = occurrences.item(i)
        if not _is_cabinet(occ):
            continue
        comp = occ.component
        carcass_type = wc_attrs.get_carcass_type(comp)
        door_type = wc_attrs.get_door_type(comp)
        if not carcass_type or not door_type:
            missing += 1
        rows.append(kitchen_schedule.schedule_row(
            comp.name, _width_mm(comp, cache), _cabinet_panels(occ),
            carcass_type, door_type))

    rows.sort(key=lambda r: str(r[0]).lower())
    return rows, missing


def _summary_html():
    """The preflight text shown in the dialog."""
    design = _active_design()
    if not design:
        return '<b>No active design.</b>'
    try:
        rows, missing = _rows(design)
    except Exception:
        futil.handle_error('Kitchen Export: summary')
        return '<b>Could not read this design.</b>'

    if not rows:
        return ('<b>No cabinets found.</b><br/>'
                'This looks for the top-level components of the design — the '
                'cabinets placed in the kitchen assembly. Components tagged as '
                'panels or hardware are skipped.')

    no_material = sum(1 for r in rows if not r[2] and not r[4])
    lines = [f'<b>{len(rows)} cabinet(s)</b> ready to export.']
    if missing:
        lines.append(f'{missing} have no Carcass/Door Type yet — run '
                     f'<b>Cabinet Data</b> on them to fill those columns.')
    if no_material:
        lines.append(f'{no_material} have no Fusion material on their panels, so '
                     f'their material columns will be blank.')
    lines.append('OK to choose where to save the spreadsheet.')
    return '<br/>'.join(lines)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    args.areInputsValid = _active_design() is not None


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    try:
        _export()
    except Exception:
        futil.handle_error('Kitchen Export: failed', show_message_box=True)


def _export():
    design = _active_design()
    if not design:
        ui.messageBox('No active design.')
        return

    rows, missing = _rows(design)
    if not rows:
        ui.messageBox('No cabinets found at the top level of this design.')
        return

    dlg = ui.createFileDialog()
    dlg.title = 'Export kitchen schedule'
    dlg.filter = 'Excel files (*.xlsx)'
    dlg.initialFilename = report_utils.safe_filename(_design_name(design)) + '_Kitchen.xlsx'
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:
        return

    xlsx_writer.write_xlsx(dlg.filename, XLSX_HEADERS,
                           [(row, 0) for row in rows],
                           sheet_name='Kitchen', col_widths=XLSX_WIDTHS)

    msg = f'Exported {len(rows)} cabinet(s) to:\n{dlg.filename}'
    if missing:
        msg += (f'\n\n{missing} cabinet(s) had no Carcass/Door Type — those cells '
                f'are blank. Run Cabinet Data on them and export again.')
    ui.messageBox(msg)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
