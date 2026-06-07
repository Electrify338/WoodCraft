"""Set Type — classify selected components for WoodCraft's reports.

Pick one or more components (or their bodies) and choose what they are:
  - Panel    → a sheet good; flows into the cut list, nesting and the BOM panels.
  - Hardware → a purchased item; flows into the BOM purchased-items section, with
               a unit cost you enter here.

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
    'the BOM. Carcass Maker / Shelf Creator already tag what they build as panels.'
)
IS_PROMOTED = True

PANEL_ID = config.CABINET_PANEL_ID
PANEL_NAME = config.CABINET_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

SEL_ID = 'cp_selection'
CAT_ID = 'cp_category'
COST_ID = 'cp_cost'

# Dropdown order → category value. Index 0 is the default (Panel).
CATEGORY_CHOICES = [
    ('Panel', config.WC_CAT_PANEL),
    ('Hardware (purchased)', config.WC_CAT_HARDWARE),
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
    sel.setSelectionLimits(1, 0)

    cat = inputs.addDropDownCommandInput(
        CAT_ID, 'Type', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (label, _value) in enumerate(CATEGORY_CHOICES):
        cat.listItems.add(label, i == 0)

    cost = inputs.addStringValueInput(COST_ID, 'Unit cost', '0')
    cost.isVisible = False   # shown only when Hardware is selected

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _component_of(entity):
    """Resolve a selection (an Occurrence or a body) to its owning Component."""
    if entity.objectType == adsk.fusion.Occurrence.classType():
        return adsk.fusion.Occurrence.cast(entity).component
    if entity.objectType == adsk.fusion.BRepBody.classType():
        return adsk.fusion.BRepBody.cast(entity).parentComponent
    return None


def _selected_category(inputs):
    dd = inputs.itemById(CAT_ID)
    idx = dd.selectedItem.index if dd and dd.selectedItem else 0
    return CATEGORY_CHOICES[idx][1]


def _parse_cost(text):
    """Float from the cost field, or None if it isn't a number."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _sync_for_category(inputs):
    """Match the cost field and the selection limit to the chosen type. Panels are
    classified in BATCH (unlimited selection); Hardware is one-at-a-time because
    each item also gets its own cost. Called ONLY from the Type dropdown's change —
    never from the selection's own change — so it can't disturb an in-progress
    multi-pick (see the selection-reentrancy project memory)."""
    is_hardware = _selected_category(inputs) == config.WC_CAT_HARDWARE
    inputs.itemById(COST_ID).isVisible = is_hardware
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
    # Only react to the Type dropdown. We deliberately do NOT touch any input while
    # the SELECTION changes — mutating inputs there clears the in-progress pick, so
    # a batch selection would collapse to a single component.
    if args.input.id == CAT_ID:
        _sync_for_category(args.inputs)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    sel = inputs.itemById(SEL_ID)
    if not sel or sel.selectionCount <= 0:
        args.areInputsValid = False
        return
    if _selected_category(inputs) == config.WC_CAT_HARDWARE:
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
    cost = _parse_cost(inputs.itemById(COST_ID).value) or 0.0 if is_hardware else 0.0

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
            wc_attrs.set_cost(comp, cost)
        else:
            wc_attrs.remove_value(comp, config.WC_COST)   # cost is meaningless on panels
        done += 1

    label = 'panel' if category == config.WC_CAT_PANEL else 'hardware item'
    plural = '' if done == 1 else 's'
    msg = f'Classified {done} component(s) as {label}{plural}.'
    if is_hardware and cost:
        msg += f'\nUnit cost set to {cost:.2f} each.'
    if skipped:
        msg += (f'\n{skipped} could not be updated — likely referenced/read-only. '
                f'Open the source design to classify those.')
    ui.messageBox(msg)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
