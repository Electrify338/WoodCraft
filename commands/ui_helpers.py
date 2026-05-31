"""Shared helpers for building WoodCraft's toolbar UI.

Every WoodCraft command lives in a single custom tab ("WoodCraft") inside the
Design workspace. Commands ask for the panel they belong to via get_panel() on
start and tear their button down via remove_command() on stop. The tab and its
panels are created lazily by the first command and cleaned up once the last
command has removed its button, so no single command "owns" the tab.
"""

import adsk.core

from .. import config

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
