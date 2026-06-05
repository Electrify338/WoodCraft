"""Pure-math rectangle nesting for the Cut List report. No Fusion API here.

A guillotine bin-packer (best-area-fit placement + shorter-axis free-rect split).
Guillotine layouts suit panel saws, which make full edge-to-edge cuts. Every
dimension is in millimetres. Kerf is reserved on the right + bottom of each part;
trim is an unusable border around the sheet.
"""

EPS = 1e-6


def _fits(fw, fh, w, h, kerf):
    return (w + kerf) <= fw + EPS and (h + kerf) <= fh + EPS


def _place_in_sheet(sheet, rect, kerf, allow_rotation):
    options = [(rect['w'], rect['h'], False)]
    if allow_rotation and abs(rect['w'] - rect['h']) > EPS:
        options.append((rect['h'], rect['w'], True))

    best = None  # (waste, free_idx, w, h, rotated)
    for fi, (fx, fy, fw, fh) in enumerate(sheet['free']):
        for (w, h, rotated) in options:
            if _fits(fw, fh, w, h, kerf):
                waste = fw * fh - (w + kerf) * (h + kerf)
                if best is None or waste < best[0]:
                    best = (waste, fi, w, h, rotated)
    if best is None:
        return False

    _, fi, w, h, rotated = best
    fx, fy, fw, fh = sheet['free'].pop(fi)
    sheet['placements'].append({
        'x': fx, 'y': fy, 'w': w, 'h': h, 'rotated': rotated,
        'id': rect['id'], 'label': rect['label'],
    })

    # Guillotine split of the leftover, along the shorter leftover axis.
    nw, nh = w + kerf, h + kerf
    lw, lh = fw - nw, fh - nh
    if lw <= lh:
        if lw > EPS:
            sheet['free'].append((fx + nw, fy, lw, nh))
        if lh > EPS:
            sheet['free'].append((fx, fy + nh, fw, lh))
    else:
        if lw > EPS:
            sheet['free'].append((fx + nw, fy, lw, fh))
        if lh > EPS:
            sheet['free'].append((fx, fy + nh, nw, lh))
    return True


def pack(rects, sheet_w, sheet_h, kerf=0.0, trim=0.0, allow_rotation=True):
    """Pack rects (each {'id','label','w','h'}) onto sheets of sheet_w x sheet_h.

    Returns {'sheets': [{'placements':[...], 'free':[...]}], 'unplaced': [...],
             'usable_w', 'usable_h'}. Parts bigger than a whole sheet go to
    'unplaced'. Parts are placed largest-first (descending longer side, then area).
    """
    usable_w = max(0.0, sheet_w - 2 * trim)
    usable_h = max(0.0, sheet_h - 2 * trim)
    order = sorted(rects, key=lambda r: (max(r['w'], r['h']), r['w'] * r['h']), reverse=True)

    sheets = []
    unplaced = []
    for rect in order:
        too_big = (not _fits(usable_w, usable_h, rect['w'], rect['h'], kerf) and
                   not (allow_rotation and _fits(usable_w, usable_h, rect['h'], rect['w'], kerf)))
        if too_big:
            unplaced.append(rect)
            continue
        placed = False
        for sheet in sheets:
            if _place_in_sheet(sheet, rect, kerf, allow_rotation):
                placed = True
                break
        if not placed:
            sheet = {'free': [(0.0, 0.0, usable_w, usable_h)], 'placements': []}
            _place_in_sheet(sheet, rect, kerf, allow_rotation)
            sheets.append(sheet)

    return {'sheets': sheets, 'unplaced': unplaced, 'usable_w': usable_w, 'usable_h': usable_h}


def sheet_used_area(sheet):
    return sum(p['w'] * p['h'] for p in sheet['placements'])


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def sheet_svg(placements, sheet_len, sheet_wid, trim, scale):
    """SVG of one sheet drawn at FULL size (sheet_len x sheet_wid), with the trim
    margin shown as a dashed inner border and the sheet dimensions labelled.

    Placement x/y are in usable (post-trim) coords, so parts are offset by `trim`
    onto the full sheet. Drawing the full sheet means the picture stays the same
    size when trim changes — only the usable border moves in.
    """
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
                   f'fill="#F3D573" stroke="#A8842F" stroke-width="1"/>')
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
