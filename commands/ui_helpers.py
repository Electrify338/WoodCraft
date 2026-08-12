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

"""Shared helpers for building WoodCraft's toolbar UI.

Every WoodCraft command lives in a single custom tab ("WoodCraft") inside the
Design workspace. Commands ask for the panel they belong to via get_panel() on
start and tear their button down via remove_command() on stop. The tab and its
panels are created lazily by the first command and cleaned up once the last
command has removed its button, so no single command "owns" the tab.
"""

import adsk.core

from .. import config
from . import wc_attrs

app = adsk.core.Application.get()
ui = app.userInterface


def get_panel(panel_id: str, panel_name: str) -> adsk.core.ToolbarPanel:
    """Return the named panel inside the WoodCraft tab, creating both if needed."""
    workspace = ui.workspaces.itemById(config.DESIGN_WORKSPACE_ID)

    tab = workspace.toolbarTabs.itemById(config.TAB_ID)
    if not tab:
        tab = workspace.toolbarTabs.add(config.TAB_ID, config.TAB_NAME)

    panel = tab.toolbarPanels.itemById(panel_id)
    if not panel:
        panel = tab.toolbarPanels.add(panel_id, panel_name)

    return panel


def remove_command(panel_id: str, cmd_id: str):
    """Remove a command button and its definition, then prune empty UI containers."""
    workspace = ui.workspaces.itemById(config.DESIGN_WORKSPACE_ID)

    tab = workspace.toolbarTabs.itemById(config.TAB_ID)
    if tab:
        panel = tab.toolbarPanels.itemById(panel_id)
        if panel:
            control = panel.controls.itemById(cmd_id)
            if control:
                control.deleteMe()
            # Drop the panel once it no longer holds any controls.
            if panel.controls.count == 0:
                panel.deleteMe()
        # Drop the whole tab once it holds no panels.
        if tab.toolbarPanels.count == 0:
            tab.deleteMe()

    cmd_def = ui.commandDefinitions.itemById(cmd_id)
    if cmd_def:
        cmd_def.deleteMe()


def tag_as_panel(component) -> bool:
    """Classify a component as a WoodCraft panel (idempotent) so the cut list and
    other output commands can find it regardless of how it was modelled. Returns
    False if it couldn't be written (e.g. a referenced/read-only component).

    Thin wrapper over wc_attrs.set_category so Carcass Maker / Shelf Creator keep a
    one-call auto-classify; richer classification lives in the Set Type command."""
    return wc_attrs.set_category(component, config.WC_CAT_PANEL)
