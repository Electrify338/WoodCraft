"""Pure-math rectangle nesting for the Cut List report. No Fusion API here.

A **guillotine** bin-packer (full edge-to-edge cuts, so layouts stay panel-saw
friendly). To cut waste it doesn't trust a single heuristic: it packs the parts
several ways — different sort orders, both guillotine split rules (split along the
shorter vs the longer leftover axis), and a few placement scores — coalesces the
leftover offcuts after every cut, and keeps the best result (fewest sheets, then
the least-fragmented layout with the largest contiguous offcut). That places equal
parts side-by-side instead of scattering them.

Every dimension is in millimetres. `kerf` is the saw gap reserved on the right +
bottom of each part; `trim` is an unusable border around the sheet.
"""

EPS = 1e-6

SCORE_AREA = 'area'     # minimise leftover area of the chosen free rect
SCORE_SHORT = 'short'   # minimise the shorter leftover side (best short-side fit)
SCORE_LONG = 'long'     # minimise the longer leftover side


def _fits(fw, fh, w, h, kerf):
    return (w + kerf) <= fw + EPS and (h + kerf) <= fh + EPS


def _coalesce(free):
    """Merge adjacent free rectangles that line up into a single larger rectangle,
    so offcuts fragmented by successive cuts are reassembled. Repeats until stable."""
    merged = True
    while merged:
        merged = False
        n = len(free)
        for i in range(n):
            for j in range(i + 1, n):
                ax, ay, aw, ah = free[i]
                bx, by, bw, bh = free[j]
                # Side by side in the same row.
                if abs(ay - by) < EPS and abs(ah - bh) < EPS:
                    if abs(ax + aw - bx) < EPS:
                        free[i] = (ax, ay, aw + bw, ah); free.pop(j); merged = True; break
                    if abs(bx + bw - ax) < EPS:
                        free[i] = (bx, by, aw + bw, ah); free.pop(j); merged = True; break
                # Stacked in the same column.
                if abs(ax - bx) < EPS and abs(aw - bw) < EPS:
                    if abs(ay + ah - by) < EPS:
                        free[i] = (ax, ay, aw, ah + bh); free.pop(j); merged = True; break
                    if abs(by + bh - ay) < EPS:
                        free[i] = (bx, by, aw, ah + bh); free.pop(j); merged = True; break
            if merged:
                break


def _place_in_sheet(sheet, rect, kerf, allow_rotation, split_long, score):
    """Place one rect into the best free rectangle of `sheet`, then guillotine-split
    the leftover. Returns False if it doesn't fit anywhere on this sheet."""
    options = [(rect['w'], rect['h'], False)]
    if allow_rotation and abs(rect['w'] - rect['h']) > EPS:
        options.append((rect['h'], rect['w'], True))

    best = None  # (score, free_idx, w, h, rotated)
    for fi, (fx, fy, fw, fh) in enumerate(sheet['free']):
        for (w, h, rotated) in options:
            if _fits(fw, fh, w, h, kerf):
                lw, lh = fw - (w + kerf), fh - (h + kerf)
                if score == SCORE_AREA:
                    sc = fw * fh - (w + kerf) * (h + kerf)
                elif score == SCORE_SHORT:
                    sc = min(lw, lh)
                else:
                    sc = max(lw, lh)
                if best is None or sc < best[0] - EPS:
                    best = (sc, fi, w, h, rotated)
    if best is None:
        return False

    _, fi, w, h, rotated = best
    fx, fy, fw, fh = sheet['free'].pop(fi)
    sheet['placements'].append({
        'x': fx, 'y': fy, 'w': w, 'h': h, 'rotated': rotated,
        'id': rect['id'], 'label': rect['label'],
    })

    nw, nh = w + kerf, h + kerf
    lw, lh = fw - nw, fh - nh
    # Guillotine split: keep the full-width strip below (horizontal cut) or the
    # full-height strip to the right (vertical cut). `split_long` flips the choice
    # so we can try both and keep whichever packs tighter.
    horizontal_cut = (lw > lh) if split_long else (lw <= lh)
    if horizontal_cut:
        if lw > EPS:
            sheet['free'].append((fx + nw, fy, lw, nh))
        if lh > EPS:
            sheet['free'].append((fx, fy + nh, fw, lh))
    else:
        if lw > EPS:
            sheet['free'].append((fx + nw, fy, lw, fh))
        if lh > EPS:
            sheet['free'].append((fx, fy + nh, nw, lh))
    _coalesce(sheet['free'])
    return True


def _run(order, usable_w, usable_h, kerf, allow_rotation, split_long, score):
    """Pack the (already sorted) parts onto as many sheets as needed with one
    fixed heuristic. Returns the list of sheets."""
    sheets = []
    for rect in order:
        placed = False
        for sheet in sheets:
            if _place_in_sheet(sheet, rect, kerf, allow_rotation, split_long, score):
                placed = True
                break
        if not placed:
            sheet = {'free': [(0.0, 0.0, usable_w, usable_h)], 'placements': []}
            _place_in_sheet(sheet, rect, kerf, allow_rotation, split_long, score)
            sheets.append(sheet)
    return sheets


def _quality(sheets):
    """Sort key for choosing the best packing (smaller is better): fewest sheets,
    then the least-fragmented layout, then the largest single contiguous offcut."""
    free_count = sum(len(s['free']) for s in sheets)
    max_free = max((fw * fh for s in sheets for (_x, _y, fw, fh) in s['free']), default=0.0)
    return (len(sheets), free_count, -max_free)


def pack(rects, sheet_w, sheet_h, kerf=0.0, trim=0.0, allow_rotation=True):
    """Pack rects (each {'id','label','w','h'}) onto sheets of sheet_w x sheet_h.

    Tries several orderings/split-rules/scores and returns the best:
    {'sheets': [{'placements':[...], 'free':[...]}], 'unplaced': [...],
     'usable_w', 'usable_h'}. Parts bigger than a whole usable sheet go to
    'unplaced'."""
    usable_w = max(0.0, sheet_w - 2 * trim)
    usable_h = max(0.0, sheet_h - 2 * trim)

    placeable, unplaced = [], []
    for rect in rects:
        too_big = (not _fits(usable_w, usable_h, rect['w'], rect['h'], kerf) and
                   not (allow_rotation and _fits(usable_w, usable_h, rect['h'], rect['w'], kerf)))
        (unplaced if too_big else placeable).append(rect)

    orderings = (
        lambda r: (max(r['w'], r['h']), r['w'] * r['h']),   # longest side, then area
        lambda r: (r['w'] * r['h'], max(r['w'], r['h'])),   # area, then longest side
        lambda r: (r['h'], r['w']),                         # tallest first
        lambda r: (r['w'], r['h']),                         # widest first
    )

    best_sheets, best_key = None, None
    for okey in orderings:
        order = sorted(placeable, key=okey, reverse=True)
        for split_long in (False, True):
            for score in (SCORE_AREA, SCORE_SHORT, SCORE_LONG):
                sheets = _run(order, usable_w, usable_h, kerf, allow_rotation, split_long, score)
                key = _quality(sheets)
                if best_key is None or key < best_key:
                    best_key, best_sheets = key, sheets

    return {'sheets': best_sheets or [], 'unplaced': unplaced,
            'usable_w': usable_w, 'usable_h': usable_h}


def sheet_used_area(sheet):
    return sum(p['w'] * p['h'] for p in sheet['placements'])


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _darken(hex_color, factor=0.65):
    """Return a darker shade of a '#rrggbb' colour for part outlines. Falls back to
    the input on anything unparseable."""
    try:
        h = str(hex_color).strip().lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
        return f'#{r:02X}{g:02X}{b:02X}'
    except Exception:
        return hex_color


def sheet_svg(placements, sheet_len, sheet_wid, trim, scale, fill=None, stroke=None):
    """SVG of one sheet drawn at FULL size (sheet_len x sheet_wid), with the trim
    margin shown as a dashed inner border and the sheet dimensions labelled.

    Placement x/y are in usable (post-trim) coords, so parts are offset by `trim`
    onto the full sheet. Drawing the full sheet means the picture stays the same
    size when trim changes — only the usable border moves in.

    `fill`/`stroke` colour the parts (e.g. the material's display colour); they
    default to the standard yellow so existing/standalone callers are unaffected.
    """
    part_fill = fill or '#F3D573'
    part_stroke = stroke or (_darken(fill) if fill else '#A8842F')
    ml, mt, mr, mb = 34, 18, 10, 10          # margins for the dimension labels
    sw, sh = sheet_len * scale, sheet_wid * scale
    ox, oy = ml, mt
    width, height = ml + sw + mr, mt + sh + mb
    out = [f'<svg width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg">']

    # Full stock sheet.
    out.append(f'<rect x="{ox:.1f}" y="{oy:.1f}" width="{sw:.1f}" height="{sh:.1f}" '
               f'fill="#f4efe0" stroke="#888" stroke-width="1"/>')
    # Usable area / trim margin.
    if trim > 0:
        t = trim * scale
        out.append(f'<rect x="{ox + t:.1f}" y="{oy + t:.1f}" width="{sw - 2 * t:.1f}" '
                   f'height="{sh - 2 * t:.1f}" fill="none" stroke="#c9bd95" '
                   f'stroke-width="1" stroke-dasharray="4 3"/>')

    # Parts (offset by trim into the usable area).
    for p in placements:
        px = ox + (trim + p['x']) * scale
        py = oy + (trim + p['y']) * scale
        pw, ph = p['w'] * scale, p['h'] * scale
        out.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{pw:.1f}" height="{ph:.1f}" '
                   f'fill="{part_fill}" stroke="{part_stroke}" stroke-width="1"/>')
        if min(pw, ph) > 26:
            cx, cy = px + pw / 2, py + ph / 2
            out.append(f'<text x="{cx:.0f}" y="{cy - 2:.0f}" font-size="11" font-family="Arial" '
                       f'text-anchor="middle" fill="#333">{_esc(p["label"])}</text>')
            out.append(f'<text x="{cx:.0f}" y="{cy + 11:.0f}" font-size="10" font-family="Arial" '
                       f'text-anchor="middle" fill="#777">{p["w"]:.0f}&#215;{p["h"]:.0f}</text>')

    # Dimension labels: length along the top, width down the left side.
    out.append(f'<text x="{ox + sw / 2:.0f}" y="{oy - 5:.0f}" font-size="11" font-family="Arial" '
               f'text-anchor="middle" fill="#555">{sheet_len:.0f} mm</text>')
    lx, ly = ox - 7, oy + sh / 2
    out.append(f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="11" font-family="Arial" '
               f'text-anchor="middle" fill="#555" transform="rotate(-90 {lx:.0f} {ly:.0f})">'
               f'{sheet_wid:.0f} mm</text>')

    out.append('</svg>')
    return ''.join(out)
