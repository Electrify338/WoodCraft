"""Shared component collection for WoodCraft output commands (Cut List, BOM, Inspect).

Components are collected by their WoodCraft *category* attribute (config.WC_CATEGORY
— 'panel' or 'hardware'); there is no geometry guessing, so panels and purchased
items never get mixed up. Collection walks the occurrence tree (root.occurrences →
childOccurrences) so it reaches items inside referenced cabinets, records ONE
instance per occurrence (so the piece count is real), and remembers each item's
immediate parent assembly (the cabinet it lives in) so reports can tell apart
same-named panels — every cabinet has a "Left Panel".
"""

import copy
import time

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


def _bbox_ext_mm(bb):
    """Bounding-box extents in millimetres, sorted largest first."""
    ext = [(bb.maxPoint.x - bb.minPoint.x) * 10.0,
           (bb.maxPoint.y - bb.minPoint.y) * 10.0,
           (bb.maxPoint.z - bb.minPoint.z) * 10.0]
    ext.sort(reverse=True)
    return ext


def _sheet_metal_dims_mm(component):
    """Unfolded (L, W, T) in millimetres for a sheet-metal component, or None for
    a regular part.

    A bent/curved sheet-metal part wraps around its bounding box, so the box's
    smallest extent is the bend envelope, not the sheet thickness (a curved 18 mm
    panel reads as 780 mm thick). Prefer the flat pattern's body — the true
    unfolded blank, which is also the size the cut list must nest (arc length,
    not chord). When no flat pattern has been created yet, fall back to the
    component's sheet-metal rule for T with the folded bounding box for L/W
    (approximate: the folded extents undersell the blank)."""
    try:
        if not any(b.isSheetMetal for b in component.bRepBodies):
            return None
    except Exception:
        return None
    try:
        fp = component.flatPattern
        if fp:
            ext = _bbox_ext_mm(fp.flatBody.boundingBox)
            return (ext[0], ext[1], ext[2])
    except Exception:
        pass
    try:
        rule = component.activeSheetMetalRule
        if rule:
            ext = _bbox_ext_mm(component.boundingBox)
            return (ext[0], ext[1], rule.thickness.value * 10.0)
    except Exception:
        pass
    return None


def _own_bodies_ext_mm(component):
    """Extents (mm, largest first) of the union of the component's OWN bodies'
    bounding boxes, or None when it has no bodies. Component.boundingBox spans
    child occurrences too, and Fusion computes it by touching every body in the
    whole subtree — seconds per call on an assembly — so measurement must stay
    on the component's own (cheap, precomputed) body boxes."""
    try:
        bodies = component.bRepBodies
        if bodies.count == 0:
            return None
        mins = [float('inf')] * 3
        maxs = [float('-inf')] * 3
        measured = 0
        for i in range(bodies.count):
            body = bodies.item(i)
            # Match Component.boundingBox: hidden bodies (alternate-position /
            # tool leftovers) don't count toward a part's size.
            if not body.isVisible:
                continue
            bb = body.boundingBox
            lo, hi = bb.minPoint, bb.maxPoint
            # A degenerate zero-size body (e.g. the leftover of a failed feature)
            # is a stray point that would inflate the union across the distance
            # to the real body — Fusion's own Component.boundingBox skips these.
            if max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) < 1e-3:   # < 0.01 mm
                continue
            measured += 1
            for axis, (lo_v, hi_v) in enumerate(((lo.x, hi.x), (lo.y, hi.y), (lo.z, hi.z))):
                mins[axis] = min(mins[axis], lo_v)
                maxs[axis] = max(maxs[axis], hi_v)
        if not measured:
            return None
        ext = sorted(((maxs[a] - mins[a]) * 10.0 for a in range(3)), reverse=True)
        return ext
    except Exception:
        return None


def panel_dims_mm(component):
    """Sorted (L, W, T) in millimetres, or None. Flat parts measure straight off
    their own bodies' bounding boxes; sheet-metal parts use their flat pattern /
    rule so bent panels report the real sheet thickness and unfolded blank size.
    A component with no bodies of its own (e.g. a priced hardware pack whose
    geometry lives in children) falls back to Component.boundingBox — expensive,
    so callers must not measure plain assemblies (BOM assembly rows skip this)."""
    dims = _sheet_metal_dims_mm(component)
    if dims:
        return dims
    ext = _own_bodies_ext_mm(component)
    if ext is None:
        try:
            ext = _bbox_ext_mm(component.boundingBox)
        except Exception:
            return None
    return (ext[0], ext[1], ext[2])


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


# ---------------------------------------------------------------------------
# Edgebanding (WC_EDGEBAND face attributes → per-component band lengths)
# ---------------------------------------------------------------------------
def face_edgeband_length_mm(face, thickness_mm=None):
    """Banding length ONE face needs, in millimetres: face area ÷ panel thickness.
    Exact for a rectangular edge face (T × L) and arc-true for a curved edge (a
    band follows the surface, so a bent front needs its arc length — the bounding
    box would undersell it). When the thickness is unknown, fall back to the
    face's largest bounding-box extent (right for straight edges only)."""
    try:
        area_mm2 = face.area * 100.0        # Fusion areas are cm²
    except Exception:
        return 0.0
    if thickness_mm and thickness_mm > 0:
        return area_mm2 / thickness_mm
    try:
        bb = face.boundingBox
        return max(bb.maxPoint.x - bb.minPoint.x,
                   bb.maxPoint.y - bb.minPoint.y,
                   bb.maxPoint.z - bb.minPoint.z) * 10.0
    except Exception:
        return 0.0


def component_edgebands(component):
    """{band name: total banding length mm} over this component's tagged faces —
    ONE instance's worth (callers multiply by occurrence quantity). Empty dict
    when nothing is tagged. Reads the WC_EDGEBAND face attributes the Edgeband
    command stamped; lengths divide each face's area by the panel thickness so
    curved edges count their real arc length."""
    dims = panel_dims_mm(component)
    thickness = dims[2] if dims else None
    out = {}
    try:
        bodies = component.bRepBodies
    except Exception:
        return out
    for bi in range(bodies.count):
        try:
            faces = bodies.item(bi).faces
        except Exception:
            continue
        for fi in range(faces.count):
            face = faces.item(fi)
            band = wc_attrs.get_edgeband(face)
            if not band:
                continue
            length = face_edgeband_length_mm(face, thickness)
            if length > 0:
                out[band] = out.get(band, 0.0) + length
    return out


def _cylinder_face_is_convex(face):
    """True when a cylindrical face bulges OUTWARD (a rounded panel edge/corner —
    bandable), False when it curves inward (a drilled hole, hinge cup, dowel bore —
    never banded). Convex ⇔ the surface normal points away from the cylinder axis.
    Non-cylindrical faces return True (no opinion)."""
    try:
        cyl = adsk.core.Cylinder.cast(face.geometry)
        if not cyl:
            return True
        pt = face.pointOnFace
        ok, normal = face.evaluator.getNormalAtPoint(pt)
        if not ok:
            return True
        # Radial direction at pt: its offset from the axis, minus the axial part.
        radial = cyl.origin.vectorTo(pt)
        axis = cyl.axis.copy()
        axis.normalize()
        along = axis.copy()
        along.scaleBy(radial.dotProduct(axis))
        radial.subtract(along)
        return radial.dotProduct(normal) >= 0
    except Exception:
        return True


# A face counts as EDGE-LIKE when its strip width (2·area ÷ perimeter — exact
# short side for a long rectangle) is at most this multiple of the panel
# thickness; anything wider is a broad face. 1.6 tolerates bbox slop and
# slightly proud bands while keeping 40 mm rails' broad faces broad.
_EDGE_WIDTH_FACTOR = 1.6


def bandable_faces(component):
    """The faces of `component` that can take edgebanding — its thickness-side
    ('edge') faces, found geometrically per body:

    - Every face gets a strip width = 2·area ÷ perimeter (for a long rectangle
      that IS the short side). Width ≤ 1.6 × panel thickness ⇒ edge-like;
      wider ⇒ a broad face (a slab skin). Width — not top-2-by-area — because a
      curved panel's outer skin is often SPLIT at a surface seam into two faces,
      and picking the two largest would orphan the end strip that only touches
      one half.
    - Bandable = an edge-like face adjacent (shared edge) to at least TWO
      distinct broad faces: the border strip between the skins. Groove/dado
      walls touch at most one skin, so joinery stays out.
    - Drilled holes are rejected two ways: a blind hole touches one skin
      (adjacency fails); a through hole is a concave cylinder
      (_cylinder_face_is_convex fails). A rounded corner/edge is convex and
      stays bandable.

    Returns NATIVE BRepFace objects, in body/face order; [] when nothing fits
    (incl. components with no measurable thickness)."""
    out = []
    dims = panel_dims_mm(component)
    if not dims or dims[2] <= 0:
        return out
    edge_cap_cm = _EDGE_WIDTH_FACTOR * dims[2] / 10.0
    try:
        bodies = component.bRepBodies
    except Exception:
        return out
    for bi in range(bodies.count):
        body = bodies.item(bi)
        faces = [body.faces.item(i) for i in range(body.faces.count)]
        if len(faces) < 3:      # a slab needs 2 broad skins + at least 1 edge
            continue
        broad_ids = set()
        for f in faces:
            try:
                perimeter = sum(f.edges.item(i).length for i in range(f.edges.count))
                if perimeter > 0 and (2.0 * f.area / perimeter) > edge_cap_cm:
                    broad_ids.add(f.tempId)
            except Exception:
                continue
        if len(broad_ids) < 2:  # no two skins — not slab-like (cleats, dowels…)
            continue
        for face in faces:
            if face.tempId in broad_ids:
                continue
            adjacent = set()
            try:
                edges = face.edges
                for ei in range(edges.count):
                    edge_faces = edges.item(ei).faces
                    for fi in range(edge_faces.count):
                        adjacent.add(edge_faces.item(fi).tempId)
            except Exception:
                continue
            adjacent.discard(face.tempId)
            if len(adjacent & broad_ids) < 2:
                continue
            if not _cylinder_face_is_convex(face):
                continue
            out.append(face)
    return out


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
# Component.partNumber on a cloud-referenced component is a BLOCKING data-service
# fetch: with a bad connection each read stalls Fusion ~30 s and then raises
# 'Failed to fetch Part number' — across a big model that reads as a total freeze.
# One failure means the service is unreachable, so stop asking for a while and
# let Part # come back blank instead of hanging the UI.
_PART_NUMBER_RETRY_AFTER = 0.0
_PART_NUMBER_COOLDOWN_S = 300.0


def _component_part_number(component):
    """Native Fusion component part number (read/write property), or ''. Returns
    '' without asking while the part-number service is in failure cooldown or
    Fusion is offline (the fetch would block for the network timeout)."""
    global _PART_NUMBER_RETRY_AFTER
    if time.time() < _PART_NUMBER_RETRY_AFTER:
        return ''
    try:
        if adsk.core.Application.get().isOffLine:
            return ''
    except Exception:
        pass
    try:
        return component.partNumber or ''
    except Exception:
        _PART_NUMBER_RETRY_AFTER = time.time() + _PART_NUMBER_COOLDOWN_S
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

    Each node also carries `edgebands`: [{name, length_mm, cost_per_m, cost}] for
    ONE instance — the summed lengths of its WC_EDGEBAND-tagged faces, priced from
    the Sheets library's band catalogue (cost_per_m/cost None when the band is
    unpriced or no longer in the library). Empty list when nothing is tagged.

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

    library = sheets_store.load()
    materials = library['materials']
    band_catalogue = library['edgebands']
    waste_mult = 1.0 + settings_store.get_waste_percent() / 100.0
    rate_cache = {}   # (material lower, thickness rounded) -> rate or None

    def rate_for(material_name, thickness):
        key = (str(material_name).strip().lower(), round(thickness, 1))
        if key not in rate_cache:
            m = sheets_store.find_material(materials, material_name, thickness)
            rate_cache[key] = sheets_store.cost_rate_per_m2(m)
        return rate_cache[key]

    def edgeband_rows(component):
        """[{name, length_mm, cost_per_m, cost}] for ONE instance of `component`,
        priced from the band catalogue. The waste factor applies like it does to
        panels (banding has offcuts at every edge)."""
        rows = []
        for name, length_mm in sorted(component_edgebands(component).items()):
            rate = sheets_store.edgeband_cost_per_m(
                sheets_store.find_edgeband(band_catalogue, name))
            cost = length_mm / 1000.0 * rate * waste_mult if rate is not None else None
            rows.append({'name': name, 'length_mm': round(length_mm, 1),
                         'cost_per_m': rate, 'cost': cost})
        return rows

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

    # One subtree build per unique component: the same cabinet dropped in 10
    # times used to re-walk its dims / materials / per-face edgeband attributes
    # 10 times over, which is what froze Fusion on big models. Keyed by
    # (source document, component name) — component names are unique within a
    # document, but two inserted library cabinets can each contain a "Left Side".
    proto_cache = {}

    def _comp_key(component):
        # parentDesign.rootComponent stays in memory; Document-level properties
        # can force a (network) load of a referenced design, so avoid them here.
        try:
            return (component.parentDesign.rootComponent.name, component.name)
        except Exception:
            return None

    def build_proto(component):
        children = build_level(component.occurrences)
        ntype = _node_type(component, bool(children))
        if ntype == 'Assembly':
            # An Assembly row shows no dims or banding; measuring one via
            # Component.boundingBox walks every body in its subtree.
            dims = (0.0, 0.0, 0.0)
            bands = []
        else:
            dims = panel_dims_mm(component) or (0.0, 0.0, 0.0)
            bands = edgeband_rows(component)
        proto = {
            'name': component.name,
            'type': ntype,
            'material': panel_material(component),
            'part_number': _component_part_number(component),
            'L': dims[0], 'W': dims[1], 'T': dims[2],
            'qty': 1,
            'edgebands': bands,
            'children': children,
        }
        unit, kind = cost_for(component, proto, children)
        proto['unit_cost'] = unit
        proto['cost'] = unit
        proto['cost_kind'] = kind
        return proto

    def node_for(component, qty):
        key = _comp_key(component)
        proto = proto_cache.get(key) if key else None
        if proto is None:
            proto = build_proto(component)
            if key:
                proto_cache[key] = proto
        node = copy.deepcopy(proto)
        node['qty'] = qty
        node['cost'] = node['unit_cost'] * qty if node['unit_cost'] is not None else None
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
    {'panels_est', 'hardware', 'edgeband', 'grand', 'unpriced_panels',
     'edgebands': [{name, length_mm, cost|None}]} — panels_est is the sheet-derived
    estimate, hardware the entered purchase costs, edgeband the priced banding,
    grand their sum; unpriced_panels counts physical panels no rate could be found
    for (so a low total can't silently mean 'panels missing from the bill'). The
    edgebands list totals every tagged band BY TYPE across the design — an unpriced
    band still reports its length with cost None, so the metres to buy are always
    complete even when the library has no price yet.

    Node costs are relative to ONE instance of their parent, so the walk carries
    the multiplier of enclosing quantities (2 cabinets × 4 screws = 8 screws)."""
    totals = {'panels_est': 0.0, 'hardware': 0.0, 'edgeband': 0.0, 'grand': 0.0,
              'unpriced_panels': 0, 'edgebands': []}
    bands = {}   # name -> {'name', 'length_mm', 'cost', 'priced'}

    def walk(ns, mult):
        for n in ns:
            eff_qty = mult * n['qty']
            kind = n.get('cost_kind')
            if kind == 'set':
                totals['hardware'] += n['unit_cost'] * eff_qty
                continue    # descendants (and their banding) are in this price
            for b in n.get('edgebands') or []:
                agg = bands.setdefault(b['name'], {'name': b['name'], 'length_mm': 0.0,
                                                   'cost': 0.0, 'priced': True})
                agg['length_mm'] += b['length_mm'] * eff_qty
                if b['cost'] is not None:
                    agg['cost'] += b['cost'] * eff_qty
                else:
                    agg['priced'] = False
            if kind == 'est':
                totals['panels_est'] += n['unit_cost'] * eff_qty
            elif n['type'] == 'Panel' and kind is None:
                totals['unpriced_panels'] += eff_qty
            walk(n['children'], eff_qty)

    walk(nodes, 1)
    for name in sorted(bands, key=str.lower):
        agg = bands[name]
        cost = agg['cost'] if agg['priced'] else None
        totals['edgebands'].append({'name': name,
                                    'length_mm': round(agg['length_mm'], 1),
                                    'cost': cost})
        if cost:
            totals['edgeband'] += cost
    totals['grand'] = totals['panels_est'] + totals['hardware'] + totals['edgeband']
    return totals


def flatten_tree(nodes, level=0):
    """Depth-first (node, level) pairs from build_tree() output — for tabular export
    (Excel outline levels) and flat rendering."""
    out = []
    for n in nodes:
        out.append((n, level))
        out.extend(flatten_tree(n['children'], level + 1))
    return out
