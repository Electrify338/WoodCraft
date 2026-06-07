"""Shared component collection for WoodCraft output commands (Cut List, BOM, Inspect).

Components are collected by their WoodCraft *category* attribute (config.WC_CATEGORY
— 'panel' or 'hardware'); there is no geometry guessing, so panels and purchased
items never get mixed up. Collection walks the occurrence tree (root.occurrences →
childOccurrences) so it reaches items inside referenced cabinets, records ONE
instance per occurrence (so the piece count is real), and remembers each item's
immediate parent assembly (the cabinet it lives in) so reports can tell apart
same-named panels — every cabinet has a "Left Panel".
"""

import adsk.core
import adsk.fusion

from .. import config
from . import wc_attrs


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
    """Geometry heuristic: a thin slab whose thickness is in sheet range and far
    smaller than its width/length (so it reads as sheet stock, not hardware).

    NOT used by collection (which is strictly category-driven) — reserved for an
    optional "auto-detect flat panels" helper in the Set Type command."""
    if not dims:
        return False
    L, W, T = dims
    if T < min_t or T > max_t or W <= 0:
        return False
    return (W / T) >= min_ratio


def _make_instance(occ_or_comp, comp, dims, category, parent=''):
    L, W, T = dims
    return {
        'name': getattr(occ_or_comp, 'name', comp.name),
        'comp_name': comp.name,
        'parent': parent,
        'category': category,
        'cost': wc_attrs.get_cost(comp) if category == config.WC_CAT_HARDWARE else 0.0,
        'L': L, 'W': W, 'T': T,
        'material': panel_material(comp),
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


def collect_instances(design, root=None, categories=None, root_name=''):
    """List of classified-component instances (one dict per physical piece /
    occurrence) under `root` (defaults to the whole design). Each dict has
    name/comp_name/parent/category/cost/L/W/T (mm)/material/component/occurrence.

    A component is included ONLY if it carries a WoodCraft category — no geometry
    guessing — so panels and purchased items stay cleanly separated. `categories`
    optionally restricts the result to an iterable of category values (e.g.
    {config.WC_CAT_PANEL}); None returns every classified component.

    `parent` is the name of the item's immediate parent assembly component (the
    cabinet it belongs to), or '' for an item at the top level. The tree is walked
    explicitly (root.occurrences → childOccurrences) rather than via the flattened
    allOccurrences so each item can be attributed to its real parent regardless of
    the assembly context. `root_name` seeds the parent for `root`'s own children —
    pass a scoped occurrence's component name so items collected under a single
    selected cabinet are still labelled with that cabinet."""
    if design is None:
        return []
    root = root or design.rootComponent
    wanted = set(categories) if categories else None
    instances = []

    def consider(owner, comp, parent):
        category = wc_attrs.get_category(comp)
        if category is None or (wanted is not None and category not in wanted):
            return
        dims = panel_dims_mm(comp)
        if dims is None:
            # A panel needs a measurable size; a purchased item is still counted.
            if category == config.WC_CAT_PANEL:
                return
            dims = (0.0, 0.0, 0.0)
        instances.append(_make_instance(owner, comp, dims, category, parent))

    def walk(occ, parent):
        consider(occ, occ.component, parent)
        # Descend with THIS occurrence's component name as its children's parent.
        try:
            children = occ.childOccurrences
        except Exception:
            return
        child_parent = occ.component.name
        for i in range(children.count):
            walk(children.item(i), child_parent)

    # The root component itself — covers scope set to a single leaf item. (For the
    # whole design the root is the assembly, which is unclassified, so this is a
    # no-op there.)
    consider(root, root, root_name)

    occs = root.occurrences
    for i in range(occs.count):
        walk(occs.item(i), root_name)

    return instances


def collect_panel_instances(design, root=None, root_name=''):
    """Panels only — thin wrapper over collect_instances() for the cut list / nest
    and other panel-centric callers."""
    return collect_instances(design, root=root, categories={config.WC_CAT_PANEL},
                             root_name=root_name)
