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
└── Tab:  "WoodCraft"            id = WoodCraft_tab
    └── Panel: "Dress Up"        id = WoodCraft_dressup_panel
        ├── Dress Up  (button)   id = WoodCraft_dressUp
        └── Trim      (button)   id = WoodCraft_trim
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

### Current state — PLACEHOLDERS

The PNGs currently in each `resources/` folder are **copies of the Fusion
sample-add-in icons**. They are placeholders only. Replace them in place with
real WoodCraft artwork using the **same filenames** — no code change is needed.

Icon folders to populate:

| Command  | Folder                                                |
|----------|-------------------------------------------------------|
| Dress Up | `commands/dressUp/resources/`                         |
| Trim     | `commands/trim/resources/`                            |

There is also a top-level [`AddInIcon.svg`](../AddInIcon.svg) (referenced by
`WoodCraft.manifest`) used as the add-in's icon in Fusion's Scripts & Add-Ins
dialog. That can be restyled too.

### Icon design notes
- PNG, transparent background, square.
- Keep the glyph readable at 16×16 — simple silhouettes, not fine detail.
- Match Fusion's monochrome/line-art toolbar style so buttons feel native.
- Suggested motifs: **Dress Up** = a box turning into separated panels;
  **Trim** = a panel with a notch/cut where another panel meets it.

### Icons the dialogs still need (button inputs)
The Dress Up dialog has a per-panel table with two action buttons, **Defaults**
and **Delete**, created as non-checkbox `BoolValueInput`s with an empty resource
folder (text-only for now). If you want them to render with proper icons, give
each a small resource folder and pass it as the 4th arg of `addBoolValueInput`.
Suggested 16/32/64 glyphs: Defaults = a reset/refresh arrow, Delete = a trash
can or minus. See `commands/dressUp/entry.py` (`DEFAULTS_BTN_ID`, `DELETE_BTN_ID`).

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
| `DRESSUP_PANEL_NAME`       | `Dress Up`                 |
| Dress Up `CMD_ID`          | `WoodCraft_dressUp`        |
| Trim `CMD_ID`              | `WoodCraft_trim`           |
