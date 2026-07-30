"""Minimal, dependency-free .xlsx writer for WoodCraft reports (the BOM export).

Writes a single-sheet workbook with a bold frozen header row, optional column
widths, and per-row outline levels (so a hierarchy collapses/indents in Excel).
Uses only the Python standard library (zipfile + hand-written XML) so the add-in
stays drop-in — no openpyxl. Strings are written inline (no shared-strings table).

Usage:
    write_xlsx(path, ['Name', 'Qty'], [
        (['Cabinet', 1], 0),        # (cells, outline_level)
        (['  Left Panel', 2], 1),
    ], sheet_name='BOM', col_widths=[40, 8])
Numbers (int/float) are written as numeric cells; everything else as text.
A `Formula` cell writes a live Excel formula (so exported costs recalc when the
user tweaks quantities or unit costs in Excel).
"""

import zipfile


class Formula:
    """A live formula cell: `expr` is the Excel formula WITHOUT the leading '=',
    `value` an optional cached numeric result (shown by viewers that don't
    calculate; Excel itself recalculates on open via fullCalcOnLoad)."""

    def __init__(self, expr, value=None):
        self.expr = expr
        self.value = value


def _col_letter(n):
    """1 -> 'A', 27 -> 'AA'."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _cell(col, row, value, bold=False):
    # Emit NO cell for an empty value: an empty inline STRING is a text cell,
    # and Excel arithmetic over a text cell (e.g. a rollup summing a costless
    # row's Total) is #VALUE! — a truly blank cell coerces to 0 instead.
    if value is None or value == '':
        return ''
    ref = f'{_col_letter(col)}{row}'
    style = ' s="1"' if bold else ''
    if isinstance(value, Formula):
        cached = ''
        if isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
            cached = f'<v>{value.value}</v>'
        return f'<c r="{ref}"{style}><f>{_esc(value.expr)}</f>{cached}</c>'
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    text = _esc('' if value is None else value)
    return (f'<c r="{ref}"{style} t="inlineStr"><is>'
            f'<t xml:space="preserve">{text}</t></is></c>')


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '</Types>')

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>')

_WB_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>')

# Two cell formats: 0 = normal, 1 = bold (for the header).
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')


def _workbook(sheet_name):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_esc(sheet_name)[:31]}" sheetId="1" r:id="rId1"/></sheets>'
        # Recalculate every formula when the workbook opens, so cells never show
        # stale cached values (we write caches only for non-calculating viewers).
        '<calcPr fullCalcOnLoad="1"/>'
        '</workbook>')


def _sheet_xml(headers, rows, col_widths):
    n_cols = max(len(headers), max((len(c) for c, _ in rows), default=0))
    n_rows = len(rows) + 1
    dim = f'A1:{_col_letter(max(1, n_cols))}{max(1, n_rows)}'

    cols_xml = ''
    if col_widths:
        cols_xml = '<cols>' + ''.join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(col_widths)) + '</cols>'

    body = [f'<row r="1">' + ''.join(_cell(c + 1, 1, headers[c], bold=True)
                                     for c in range(len(headers))) + '</row>']
    r = 2
    for cells, level in rows:
        lvl = f' outlineLevel="{int(level)}"' if level else ''
        body.append(f'<row r="{r}"{lvl}>'
                    + ''.join(_cell(c + 1, r, cells[c]) for c in range(len(cells)))
                    + '</row>')
        r += 1

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetPr><outlinePr summaryBelow="0" summaryRight="0"/></sheetPr>'
        f'<dimension ref="{dim}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'{cols_xml}<sheetData>{"".join(body)}</sheetData></worksheet>')


def write_xlsx(path, headers, rows, sheet_name='Sheet1', col_widths=None):
    """Write `rows` (each a tuple of (cells_list, outline_level)) to an .xlsx at
    `path` with a bold frozen `headers` row. `col_widths` is an optional list of
    Excel column widths. Numeric cells stay numeric; other values become text."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CONTENT_TYPES)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('xl/workbook.xml', _workbook(sheet_name))
        z.writestr('xl/_rels/workbook.xml.rels', _WB_RELS)
        z.writestr('xl/styles.xml', _STYLES)
        z.writestr('xl/worksheets/sheet1.xml', _sheet_xml(headers, rows, col_widths))
    return path
