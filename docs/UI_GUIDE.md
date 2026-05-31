# WoodCraft — UI / Icon Guide for Agents

This document is for agents (or people) working on the **visual side** of the
WoodCraft add-in: command icons, the toolbar tab, and any future palettes. It
describes what the code already wires up so you know exactly which files to
touch and which names/IDs to honour. **Do not rename IDs** — they are how the
runtime finds and removes UI elements.

---

## 1. Where the UI lives

WoodCraft adds a dedicated tab to Fusion's **Design** workspace. Everything is
built at runtime from Python; there is no static UI definition file.

```
Design workspace (FusionSolidEnvironment)
└── Tab:  "WoodCraft"             id = WoodCraft_tab
    └── Panel: "Cabinet Builder"  id = WoodCraft_dressup_panel
        ├── Carcass Maker  (button) id = WoodCraft_dressUp
        ├── Trim           (button) id = WoodCraft_trim
        ├── Edit Thickness (button) id = WoodCraft_editThickness
        └── Shelf Creator  (button) id = WoodCraft_shelf
```

All of these IDs are defined in [`config.py`](../config.py). The tab and panel
are created lazily by the first command that starts and removed when the last
command stops — see [`commands/ui_helpers.py`](../commands/ui_helpers.py). When
you add a new panel or tab, add its ID/name constants to `config.py`, never
hard-code strings in command files.

---

## 2. Command icons

Each command points at a `resources/` folder next to its `entry.py` via the
`ICON_FOLDER` constant. Fusion looks inside that folder for these exact
filenames:

| File        | Used for                                  |
|-------------|-------------------------------------------|
| `16x16.png` | Small toolbar / list views                |
| `32x32.png` | Standard toolbar button                   |
| `64x64.png` | High-DPI displays                         |

Optional but recommended (Fusion will use them if present):

| File        | Used for                                  |
|-------------|-------------------------------------------|
| `96x96.png` | Extra high-DPI                            |
| `disabled-16x16.png` / `disabled-32x32.png` / `disabled-64x64.png` | Greyed-out state when the command is unavailable |

### Current state — custom artwork

Each command's `resources/` folder holds **custom WoodCraft icons** (16/32/64).
To restyle a command, replace the PNGs in place using the **same filenames** —
no code change is needed.

Icon folders:

| Command        | Folder                                          |
|----------------|-------------------------------------------------|
| Carcass Maker  | `commands/dressUp/resources/`                   |
| Trim           | `commands/trim/resources/`                      |
| Edit Thickness | `commands/editThickness/resources/`             |
| Shelf Creator  | `commands/shelf/resources/`                     |

> Note: the **folder names differ from the display names** (Carcass Maker lives
> in `dressUp/`, Shelf Creator in `shelf/`, Edit Thickness in `editThickness/`).
> The folder name is internal; the display name comes from `CMD_NAME` in each
> `entry.py`. If you find stray icon-only folders like `panelThickness/` or
> `shelfCreator/`, they are leftovers and not used by any command.

There is also a top-level [`AddInIcon.svg`](../AddInIcon.svg) (referenced by
`WoodCraft.manifest`) used as the add-in's icon in Fusion's Scripts & Add-Ins
dialog.

### Icon design notes
- PNG, transparent background, square.
- Keep the glyph readable at 16×16 — simple silhouettes, not fine detail.
- Match Fusion's monochrome/line-art toolbar style so buttons feel native.
- Motif ideas: **Carcass Maker** = a box turning into separated panels;
  **Trim** = a panel with a notch where another panel meets it;
  **Edit Thickness** = a panel with a thickness arrow;
  **Shelf Creator** = a shelf spanning between two sides.

### Dialog action-button icons
The Carcass Maker dialog has three in-dialog action buttons — **Collect all flat
faces**, **Reset rows to defaults**, and **Delete selected row** — created as
icon `BoolValueInput`s (non-checkbox) that reset themselves after firing. Each
points at its own icon sub-folder under the command's `resources/`:

| Button         | Icon sub-folder                          | id (in `entry.py`) |
|----------------|------------------------------------------|--------------------|
| Collect faces  | `commands/dressUp/resources/collect/`    | `COLLECT_BTN_ID`   |
| Reset defaults | `commands/dressUp/resources/defaults/`   | `DEFAULTS_BTN_ID`  |
| Delete row     | `commands/dressUp/resources/delete/`     | `DELETE_BTN_ID`    |

Each sub-folder holds its own 16/32/64 PNGs. (A non-checkbox `BoolValueInput`
*must* have a valid icon folder — an empty one throws and silently aborts the
dialog setup, so always keep these populated.)

---

## 3. Adding a new command (for reference)

The pattern every command follows (see `commands/dressUp/entry.py` as the
reference implementation):

1. Create `commands/<name>/` with `__init__.py` (empty), `entry.py`, and a
   `resources/` folder holding the three PNGs.
2. In `entry.py` define `CMD_ID`, `CMD_NAME`, `PANEL_ID`, `ICON_FOLDER`, and
   `start()` / `stop()`. Use `ui_helpers.get_panel(...)` in `start()` and
   `ui_helpers.remove_command(...)` in `stop()`.
3. Register the module in [`commands/__init__.py`](../commands/__init__.py).

`CMD_ID` convention: `f'{config.COMPANY_NAME}_<camelCaseName>'`
(e.g. `WoodCraft_dressUp`). Keep it globally unique.

---

## 4. Future: palettes (HTML/JS UI)

WoodCraft does not use any HTML palettes yet. When richer UI is needed (e.g. a
materials browser), palettes are the route — an embedded web view docked in
Fusion's side panel. They live under a `resources/html/` folder per command and
are created with `ui.palettes.add(...)`. The original Fusion template's
`paletteShow` / `paletteSend` samples (removed from this project) are the
reference pattern if you need it; they can be restored from the template repo.

---

## 5. Quick reference — IDs you must not change

| Constant (in `config.py`)   | Value                      |
|-----------------------------|----------------------------|
| `COMPANY_NAME`              | `WoodCraft`                |
| `DESIGN_WORKSPACE_ID`      | `FusionSolidEnvironment`   |
| `TAB_ID` / `TAB_NAME`      | `WoodCraft_tab` / WoodCraft |
| `DRESSUP_PANEL_ID`         | `WoodCraft_dressup_panel`  |
| `DRESSUP_PANEL_NAME`       | `Cabinet Builder`          |
| Carcass Maker `CMD_ID`     | `WoodCraft_dressUp`        |
| Trim `CMD_ID`              | `WoodCraft_trim`           |
| Edit Thickness `CMD_ID`    | `WoodCraft_editThickness`  |
| Shelf Creator `CMD_ID`     | `WoodCraft_shelf`          |
