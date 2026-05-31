# WoodCraft

A lightweight Autodesk Fusion add-in for cabinetmaking — a lean, open alternative
to tools like JoinerCAD, focused on turning a simple "skeleton" body into a set of
parametric panel components and joining them, without the bloat or subscription.

> **Status:** early development. Two features are working (Carcass Maker and Trim);
> more are planned. Toolbar icons are placeholders.

---

## Features

All commands live in a dedicated **WoodCraft** tab in the Design workspace, under
the **Cabinet Builder** panel.

### Carcass Maker
Turns the flat faces of a solid "skeleton" body (typically a box representing the
outer shell of a cabinet) into individual panel components.

- Select planar faces; each becomes its own component containing one panel body.
- Panels are extruded **directly from the skeleton face**, so they stay
  associatively linked — change the skeleton's parameters and the whole cabinet
  updates.
- Global defaults for **thickness**, **direction** (Inside / Outside / Symmetric)
  and **offset**, plus a per-panel **Advanced Control** table to override name,
  thickness, direction and offset for each panel individually.
- **Collect all flat faces** button grabs every flat face of a picked body in one
  click.
- On-screen name **labels** and direction **arrows** while the dialog is open,
  with the skeleton dimmed for readability; the skeleton is hidden once the
  panels are built.

Panels are intentionally left overlapping at the corners — that's what Trim is for.

### Trim
Cuts panels so they fit against each other, using Fusion's Combine (cut).

- Pick the **panels to trim** and the **panels to trim them with**.
- Optional **gap** leaves a uniform clearance/reveal between them (0 = flush cut),
  e.g. a reveal around a door or clearance so a bottom panel doesn't bind between
  two sides.

### Planned
Miter, shelves & dividers, materials, BOM, and CAM helpers (see
`JoinerCAD_Addon_Analysis.md` for the broader reference set this is modelled on).

---

## Installation

This is a standard Fusion **Python add-in**.

1. Copy/clone this folder into your Fusion add-ins directory:
   - **Windows:** `%appData%\Autodesk\Autodesk Fusion 360\API\AddIns\WoodCraft`
2. In Fusion, open **Utilities → Add-Ins → Scripts and Add-Ins** (or press
   `Shift+S`).
3. On the **Add-Ins** tab, select **WoodCraft** and click **Run**. Tick *Run on
   Startup* if you want it loaded automatically.
4. Switch to the **Design** workspace — the **WoodCraft** tab appears in the
   toolbar.

Requires a Fusion version with the `OffsetFacesFeatures` and `CombineFeatures`
APIs (current releases). Windows is the declared supported OS in the manifest.

---

## Usage

**Build a carcass**
1. Model a solid box at the cabinet's outer dimensions (the "skeleton").
2. Run **Cabinet Builder → Carcass Maker**.
3. Click a face (or use **Collect all flat faces**), set thickness/direction/offset,
   tweak individual panels in the table if needed, and click **OK**.

**Trim the joints**
1. Run **Cabinet Builder → Trim**.
2. Select the panels to trim, then the panels to trim them with, set a gap if you
   want clearance, and click **OK**.

---

## Project layout

```
WoodCraft/
├── WoodCraft.py              # add-in entry point (run/stop)
├── WoodCraft.manifest        # Fusion add-in manifest
├── config.py                 # shared ids: company, tab, panel names
├── commands/
│   ├── __init__.py           # registers the commands
│   ├── ui_helpers.py         # shared tab/panel creation + teardown
│   ├── dressUp/              # Carcass Maker command
│   └── trim/                 # Trim command
├── lib/fusionAddInUtils/     # Autodesk add-in template helpers (logging, events)
├── docs/UI_GUIDE.md          # icon/UI guide for design work
└── JoinerCAD_Addon_Analysis.md   # reference analysis of the tool this mimics
```

Each command is a self-contained folder with an `entry.py` exposing `start()` and
`stop()`. To add one, create the folder, import it in `commands/__init__.py`, and
append it to the `commands` list. See `docs/UI_GUIDE.md` for the toolbar/icon
conventions and the IDs that must stay stable.

---

## Notes & known limitations

- **Icons are placeholders** (copied from the Fusion sample add-in). The
  Defaults/Delete/Collect actions render as checkbox-style buttons until real icon
  resources are added — see `docs/UI_GUIDE.md`.
- The Trim **gap** is positive (clearance) only; a negative-offset "groove" mode
  was explored and removed because Fusion lacks a clean uniform solid-offset API.
- Author: Abdelrahman Youssry.
