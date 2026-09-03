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

"""Finish Lists — choose what Set Finish offers, without leaving Fusion.

Set Finish has four dropdowns (Carcass Material, Carcass Appearance, Door Material,
Door Appearance) and each is filled from its own curated list of names held in
commands/finish_store.py. This command edits those lists:

    List      — which of the four you are editing.
    Library   — narrows the pool below; 'All libraries' spans every loaded one.
    Search    — narrows it further; matches anywhere in a name, ignoring case. The
                Fusion Material Library alone holds 324 materials, so this is the
                practical way to find one.
    Items     — a checkbox list of everything the filters leave, OF THE RIGHT KIND
                (materials for a Material list, appearances for an Appearance one).
                Ticked = in the list.

Everything is edited in one sitting and written on OK, so switching list, library or
search doesn't lose the ticks you just made.

Two behaviours worth knowing, both deliberate:

- Only what is currently DISPLAYED is read back. A name hidden by the library filter
  or the search box keeps its place in the list rather than being dropped — which is
  also why a name no loaded library offers any more survives untouched. It is
  reported in the summary so it can be removed from the JSON by hand.
- Ticks are harvested on every change, not just on OK. Fusion refills the list when
  you switch list, library or search, and anything not read back before that would
  be lost.
"""

import os

import adsk.core

from .. import ui_helpers
from .. import finish_store
from .. import material_pool
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_finishLists'
CMD_NAME = 'Finish Lists'
CMD_Description = (
    'Choose which materials and appearances Set Finish offers. Each of its four '
    'dropdowns (Carcass Material, Carcass Appearance, Door Material, Door Appearance) '
    'has its own list, picked from your loaded material libraries and saved to a JSON '
    'file alongside the rest of the WoodCraft library data.'
)
IS_PROMOTED = False        # a setup command, not part of the modelling flow

# Kitchen, not Cabinet Builder: both act on an assembled run of cabinets — the
# finish spec for a whole kitchen and the lists that feed it — rather than on one
# cabinet being modelled.
PANEL_ID = config.KITCHEN_PANEL_ID
PANEL_NAME = config.KITCHEN_PANEL_NAME

ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

CATEGORY_ID = 'fl_category'
LIBRARY_ID = 'fl_library'
SEARCH_ID = 'fl_search'
ITEMS_ID = 'fl_items'
INFO_ID = 'fl_info'

ALL_LIBRARIES = 'All libraries'

local_handlers = []

# Edits in progress: {list key: [names]}. Loaded on open, harvested on every change,
# written on OK. Order is preserved because it is the dropdown order in Set Finish,
# and that is the user's choice — newly ticked names are appended.
_pending = {}


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


# ---------------------------------------------------------------------------
# Dialog state
# ---------------------------------------------------------------------------
def _current_category(inputs) -> str:
    dropdown = inputs.itemById(CATEGORY_ID)
    item = dropdown.selectedItem if dropdown else None
    index = item.index if item else 0
    keys = finish_store.CATEGORY_KEYS
    return keys[index if 0 <= index < len(keys) else 0]


def _current_library(inputs):
    """The library name to draw from, or None for every loaded library."""
    dropdown = inputs.itemById(LIBRARY_ID)
    item = dropdown.selectedItem if dropdown else None
    if item is None or item.index <= 0:
        return None
    return item.name


def _search_text(inputs) -> str:
    """The search box, folded for matching. '' when empty or unreadable."""
    field = inputs.itemById(SEARCH_ID)
    try:
        return material_pool.fold(field.value) if field else ''
    except Exception:
        return ''


def _pool(category, library, search=''):
    """[(name, library, object)] for the current list and filters."""
    kind = finish_store.CATEGORY_KINDS.get(category, finish_store.KIND_MATERIAL)
    try:
        rows = material_pool.available(kind, [library] if library else None)
    except Exception:
        futil.handle_error('Finish Lists: reading the material libraries')
        return []
    if search:
        rows = [row for row in rows if search in material_pool.fold(row[0])]
    return rows


def _harvest(inputs, category):
    """Read the checkbox list back into `_pending[category]`.

    Only the items currently DISPLAYED are considered, so a name hidden by the
    library filter or the search box keeps its place — the same reason a name missing
    from every library survives. Ticked-and-absent is appended; unticked-and-present
    is removed."""
    items = inputs.itemById(ITEMS_ID)
    if not items:
        return
    kept = list(_pending.get(category, []))
    index = {material_pool.fold(name): i for i, name in enumerate(kept)}

    try:
        count = items.listItems.count
    except Exception:
        return
    for i in range(count):
        entry = items.listItems.item(i)
        name = entry.name
        at = index.get(material_pool.fold(name))
        if entry.isSelected and at is None:
            kept.append(name)
            index[material_pool.fold(name)] = len(kept) - 1
        elif not entry.isSelected and at is not None:
            kept[at] = None
    _pending[category] = [name for name in kept if name is not None]


def _rebuild_items(inputs, category, library):
    """Refill the checkbox list for the current list, library and search."""
    items = inputs.itemById(ITEMS_ID)
    if not items:
        return
    search = _search_text(inputs)
    chosen = {material_pool.fold(name) for name in _pending.get(category, [])}

    rows = _pool(category, library, search)
    items.listItems.clear()
    for name, _lib, _obj in rows:
        items.listItems.add(name, material_pool.fold(name) in chosen)

    futil.log(f'Finish Lists: {len(rows)} item(s) shown'
              + (f' for search {search!r}' if search else ''))


def _refresh_info(inputs):
    """Restate what is configured, including names no library currently offers."""
    info = inputs.itemById(INFO_ID)
    if not info:
        return
    # Resolve against EVERY library regardless of the current filter: "is this name
    # findable at all" is a different question from "is it in the library I'm
    # browsing right now".
    indexes = {}
    for kind in (finish_store.KIND_MATERIAL, finish_store.KIND_APPEARANCE):
        try:
            indexes[kind] = material_pool.lookup(kind)
        except Exception:
            indexes[kind] = {}

    lines = []
    for key, label, kind in finish_store.CATEGORIES:
        names = _pending.get(key, [])
        index = indexes.get(kind, {})
        absent = [n for n in names if material_pool.fold(n) not in index]
        # Name them rather than just counting: an entry no library offers can't be
        # shown in the list below, so the only way to remove it is to know what it
        # is called and edit the JSON.
        note = ''
        if absent:
            shown = ', '.join(absent[:3])
            more = f' +{len(absent) - 3} more' if len(absent) > 3 else ''
            note = f' — not in any library: {shown}{more}'
        lines.append(f'<b>{label}</b>: {len(names)} selected{note}')
    lines.append(f'Saved to {finish_store.lists_path()}')
    info.formattedText = '<br>'.join(lines)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    # First open writes the shipped defaults, so the dialog reflects what Set Finish
    # would actually offer rather than an empty file.
    try:
        material_pool.seed_appearance_defaults()
    except Exception:
        futil.handle_error('Finish Lists: seeding the defaults')

    global _pending
    stored = finish_store.load()
    _pending = {key: list(stored.get(key, [])) for key in finish_store.CATEGORY_KEYS}

    category_input = inputs.addDropDownCommandInput(
        CATEGORY_ID, 'List', adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (_key, label, _kind) in enumerate(finish_store.CATEGORIES):
        category_input.listItems.add(label, i == 0)
    category_input.tooltip = 'Which of Set Finish\'s four dropdowns you are editing.'

    library_input = inputs.addDropDownCommandInput(
        LIBRARY_ID, 'Library', adsk.core.DropDownStyles.TextListDropDownStyle)
    library_input.listItems.add(ALL_LIBRARIES, True)
    for name in material_pool.library_names():
        library_input.listItems.add(name, False)
    library_input.tooltip = ('Narrows the list below. Names you tick are stored '
                             'without their library, so moving a decor between '
                             'libraries later doesn\'t break the list.')

    search = inputs.addStringValueInput(SEARCH_ID, 'Search', '')
    search.tooltip = ('Show only entries whose name contains this text. Matches '
                      'anywhere in the name and ignores case. Clear it to see '
                      'everything again.')

    items = inputs.addDropDownCommandInput(
        ITEMS_ID, 'Items', adsk.core.DropDownStyles.CheckBoxDropDownStyle)
    items.tooltip = 'Tick everything this list should offer in Set Finish.'

    info = inputs.addTextBoxCommandInput(INFO_ID, '', '', 6, True)
    info.isFullWidth = True

    category = _current_category(inputs)
    _rebuild_items(inputs, category, _current_library(inputs))
    _refresh_info(inputs)

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    inputs = args.inputs
    changed = args.input
    category = _current_category(inputs)

    if changed.id == ITEMS_ID:
        # A tick changed: record it and update the summary, and DELIBERATELY nothing
        # else. Refilling a checkbox list from inside its own change event closes it,
        # so ticking a second item would mean reopening the list every time.
        _harvest(inputs, category)
        _refresh_info(inputs)
        return

    if changed.id in (CATEGORY_ID, LIBRARY_ID, SEARCH_ID):
        # The visible list is about to be replaced. Anything ticked since the last
        # harvest was already captured above, so just rebuild for the new view.
        _rebuild_items(inputs, category, _current_library(inputs))
        _refresh_info(inputs)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs
    _harvest(inputs, _current_category(inputs))

    data = finish_store.load()
    for key in finish_store.CATEGORY_KEYS:
        data[key] = _pending.get(key, [])
    try:
        written = finish_store.save(data)
    except Exception:
        futil.handle_error('Finish Lists: saving')
        ui.messageBox(f'Could not write {finish_store.lists_path()}.')
        return

    lines = [f'{label}: {len(written.get(key, []))} entr'
             f'{"y" if len(written.get(key, [])) == 1 else "ies"}'
             for key, label, _kind in finish_store.CATEGORIES]
    lines.append('')
    lines.append(f'Saved to {finish_store.lists_path()}')
    lines.append('Reopen Set Finish to see the new lists.')
    ui.messageBox('\n'.join(lines))


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers, _pending
    local_handlers = []
    _pending = {}
