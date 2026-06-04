# Application Global Variables
# This module serves as a way to share variables across different
# modules (global variables).

import os

# Flag that indicates to run in Debug mode or not. When running in Debug mode
# more information is written to the Text Command window. Generally, it's useful
# to set this to True while developing an add-in and set it to False when you
# are ready to distribute it.
DEBUG = True

# Gets the name of the add-in from the name of the folder the py file is in.
# This is used when defining unique internal names for various UI elements 
# that need a unique name. It's also recommended to use a company name as 
# part of the ID to better ensure the ID is unique.
ADDIN_NAME = os.path.basename(os.path.dirname(__file__))
COMPANY_NAME = 'WoodCraft'

# ---------------------------------------------------------------------------
# UI layout
# ---------------------------------------------------------------------------
# All WoodCraft commands live in a dedicated tab inside the Design workspace.
# The tab is created on demand by the first command that starts (see
# commands/ui_helpers.py) and removed when the last command stops.
DESIGN_WORKSPACE_ID = 'FusionSolidEnvironment'

TAB_ID = f'{COMPANY_NAME}_tab'
TAB_NAME = 'WoodCraft'

# Toolbar panels (groups of related commands inside the tab). The id is kept
# stable for backwards compatibility; only the display name changes.
#
# Commands are split across two panels so the modelling step and the
# hardware/machining step read as distinct groups in the toolbar (the gap
# between panels acts as the separator):
#   - Cabinet Builder : modelling commands (Carcass Maker, Trim, Edit
#                       Thickness, Shelf Creator).
#   - Hardware        : cut panels with hardware cut points (Sculpt). A separate
#                       output panel (BOM, Labels) can be added later.
DRESSUP_PANEL_ID = f'{COMPANY_NAME}_dressup_panel'
DRESSUP_PANEL_NAME = 'Cabinet Builder'

HARDWARE_PANEL_ID = f'{COMPANY_NAME}_hardware_panel'
HARDWARE_PANEL_NAME = 'Hardware'

# ---------------------------------------------------------------------------
# Hardware library
# ---------------------------------------------------------------------------
# The Insert Hardware command reads its catalogue from a dedicated Fusion cloud
# project whose top-level folders are the hardware categories (e.g. "Hinges",
# "Connectors", "Dowels") and whose files are the individual hardware parts.
# Set this to the EXACT display name of that project. If the command can't find
# it, the dialog lists the projects it CAN see so you can copy the right name.
HARDWARE_PROJECT_NAME = 'WoodCraft Hardware'