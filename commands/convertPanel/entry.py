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

"""Set Type — classify selected components for WoodCraft's reports.

Pick one or more components (or their bodies) and choose what they are:
  - Panel      → a sheet good; flows into the cut list, nesting and the BOM panels.
  - Hardware   → a purchased item; flows into the BOM purchased-items section, with
                 a unit cost you enter here.
  - Countertop → a worktop slab; costed by area and edgebandable like a panel, but
                 NOT nested — it is bought as a slab or a cut length. The
                 Countertop command stamps this on what it builds; choose it here
                 for a worktop you modelled yourself.

Carcass Maker and Shelf Creator auto-classify what they build as panels; this
command classifies hand-modelled or imported components (and lets you re-type or
price existing ones). The classification lives on the component (config.WC_*) and
is saved with the document. All attribute writes go through commands/wc_attrs.py.
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

CMD_ID = f'{config.COMPANY_NAME}_convertPanel'
CMD_NAME = 'Set Type'
CMD_Description = (
    'Classify the selected components as WoodCraft panels or purchased hardware so '
    'the cut list, nesting and BOM can sort them. Hardware carries a unit cost for '
    'the BOM; pricing an assembly covers everything inside it (its children are not '
    'billed again). Carcass Maker / Shelf Creator already tag what they build as panels.'
)
IS_PROMOTED = True

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SEL_ID = 'cp_selection'
CAT_ID = 'cp_category'
MODE_ID = 'cp_purchase'
COST_ID = 'cp_cost'

# Dropdown order → category value. Index 0 is the default (Panel).
# 'Countertop' is here so a worktop modelled by hand can be classified the same
# way the Countertop command classifies the ones it builds — costed by area and
# edgebandable like a panel, but never nested (see config.WC_SHEET_LIKE).
CATEGORY_CHOICES = [
    ('Panel', config.WC_CAT_PANEL),
    ('Hardware (purchased)', config.WC_CAT_HARDWARE),
    ('Countertop (not nested)', config.WC_CAT_COUNTERTOP),
]

# Category → the word the confirmation message uses.
CATEGORY_LABELS = {
    config.WC_CAT_PANEL: 'panel',
    config.WC_CAT_HARDWARE: 'hardware item',
    config.WC_CAT_COUNTERTOP: 'countertop',
}

# Purchase-mode dropdown order → attribute value. Index 0 is the default (pack).
# Hardware modelled as an assembly (Minifix, hinge…) can be bought either way:
# as one pack with one price, or as separate parts each priced on its own.
MODE_CHOICES = [
    ('Complete pack — one price', config.WC_PURCHASE_PACK),
    ('Separate parts — sum of contents', config.WC_PURCHASE_SEPARATE),
]

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
        SEL_ID, 'Components', 'Select the components (or their bodies) to classify')
    sel.addSelectionFilter('Occurrences')
    sel.addSelectionFilter('SolidBodies')
    # Lets a PART document's root component be picked from the browser (a part
    # file has no occurrences to select). Guarded: an unknown filter name would
    # throw, and command_created swallows exceptions — killing the whole dialog.
    try:
        sel.addSelectionFilter('RootComponents')
    except Exception:
        futil.log('Set Type: RootComponents selection filter unavailable')
    sel.setSelectionLimits(1, 0)

    cat = inputs.addDropDownCommandInput(
        CAT_ID, 'Type', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(CATEGORY_CHOICES):
        cat.listItems.add(label, i == 0)

    mode = inputs.addDropDownCommandInput(
        MODE_ID, 'Purchased as', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(MODE_CHOICES):
        mode.listItems.add(label, i == 0)
    mode.isVisible = False   # shown only when Hardware is selected
    mode.tooltip = ('Only matters for hardware modelled as an assembly (Minifix, '
                    'hinge…): bill it as one pack at this price, or as separate '
                    'parts so reports sum the individually-priced parts inside.')

    cost = inputs.addStringValueInput(COST_ID, 'Unit cost', '0')
    cost.isVisible = False   # shown only for Hardware bought as a pack

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _component_of(entity):
    """Resolve a selection (an Occurrence, a body, or a root Component — the only
    way to pick a part document's own component) to its owning Component."""
    if entity.objectType == adsk.fusion.Occurrence.classType():
        return adsk.fusion.Occurrence.cast(entity).component
    if entity.objectType == adsk.fusion.BRepBody.classType():
        return adsk.fusion.BRepBody.cast(entity).parentComponent
    if entity.objectType == adsk.fusion.Component.classType():
        return adsk.fusion.Component.cast(entity)
    return None


def _selected_category(inputs):
    dd = inputs.itemById(CAT_ID)
    idx = dd.selectedItem.index if dd and dd.selectedItem else 0
    return CATEGORY_CHOICES[idx][1]


def _selected_mode(inputs):
    dd = inputs.itemById(MODE_ID)
    idx = dd.selectedItem.index if dd and dd.selectedItem else 0
    return MODE_CHOICES[idx][1]


def _parse_cost(text):
    """Float from the cost field, or None if it isn't a number."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _sync_for_category(inputs):
    """Match the purchase-mode/cost fields and the selection limit to the chosen
    type. Panels are classified in BATCH (unlimited selection); Hardware is
    one-at-a-time because each item also gets its own purchase mode and cost.
    Called ONLY from the Type/Purchased-as dropdowns' change — never from the
    selection's own change — so it can't disturb an in-progress multi-pick (see
    the selection-reentrancy project memory)."""
    is_hardware = _selected_category(inputs) == config.WC_CAT_HARDWARE
    is_pack = _selected_mode(inputs) == config.WC_PURCHASE_PACK
    inputs.itemById(MODE_ID).isVisible = is_hardware
    inputs.itemById(COST_ID).isVisible = is_hardware and is_pack
    sel = inputs.itemById(SEL_ID)
    if is_hardware:
        sel.setSelectionLimits(1, 1)        # exactly one component
        if sel.selectionCount > 1:
            sel.clearSelection()            # drop a batch picked while on Panel
    else:
        sel.setSelectionLimits(1, 0)        # 0 max = unlimited → convert all at once


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def command_input_changed(args: adsk.core.InputChangedEventArgs):
    # Only react to the dropdowns. We deliberately do NOT touch any input while
    # the SELECTION changes — mutating inputs there clears the in-progress pick, so
    # a batch selection would collapse to a single component.
    if args.input.id in (CAT_ID, MODE_ID):
        _sync_for_category(args.inputs)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    sel = inputs.itemById(SEL_ID)
    if not sel or sel.selectionCount <= 0:
        args.areInputsValid = False
        return
    if (_selected_category(inputs) == config.WC_CAT_HARDWARE
            and _selected_mode(inputs) == config.WC_PURCHASE_PACK):
        # Only a pack needs a price here; separate parts are priced one by one.
        cost = _parse_cost(inputs.itemById(COST_ID).value)
        args.areInputsValid = cost is not None and cost >= 0
    else:
        args.areInputsValid = True


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs
    sel: adsk.core.SelectionCommandInput = inputs.itemById(SEL_ID)

    category = _selected_category(inputs)
    is_hardware = category == config.WC_CAT_HARDWARE
    mode = _selected_mode(inputs)
    is_pack = mode == config.WC_PURCHASE_PACK
    cost = (_parse_cost(inputs.itemById(COST_ID).value) or 0.0) \
        if (is_hardware and is_pack) else 0.0

    # Snapshot ALL selected components BEFORE writing anything. Writing a component
    # attribute mutates the document, which invalidates the SelectionCommandInput's
    # live selection list mid-loop — Fusion then throws "invalid argument index" on
    # the next sel.selection(i) (only the first selection got processed). So resolve
    # every selection up front, then classify in a second pass. Classifying is
    # idempotent, so we don't de-dup (that check could wrongly drop distinct panels).
    comps = []
    for i in range(sel.selectionCount):
        comp = _component_of(sel.selection(i).entity)
        if comp:
            comps.append(comp)

    done = 0
    skipped = 0
    for comp in comps:
        if not wc_attrs.set_category(comp, category):
            skipped += 1
            futil.log(f'Set Type: could not classify "{getattr(comp, "name", "?")}" '
                      f'(referenced/read-only?)')
            continue
        if is_hardware:
            wc_attrs.set_purchase_mode(comp, mode)
            if is_pack:
                wc_attrs.set_cost(comp, cost)
            # 'separate': keep any stored pack cost — it is ignored while in this
            # mode, and switching back to pack recovers it without retyping.
        else:
            wc_attrs.remove_value(comp, config.WC_COST)      # meaningless on panels
            wc_attrs.remove_value(comp, config.WC_PURCHASE)
        done += 1

    label = CATEGORY_LABELS.get(category, 'item')
    plural = '' if done == 1 else 's'
    msg = f'Classified {done} component(s) as {label}{plural}.'
    if is_hardware and is_pack and cost:
        msg += f'\nUnit cost set to {cost:.2f} each (a pack price covers everything inside).'
    elif is_hardware and not is_pack:
        msg += ('\nPurchased as separate parts — reports sum the individually '
                'priced parts inside; price each with Set Type.')
    if skipped:
        msg += (f'\n{skipped} could not be updated — likely referenced/read-only. '
                f'Open the source design to classify those.')
    ui.messageBox(msg)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
