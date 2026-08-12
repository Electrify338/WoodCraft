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

"""Shared helpers for WoodCraft's HTML reports (Cut List & Nest, BOM).

Pure stdlib utilities — HTML escaping, filename sanitising, a colour swatch, a
common stylesheet, a printable page shell, and a write-to-temp-and-open helper —
so the look of the reports lives in one place. No Fusion API here.
"""

import os
import re
import pathlib
import tempfile
import webbrowser


def esc(s):
    """Escape the HTML-significant characters in `s`."""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def safe_filename(name):
    """A filesystem-safe stem (no extension) derived from `name`."""
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', str(name)).strip('_')
    return base[:60] or 'woodcraft_report'


def swatch(color):
    """A small inline colour chip for legends / headings."""
    return (f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;"
            f"background:{esc(color)};border:1px solid #0003;vertical-align:middle;"
            f"margin-right:6px'></span>")


# Common styling. Report-specific rules (e.g. the cut list's nest diagrams and
# label cards) are appended by that report via the `extra_css` argument to page().
BASE_CSS = """<style>
  body{font-family:'Segoe UI',Arial,sans-serif;margin:24px;color:#222;}
  h1{font-size:20px;margin:0 0 2px;} .sub{color:#777;font-size:12px;margin-bottom:14px;}
  .params{background:#f5f5f5;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:14px;break-inside:avoid;}
  .legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 16px;font-size:12px;}
  .summary{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;break-inside:avoid;}
  .summary div{background:#fff;border:1px solid #e3dcc4;border-radius:8px;padding:8px 14px;min-width:82px;text-align:center;}
  .summary span{display:block;font-size:11px;color:#888;} .summary b{font-size:17px;}
  h2{font-size:15px;margin:24px 0 6px;border-bottom:2px solid #E5C05B;padding-bottom:4px;break-after:avoid;}
  table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:10px;}
  th,td{border:1px solid #ddd;padding:6px 8px;text-align:right;}
  th{background:#fafafa;} td.l,th.l{text-align:left;}
  thead{display:table-header-group;} tr{break-inside:avoid;}
  .section{break-inside:avoid;}
  .warn{color:#b00;font-size:12px;margin:6px 0;}
  button{background:#E5C05B;border:none;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;margin-top:8px;}
  .pagebreak{page-break-before:always;}
  @media print{
    body{margin:12mm;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
    button{display:none;}
    h1,h2,.summary,.params{break-inside:avoid;}
  }
</style>"""


def page(title, subtitle_html, body_html, extra_css=''):
    """Wrap report body HTML in a full printable document (title, subtitle, body and
    a Print / Save-PDF button). `subtitle_html` and `body_html` are inserted as-is;
    `title` is escaped."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{esc(title)}</title>' + BASE_CSS + extra_css + '</head><body>'
        f'<h1>{esc(title)}</h1>'
        f'<div class="sub">{subtitle_html}</div>'
        + body_html +
        '<button onclick="window.print()">Print / Save PDF</button>'
        '</body></html>')


def open_report(html, name):
    """Write `html` to a temp file named after `name` and open it in the browser.
    Returns the file path."""
    out = os.path.join(tempfile.gettempdir(), safe_filename(name) + '.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open(pathlib.Path(out).as_uri())
    return out
