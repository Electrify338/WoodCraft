"""Kitchen schedule rules — pure Python, no Fusion API.

Kitchen Export's only real decisions are "is this panel a front or part of the
carcass?" and "given several panels, what is THE material of this cabinet?".
Both are policy, not geometry, so they live here where they can be unit-tested
and edited without touching Fusion plumbing (the same split as ``nesting.py``,
``boring.py`` and ``countertop_geom.py``).

A panel is a **front** when its component name contains one of
``config.DOOR_PANEL_KEYWORDS`` — 'door', 'drawer' or 'front' by default. Naming
rather than tagging, because it works on cabinets modelled before this fork
existed and because renaming a component is cheaper than re-tagging it.
Everything that is not a front is **carcass**.
"""

from .. import config


def is_door_panel(name, keywords=None) -> bool:
    """True if this panel's name marks it as a door / drawer / front.

    Matching is case-insensitive and on substrings, so 'Door L', 'Drawer Front 2'
    and 'FRONT PANEL' all count, and so does 'Doors'. A panel named for something
    that merely contains a keyword (there is no common cabinet part named
    '...drawer...' that isn't a front) would be a false positive — adjust
    config.DOOR_PANEL_KEYWORDS if your naming needs it.
    """
    if keywords is None:
        keywords = config.DOOR_PANEL_KEYWORDS
    lowered = str(name or '').lower()
    return any(word in lowered for word in keywords)


def merge_materials(materials) -> str:
    """One cell's worth of material from however many panels contributed.

    Almost always every panel in a group shares one material and this returns
    that name. When they don't, the names are joined with ' / ' most-used first
    rather than silently picking one — a mixed carcass is nearly always a
    mistake, and the schedule should show it instead of hiding it.

    Blank / missing materials are ignored; if nothing is left the result is ''
    (the panels have no Fusion physical material assigned).
    """
    counts = {}
    order = []
    for name in materials:
        clean = str(name or '').strip()
        if not clean:
            continue
        if clean not in counts:
            counts[clean] = 0
            order.append(clean)
        counts[clean] += 1
    if not counts:
        return ''
    # Most used first; ties keep first-seen order so the result is deterministic.
    ranked = sorted(order, key=lambda n: (-counts[n], order.index(n)))
    return ' / '.join(ranked)


def split_materials(panels, keywords=None):
    """(carcass_material, door_material) for one cabinet.

    `panels` is an iterable of (component_name, material_name) pairs — every
    panel found anywhere inside the cabinet, at any depth.
    """
    carcass, door = [], []
    for name, material in panels:
        (door if is_door_panel(name, keywords) else carcass).append(material)
    return merge_materials(carcass), merge_materials(door)


def schedule_row(model_name, width_mm, panels, carcass_type, door_type,
                 keywords=None):
    """One export row, in the column order of Kitchen Export's spreadsheet:

        Cabinet model name | Cabinet width (mm) | Carcass material |
        Carcass Type | Door material | Door Type
    """
    carcass_material, door_material = split_materials(panels, keywords)
    return [model_name,
            None if width_mm is None else round(float(width_mm), 1),
            carcass_material,
            carcass_type or '',
            door_material,
            door_type or '']
