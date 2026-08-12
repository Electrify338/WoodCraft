# WoodCraft

A lightweight Autodesk **Fusion** add-in for cabinetmaking — a lean, open
alternative to tools like JoinerCAD. It turns a simple "skeleton" body into
parametric panel components, joins and machines them, and produces material‑aware
cut lists with colour‑coded nesting diagrams — without the bloat or a subscription.

> **Status:** active development. Seventeen commands across five toolbar panels
> (modelling, hardware, kitchen, output and dev). Pure Python + the Fusion API —
> **no external packages, no build step**.

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
| **Line Boring** | Bores the shelf‑pin hole pattern into a side/gable panel from a pluggable **rule** (default **Emaar**: three‑hole sets in two columns, set centres dividing the panel height into N+1 equal gaps). Builds **live‑parametric** — `wc_lb_*` user parameters driving a sketch → seed hole → 2‑direction pattern — so editing the parameters reflows the holes; falls back to explicit holes if any step of the parametric build fails. Geometry and the rule registry live in `commands/boring.py`. |
| **Edgeband** | Tags a panel's thin **edge faces** with an edgeband type from the Sheets library's band catalogue, and **tints** them in the viewport so banded edges read at a glance. The BOM sums tagged length per band type (face area ÷ thickness, so curves count their true arc length) and prices the metres from the catalogue. An "only exposed edges" detector probes each face to skip edges butted against another panel. |
| **Set Type** | Classifies selected components/bodies as **panels** or **purchased hardware** (with a unit cost) so the cut list, nesting and BOM can sort them. Hardware assemblies can be priced as a **complete pack** (one price, children not billed again) or as **separate parts** (sum of contents). Use it for hand‑modelled or imported parts. |

### Hardware (machining)
| Command | What it does |
|---|---|
| **Insert Hardware** | Inserts parts from a Fusion **cloud library** (top‑level folders = categories) linked at the origin, then launches Fusion's Move gizmo to position them. Thumbnail preview, module cache, and a Refresh button. *(Needs a cloud project — see setup.)* |
| **Sculpt** | Combine‑cuts panels with hardware "tool" bodies that intersect them (e.g. hinge cups, dowel holes), keeping the tool bodies. The productised "machining" step. |

### Kitchen (whole-assembly)
These act on a **finished kitchen** — a run of cabinets already assembled — rather
than on one cabinet at a time.

| Command | What it does |
|---|---|
| **Countertop** | Builds the worktop over assembled cabinets. **The wall is the reference:** the slab's back edge lies on the picked wall face and its front edge is that face offset by the **cabinet depth + a 20 mm overhang** (editable). The **side panels supply only the two end lines** — where the run starts and stops along the wall, taken from their outer faces. The underside lands on the **top of the tallest selected side panel**, so you never measure the plinth + carcass height. Tick **Backsplash** for an upstand as well, with its own **thickness** and **height**: it runs the full length of each run, hard against the wall, standing on the worktop. A **live preview** draws every piece as a wireframe box (slab in cyan, upstand in amber) labelled with its run length, so you see it before you commit. One wall face = one run = one component with one body (`Countertop` / `Countertop 1..N`, plus `Backsplash N`), each tagged with its own **countertop** category — costed by area and edgebandable exactly like a panel, but kept **out of the cut list and the nest**, because a worktop is bought as a slab or a cut length rather than nested out of a stock sheet. **L‑ and U‑shaped kitchens in one go:** select every wall and every end panel — each run claims the panels standing in front of *its* wall, is **extended and then clipped to the other walls' planes** so it ends exactly where the walls meet — neither short of the corner nor through the wall — and where two runs still overlap the command finishes with a **Combine cut** (keeping the tool) so the corner is solid once, not twice. |

### Output (production)
| Command | What it does |
|---|---|
| **Sheets** | A docked **HTML palette** that edits a global stock‑sheet **library** modelled on Fusion's Nesting *Process Material Library*: **Material → Sheets**. Each material has a name (matching the Fusion material), thickness, category and a display **colour**; each sheet has a size, cost and nesting params (rotation, item separation, edge trim). Save / **Export** / **Import** for sharing. |
| **Cut List & Nest** | Collects all panels, groups them by **(material, thickness)**, matches each group to the Sheets library, and opens a **colour‑coded HTML report**: cut‑list table, per‑sheet **guillotine nesting** diagrams, sheet count, yield, optional cost, a **purchased‑items** list (your hardware + costs), and a printable label sheet. Pick one or more assemblies (or the whole design), and choose which stock sheet to nest on when a material has several. |
| **BOM** | A **docked palette** showing the **assembly hierarchy** — root → components → sub‑components — one row per component with its **type, dimensions, material, quantity and part number** (the native Fusion `Component.partNumber`). Expand/collapse the tree and **Export to Excel** (a native `.xlsx`, written with the stdlib — no add‑on dependency, with **live formulas** so costs recalc when you tweak quantities). Shows the active **configuration** name. This is the structural bill; the cutting/nesting view lives in Cut List & Nest. |
| **Settings** | Add‑on‑wide options shared by every design (stored next to the Sheets library). Today that's the panel‑cost **waste factor** — the percentage added on top of a panel's raw area when the BOM estimates its cost from sheet prices, since nesting never uses 100 % of a sheet. Not promoted to the toolbar; find it in the Output panel's overflow. |

### Dev
| Command | What it does |
|---|---|
| **Inspect Panels** | Lists every classified WoodCraft component (panel/hardware) with its cut size — a debugging aid. Self‑contained and safe to delete before release. |

---

## How panels & materials work

- **Component classification.** Every WoodCraft component carries invisible custom
  attributes under one group (`WoodCraft`), the key one being `category`
  (`panel`, `hardware` or `countertop`). Carcass Maker and Shelf Creator
  auto‑classify what they build as panels, Countertop stamps its own category;
  **Set Type** classifies existing geometry (and prices hardware).
  Output commands collect strictly by this category — no geometry guessing — so
  panels and purchased items stay cleanly separated, even across referenced cabinets
  in a larger assembly. The scheme is an extensible key/value store
  (`commands/wc_attrs.py`); new commands add keys without migrations.
- **A worktop is not a panel.** `countertop` is its own category because a slab is
  measured, priced by area and edgebanded exactly like a sheet good but is *bought*
  as a slab or a cut length — so it belongs on the BOM and never on a nesting
  diagram. `config.WC_SHEET_LIKE` is the tuple that says "costed like a panel";
  `WC_CAT_PANEL` alone is what says "nested like a panel". Anything else that
  should be billed by area but never nested joins `WC_SHEET_LIKE` rather than
  becoming a second flavour of panel.
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
3. **Shelf Creator** for shelves; **Edit Thickness** to re‑thickness anything;
   **Line Boring** for the shelf‑pin holes.
4. Assign **Fusion materials** to your panels, and **Edgeband** the exposed edges.
5. **Sheets** → define your stock (use **+ From design** to pull in the materials
   the design actually uses), set sizes / cost / colour, **Save**.
6. **Cut List & Nest** → pick the assemblies (or leave empty for the whole design)
   → the colour‑coded report opens in your browser.

### …and for a whole kitchen

7. Assemble the cabinets into the kitchen.
8. **Countertop** → pick the wall face(s) and the side panels at each end of each
   run, set cabinet depth + slab thickness, tick **Backsplash** if you want an
   upstand → check the preview → the worktop lands on top, corners already cut.
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
├── config.py                   # shared ids, panel names, DEBUG, hardware project name,
│                               #   attribute schema
├── commands/
│   ├── __init__.py             # registers every command (start/stop, per-command error isolation)
│   ├── ui_helpers.py           # shared tab/panel creation, teardown, panel tagging
│   ├── wc_attrs.py             # component attribute store (category, cost, purchase mode,
│   │                           #   edgeband)
│   ├── panels.py               # shared panel collector, material reading, assembly tree
│   ├── boring.py               # pure-math shelf-pin boring rules + geometry (no Fusion features)
│   ├── countertop_geom.py      # pure-math worktop outline from wall + side panels (no Fusion API)
│   ├── nesting.py              # pure-math guillotine nester + SVG (no Fusion API)
│   ├── sheets_store.py         # global stock-sheet + edgeband library (load/save/match; pure)
│   ├── settings_store.py       # global add-on settings JSON (waste factor)
│   ├── report_utils.py         # shared HTML report shell, CSS, escaping, open-in-browser
│   ├── xlsx_writer.py          # dependency-free .xlsx writer (stdlib zipfile + XML)
│   ├── carcassMaker/  trim/  editThickness/  shelf/  lineBoring/  edgeband/  convertPanel/
│   ├── insertHardware/  sculpt/
│   ├── countertop/             # Kitchen panel
│   ├── sheets/                 # Sheets palette: entry.py + resources/html/{index,style,main}
│   ├── cutList/                # Cut List & Nest
│   ├── bom/                    # BOM palette: entry.py + resources/html/{index,style,main}
│   ├── settings/               # Add-on settings dialog
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
- **Countertop runs start as rectangles.** Each wall face gives one slab, then it
  is stretched into any corner it meets and clipped by the other picked walls, so
  a run in an L or U lands exactly on the wall‑to‑wall intersection. Where two
  finished runs still overlap the command Combine‑cuts the later one with the
  earlier one — but the joint is a **butt, not a mitre**, and the first wall you
  pick is the run that stays whole. Cut‑outs (sink, hob) and a nosing profile are
  modelling steps, not part of this command. The slab is also **not
  associative**: it is built from the cabinets' positions at the moment you run
  it, so move a cabinet and you re‑run Countertop.
- **Corners only work with the walls you pick.** A wall that bounds a run but
  isn't selected can neither extend nor clip it — if a run stops short of a
  corner or runs past one, add that wall face to the selection.
- **A run is only stretched into a nearby corner** — a wall further than the
  worktop depth (plus 100 mm) beyond the run's end is treated as a different part
  of the house and ignored, and a wall parallel to the run never extends it. So a
  run that genuinely stops short of a wall (a doorway, an appliance gap) will
  still be pulled to it if that wall is selected and within range; leave it out of
  the selection in that case.
- **The corner cut needs real overlap.** Runs that merely butt end‑to‑end, or that
  sit at different heights (a raised breakfast bar over base units), are left
  alone — only genuinely coincident material is trimmed.
- **UI/icons** are maintained partly by separate passes; see `docs/UI_GUIDE.md`.
  The Kitchen icons are rendered by `generate_icons_kitchen.py` (dev‑only,
  Pillow, `.gitignore`d — the PNGs are what ships).

---

## License

**GNU GPL v3.0 or later** — see [`LICENSE`](LICENSE). You're free to use, modify,
distribute and even sell this, but any copy or derivative you distribute must
also be under the GPL, with its source made available to whoever receives it.
It comes with no warranty.

**Author:** Abdelrahman Youssry
