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

"""Appearance Config — build & maintain the appearance configuration table.

Automates the appearance-table half of a configured design: scan the assembly,
classify every part (door / carcass / skip) with reasons shown, let the user
review and OVERRIDE the plan in an HTML palette BEFORE anything mutates, then
build (or grow) the appearance table — one column per part occurrence, one row
per carcass×finish from the profile (commands/config_tables_store.py) — and
fill every cell per the rules. The same sweep doubles as a Verify & Fix pass
for tables built earlier (including by hand).

The heavy lifting lives in commands/appearance_tables.py; this module is the
launcher button (Kitchen panel) plus the JS↔Python palette bridge, mirroring
the Sheets palette.

Bridge actions (JS → Python via adsk.fusionSendData; reply via returnData):
  ready       -> {profile, path, doc}
  scan        -> {plan, table, appearances, expectedRows, ...} (read-only)
  build       -> persist overrides (opt) + apply plan, creating tables if needed
  fix         -> same sweep but refuses to create tables (verify+fill only)
  verify      -> read-only cell sweep report
  preview     -> point the active configuration at a chosen appearance row
  restore     -> undo preview
  open_source -> open the profile's cloud source document (appearance donor)
"""

import json
import os
import pathlib
import traceback

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import appearance_tables
from .. import config_tables_store
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_appearanceConfig'
CMD_NAME = 'Appearance Config'
CMD_Description = (
    'Build or fix the appearance configuration table of a cabinet assembly: '
    'scan and classify parts, review the plan, then generate the carcass × '
    'door-finish rows and fill every cell. Opens a docked panel.'
)
IS_PROMOTED = True

PANEL_ID = config.KITCHEN_PANEL_ID
PANEL_NAME = config.KITCHEN_PANEL_NAME
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

PALETTE_ID = f'{config.COMPANY_NAME}_appearanceConfig_palette'
PALETTE_NAME = 'Appearance Config'
# A proper file:// URI (forward slashes, percent-encoded) — a raw Windows path
# makes Fusion build a broken file:///C:/%5C... URL.
PALETTE_URL = pathlib.Path(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'resources', 'html', 'index.html')).as_uri()

local_handlers = []
palette_handlers = []

# Build/fix mutate thousands of cells and pump adsk.doEvents() for the progress
# dialog, which lets palette messages re-enter this handler — refuse them.
_busy = False


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
    # Launcher only: no inputs → the command auto-executes with no dialog and
    # clicking the button just opens the side panel.
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
            680, 720)
        try:
            palette.setMinimumSize(480, 420)
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
        # Guard against a stale palette that cached a bad URL from an earlier run.
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


def _overrides(data):
    role = data.get('roleOverrides') or {}
    group = data.get('groupOverrides') or {}
    role = {str(k): str(v) for k, v in role.items() if v in config.WC_ROLES}
    group = {str(k): str(v) for k, v in group.items() if v in ('include', 'exclude')}
    return role, group


def _scan_payload(design, data):
    """The palette's whole world-state: plan + table + appearance report."""
    profile = config_tables_store.load()
    role_ov, group_ov = _overrides(data)
    plan = appearance_tables.scan(design, profile, role_ov, group_ov)
    table = appearance_tables.table_status(design, plan)
    with_doors = any(p['role'] == config.WC_ROLE_DOOR for p in plan['parts'])
    return {
        'ok': True,
        'doc': app.activeDocument.name if app.activeDocument else '',
        # 'occs' holds live Occurrence proxies for the builder — not JSON-able.
        'plan': {k: v for k, v in plan.items() if k != 'occs'},
        'table': table,
        'appearances': appearance_tables.appearance_status(design, profile),
        'expectedRows': config_tables_store.expected_row_names(profile, with_doors),
        'roles': list(config.WC_ROLES),
        'profilePath': config_tables_store.profile_path(),
        'sourceDoc': profile.get('source_document', {}),
        # For the per-cabinet Custom Finish form: the scheme's palette.
        'finishOptions': {'carcasses': profile['carcasses'],
                          'finishes': profile['finishes']},
    }


def _apply(design, data, create):
    """Shared handler for build (create=True) and fix (create=False)."""
    profile = config_tables_store.load()
    role_ov, group_ov = _overrides(data)
    persisted = None
    if data.get('persist'):
        persisted = appearance_tables.persist_overrides(design, role_ov, group_ov)
    plan = appearance_tables.scan(design, profile, role_ov, group_ov)
    report = appearance_tables.apply_plan(design, plan, profile, ui, create=create)
    if persisted:
        report['persisted'] = persisted
    # Ship the refreshed world-state along so the palette re-renders in one trip.
    try:
        report['state'] = _scan_payload(design, data)
    except Exception:
        pass
    return report


def palette_incoming(args: adsk.core.HTMLEventArgs):
    global _busy
    action = args.action
    try:
        data = json.loads(args.data) if args.data else {}
    except Exception:
        data = {}

    if _busy:
        args.returnData = json.dumps(
            {'ok': False, 'error': 'A build is already running — wait for it to finish.'})
        return

    design = _active_design()
    try:
        if design is None and action != 'ready':
            result = {'ok': False, 'error': 'No active design — open the '
                      'kitchen/assembly document first.'}
        elif action == 'ready':
            result = {'ok': True,
                      'doc': app.activeDocument.name if app.activeDocument else '',
                      'profilePath': config_tables_store.profile_path(),
                      'profile': config_tables_store.load()}
        elif action == 'scan':
            result = _scan_payload(design, data)
        elif action in ('build', 'fix'):
            _busy = True
            try:
                result = _apply(design, data, create=(action == 'build'))
            finally:
                _busy = False
        elif action == 'verify':
            profile = config_tables_store.load()
            role_ov, group_ov = _overrides(data)
            plan = appearance_tables.scan(design, profile, role_ov, group_ov)
            if not design.isConfiguredDesign:
                result = {'ok': False, 'error': 'Not a configured design yet — '
                          'run Build first.'}
            else:
                result = {'ok': True,
                          'verify': appearance_tables.verify(
                              design, profile=profile, plan=plan)}
        elif action == 'custom_finish':
            _busy = True
            try:
                profile = config_tables_store.load()
                role_ov, group_ov = _overrides(data)
                group = str(data.get('group', ''))
                group_ov[group] = 'exclude'
                # The exclusion must OUTLIVE this session, or the next fix
                # pass re-adds columns and the theme paints over the custom
                # finish — so it is always persisted (role=skip on the
                # cabinet component).
                persisted = appearance_tables.persist_overrides(
                    design, {}, {group: 'exclude'})
                plan = appearance_tables.scan(design, profile, role_ov, group_ov)
                result = appearance_tables.apply_custom_finish(
                    design, plan, profile, ui, group,
                    str(data.get('carcass', '')), str(data.get('door', '')))
                result['persisted'] = persisted
                try:
                    merged = dict(data)
                    merged['groupOverrides'] = group_ov
                    result['state'] = _scan_payload(design, merged)
                except Exception:
                    pass
            finally:
                _busy = False
        elif action == 'preview':
            result = appearance_tables.preview(design, str(data.get('row', '')))
        elif action == 'restore':
            result = appearance_tables.restore(design)
        elif action == 'open_source':
            result = appearance_tables.open_source_document(config_tables_store.load())
        else:
            result = {'ok': False, 'error': f'unknown action: {action}'}
    except Exception:
        futil.handle_error('Appearance Config palette bridge')
        result = {'ok': False, 'error': traceback.format_exc(limit=3)}

    args.returnData = json.dumps(result)


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
