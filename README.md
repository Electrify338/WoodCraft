# WoodCraft

A lightweight Autodesk **Fusion** add-in for cabinetmaking — a lean, open
alternative to tools like JoinerCAD. It turns a simple "skeleton" body into
parametric panel components, joins and machines them, and produces material‑aware
cut lists with colour‑coded nesting diagrams — without the bloat or a subscription.

> **Status:** active development. Ten commands across four toolbar panels
> (modelling, hardware, output and dev). Pure Python + the Fusion API — **no
> external packages, no build step**.

---

## What's inside

Everything lives in a dedicated **WoodCraft** tab in the **Design** workspace,
split into panels that read as a workflow (design → hardware → output):

### Cabinet Builder (modelling)
| Command | What it does |
|---|---|
| **Carcass Maker** | Select the flat faces of a solid "skeleton" box; each becomes its own panel component, extruded **directly from the face** so it stays associative. Global thickness / direction (Inside·Outside·Symmetric) / offset, plus a per‑panel override table, a "Collect all flat faces" button, and on‑screen labels + build‑direction arrows. |
| **Trim** | Combine‑cuts panels so they fit against each other, with an optional uniform **gap** (clearance/reveal; 0 = flush). |
| **Edit Thickness** | Re‑thickness existing panels by editing the extrude extent **in place** (preserves direction + offset). Prefills the current thickness. |
| **Shelf Creator** | Builds a parametric shelf on a chosen plane bounded by four faces, each with its own offset (positive, negative or uneven), kept associative to the walls. |
| **Convert to Panel** | Tags hand‑modelled or imported components/bodies as WoodCraft panels so the output commands can find them. |

### Hardware (machining)
| Command | What it does |
|---|---|
| **Insert Hardware** | Inserts parts from a Fusion **cloud library** (top‑level folders = categories) linked at the origin, then launches Fusion's Move gizmo to position them. Thumbnail preview, module cache, and a Refresh button. *(Needs a cloud project — see setup.)* |
| **Sculpt** | Combine‑cuts panels with hardware "tool" bodies that intersect them (e.g. hinge cups, dowel holes), keeping the tool bodies. The productised "machining" step. |

### Output (production)
| Command | What it does |
|---|---|
| **Sheets** | A docked **HTML palette** that edits a global stock‑sheet **library** modelled on Fusion's Nesting *Process Material Library*: **Material → Sheets**. Each material has a name (matching the Fusion material), thickness, category and a display **colour**; each sheet has a size, cost and nesting params (rotation, item separation, edge trim). Save / **Export** / **Import** for sharing. |
| **Cut List & Nest** | Collects all panels, groups them by **(material, thickness)**, matches each group to the Sheets library, and opens a **colour‑coded HTML report**: cut‑list table, per‑sheet **guillotine nesting** diagrams, sheet count, yield, optional cost, and a printable label sheet. Pick one or more assemblies (or the whole design), and choose which stock sheet to nest on when a material has several. |

### Dev
| Command | What it does |
|---|---|
| **Inspect Panels** | Lists every component tagged as a WoodCraft panel with its cut size — a debugging aid. Self‑contained and safe to delete before release. |

---

## How panels & materials work

- **Panel tagging.** Every panel component carries an invisible custom attribute
  (`WoodCraft / panel / true`). Carcass Maker and Shelf Creator tag automatically;
  Convert to Panel tags existing geometry. Output commands collect panels by this
  tag (with a flat‑sheet geometry fallback), so they work across referenced
  cabinets in a larger assembly.
- **Material = Fusion's native material.** Cut List reads each panel's Fusion
  physical material name and matches it (plus thickness) to the Sheets library.
  Assign real materials to your parts in Fusion, define matching stock in the
  **Sheets** palette, and nesting/costing follows. Parts with no matching stock
  are listed as a warning rather than nested.

---

## Installation & setup

This is a standard Fusion **Python add-in** — drop the folder in, enable it, done.
There is **nothing to `pip install` and no build step**.

### 1. Get the files
- **Zip:** unzip it, **or**
- **GitHub:** `git clone` the repo, or use **Code → Download ZIP**.

> ⚠️ **The folder must be named exactly `WoodCraft`.** Fusion matches the folder
> name to `WoodCraft.py` / `WoodCraft.manifest`, and the add-in derives its name
> from the folder. GitHub's "Download ZIP" gives you a `WoodCraft-main/` folder —
> **rename it to `WoodCraft`**. (A `git clone` of a repo named `WoodCraft` is
> already correct.)

### 2. Put it in the Fusion add‑ins folder
- **Windows:** `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\WoodCraft`
- **macOS:** `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/WoodCraft`

### 3. Enable it
1. In Fusion, open **Utilities → Add‑Ins** (or press **`Shift+S`**) → **Add‑Ins** tab.
2. Select **WoodCraft** → **Run**. Tick **Run on Startup** to load it automatically.
3. Switch to the **Design** workspace — the **WoodCraft** tab appears.

That's it — the stock‑sheet library auto‑creates with sensible defaults the first
time you open **Sheets** or run **Cut List**, so there's nothing else to configure.

### Notes for testers
- **macOS:** the manifest declares `"supportedOS": "windows"`, so Fusion on a Mac
  won't list the add-in until you change that line in `WoodCraft.manifest` to
  `"mac"` (or remove the key). The code itself is cross‑platform.
- **Insert Hardware** is the only feature needing external setup: it reads a Fusion
  cloud project named **`WoodCraft Hardware`** (set in `config.py` →
  `HARDWARE_PROJECT_NAME`). Without it, that one command just shows an empty
  catalogue and lists the projects it *can* see; **everything else works with zero
  config.**
- **For a "release" build:** set `DEBUG = False` in `config.py` (quiets the Text
  Commands log) and optionally delete `commands/inspectPanels/` (the Dev tool).

### Requirements
- A recent **Autodesk Fusion** (uses standard Design‑workspace APIs — extrude,
  combine, offset‑faces, custom graphics, palettes). Fusion ships its own Python;
  no separate Python install.
- No third‑party Python packages at runtime. *(The optional `generate_icons.py`
  needs Pillow, but it's a dev‑only icon generator and isn't shipped.)*

---

## Quick start

1. **Model a skeleton** box at the cabinet's outer dimensions.
2. **Carcass Maker** → pick faces (or *Collect all flat faces*), set thickness /
   direction / offset, **OK**. → **Trim** to resolve the corner overlaps.
3. **Shelf Creator** for shelves; **Edit Thickness** to re‑thickness anything.
4. Assign **Fusion materials** to your panels.
5. **Sheets** → define your stock (use **+ From design** to pull in the materials
   the design actually uses), set sizes / cost / colour, **Save**.
6. **Cut List & Nest** → pick the assemblies (or leave empty for the whole design)
   → the colour‑coded report opens in your browser.

---

## Sharing your stock library

The library is a single portable JSON file at
`%APPDATA%\WoodCraft\sheets.json` (Windows) — colours, costs and sheets included.
Share it by sending that file (the recipient drops it in their own
`%APPDATA%\WoodCraft\`) or, more conveniently, use the **Export / Import** buttons
in the Sheets palette.

---

## Project layout

```
WoodCraft/
├── WoodCraft.py                # add-in entry point (run / stop)
├── WoodCraft.manifest          # Fusion add-in manifest
├── AddInIcon.svg               # add-in icon
├── config.py                   # shared ids, panel names, DEBUG, hardware project name
├── commands/
│   ├── __init__.py             # registers every command
│   ├── ui_helpers.py           # shared tab/panel creation, teardown, panel tagging
│   ├── panels.py               # shared panel collector + material reading
│   ├── nesting.py              # pure-math guillotine nester + SVG (no Fusion API)
│   ├── sheets_store.py         # global stock-sheet library (load/save/match; pure)
│   ├── carcassMaker/  trim/  editThickness/  shelf/  convertPanel/
│   ├── insertHardware/  sculpt/
│   ├── sheets/                 # Sheets palette: entry.py + resources/html/{index,style,main}
│   ├── cutList/                # Cut List & Nest
│   └── inspectPanels/          # Dev tool (removable)
├── lib/fusionAddInUtils/       # Autodesk template helpers (logging, event wiring)
└── docs/UI_GUIDE.md            # icon / UI guide for design work
```

Each command is a self‑contained folder with an `entry.py` exposing `start()` /
`stop()`. To add one: create the folder, import it in `commands/__init__.py`,
append it to the `commands` list, and drop icons in its `resources/`. See
`docs/UI_GUIDE.md` for toolbar/icon conventions and the IDs that must stay stable.

---

## Notes & known limitations

- **Nesting is guillotine** (full edge‑to‑edge cuts, panel‑saw friendly). It tries
  several heuristics and keeps the tightest layout, but won't beat true‑shape
  nesting on yield. Fusion's own Nesting *Process Material Library* is **not**
  API‑readable (paid extension), which is why WoodCraft keeps its own library.
- **Trim gap** is positive (clearance) only — a negative‑offset "groove" mode was
  removed for lack of a clean uniform solid‑offset API. (Shelf offsets *do* allow
  negatives.)
- **Shelf Creator** assumes the four bounding faces form two parallel pairs (the
  normal cabinet case).
- **UI/icons** are maintained partly by separate passes; see `docs/UI_GUIDE.md`.

---

## License

**MIT** — see [`LICENSE`](LICENSE). You're free to use, modify, distribute and
even sell this, including in closed-source work; just keep the copyright notice.

**Author:** Abdelrahman Youssry
