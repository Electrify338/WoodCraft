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

# Toolbar panels (groups of related commands inside the tab). Commands are split
# across panels so each step reads as a distinct group (the gap between panels
# acts as the separator):
#   - Cabinet Builder : modelling commands (Carcass Maker, Trim, Edit Thickness,
#                       Shelf Creator, Convert to Panel).
#   - Hardware        : Insert Hardware + Sculpt (place parts, cut their holes).
#   - Output / Dev    : reports and debug tools (see below).
CABINET_PANEL_ID = f'{COMPANY_NAME}_cabinet_panel'
CABINET_PANEL_NAME = 'Cabinet Builder'

HARDWARE_PANEL_ID = f'{COMPANY_NAME}_hardware_panel'
HARDWARE_PANEL_NAME = 'Hardware'

# Output / production reports (Sheets stock library + Cut List & Nest today;
# BOM, labels later).
OUTPUT_PANEL_ID = f'{COMPANY_NAME}_output_panel'
OUTPUT_PANEL_NAME = 'Output'

# Developer / debug tools — kept in their own segment so they're easy to find
# and easy to strip out before release.
DEV_PANEL_ID = f'{COMPANY_NAME}_dev_panel'
DEV_PANEL_NAME = 'Dev'

# ---------------------------------------------------------------------------
# Hardware library
# ---------------------------------------------------------------------------
# The Insert Hardware command reads its catalogue from a dedicated Fusion cloud
# project whose top-level folders are the hardware categories (e.g. "Hinges",
# "Connectors", "Dowels") and whose files are the individual hardware parts.
# Set this to the EXACT display name of that project. If the command can't find
# it, the dialog lists the projects it CAN see so you can copy the right name.
HARDWARE_PROJECT_NAME = 'WoodCraft Hardware'

# ---------------------------------------------------------------------------
# Panel tagging
# ---------------------------------------------------------------------------
# WoodCraft stamps every panel component with this invisible custom attribute so
# later output commands (cut list, BOM, labels) can reliably collect "the panels"
# regardless of how the model was built — including across referenced cabinets.
# Carcass Maker and Shelf Creator tag automatically; the Convert to Panel command
# tags hand-modelled or imported components. The tag is saved inside the .f3d.
PANEL_ATTR_GROUP = 'WoodCraft'
PANEL_ATTR_NAME = 'panel'
PANEL_ATTR_VALUE = 'true'