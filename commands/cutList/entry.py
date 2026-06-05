"""Cut List & Nest — collect WoodCraft panels and produce a cut-list report.

PHASE 1 (this version): walks the design (or a selected assembly) for WoodCraft
panels via the shared collector, groups them by thickness then size, and opens an
HTML report in the browser with the cut list and an *estimated* sheet count per
thickness. Stock sheet size, kerf, edge trim and rotation are editable inputs.

PHASE 2 (next): real rectangle nesting — per-sheet SVG layout diagrams, exact
sheet count + yield %, and a printable label sheet.
"""

import math
import os
import re
import pathlib
import tempfile
import webbrowser
import datetime

import adsk.core
import adsk.fusion

from .. import ui_helpers
from .. import panels
from .. import nesting
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_cutList'
CMD_NAME = 'Cut List & Nest'
CMD_Description = (
    'Collect all WoodCraft panels and open a cut-list report grouped by thickness, '
    'with an estimated sheet count. Visual nesting comes next.'
)
IS_PROMOTED = True

PANEL_ID = config.OUTPUT_PANEL_ID
PANEL_NAME = config.OUTPUT_PANEL_NAME
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

NAME_ID = 'cl_name'
QTY_ID = 'cl_qty'
SCOPE_ID = 'cl_scope'
SHEET_L_ID = 'cl_sheet_l'
SHEET_W_ID = 'cl_sheet_w'
KERF_ID = 'cl_kerf'
TRIM_ID = 'cl_trim'
ROTATE_ID = 'cl_rotate'

local_handlers = []


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = ui_helpers.get_panel(PANEL_ID, PANEL_NAME)
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


def stop():
    ui_helpers.remove_command(PANEL_ID, CMD_ID)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    design = adsk.fusion.Design.cast(app.activeProduct)
    default_name = ''
    if design:
        try:
            default_name = design.parentDocument.name
        except Exception:
            default_name = ''
    inputs.addStringValueInput(NAME_ID, 'Report name', default_name)
    inputs.addIntegerSpinnerCommandInput(QTY_ID, 'Quantity (assemblies)', 1, 1000, 1, 1)

    scope = inputs.addSelectionInput(
        SCOPE_ID, 'Assembly (optional)',
        'Limit the cut list to a selected assembly; leave empty for the whole design')
    scope.addSelectionFilter('Occurrences')
    scope.setSelectionLimits(0, 1)

    inputs.addValueInput(SHEET_L_ID, 'Sheet length', 'mm', adsk.core.ValueInput.createByString('2440 mm'))
    inputs.addValueInput(SHEET_W_ID, 'Sheet width', 'mm', adsk.core.ValueInput.createByString('1220 mm'))
    inputs.addValueInput(KERF_ID, 'Saw kerf', 'mm', adsk.core.ValueInput.createByString('3 mm'))
    inputs.addValueInput(TRIM_ID, 'Edge trim', 'mm', adsk.core.ValueInput.createByString('0 mm'))
    rot = inputs.addBoolValueInput(ROTATE_ID, 'Allow rotation (ignore grain)', True, '', True)
    rot.tooltip = 'Allow parts to rotate 90° for better yield. Turn off when grain direction matters.'

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    inputs = args.command.commandInputs

    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        ui.messageBox('Open a design first.')
        return

    scope = inputs.itemById(SCOPE_ID)
    root = None
    if scope.selectionCount == 1:
        try:
            root = scope.selection(0).entity.component
        except Exception:
            root = None

    params = {
        'sheet_l': inputs.itemById(SHEET_L_ID).value * 10.0,   # cm -> mm
        'sheet_w': inputs.itemById(SHEET_W_ID).value * 10.0,
        'kerf': inputs.itemById(KERF_ID).value * 10.0,
        'trim': inputs.itemById(TRIM_ID).value * 10.0,
        'rotate': inputs.itemById(ROTATE_ID).value,
    }
    qty = max(1, int(inputs.itemById(QTY_ID).value))
    report_name = (inputs.itemById(NAME_ID).value or '').strip()
    if not report_name:
        try:
            report_name = design.parentDocument.name
        except Exception:
            report_name = 'WoodCraft'

    instances = panels.collect_panel_instances(design, root=root)
    if not instances:
        ui.messageBox('No panels found.\n\nTag panels with Convert to Panel, or build '
                      'them with Carcass Maker / Shelf Creator, then try again.')
        return
    instances = instances * qty   # global assembly quantity multiplier

    sections = _build_sections(instances, params)

    try:
        html = _build_html(sections, instances, params, report_name)
        out = os.path.join(tempfile.gettempdir(), _safe_filename(report_name) + '.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html)
        webbrowser.open(pathlib.Path(out).as_uri())
    except Exception:
        futil.handle_error('Cut List: failed to build/open the report', show_message_box=True)
        return

    total_sheets = sum(s['num_sheets'] for s in sections)
    total_unplaced = sum(len(s['unplaced']) for s in sections)
    msg = (f'Cut list "{report_name}" (×{qty}): {len(instances)} panel(s) across '
           f'{len(sections)} thickness group(s) → {total_sheets} sheet(s).')
    if total_unplaced:
        msg += f'\n⚠ {total_unplaced} part(s) too large for the sheet (see report).'
    msg += '\n\nReport opened in your browser.'
    ui.messageBox(msg)


# ---------------------------------------------------------------------------
# Grouping + estimate
# ---------------------------------------------------------------------------
def _build_sections(instances, params):
    by_t = {}
    for it in instances:
        by_t.setdefault(round(it['T'], 1), []).append(it)

    sections = []
    for t in sorted(by_t.keys(), reverse=True):
        items = by_t[t]
        parts = {}
        area = 0.0
        rects = []
        for idx, it in enumerate(items):
            L, W = max(it['L'], it['W']), min(it['L'], it['W'])
            key = (round(L, 1), round(W, 1))
            p = parts.setdefault(key, {'L': key[0], 'W': key[1], 'qty': 0, 'names': {}})
            p['qty'] += 1
            p['names'][it['comp_name']] = p['names'].get(it['comp_name'], 0) + 1
            area += it['L'] * it['W']
            rects.append({'id': idx, 'label': it['comp_name'], 'w': it['L'], 'h': it['W']})
        rows = sorted(parts.values(), key=lambda p: (-p['L'], -p['W']))

        result = nesting.pack(rects, params['sheet_l'], params['sheet_w'],
                              params['kerf'], params['trim'], params['rotate'])
        num_sheets = len(result['sheets'])
        usable_area = result['usable_w'] * result['usable_h']
        placed_area = sum(nesting.sheet_used_area(sh) for sh in result['sheets'])
        yld = (placed_area / (num_sheets * usable_area) * 100.0) if (num_sheets and usable_area) else 0.0

        sections.append({
            'thickness': t,
            'rows': rows,
            'pieces': len(items),
            'area_m2': area / 1.0e6,
            'sheets': result['sheets'],
            'num_sheets': num_sheets,
            'yield': yld,
            'unplaced': result['unplaced'],
            'usable_w': result['usable_w'],
            'usable_h': result['usable_h'],
        })
    return sections


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _safe_filename(name):
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', str(name)).strip('_')
    return base[:60] or 'woodcraft_cutlist'


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _build_html(sections, instances, params, title):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    total_pieces = len(instances)
    total_sheets = sum(s['num_sheets'] for s in sections)
    total_unplaced = sum(len(s['unplaced']) for s in sections)

    sheet_area_mm2 = params['sheet_l'] * params['sheet_w']
    board_m2 = total_sheets * sheet_area_mm2 / 1.0e6
    placed_m2 = sum(nesting.sheet_used_area(sh) for s in sections for sh in s['sheets']) / 1.0e6
    overall_yield = (placed_m2 / board_m2 * 100.0) if board_m2 else 0.0
    waste_m2 = max(0.0, board_m2 - placed_m2)

    css = """<style>
      body{font-family:'Segoe UI',Arial,sans-serif;margin:24px;color:#222;}
      h1{font-size:20px;margin:0 0 2px;} .sub{color:#777;font-size:12px;margin-bottom:14px;}
      .params{background:#f5f5f5;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:14px;break-inside:avoid;}
      .summary{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;break-inside:avoid;}
      .summary div{background:#fff;border:1px solid #e3dcc4;border-radius:8px;padding:8px 14px;min-width:82px;text-align:center;}
      .summary span{display:block;font-size:11px;color:#888;} .summary b{font-size:17px;}
      h2{font-size:15px;margin:24px 0 6px;border-bottom:2px solid #E5C05B;padding-bottom:4px;break-after:avoid;}
      table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:10px;}
      th,td{border:1px solid #ddd;padding:6px 8px;text-align:right;}
      th{background:#fafafa;} td.l,th.l{text-align:left;}
      thead{display:table-header-group;} tr{break-inside:avoid;}
      .section{break-inside:avoid;}
      .sheets{display:flex;flex-wrap:wrap;gap:18px;margin:8px 0 4px;align-items:flex-start;}
      .sheet{font-size:11px;color:#555;break-inside:avoid;} .sheet .cap{margin-bottom:3px;font-weight:600;color:#333;}
      .warn{color:#b00;font-size:12px;margin:6px 0;}
      .labels{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px;}
      .label{border:1px solid #ccc;border-radius:6px;padding:8px;font-size:12px;break-inside:avoid;}
      .label .ln{font-weight:600;} .label .ld{color:#333;} .label .lt{color:#888;font-size:11px;}
      button{background:#E5C05B;border:none;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;margin-top:8px;}
      .pagebreak{page-break-before:always;}
      @media print{
        body{margin:12mm;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
        button{display:none;}
        h1,h2,.summary,.params{break-inside:avoid;}
      }
    </style>"""

    summary_html = (
        "<div class='summary'>"
        f"<div><span>Panels</span><b>{total_pieces}</b></div>"
        f"<div><span>Sheets</span><b>{total_sheets}</b></div>"
        f"<div><span>Board area</span><b>{board_m2:.2f} m&sup2;</b></div>"
        f"<div><span>Used</span><b>{placed_m2:.2f} m&sup2;</b></div>"
        f"<div><span>Yield</span><b>{overall_yield:.0f}%</b></div>"
        f"<div><span>Waste</span><b>{waste_m2:.2f} m&sup2;</b></div>"
        "</div>")

    display_w = 380.0
    scale = (display_w / params['sheet_l']) if params['sheet_l'] > 0 else 0.1
    blocks = []
    for s in sections:
        blocks.append("<div class='section'>")
        blocks.append(
            f"<h2>{s['thickness']:.1f} mm &mdash; {s['pieces']} pcs &nbsp;|&nbsp; "
            f"{s['num_sheets']} sheet(s) &nbsp;|&nbsp; {s['yield']:.0f}% yield "
            f"&nbsp;|&nbsp; {s['area_m2']:.2f} m&sup2;</h2>")

        blocks.append("<table><thead><tr><th>Qty</th><th>Length (mm)</th><th>Width (mm)</th>"
                      "<th>Area (m&sup2;)</th><th class='l'>Parts</th></tr></thead><tbody>")
        for r in s['rows']:
            names = ', '.join(f"{_esc(n)}&times;{c}" if c > 1 else _esc(n)
                              for n, c in sorted(r['names'].items()))
            row_area = r['L'] * r['W'] * r['qty'] / 1.0e6
            blocks.append(f"<tr><td>{r['qty']}</td><td>{r['L']:.1f}</td><td>{r['W']:.1f}</td>"
                          f"<td>{row_area:.2f}</td><td class='l'>{names}</td></tr>")
        blocks.append("</tbody></table>")

        if s['unplaced']:
            names = ', '.join(_esc(u['label']) for u in s['unplaced'])
            blocks.append(f"<div class='warn'>&#9888; {len(s['unplaced'])} part(s) larger "
                          f"than the sheet: {names}</div>")
        blocks.append("</div>")  # /section — keep heading + table together

        blocks.append("<div class='sheets'>")
        for i, sheet in enumerate(s['sheets']):
            used = nesting.sheet_used_area(sheet)
            sy = (used / (s['usable_w'] * s['usable_h']) * 100.0) if (s['usable_w'] and s['usable_h']) else 0.0
            svg = nesting.sheet_svg(sheet['placements'], params['sheet_l'], params['sheet_w'],
                                    params['trim'], scale)
            blocks.append(f"<div class='sheet'><div class='cap'>Sheet {i + 1} &mdash; "
                          f"{len(sheet['placements'])} parts &nbsp;|&nbsp; {sy:.0f}% used</div>{svg}</div>")
        blocks.append("</div>")

    label_cards = []
    for it in instances:
        L, W = max(it['L'], it['W']), min(it['L'], it['W'])
        label_cards.append(
            f"<div class='label'><div class='ln'>{_esc(it['comp_name'])}</div>"
            f"<div class='ld'>{L:.0f} &times; {W:.0f} mm</div>"
            f"<div class='lt'>{it['T']:.1f} mm thick</div></div>")
    labels_html = (f"<div class='pagebreak'></div><h2>Labels &mdash; {total_pieces} pieces</h2>"
                   f"<div class='labels'>{''.join(label_cards)}</div>")

    p = params
    params_html = (
        f"Stock sheet: <b>{p['sheet_l']:.0f} &times; {p['sheet_w']:.0f} mm</b> &nbsp;|&nbsp; "
        f"Kerf: <b>{p['kerf']:.1f} mm</b> &nbsp;|&nbsp; "
        f"Edge trim: <b>{p['trim']:.0f} mm</b> &nbsp;|&nbsp; "
        f"Rotation: <b>{'allowed' if p['rotate'] else 'off (grain)'}</b>")

    warn = (f' &nbsp;|&nbsp; <span style="color:#b00">&#9888; {total_unplaced} oversized</span>'
            if total_unplaced else '')

    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<title>WoodCraft Cut List</title>' + css + '</head><body>'
        f'<h1>WoodCraft Cut List &mdash; {_esc(title)}</h1>'
        f'<div class="sub">Generated {now}{warn}</div>'
        f'<div class="params">{params_html}</div>'
        + summary_html + ''.join(blocks) + labels_html +
        '<button onclick="window.print()">Print / Save PDF</button>'
        '</body></html>')


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')
    global local_handlers
    local_handlers = []
