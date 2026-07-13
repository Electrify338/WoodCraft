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
#                       Shelf Creator, Set Type).
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
# Component classification (attribute schema)
# ---------------------------------------------------------------------------
# Every WoodCraft-relevant component is stamped with invisible custom attributes,
# all under ONE group (WC_GROUP) as plain name/value pairs. Output commands
# (Cut List, BOM, labels) collect and split components by these. The scheme is a
# deliberately flat, extensible key/value store: a new command adds a new key
# constant here and reads/writes it through commands/wc_attrs.py — no schema churn,
# no migration. Attributes live on the component, are saved inside the .f3d, and
# survive across referenced cabinets and configuration changes.
WC_GROUP = 'WoodCraft'

# Category — what KIND of item the component is. Decides which BOM section it lands
# in and whether the cut list / nesting includes it. Carcass Maker and Shelf
# Creator stamp 'panel' automatically; Set Type classifies anything by hand.
WC_CATEGORY = 'category'
WC_CAT_PANEL = 'panel'          # sheet-good panel → cut list, nesting, BOM panels
WC_CAT_HARDWARE = 'hardware'    # purchased item   → BOM purchased-items only
WC_CATEGORIES = (WC_CAT_PANEL, WC_CAT_HARDWARE)

# Hardware unit cost (string-encoded float; currency is the user's own). Read back
# by the BOM and Cut List. Only meaningful on hardware components. Panels never
# store a cost — theirs is derived at report time from the Sheets library (avg
# sheet cost/m² × raw area, plus the Settings waste factor).
WC_COST = 'cost'

# How a hardware ASSEMBLY is purchased (hardware like a Minifix or a hinge is
# correctly modelled as an assembly, but can be bought either way):
#   'pack'     — one purchased unit: ITS cost applies and covers everything inside,
#                so reports never also bill its children. Default (a lone screw is
#                trivially its own pack).
#   'separate' — translucent: its parts are bought individually, so reports look
#                THROUGH it and sum the children's costs; a stored pack cost is
#                kept on the component but ignored (switching modes loses nothing).
WC_PURCHASE = 'purchase'
WC_PURCHASE_PACK = 'pack'
WC_PURCHASE_SEPARATE = 'separate'

# Edgeband — stamped on a panel's edge FACES (BRepFace), not the component: the
# value is the NAME of an edgeband from the Sheets library's band catalogue. The
# Edgeband command writes it; the BOM joins name → catalogue row at report time
# to price the summed edge lengths (cost per metre lives in the library, never
# on the face — same philosophy as panel costs being derived, never stored).
WC_EDGEBAND = 'edgeband'

# Future keys plug in here with no core change, e.g.:
#   WC_FINISH = 'finish'; WC_PART_NO = 'partNumber'