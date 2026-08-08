"""Countertop outline maths — pure Python, no Fusion API.

The Countertop command's only hard part is turning "these wall faces + these
side panels" into rectangles, and that is plain 2D vector work. Keeping it here
(the same split as ``nesting.py`` and ``boring.py``) means the geometry can be
unit-tested with plain Python and the Fusion module stays thin glue.

Everything is in Fusion's internal length unit, the CENTIMETRE, and everything
happens in the horizontal plane: a worktop is a flat slab, so the Z axis only
ever contributes "how high do the cabinets reach".

The frame
---------
Each wall face defines a local 2D frame:

    o  a point on the wall (the face's own point, in world coords)
    n  the wall's unit normal, flattened to horizontal and flipped so it points
       AWAY from the wall and INTO the room (i.e. toward the cabinets)
    u  along the wall, = n rotated 90° (so (u, n) is a right-handed 2D basis)

A world point maps to ``(s, d)``: ``s`` runs along the wall, ``d`` is distance
out from the wall. The slab is then just the rectangle ``s ∈ [smin, smax]``,
``d ∈ [0, depth_total]`` — the back edge sits flush on the wall, the ends line
up with the outermost faces of the two edge cabinets' side panels.

Boxes
-----
Side panels arrive as axis-aligned world bounding boxes, 6-tuples
``(minx, miny, minz, maxx, maxy, maxz)``. Bounding boxes rather than real faces
because the ends of a run only need the panel's outer extent, and a bbox is what
Fusion hands over cheaply for both a body and a whole occurrence.
"""

import math

EPS = 1e-9
MM = 0.1                    # 1 mm expressed in cm

# A face counts as a "wall" only if its normal is near-horizontal. A worktop
# referenced off a ceiling or a floor is always a mis-pick, and catching it here
# gives a clear error instead of a nonsense slab. ~3° of slop.
WALL_NORMAL_Z_TOL = 0.05

# Which side panels belong to WHICH wall run.
#
# A panel counts toward a wall when its own depth extent OVERLAPS the band of
# depth that wall's worktop covers — not when its centre point happens to fall
# in a tolerance window. The centre test was too strict: a single panel slipping
# through left a "run" as long as that one panel was thick (18 mm), which is
# exactly the failure this replaced.
#
# `MIN_OVERLAP_FRACTION` of the shallower of (panel depth, worktop depth) must be
# shared. A side panel standing under the worktop overlaps essentially 100%; a
# panel on the far wall of a galley kitchen overlaps 0%.
MIN_OVERLAP_FRACTION = 0.3

# Two hard safety nets, because a wrong slab is worse than a wide one:
#   - a run needs at least MIN_BOXES_PER_RUN panels to define its ends. Ends come
#     in pairs; one surviving panel cannot describe a run, so rather than build a
#     sliver we fall back to every selected panel.
#   - and the result must still be at least MIN_RUN_CM long. No kitchen worktop is
#     100 mm; anything shorter means the filter went wrong, so fall back too.
MIN_BOXES_PER_RUN = 2
MIN_RUN_CM = 10.0

# Reaching INTO a corner.
#
# A run's ends come from its side panels, but at an inside corner the last
# cabinet stops short of the adjoining wall — the corner itself is occupied by
# the other run's cabinet, or there is simply a scribe gap. A worktop, though,
# genuinely runs right up to that wall. Left un-extended two things go wrong:
# the worktop has a gap at the corner, and — because the run doing the cutting
# no longer covers the whole overlap — a thin strip of the cut run survives
# alongside it.
#
# So each run's span is stretched to any picked wall its axis actually runs
# into. `EXTEND_MARGIN_CM` past the worktop depth is the furthest a corner gap
# can plausibly be (the adjoining cabinet's depth), which keeps the extension
# from stretching a run across a room to some unrelated wall.
EXTEND_MARGIN_CM = 10.0
PARALLEL_EPS = 1e-6         # |u·m| below this ⇒ the wall never crosses the run


# ---------------------------------------------------------------------------
# Vector helpers (2D, horizontal plane)
# ---------------------------------------------------------------------------
def normalize2(x, y):
    """Unit (x, y), or None if the vector is degenerate."""
    mag = math.hypot(x, y)
    if mag < EPS:
        return None
    return (x / mag, y / mag)


def is_wall_normal(normal) -> bool:
    """True if a 3D face normal is near-horizontal, i.e. the face is a wall."""
    nx, ny, nz = normal
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < EPS:
        return False
    return abs(nz / mag) < WALL_NORMAL_Z_TOL


def wall_axes(normal, origin, boxes):
    """The (n, u) frame for a wall.

    `normal` is the face's 3D normal (only its horizontal part is used). Its SIGN
    is unreliable — it depends on which side of the wall body Fusion considers
    outward — so the cabinets decide which way is "into the room": n is flipped
    to point toward whichever side most of the side panels are on.

    A count vote rather than a centroid, so one distant panel in an L-shaped
    kitchen can't drag the direction round. A tie falls back to the centroid.

    Returns (n, u) as 2D unit tuples, or None if the face is horizontal.
    """
    n = normalize2(normal[0], normal[1])
    if n is None:
        return None

    distances = []
    for box in boxes:
        cx, cy = box_center_xy(box)
        distances.append((cx - origin[0]) * n[0] + (cy - origin[1]) * n[1])

    positive = sum(1 for d in distances if d > 0)
    negative = len(distances) - positive
    if positive < negative or (positive == negative and sum(distances) < 0):
        n = (-n[0], -n[1])
    return n, (-n[1], n[0])


def to_frame(point, o, n, u):
    """World (x, y) → (s, d): along the wall, out from the wall."""
    dx, dy = point[0] - o[0], point[1] - o[1]
    return (dx * u[0] + dy * u[1], dx * n[0] + dy * n[1])


def to_world(s, d, o, n, u):
    """(s, d) → world (x, y)."""
    return (o[0] + u[0] * s + n[0] * d,
            o[1] + u[1] * s + n[1] * d)


# ---------------------------------------------------------------------------
# Bounding-box helpers
# ---------------------------------------------------------------------------
def box_center_xy(box):
    return ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0)


def box_corners_xy(box):
    """The four horizontal corners of an axis-aligned box."""
    return [(box[0], box[1]), (box[3], box[1]), (box[3], box[4]), (box[0], box[4])]


def top_z(boxes):
    """Highest point of any box — where the worktop's underside sits."""
    return max(b[5] for b in boxes)


def depth_range(box, o, n):
    """(dmin, dmax) — how far a box spans out from the wall."""
    values = [(cx - o[0]) * n[0] + (cy - o[1]) * n[1]
              for cx, cy in box_corners_xy(box)]
    return min(values), max(values)


def boxes_for_wall(boxes, o, n, depth_total, fraction=MIN_OVERLAP_FRACTION):
    """The subset of `boxes` standing under this wall's worktop.

    Membership is depth OVERLAP: how much of the band [0, depth_total] out from
    the wall the panel shares. Falls back to EVERY box unless at least
    MIN_BOXES_PER_RUN survive — a run's ends come in pairs, and one lone panel
    would otherwise produce a slab as long as that panel is thick.
    """
    keep = []
    for box in boxes:
        lo, hi = depth_range(box, o, n)
        overlap = min(hi, depth_total) - max(lo, 0.0)
        if overlap <= 0:
            continue
        reference = max(min(hi - lo, depth_total), EPS)
        if overlap >= fraction * reference:
            keep.append(box)
    return keep if len(keep) >= MIN_BOXES_PER_RUN else list(boxes)


# ---------------------------------------------------------------------------
# The outline
# ---------------------------------------------------------------------------
def run_span(boxes, o, n, u):
    """(smin, smax) — how far the run reaches along the wall.

    Every corner of every box is projected, so the span covers the panels'
    OUTER faces however the cabinets are rotated. Returns None for no boxes or
    a degenerate (zero-length) span.
    """
    values = [to_frame(corner, o, n, u)[0]
              for box in boxes for corner in box_corners_xy(box)]
    if not values:
        return None
    smin, smax = min(values), max(values)
    if smax - smin < MM:            # under 1 mm long — nothing sensible to build
        return None
    return (smin, smax)


def clip_polygon(polygon, point, normal, tol=1e-9):
    """Sutherland–Hodgman: the part of `polygon` on the side `normal` points to.

    Used to stop a run at the OTHER walls. A worktop cannot pass through a wall,
    but the ends of a run come from the side panels, which say nothing about
    where the room stops — so a run whose panels reach past an inside corner
    would otherwise poke through the adjoining wall and leave a sliver there
    once the corner cut removed the rest.

    `normal` must point INTO the room (the same orientation `wall_axes` returns),
    so the half-plane kept is the habitable side. Returns [] if nothing survives.
    """
    result = []
    count = len(polygon)
    for i in range(count):
        current = polygon[i]
        following = polygon[(i + 1) % count]
        d_current = (current[0] - point[0]) * normal[0] + (current[1] - point[1]) * normal[1]
        d_next = (following[0] - point[0]) * normal[0] + (following[1] - point[1]) * normal[1]

        if d_current >= -tol:
            result.append(current)
        # Crossing the plane: add the intersection so the cut edge is exact.
        if (d_current > tol and d_next < -tol) or (d_current < -tol and d_next > tol):
            t = d_current / (d_current - d_next)
            result.append((current[0] + t * (following[0] - current[0]),
                           current[1] + t * (following[1] - current[1])))
    return result


def dedupe(polygon, tol=MM * 0.1):
    """Drop points that repeat the one before (or the last, for the closing
    edge). A clip plane passing exactly through a corner emits a duplicate, and
    a duplicate becomes a zero-length sketch line that Fusion cannot profile.
    """
    out = []
    for point in polygon:
        if out and abs(point[0] - out[-1][0]) < tol and abs(point[1] - out[-1][1]) < tol:
            continue
        out.append(point)
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) < tol and abs(out[0][1] - out[-1][1]) < tol:
        out.pop()
    return out


def clip_to_walls(polygon, clips):
    """Clip a footprint by every wall plane in `clips` — [(point, normal), …].

    Falls back to the unclipped polygon if the clips would erase it: an empty
    run is never the answer, and a too-long one is at least visible and
    trimmable.
    """
    current = list(polygon)
    for point, normal in clips:
        clipped = dedupe(clip_polygon(current, point, normal))
        if len(clipped) < 3:
            return list(polygon)
        current = clipped
    return current


def rect_corners(o, n, u, span, near, far):
    """A rectangle in the wall frame → four world (x, y) corners, wound
    consistently. `span` is (smin, smax) along the wall; `near`/`far` are
    distances out from the wall face.
    """
    smin, smax = span
    return [to_world(smin, near, o, n, u),
            to_world(smax, near, o, n, u),
            to_world(smax, far, o, n, u),
            to_world(smin, far, o, n, u)]


def extend_span_to_walls(span, o, n, u, clips, limit):
    """Stretch a run's ends out to any wall its axis runs into.

    For each wall (point Q, inward normal m), the run's axis meets that plane at
        s* = ((Q - o)·m) / (u·m)
    and a wall parallel to the run gives a vanishing denominator — no crossing,
    so it is skipped (which is exactly what should happen to the far wall of a
    galley kitchen).

    Only a wall lying JUST beyond an end counts, within `limit`: that is a corner
    the run should fill, whereas a distant perpendicular wall is a different part
    of the house. Ends already past a wall are left alone — clipping pulls those
    back, and extending them would fight it.
    """
    smin, smax = span
    for point, normal in clips:
        denom = u[0] * normal[0] + u[1] * normal[1]
        if abs(denom) < PARALLEL_EPS:
            continue
        s = ((point[0] - o[0]) * normal[0] + (point[1] - o[1]) * normal[1]) / denom
        if smax < s <= smax + limit:
            smax = s
        elif smin - limit <= s < smin:
            smin = s
    return (smin, smax)


def plan_run(wall_origin, wall_normal, boxes, depth_total, other_walls=()):
    """Everything the Fusion side needs for one wall, or None if it can't build.

    The wall is the reference: the back edge lies ON the picked face and the
    front edge is that face offset by `depth_total`. The side panels only supply
    the two END lines — where the run starts and stops along the wall.

    `other_walls` is every OTHER picked wall, as (origin_xy, normal_xyz) pairs.
    The footprint is clipped against each, so a run stops exactly where the two
    wall planes intersect rather than carrying on past the corner. Without this
    the ends depend purely on the side panels — and a panel reaching past an
    inside corner pushes the slab through the adjoining wall, which then
    survives the corner cut as a thin sliver hugging that wall.

    Returns a dict:
        corners  world (x, y) tuples for the slab outline — a rectangle, or a
                 polygon with more sides where a wall has clipped it
        z        world Z of the slab's underside (top of the cabinets)
        length   run length in cm (for the summary and preview)
        used     how many of the given boxes set this run's ends
        total    how many boxes were offered, so the caller can say "2 of 4"
        clips    the wall half-planes applied, so the backsplash matches
    """
    if not boxes or not is_wall_normal(wall_normal) or depth_total <= 0:
        return None

    axes = wall_axes(wall_normal, wall_origin, boxes)
    if axes is None:
        return None
    n, u = axes

    # Orient every other wall the same way — into the room — so clipping keeps
    # the habitable side instead of cutting the run away entirely.
    clips = []
    for origin, normal in other_walls:
        if not is_wall_normal(normal):
            continue
        other = wall_axes(normal, origin, boxes)
        if other is not None:
            clips.append((origin, other[0]))

    mine = boxes_for_wall(boxes, wall_origin, n, depth_total)
    span = run_span(mine, wall_origin, n, u)

    # Last safety net: a plausible run is never shorter than MIN_RUN_CM. If the
    # filter produced a sliver, ignore it and let every selected panel set the
    # ends — a run that is too long is obvious on screen and trivially trimmed,
    # whereas an 18 mm sliver just looks broken.
    if span is None or (span[1] - span[0]) < MIN_RUN_CM:
        mine = list(boxes)
        span = run_span(mine, wall_origin, n, u)
    if span is None:
        return None

    # Reach into the corners FIRST, then clip. Extending makes the run meet the
    # adjoining wall (no gap in the worktop, and the run doing the cutting now
    # covers the whole overlap, so nothing survives as a strip); clipping then
    # guarantees it stops exactly there and never crosses.
    span = extend_span_to_walls(span, wall_origin, n, u, clips,
                                depth_total + EXTEND_MARGIN_CM)
    corners = clip_to_walls(rect_corners(wall_origin, n, u, span, 0.0, depth_total),
                            clips)

    # Report the length actually built, measured on the clipped footprint —
    # otherwise the summary and the preview label would advertise the overshoot
    # rather than the worktop you get.
    clipped_span = polygon_span(corners, wall_origin, n, u)

    return {'corners': corners,
            'z': top_z(mine),
            'length': (clipped_span[1] - clipped_span[0]) if clipped_span else 0.0,
            'used': len(mine),
            'total': len(boxes),
            # The frame is handed back so the caller can lay out anything else
            # against the same wall — the backsplash — without re-deriving it.
            'origin': wall_origin,
            'n': n,
            'u': u,
            'span': span,
            'clips': clips}


def polygon_span(polygon, o, n, u):
    """(smin, smax) of a footprint along the wall, or None if it is empty."""
    if not polygon:
        return None
    values = [to_frame(point, o, n, u)[0] for point in polygon]
    return (min(values), max(values))


def backsplash_corners(plan, thickness):
    """The backsplash footprint for a planned run: the same length, but only
    `thickness` deep, hard against the wall. It stands ON the worktop, so the
    caller starts its extrude at the slab's top face.

    Clipped by the same wall planes as its slab, so an upstand stops at the
    corner exactly where the worktop under it does.
    """
    if thickness <= 0:
        return None
    corners = rect_corners(plan['origin'], plan['n'], plan['u'],
                           plan['span'], 0.0, thickness)
    return clip_to_walls(corners, plan.get('clips', ()))


# ---------------------------------------------------------------------------
# Overlap between runs (the inside corner of an L- or U-shaped kitchen)
# ---------------------------------------------------------------------------
# Two runs meeting at a corner produce two rectangles that overlap over a
# square roughly depth × depth. Left alone that is coincident material, which
# reads as a modelling error and double-counts in the cut list — so the caller
# combine-cuts one with the other. These helpers only decide WHETHER two pieces
# overlap; the boolean itself is Fusion's job.

# Pieces that merely touch along an edge (a run ending exactly where the next
# begins) are NOT overlapping. A hair of tolerance keeps floating-point noise
# from turning a clean butt joint into a needless cut.
TOUCH_TOL_CM = 0.01         # 0.1 mm


def _edge_normals(polygon):
    """One outward axis per edge — the candidate separating axes for SAT."""
    axes = []
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        axis = normalize2(-(y2 - y1), x2 - x1)
        if axis is not None:
            axes.append(axis)
    return axes


def _projection(polygon, axis):
    values = [px * axis[0] + py * axis[1] for px, py in polygon]
    return min(values), max(values)


def polygons_overlap(a, b, tol=TOUCH_TOL_CM) -> bool:
    """True if two convex polygons share area (separating-axis theorem).

    Convex is guaranteed here — both are rectangles — and SAT handles them at
    any rotation, which matters because a kitchen's two walls need not meet at
    90° and the runs are built in each wall's own frame.
    """
    for axis in _edge_normals(a) + _edge_normals(b):
        amin, amax = _projection(a, axis)
        bmin, bmax = _projection(b, axis)
        if amin >= bmax - tol or bmin >= amax - tol:
            return False            # a gap on this axis ⇒ no overlap at all
    return True


def ranges_overlap(a_lo, a_hi, b_lo, b_hi, tol=TOUCH_TOL_CM) -> bool:
    """True if two 1D intervals share more than `tol`. Used on Z, so runs at
    different heights (a raised breakfast bar over base units) are left alone."""
    return min(a_hi, b_hi) - max(a_lo, b_lo) > tol


def pieces_overlap(a, b) -> bool:
    """True if two solids overlap in plan AND in height.

    Each piece is a dict with `corners` (its footprint), `z` (underside) and
    `height`.
    """
    if not ranges_overlap(a['z'], a['z'] + a['height'],
                          b['z'], b['z'] + b['height']):
        return False
    return polygons_overlap(a['corners'], b['corners'])


def overlapping_pairs(pieces):
    """(keep_index, cut_index) for every overlapping pair, earlier piece kept.

    Deterministic on purpose: run 1 survives intact and later runs are the ones
    trimmed back, so re-running the command gives the same result and the corner
    always belongs to the first wall you picked.
    """
    pairs = []
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            if pieces_overlap(pieces[i], pieces[j]):
                pairs.append((i, j))
    return pairs
