"""Global stock-sheet library for WoodCraft — Fusion-style Material → Sheets.

Mirrors how Fusion's Nesting "Process Material Library" is organised: a **material**
(its Fusion material name + thickness + category + a display colour) holds one or more
**sheets** (Fusion calls them "packagings") — each a stock board size with its own
nesting params. Cut List & Nest matches every panel to the material of its Fusion
material name + thickness, then nests it on a chosen sheet.

The library is a single portable JSON file shared across designs (so you define your
stock once, and can hand the file to someone else). No Fusion API is used here, so
this module is unit-testable with plain Python like `nesting.py`.

Library shape (sizes in millimetres):
    {"materials": [
        {"name": "MDF Medium Density Fiberboard", "thickness": 18.0,
         "category": "Boards", "color": "#C9A86A", "comment": "",
         "sheets": [
            {"name": "Standard", "length": 2440, "width": 1220, "form": "Rectangular",
             "cost": 0.0, "rotation": "all", "separation": 3.0, "trim": 10.0,
             "comment": ""}]}]}

`rotation` is one of: 'all' | 'none' | '90_270' | '180' (only 'all'/'90_270' let our
guillotine packer rotate a part 90°; '180' doesn't change a rectangle's footprint).
"""

import json
import os

ROTATIONS = ('all', 'none', '90_270', '180')
DEFAULT_COLOR = '#C9A86A'

# Seeded into a fresh / unreadable library so there's something to edit and match.
DEFAULT_LIBRARY = {
    "materials": [
        {"name": "MDF", "thickness": 18.0, "category": "Boards", "color": "#C9A86A",
         "comment": "",
         "sheets": [{"name": "Standard", "length": 2440.0, "width": 1220.0,
                     "form": "Rectangular", "cost": 0.0, "rotation": "all",
                     "separation": 3.0, "trim": 10.0, "comment": ""}]},
        {"name": "Plywood", "thickness": 18.0, "category": "Boards", "color": "#D6B894",
         "comment": "",
         "sheets": [{"name": "Standard", "length": 2440.0, "width": 1220.0,
                     "form": "Rectangular", "cost": 0.0, "rotation": "all",
                     "separation": 3.0, "trim": 10.0, "comment": ""}]},
    ]
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def library_dir():
    """Folder holding the library file, per platform."""
    appdata = os.environ.get("APPDATA")
    if appdata:  # Windows
        return os.path.join(appdata, "WoodCraft")
    home = os.path.expanduser("~")
    mac = os.path.join(home, "Library", "Application Support")
    if os.path.isdir(mac):  # macOS
        return os.path.join(mac, "WoodCraft")
    return os.path.join(home, ".woodcraft")  # fallback


def library_path():
    """Absolute path to the global library JSON file."""
    return os.path.join(library_dir(), "sheets.json")


# ---------------------------------------------------------------------------
# Coercion / validation
# ---------------------------------------------------------------------------
def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_sheet(row):
    """Coerce a raw sheet into a clean dict, or None if it has no usable size."""
    if not isinstance(row, dict):
        return None
    length = _num(row.get("length"))
    width = _num(row.get("width"))
    if length <= 0 or width <= 0:
        return None
    rotation = str(row.get("rotation", "all")).strip().lower()
    if rotation not in ROTATIONS:
        rotation = "all"
    return {
        "name": (str(row.get("name", "")).strip() or "Sheet"),
        "length": round(length, 3),
        "width": round(width, 3),
        "form": (str(row.get("form", "")).strip() or "Rectangular"),
        "cost": round(_num(row.get("cost")), 4),
        "rotation": rotation,
        "separation": round(max(0.0, _num(row.get("separation"))), 3),
        "trim": round(max(0.0, _num(row.get("trim"))), 3),
        "comment": str(row.get("comment", "") or ""),
    }


def normalize_material(row):
    """Coerce a raw material into a clean dict, or None if unusable. A material
    needs a name + positive thickness; it may carry zero sheets (still editable)."""
    if not isinstance(row, dict):
        return None
    name = str(row.get("name", "")).strip()
    thickness = _num(row.get("thickness"))
    if not name or thickness <= 0:
        return None
    color = (str(row.get("color", "")).strip() or DEFAULT_COLOR)
    sheets = [s for s in (normalize_sheet(x) for x in (row.get("sheets") or [])) if s]
    return {
        "name": name,
        "thickness": round(thickness, 3),
        "category": str(row.get("category", "") or "").strip(),
        "color": color,
        "comment": str(row.get("comment", "") or ""),
        "sheets": sheets,
    }


def clean_materials(rows):
    """Normalize a list of materials, dropping any that aren't usable."""
    out = []
    for row in rows or []:
        norm = normalize_material(row)
        if norm:
            out.append(norm)
    return out


# ---------------------------------------------------------------------------
# Migration from the old flat format
# ---------------------------------------------------------------------------
def migrate_flat(sheets):
    """Convert the old flat list [{material,thickness,length,width,cost}] into the
    nested model: group by (material, thickness) → one material, each old row a
    'Standard' sheet under it. Preserves data saved by the first Sheets version."""
    groups = {}
    order = []
    for s in sheets or []:
        if not isinstance(s, dict):
            continue
        mat = str(s.get("material", "")).strip()
        th = _num(s.get("thickness"))
        if not mat or th <= 0:
            continue
        key = (mat.lower(), round(th, 1))
        if key not in groups:
            groups[key] = {"name": mat, "thickness": round(th, 3), "category": "",
                           "color": DEFAULT_COLOR, "comment": "", "sheets": []}
            order.append(key)
        groups[key]["sheets"].append({
            "name": "Standard", "length": _num(s.get("length")),
            "width": _num(s.get("width")), "form": "Rectangular",
            "cost": _num(s.get("cost")), "rotation": "all",
            "separation": 3.0, "trim": 0.0, "comment": "",
        })
    return clean_materials([groups[k] for k in order])


def _materials_from_data(data):
    """Extract a materials list from any supported on-disk shape (new, old-flat,
    or a bare list), already cleaned. Empty list if nothing usable."""
    if isinstance(data, dict) and "materials" in data:
        return clean_materials(data["materials"])
    if isinstance(data, dict) and "sheets" in data:
        return migrate_flat(data["sheets"])
    if isinstance(data, list):
        return migrate_flat(data)
    return []


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------
def load():
    """Return {'materials': [...]} from the global library, migrating the old flat
    format if needed. Missing/corrupt/empty → a copy of DEFAULT_LIBRARY. Never
    raises and never writes."""
    try:
        with open(library_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        materials = _materials_from_data(data)
        if materials:
            return {"materials": materials}
    except Exception:
        pass
    return {"materials": clean_materials(DEFAULT_LIBRARY["materials"])}


def save(materials):
    """Write the (cleaned) materials list to the global library file, creating the
    folder if needed. Returns the list actually written."""
    cleaned = clean_materials(materials)
    os.makedirs(library_dir(), exist_ok=True)
    with open(library_path(), "w", encoding="utf-8") as f:
        json.dump({"materials": cleaned}, f, indent=2)
    return cleaned


def write_path(path, materials):
    """Export: write (cleaned) materials to an arbitrary path. Returns the list."""
    cleaned = clean_materials(materials)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"materials": cleaned}, f, indent=2)
    return cleaned


def read_path(path):
    """Import: read + validate a library from an arbitrary path (any supported
    shape). Returns a cleaned materials list (may be empty). Raises on unreadable
    file / invalid JSON so the caller can report it."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _materials_from_data(data)


# ---------------------------------------------------------------------------
# Matching helpers (used by Cut List)
# ---------------------------------------------------------------------------
def find_material(materials, name, thickness, tol=0.5):
    """The material whose name (trimmed, case-insensitive) and thickness (within
    `tol` mm) match a panel, or None."""
    want = str(name or "").strip().lower()
    if not want:
        return None
    for m in materials:
        if str(m.get("name", "")).strip().lower() != want:
            continue
        if abs(_num(m.get("thickness")) - _num(thickness)) <= tol:
            return m
    return None


def rotation_allows_rotation(code):
    """Does this rotation setting let our guillotine packer rotate a part 90°?
    'all'/'90_270' yes; 'none'/'180' no (180° doesn't change a rectangle)."""
    return str(code or "all").strip().lower() in ("all", "90_270")
