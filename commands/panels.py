"""Shared panel collection for WoodCraft output commands (Cut List, Inspect).

A "panel" is any component carrying the WoodCraft panel attribute
(config.PANEL_ATTR_*), or — as a fallback for untagged/imported parts — a
component whose geometry looks like a flat sheet. Collection walks
Component.allOccurrences so it reaches panels inside referenced cabinets, and
records ONE instance per occurrence (so the piece count is real).
"""

import adsk.core
import adsk.fusion

from .. import config


def _is_tagged_panel(component):
    try:
        return component.attributes.itemByName(
            config.PANEL_ATTR_GROUP, config.PANEL_ATTR_NAME) is not None
    except Exception:
        return False


def panel_material(component):
    """Native Fusion material name for a panel, or '' if none is set.

    Prefers the material of the component's single body (the usual case for a
    panel — a material dragged onto the body wins over the component default),
    then the component-level material. The Cut List matches panels to stock
    sheets by this name, so it must reflect what the user assigned in Fusion.
    """
    try:
        bodies = component.bRepBodies
        if bodies.count == 1:
            mat = bodies.item(0).material
            if mat:
                return mat.name
    except Exception:
        pass
    try:
        mat = component.material
        if mat:
            return mat.name
    except Exception:
        pass
    return ''


def panel_dims_mm(component):
    """Sorted (L, W, T) in millimetres from the component's bounding box, or None."""
    try:
        bb = component.boundingBox
        ext = [(bb.maxPoint.x - bb.minPoint.x) * 10.0,
               (bb.maxPoint.y - bb.minPoint.y) * 10.0,
               (bb.maxPoint.z - bb.minPoint.z) * 10.0]
        ext.sort(reverse=True)
        return (ext[0], ext[1], ext[2])
    except Exception:
        return None


def looks_like_panel(dims, min_t=3.0, max_t=40.0, min_ratio=4.0):
    """Geometry fallback: a thin slab whose thickness is in sheet range and far
    smaller than its width/length (so it reads as sheet stock, not hardware)."""
    if not dims:
        return False
    L, W, T = dims
    if T < min_t or T > max_t or W <= 0:
        return False
    return (W / T) >= min_ratio


def _make_instance(occ_or_comp, comp, dims, tagged):
    L, W, T = dims
    return {
        'name': getattr(occ_or_comp, 'name', comp.name),
        'comp_name': comp.name,
        'L': L, 'W': W, 'T': T,
        'material': panel_material(comp),
        'tagged': tagged,
        'component': comp,
        'occurrence': occ_or_comp,
    }


def design_panel_materials(design):
    """Sorted, distinct Fusion material names found on panels in `design` — the
    exact strings Cut List matches against. Reused by the Sheets palette (to offer
    real names) and Cut List. Empty list if no design / none found."""
    if design is None:
        return []
    found = set()
    try:
        for it in collect_panel_instances(design):
            mat = (it.get('material') or '').strip()
            if mat:
                found.add(mat)
    except Exception:
        pass
    return sorted(found)


def design_panel_groups(design):
    """[{'material','thickness','count'}] for the design's panels, grouped by
    (material name, thickness mm). Lets the Sheets palette show/offer the exact
    (name, thickness) combinations present in the design. Sorted by name, then
    thickness descending."""
    if design is None:
        return []
    groups = {}
    try:
        for it in collect_panel_instances(design):
            mat = (it.get('material') or '').strip() or 'Unassigned'
            t = round(it['T'], 1)
            key = (mat, t)
            groups[key] = groups.get(key, 0) + 1
    except Exception:
        pass
    out = [{'material': k[0], 'thickness': k[1], 'count': v} for k, v in groups.items()]
    out.sort(key=lambda g: (g['material'].lower(), -g['thickness']))
    return out


def collect_panel_instances(design, root=None, use_geometry_fallback=True):
    """List of panel instances (one dict per physical piece) under `root`
    (defaults to the whole design). Each dict has name/comp_name/L/W/T (mm)/
    tagged/component/occurrence."""
    if design is None:
        return []
    root = root or design.rootComponent
    instances = []

    def consider(owner, comp):
        dims = panel_dims_mm(comp)
        tagged = _is_tagged_panel(comp)
        if not tagged and not (use_geometry_fallback and looks_like_panel(dims)):
            return
        if not dims:
            return
        instances.append(_make_instance(owner, comp, dims, tagged))

    occs = root.allOccurrences
    for i in range(occs.count):
        occ = occs.item(i)
        consider(occ, occ.component)

    # The root component itself — covers scope set to a single leaf panel. (For
    # the whole design the root is the assembly, which is not a panel, so this
    # is a no-op there.)
    consider(root, root)

    return instances
