# WoodCraft — a Fusion add-in for cabinetmaking.
# Copyright (C) 2026 Abdelrahman Youssry
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.

"""Skirting (plinth) outline maths — pure Python, no Fusion API.

Same split as ``countertop_geom.py``, ``nesting.py`` and ``boring.py``: the hard
part is 2D vector work, so it lives here where it can be unit-tested with plain
Python, and the Fusion module stays thin glue.

Everything is in Fusion's internal length unit, the CENTIMETRE. Everything happens
in the horizontal plane — a skirting board is a vertical slab of constant height, so
Z only ever contributes "how tall": from the ground up to the underside of the
cabinets.

The shape of the problem
------------------------
A skirting board follows the FRONT of a cabinet run, set back from it, and runs from
the underside of the carcass down to the floor. So each run reduces to one straight
line in plan:

    front plane, pushed back by `setback`  ->  the skirting's OUTER face
    that line, pushed back by `thickness`  ->  its INNER face

which makes a run a rectangle, and an L or a U a chain of rectangles that have to
meet cleanly at the corners. An island is the same thing closed into a loop.

Mitres
------
Corners are mitred, so the pieces are NOT plain rectangles: at a corner the outer
edge runs to the outer intersection point and the inner edge stops at the inner
intersection point, and the cut joins the two. For two runs meeting at 90° that is
the familiar 45° cut; the same construction handles any angle, which matters for a
kitchen that isn't perfectly square.

This is the classic offset-polyline problem, and doing it by intersecting the offset
LINES (rather than trimming rectangles against each other) is what makes it fall out
correctly for both directions of turn.

Frames
------
A `Segment` carries its own frame so a run at any angle works the same as one along
X or Y:

    p0, p1  the ends of the OUTER face line, in world plan coordinates
    m       unit inward normal — points from the outer face toward the inner one,
            i.e. INTO the cabinet

Pieces come back as plan polygons: lists of (x, y) in anticlockwise-or-clockwise
order as given, ready to be drawn as a sketch profile and extruded upward.
"""

import math

EPS = 1e-9
MM = 0.1                        # 1 mm in cm

# Longest single piece of skirting. Board stock is sold in lengths and a 4 m run is
# not one piece, so anything longer is split into equal pieces no longer than this.
# Splits are BUTT joints cut square across the board — only corners are mitred.
MAX_PIECE_CM = 300.0

# Two segments are treated as meeting at a corner when their outer lines cross
# within this distance of both segments' ends. Generous because the front planes of
# two runs meeting at a corner rarely intersect exactly at either run's end — one
# usually has to be extended a cabinet-depth or so to reach the other.
CORNER_REACH_CM = 120.0

# Below this, two directions count as the same line and are never mitred together.
PARALLEL_TOL = 1e-6


# ---------------------------------------------------------------------------
# Small 2D helpers
# ---------------------------------------------------------------------------
def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def scale(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    """2D scalar cross product — sign tells which way a turns onto b."""
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.hypot(a[0], a[1])


def normalize(a):
    n = length(a)
    if n < EPS:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def left_normal(u):
    """u rotated 90° anticlockwise."""
    return (-u[1], u[0])


def line_intersection(p, u, q, v):
    """Intersection of the infinite lines p+su and q+tv, or None if parallel."""
    denom = cross(u, v)
    if abs(denom) < PARALLEL_TOL:
        return None
    w = sub(q, p)
    s = cross(w, v) / denom
    return add(p, scale(u, s))


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------
class Segment:
    """One straight length of skirting, described by its OUTER face line.

    `m` is the inward normal: the direction the board's thickness goes, pointing
    away from the room and into the cabinets. Keeping it explicit (rather than
    deriving it from winding order) is what lets an open L-shaped chain and a closed
    island loop share all the same code."""

    def __init__(self, p0, p1, m, label=''):
        self.p0 = (float(p0[0]), float(p0[1]))
        self.p1 = (float(p1[0]), float(p1[1]))
        self.m = normalize(m)
        self.label = label

    @property
    def u(self):
        """Unit direction along the run, p0 -> p1."""
        return normalize(sub(self.p1, self.p0))

    @property
    def length(self):
        return length(sub(self.p1, self.p0))

    def inner_line(self, thickness):
        """(point, direction) of the inner face line."""
        offset = scale(self.m, thickness)
        return add(self.p0, offset), self.u

    def __repr__(self):
        return (f'Segment({self.p0} -> {self.p1}, m={self.m}, '
                f'len={self.length:.1f}, {self.label!r})')


def segment_from_span(origin, u, s_min, s_max, m):
    """A segment from a run frame: origin + s·u for s in [s_min, s_max]."""
    u = normalize(u)
    return Segment(add(origin, scale(u, s_min)), add(origin, scale(u, s_max)), m)


# ---------------------------------------------------------------------------
# Chaining runs into corners
# ---------------------------------------------------------------------------
def _corner_point(a: Segment, b: Segment):
    """Where a's and b's OUTER lines cross, if that is plausibly a shared corner.

    Plausible means the crossing is near an end of both runs — within
    CORNER_REACH_CM of the segment, measured along its own direction. Two runs on
    opposite sides of a galley kitchen have parallel lines and never cross; two runs
    of a U meet close to their ends and do."""
    point = line_intersection(a.p0, a.u, b.p0, b.u)
    if point is None:
        return None
    for seg in (a, b):
        s = dot(sub(point, seg.p0), seg.u)
        if s < -CORNER_REACH_CM or s > seg.length + CORNER_REACH_CM:
            return None
    return point


def chain_segments(segments):
    """Order `segments` into chains of runs that meet at corners.

    Returns [[Segment, ...], ...]. A straight run on its own comes back as a chain
    of one; an L as a chain of two; a U as a chain of three. Segments that meet
    nothing keep their own chain rather than being dropped — a detached run still
    needs its skirting.

    Greedy rather than clever: kitchens have three or four runs, so the cost of
    walking every pair is nothing, and a greedy walk from an unvisited end produces
    the natural order (left arm, back, right arm)."""
    remaining = list(segments)
    chains = []

    while remaining:
        chain = [remaining.pop(0)]

        # Extend forward, then backward, so a middle run picks up both neighbours.
        extended = True
        while extended:
            extended = False
            for end in (1, 0):
                anchor = chain[-1] if end else chain[0]
                for i, candidate in enumerate(remaining):
                    if _corner_point(anchor, candidate) is None:
                        continue
                    if end:
                        chain.append(remaining.pop(i))
                    else:
                        chain.insert(0, remaining.pop(i))
                    extended = True
                    break
                if extended:
                    break
        chains.append(chain)
    return chains


def _orient_chain(chain):
    """Flip segments so each one's p1 end is the one nearest the next segment.

    A run's endpoints come out of a bounding-box span in arbitrary order. Mitring
    needs them to run nose-to-tail, or the corner is computed at the wrong ends and
    the piece is mitred where it should be square."""
    if len(chain) < 2:
        return chain

    out = [chain[0]]
    for nxt in chain[1:]:
        prev = out[-1]
        corner = _corner_point(prev, nxt)
        if corner is None:
            out.append(nxt)
            continue
        # prev should END at the corner, nxt should START there.
        if dot(sub(corner, prev.p0), prev.u) < prev.length * 0.5:
            prev.p0, prev.p1 = prev.p1, prev.p0
        if dot(sub(corner, nxt.p0), nxt.u) > nxt.length * 0.5:
            nxt.p0, nxt.p1 = nxt.p1, nxt.p0
        out.append(nxt)
    return out


# ---------------------------------------------------------------------------
# Mitring
# ---------------------------------------------------------------------------
def mitre_chain(chain, thickness, closed=False):
    """Plan polygons for a chain of segments, mitred where they meet.

    One polygon per segment, each [outer start, outer end, inner end, inner start].
    A free end is cut square; a shared end is cut to the mitre.

    The construction: the outer corner is where the two OUTER lines cross and the
    inner corner is where the two INNER lines cross. Joining those two points is the
    mitre, and because both come from line intersections it lands at 45° for a
    square corner and at the correct half-angle for anything else — including a
    corner that turns the other way, which is what a naive "trim the rectangles"
    approach gets wrong."""
    if not chain:
        return []
    chain = _orient_chain(list(chain))
    n = len(chain)

    def neighbour(i, step):
        j = i + step
        if 0 <= j < n:
            return chain[j]
        return chain[j % n] if closed and n > 1 else None

    polygons = []
    for i, seg in enumerate(chain):
        inner_pt, inner_dir = seg.inner_line(thickness)

        outer_start, inner_start = seg.p0, inner_pt
        outer_end = seg.p1
        inner_end = add(seg.p1, scale(seg.m, thickness))

        prev = neighbour(i, -1)
        if prev is not None and prev is not seg:
            corner = _corner_point(prev, seg)
            if corner is not None:
                prev_inner_pt, prev_inner_dir = prev.inner_line(thickness)
                inner_corner = line_intersection(inner_pt, inner_dir,
                                                 prev_inner_pt, prev_inner_dir)
                if inner_corner is not None:
                    outer_start, inner_start = corner, inner_corner

        nxt = neighbour(i, 1)
        if nxt is not None and nxt is not seg:
            corner = _corner_point(seg, nxt)
            if corner is not None:
                nxt_inner_pt, nxt_inner_dir = nxt.inner_line(thickness)
                inner_corner = line_intersection(inner_pt, inner_dir,
                                                 nxt_inner_pt, nxt_inner_dir)
                if inner_corner is not None:
                    outer_end, inner_end = corner, inner_corner

        polygons.append([outer_start, outer_end, inner_end, inner_start])
    return polygons


# ---------------------------------------------------------------------------
# Splitting long pieces
# ---------------------------------------------------------------------------
def split_polygon(polygon, u, max_len=MAX_PIECE_CM):
    """Cut a mitred piece into lengths of at most `max_len`, square across the board.

    Splits are square, not mitred: a mitre is what a CORNER needs; a length join in
    the middle of a straight run is a butt joint, and cutting it at an angle would
    just waste board. Cuts are evenly spaced so a 4 m run becomes 2 × 2 m rather than
    3 m + 1 m — two matched pieces look deliberate, a stub does not.

    `u` is the run direction; the polygon may be a trapezoid because of its mitres,
    and the cut planes are perpendicular to u."""
    if not polygon:
        return []
    u = normalize(u)
    projections = [dot(p, u) for p in polygon]
    lo, hi = min(projections), max(projections)
    span = hi - lo
    if span <= max_len + EPS:
        return [polygon]

    count = int(math.ceil(span / max_len - EPS))
    step = span / count

    pieces = []
    for i in range(count):
        a = lo + i * step
        b = lo + (i + 1) * step
        piece = polygon
        if i > 0:
            piece = clip_half_plane(piece, u, a, keep_greater=True)
        if i < count - 1:
            piece = clip_half_plane(piece, u, b, keep_greater=False)
        if len(piece) >= 3:
            pieces.append(piece)
    return pieces


def clip_half_plane(polygon, axis, value, keep_greater, tol=1e-9):
    """Sutherland–Hodgman clip of `polygon` against dot(p, axis) ≷ value."""
    if not polygon:
        return []

    def inside(p):
        d = dot(p, axis) - value
        return d >= -tol if keep_greater else d <= tol

    out = []
    count = len(polygon)
    for i in range(count):
        current, nxt = polygon[i], polygon[(i + 1) % count]
        cur_in, nxt_in = inside(current), inside(nxt)
        if cur_in:
            out.append(current)
        if cur_in != nxt_in:
            d1 = dot(current, axis) - value
            d2 = dot(nxt, axis) - value
            denom = d1 - d2
            if abs(denom) > tol:
                t = d1 / denom
                out.append(add(current, scale(sub(nxt, current), t)))
    return dedupe(out)


def dedupe(polygon, tol=MM * 0.1):
    """Drop consecutive duplicate points (and a closing duplicate)."""
    out = []
    for p in polygon:
        if not out or length(sub(p, out[-1])) > tol:
            out.append(p)
    while len(out) > 1 and length(sub(out[0], out[-1])) <= tol:
        out.pop()
    return out


def polygon_area(polygon):
    """Twice-signed area / 2 — used to reject slivers left by a clip."""
    total = 0.0
    for i in range(len(polygon)):
        a, b = polygon[i], polygon[(i + 1) % len(polygon)]
        total += cross(a, b)
    return abs(total) * 0.5


# ---------------------------------------------------------------------------
# Whole-run planning
# ---------------------------------------------------------------------------
def plan_chain(chain, thickness, closed=False, max_len=MAX_PIECE_CM):
    """[[polygon, ...], ...] — for each segment in the chain, its mitred piece split
    into stock lengths. The nesting mirrors the browser structure the command
    builds: one component per run, one body per piece inside it."""
    polygons = mitre_chain(chain, thickness, closed=closed)
    out = []
    for seg, polygon in zip(_orient_chain(list(chain)), polygons):
        polygon = dedupe(polygon)
        if len(polygon) < 3 or polygon_area(polygon) < (MM * MM):
            out.append([])
            continue
        out.append([p for p in split_polygon(polygon, seg.u, max_len)
                    if len(p) >= 3 and polygon_area(p) > (MM * MM)])
    return out


def island_segments(corners, setback, inward_hint=None):
    """Four segments forming the OUTER faces of an island's skirting.

    `corners` is the island's plan footprint as four points in order. Each side is
    pushed IN by `setback`, because a plinth is set back on every face of an island
    exactly as it is on the front of a run — an island is visible from all sides,
    which is the whole reason it gets skirting all the way round.

    The inward direction per side is derived from the polygon's winding, so a
    footprint given either clockwise or anticlockwise produces skirting that faces
    outward and thickens inward."""
    corners = dedupe(list(corners))
    if len(corners) < 3:
        return []

    # Signed area tells the winding, which tells which normal points inward.
    signed = 0.0
    for i in range(len(corners)):
        a, b = corners[i], corners[(i + 1) % len(corners)]
        signed += cross(a, b)
    turn = 1.0 if signed > 0 else -1.0

    segments = []
    for i in range(len(corners)):
        a, b = corners[i], corners[(i + 1) % len(corners)]
        u = normalize(sub(b, a))
        if length(u) < EPS:
            continue
        # For anticlockwise winding the interior is to the LEFT of a->b.
        inward = scale(left_normal(u), turn)
        offset = scale(inward, setback)
        segments.append(Segment(add(a, offset), add(b, offset), inward))
    return segments
