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
from . import sheets_store
from . import settings_store


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


def _priced_hardware(component):
    """True when this component counts as ONE priced purchased unit whose price
    covers everything inside it: hardware, with its own cost, bought as a pack.
    In 'separate' purchase mode the component is translucent — its parts are
    bought individually, so any stored pack cost is ignored and reports sum the
    children instead."""
    return (wc_attrs.is_hardware(component)
            and wc_attrs.get_cost(component) > 0
            and wc_attrs.get_purchase_mode(component) == config.WC_PURCHASE_PACK)


def _make_instance(occ_or_comp, comp, dims, category, parent=''):
    L, W, T = dims
    return {
        'name': getattr(occ_or_comp, 'name', comp.name),
        'comp_name': comp.name,
        'parent': parent,
        'category': category,
        # Only a pack-priced unit bills its own cost; a separate-mode assembly's
        # stored pack price must not ALSO be billed next to its children's.
        'cost': wc_attrs.get_cost(comp) if _priced_hardware(comp) else 0.0,
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
        # A hardware component with its OWN price is a purchased unit: whatever
        # is inside it is already covered by that price, so descending would
        # double-count its children (e.g. a Minifix assembly priced as a whole
        # vs. its screw + cam priced individually — only one level may count).
        if _priced_hardware(occ.component):
            return
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

    if not _priced_hardware(root):
        occs = root.occurrences
        for i in range(occs.count):
            walk(occs.item(i), root_name)

    return instances


def collect_panel_instances(design, root=None, root_name=''):
    """Panels only — thin wrapper over collect_instances() for the cut list / nest
    and other panel-centric callers."""
    return collect_instances(design, root=root, categories={config.WC_CAT_PANEL},
                             root_name=root_name)


# ---------------------------------------------------------------------------
# Shared grouping / labelling (used by Cut List and BOM)
# ---------------------------------------------------------------------------
def instance_label(it):
    """Item name qualified by its parent assembly (cabinet), e.g.
    'Base Cabinet / Left Panel', so identical names across cabinets stay distinct.
    Falls back to the bare name for items at the top level (no parent)."""
    parent = (it.get('parent') or '').strip()
    name = it.get('comp_name') or ''
    return f'{parent} / {name}' if parent else name


def group_by_material_thickness(instances):
    """Ordered list of {key, material, thickness, items} grouped by (material name,
    thickness mm). 'Unassigned' stands in for items with no Fusion material. Sorted
    by material name, then thickness descending."""
    groups = {}
    order = []
    for it in instances:
        material = (it.get('material') or '').strip() or 'Unassigned'
        t = round(it['T'], 1)
        key = (material.lower(), t)
        if key not in groups:
            groups[key] = {'key': key, 'material': material, 'thickness': t, 'items': []}
            order.append(key)
        groups[key]['items'].append(it)
    order.sort(key=lambda k: (k[0], -k[1]))
    return [groups[k] for k in order]


# ---------------------------------------------------------------------------
# Hierarchical BOM tree (used by the BOM palette / Excel export)
# ---------------------------------------------------------------------------
def _component_part_number(component):
    """Native Fusion component part number (read/write property), or ''."""
    try:
        return component.partNumber or ''
    except Exception:
        return ''


def _node_type(component, has_children):
    """BOM type label from the WoodCraft category, falling back to the structure:
    a component with children is an Assembly, an unclassified leaf is a Part."""
    category = wc_attrs.get_category(component)
    if category == config.WC_CAT_PANEL:
        return 'Panel'
    if category == config.WC_CAT_HARDWARE:
        return 'Hardware'
    return 'Assembly' if has_children else 'Part'


def build_tree(design, root=None):
    """Hierarchical bill of materials. Returns a list of top-level nodes; each node:
    {name, type, material, part_number, L, W, T (mm), qty,
     unit_cost, cost, cost_kind, children:[...]}.

    Walks the occurrence tree (occurrences -> childOccurrences) so the structure
    mirrors the browser, and groups identical sibling components into ONE node whose
    `qty` is the count within that parent (standard indented-BOM quantities). Every
    component is included — assemblies (cabinets), classified panels/hardware, and
    unclassified parts alike — so the structure is complete regardless of tagging.

    Costing (`unit_cost` = one instance, `cost` = unit_cost × qty, both None when
    unpriced; `cost_kind` says where the number came from):
      'set'      hardware with its own WC_COST — a purchased unit. Its descendants
                 are re-marked 'absorbed' (cost None): the parent price covers them,
                 counting both would double-bill (e.g. a priced Minifix assembly
                 vs. its individually-priced screw + cam).
      'est'      panel — raw area × the sheet library's average cost/m² for its
                 (material, thickness), plus the global waste factor (Settings).
      'rollup'   assembly / unpriced hardware — the sum of its children's costs.
      'absorbed' inside a priced purchased unit (unit_cost kept for reference).
      None       nothing priced anywhere below."""
    if design is None:
        return []
    root = root or design.rootComponent

    materials = sheets_store.load()['materials']
    waste_mult = 1.0 + settings_store.get_waste_percent() / 100.0
    rate_cache = {}   # (material lower, thickness rounded) -> rate or None

    def rate_for(material_name, thickness):
        key = (str(material_name).strip().lower(), round(thickness, 1))
        if key not in rate_cache:
            m = sheets_store.find_material(materials, material_name, thickness)
            rate_cache[key] = sheets_store.cost_rate_per_m2(m)
        return rate_cache[key]

    def absorb(nodes):
        for n in nodes:
            n['cost'] = None
            n['cost_kind'] = 'absorbed'
            absorb(n['children'])

    def cost_for(component, node, children):
        """(unit_cost, cost_kind) for one instance of `component`."""
        if _priced_hardware(component):
            absorb(children)
            return wc_attrs.get_cost(component), 'set'
        if node['type'] == 'Panel':
            rate = rate_for(node['material'], node['T'])
            if rate is None or node['L'] <= 0:
                return None, None
            area_m2 = node['L'] * node['W'] / 1e6
            return area_m2 * rate * waste_mult, 'est'
        rolled = [c['cost'] for c in children if c['cost'] is not None]
        if rolled:
            return sum(rolled), 'rollup'
        return None, None

    def node_for(component, qty):
        children = build_level(component.occurrences)
        dims = panel_dims_mm(component) or (0.0, 0.0, 0.0)
        node = {
            'name': component.name,
            'type': _node_type(component, bool(children)),
            'material': panel_material(component),
            'part_number': _component_part_number(component),
            'L': dims[0], 'W': dims[1], 'T': dims[2],
            'qty': qty,
            'children': children,
        }
        unit, kind = cost_for(component, node, children)
        node['unit_cost'] = unit
        node['cost'] = unit * qty if unit is not None else None
        node['cost_kind'] = kind
        return node

    def build_level(occ_collection):
        # Aggregate identical sibling components into one node carrying a quantity,
        # using component IDENTITY (==) — the way Fusion's own ExtractBOM sample
        # does. entityToken is NOT a reliable grouping key (distinct components can
        # collide on it, which dropped a sibling), so compare the components directly.
        groups = []   # [{'comp': Component, 'qty': int}], in first-seen order
        for i in range(occ_collection.count):
            comp = occ_collection.item(i).component
            for g in groups:
                if g['comp'] == comp:
                    g['qty'] += 1
                    break
            else:
                groups.append({'comp': comp, 'qty': 1})
        return [node_for(g['comp'], g['qty']) for g in groups]

    nodes = build_level(root.occurrences)
    # A PART document (or a scope narrowed to a leaf) has no occurrences to walk —
    # the root component IS the item. Emit it as the single node so a lone dowel
    # or bracket still gets a BOM. Assemblies keep the root out (its children are
    # the top-level rows), same as before.
    if not nodes:
        has_content = False
        try:
            has_content = root.bRepBodies.count > 0
        except Exception:
            pass
        if has_content or wc_attrs.get_category(root):
            nodes = [node_for(root, 1)]
    _number_tree(nodes)
    return nodes


def _number_tree(nodes, prefix=''):
    """Stamp standard indented-BOM item numbers on every node ('no'): top level
    1, 2, 3…; children 1.1, 1.2…; grandchildren 1.1.1… Position-derived, so the
    palette and the Excel export always agree."""
    for i, n in enumerate(nodes, 1):
        n['no'] = f'{prefix}.{i}' if prefix else str(i)
        _number_tree(n['children'], n['no'])


def estimate_panel_unit_cost(material_name, thickness, L_mm, W_mm,
                             materials=None, waste_mult=None):
    """Sheet-derived estimated cost of ONE panel — raw area × the material's
    average sheet cost/m² × the waste factor — or None when the Sheets library
    has no priced sheet for (material_name, thickness). Pass `materials` /
    `waste_mult` when calling in a loop to avoid re-reading the stores."""
    if materials is None:
        materials = sheets_store.load()['materials']
    if waste_mult is None:
        waste_mult = 1.0 + settings_store.get_waste_percent() / 100.0
    rate = sheets_store.cost_rate_per_m2(
        sheets_store.find_material(materials, material_name, thickness))
    if rate is None or L_mm <= 0:
        return None
    return L_mm * W_mm / 1e6 * rate * waste_mult


def tree_cost_totals(nodes):
    """Bill split for a build_tree() result:
    {'panels_est', 'hardware', 'grand', 'unpriced_panels'} — panels_est is the
    sheet-derived estimate, hardware the entered purchase costs, grand their sum;
    unpriced_panels counts physical panels no rate could be found for (so a low
    total can't silently mean 'panels missing from the bill').

    Node costs are relative to ONE instance of their parent, so the walk carries
    the multiplier of enclosing quantities (2 cabinets × 4 screws = 8 screws)."""
    totals = {'panels_est': 0.0, 'hardware': 0.0, 'grand': 0.0, 'unpriced_panels': 0}

    def walk(ns, mult):
        for n in ns:
            eff_qty = mult * n['qty']
            kind = n.get('cost_kind')
            if kind == 'set':
                totals['hardware'] += n['unit_cost'] * eff_qty
                continue    # descendants are absorbed in this price
            if kind == 'est':
                totals['panels_est'] += n['unit_cost'] * eff_qty
            elif n['type'] == 'Panel' and kind is None:
                totals['unpriced_panels'] += eff_qty
            walk(n['children'], eff_qty)

    walk(nodes, 1)
    totals['grand'] = totals['panels_est'] + totals['hardware']
    return totals


def flatten_tree(nodes, level=0):
    """Depth-first (node, level) pairs from build_tree() output — for tabular export
    (Excel outline levels) and flat rendering."""
    out = []
    for n in nodes:
        out.append((n, level))
        out.extend(flatten_tree(n['children'], level + 1))
    return out
