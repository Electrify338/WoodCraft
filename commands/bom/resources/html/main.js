/*
 * WoodCraft — a Fusion add-in for cabinetmaking.
 * Copyright (C) 2026 Abdelrahman Youssry
 *
 * This program is free software: you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later
 * version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 * FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with
 * this program.  If not, see <https://www.gnu.org/licenses/>.
 */

'use strict';

// ---------------------------------------------------------------------------
// Fusion <-> JS bridge. adsk.fusionSendData(action, json) resolves with the
// string Python put in args.returnData; we parse it back to an object.
// ---------------------------------------------------------------------------
async function bridge(action, payload) {
  if (typeof adsk === 'undefined' || !adsk.fusionSendData) {
    console.warn('No Fusion bridge available; action =', action);
    return {};
  }
  try {
    const res = await adsk.fusionSendData(action, JSON.stringify(payload || {}));
    return res ? JSON.parse(res) : {};
  } catch (e) {
    console.error('bridge error', action, e);
    return { ok: false, error: String(e) };
  }
}

// Fusion calls this for messages pushed from Python; we don't push, but it must exist.
window.fusionJavaScriptHandler = { handle: function () { return 'OK'; } };

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = { tree: [], design: '', config: '', totals: null };
const collapsed = new WeakSet();   // assemblies the user has collapsed (default: open)

// Small DOM builder (avoids manual HTML escaping of component names).
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  attrs = attrs || {};
  for (const k in attrs) {
    if (k === 'class') e.className = attrs[k];
    else if (k === 'text') e.textContent = attrs[k];
    else if (k === 'title') e.title = attrs[k];
    else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
  }
  for (const kid of kids) {
    if (kid == null) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return e;
}

function fmt(n) { const v = parseFloat(n); return isNaN(v) ? '0' : (Math.round(v * 10) / 10).toString(); }
function money(n) { const v = parseFloat(n); return isNaN(v) ? '' : v.toFixed(2); }
function metres(mm) { const v = parseFloat(mm); return isNaN(v) ? '' : (v / 1000).toFixed(2) + ' m'; }

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  document.getElementById('btnExpand').addEventListener('click', () => { collapsedClear(); render(); });
  document.getElementById('btnCollapse').addEventListener('click', () => { collapseAll(state.tree); render(); });
  document.getElementById('btnRefresh').addEventListener('click', onRefresh);
  document.getElementById('btnExport').addEventListener('click', onExport);
  await load();
}

async function load() {
  const p = await bridge('ready', {});
  state.tree = Array.isArray(p.tree) ? p.tree : [];
  state.design = p.design || '';
  state.config = p.config || '';
  state.totals = p.totals || null;
  render();
}

async function onRefresh() {
  await load();
  toast('Reloaded from the model.');
}

async function onExport() {
  const r = await bridge('export', {});
  if (r && r.ok) toast('Exported to ' + r.path);
  else if (r && r.cancelled) { /* user cancelled */ }
  else toast('Export failed' + (r && r.error ? ': ' + r.error : ''), true);
}

// ---------------------------------------------------------------------------
// Expand / collapse helpers (collapsed nodes only; default is expanded)
// ---------------------------------------------------------------------------
function collapsedClear() { state.tree.forEach(walkUncollapse); }
function walkUncollapse(n) { collapsed.delete(n); (n.children || []).forEach(walkUncollapse); }
function collapseAll(nodes) {
  nodes.forEach(n => {
    if ((n.children && n.children.length) || (n.edgebands && n.edgebands.length)) collapsed.add(n);
    if (n.children && n.children.length) collapseAll(n.children);
  });
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------
function render() {
  // Summary
  const totalRows = countRows(state.tree);
  const sum = document.getElementById('summary');
  sum.innerHTML = '';
  if (!state.tree.length) {
    sum.append('No components found.');
  } else {
    sum.append(h('span', {}, totalRows + ' component rows'));
    if (state.design) sum.append(h('span', {}, '  ·  design '), h('b', {}, state.design));
    if (state.config) sum.append(h('span', {}, '  ·  configuration '), h('b', {}, state.config));
    const t = state.totals;
    if (t && (t.grand || t.unpriced_panels)) {
      sum.append(h('span', {}, '  ·  panels '), h('b', { class: 'est' }, '≈ ' + money(t.panels_est)));
      sum.append(h('span', {}, '  ·  hardware '), h('b', {}, money(t.hardware)));
      if (t.edgeband) sum.append(h('span', {}, '  ·  edgeband '), h('b', { class: 'est' }, '≈ ' + money(t.edgeband)));
      sum.append(h('span', {}, '  ·  total '), h('b', {}, '≈ ' + money(t.grand)));
      if (t.unpriced_panels) {
        sum.append(h('span', { class: 'est', title: 'No sheet cost found for their material in the Sheets library' },
          '  ·  ' + t.unpriced_panels + ' panel(s) unpriced'));
      }
    }
  }

  // Edgebanding purchase line: total metres (and cost) per band type, design-wide.
  const ebBar = document.getElementById('ebBar');
  ebBar.innerHTML = '';
  const bands = (state.totals && state.totals.edgebands) || [];
  if (bands.length) {
    ebBar.className = 'bar ebline';
    ebBar.append(h('span', {}, 'Edgebanding: '));
    bands.forEach((b, i) => {
      if (i) ebBar.append(h('span', {}, '  ·  '));
      ebBar.append(h('b', {}, b.name), h('span', {}, ' ' + metres(b.length_mm)));
      ebBar.append(b.cost != null
        ? h('span', { class: 'est', title: 'Length × cost/m from the Sheets library + waste factor' }, ' ≈ ' + money(b.cost))
        : h('span', { class: 'est', title: 'No cost per metre set for this band in the Sheets library' }, ' (unpriced)'));
    });
  } else {
    ebBar.className = 'bar ebline hidden';
  }
  document.getElementById('pathNote').textContent =
    'Panel costs are estimates: raw area × average sheet cost/m² + the waste factor from Settings. ' +
    'Hardware costs come from Set Type. Export writes a native .xlsx.';

  // Rows
  const box = document.getElementById('rows');
  box.innerHTML = '';
  if (!state.tree.length) {
    box.append(h('div', { class: 'empty' }, 'No components in the active design.'));
    return;
  }
  renderRows(box, state.tree, 0);
}

function countRows(nodes) { return nodes.reduce((a, n) => a + 1 + countRows(n.children || []), 0); }

function renderRows(box, nodes, level) {
  nodes.forEach(node => {
    const hasChildren = node.children && node.children.length;
    // Rows with edgebands expand too: their banding renders as detail sub-rows.
    const expandable = hasChildren || (node.edgebands && node.edgebands.length);
    const open = !collapsed.has(node);
    box.append(rowEl(node, level, expandable, open));
    if (expandable && open) {
      renderEdgebandRows(box, node, level + 1);
      if (hasChildren) renderRows(box, node.children, level + 1);
    }
  });
}

// Per-panel edgeband detail rows (shown when the panel row is expanded): one row
// per band with the metres per piece, the library rate, and the row total.
function renderEdgebandRows(box, node, level) {
  (node.edgebands || []).forEach(b => {
    const caret = h('span', { class: 'caret leaf' }, '•');
    caret.style.marginLeft = (level * 16) + 'px';
    const unitTxt = b.cost != null ? money(b.cost) : '';
    const total = b.cost != null ? b.cost * node.qty : null;
    box.append(h('div', { class: 'row grid ebrow' },
      h('span', { class: 'c-no' }, ''),
      h('span', { class: 'c-part muted' }, '—'),
      h('span', { class: 'c-name' }, caret, h('span', { class: 'nm', title: b.name }, b.name)),
      h('span', { class: 'c-type' }, h('span', { class: 'badge Edgeband' }, 'Edgeband')),
      h('span', { class: 'c-dims', title: 'Banding length per piece' }, metres(b.length_mm)),
      h('span', { class: 'c-mat' + (b.cost_per_m != null ? '' : ' est'),
                  title: b.cost_per_m != null ? 'Cost per metre from the Sheets library' : 'No cost per metre set in the Sheets library' },
        b.cost_per_m != null ? money(b.cost_per_m) + ' /m' : 'unpriced'),
      h('span', { class: 'c-app' }, ''),
      h('span', { class: 'c-qty' }, String(node.qty)),
      h('span', { class: 'c-unit' + (unitTxt ? '' : ' muted'), title: unitTxt ? 'Banding cost per piece (incl. waste factor)' : '' }, unitTxt || '—'),
      h('span', { class: 'c-cost' + (total != null ? ' est' : ' muted'),
                  title: total != null ? 'Estimated: metres × cost/m + waste factor' : '' },
        total != null ? '≈ ' + money(total) : '—'),
      h('span', { class: 'c-code' }, '')
    ));
  });
}

function rowEl(node, level, hasChildren, open) {
  const isAsm = node.type === 'Assembly';
  const caret = h('span', {
    class: 'caret' + (hasChildren ? '' : ' leaf'),
    onclick: hasChildren ? (() => { toggle(node); }) : null
  }, hasChildren ? (open ? '▾' : '▸') : '•');
  caret.style.marginLeft = (level * 16) + 'px';

  // Assemblies carry W × H × D from the cabinet's parameters; leaves carry
  // sorted extents. Both render the same way once L is filled.
  const dims = node.L > 0
    ? (fmt(node.L) + ' × ' + fmt(node.W) + ' × ' + fmt(node.T))
    : '';
  const mat = node.material || '';
  const app = node.appearance || '';
  const part = node.part_number || '';

  // Cost cells. 'est' totals are sheet-derived estimates (≈); 'absorbed' means the
  // item is inside a priced purchased unit, so its own price is not counted again.
  const kind = node.cost_kind;
  const unitTxt = node.unit_cost != null ? money(node.unit_cost) : '';
  let costTxt = '—', costTitle = '', costClass = ' muted';
  if (kind === 'absorbed') {
    costTxt = 'in parent';
    costTitle = 'Covered by the price of the purchased unit it belongs to';
  } else if (node.cost != null) {
    costTxt = (kind === 'est' ? '≈ ' : '') + money(node.cost);
    costClass = kind === 'est' ? ' est' : '';
    if (kind === 'est') costTitle = 'Estimated from sheet cost/m² × area + waste factor';
    if (kind === 'rollup') costTitle = 'Sum of the items inside';
  }

  // EB badge on rows with edgeband-tagged faces; the tooltip lists band + metres.
  const ebs = node.edgebands || [];
  const ebTag = ebs.length
    ? h('span', { class: 'ebtag', title: 'Edgeband (per piece):\n' + ebs.map(b => b.name + ' — ' + metres(b.length_mm)).join('\n') }, 'EB')
    : null;

  return h('div', { class: 'row grid' + (isAsm ? ' asm' : '') },
    h('span', { class: 'c-no' }, node.no || ''),
    h('span', { class: 'c-part', title: part }, part || '—'),
    h('span', { class: 'c-name' }, caret, h('span', { class: 'nm', title: node.name }, node.name), ebTag),
    h('span', { class: 'c-type' }, h('span', { class: 'badge ' + node.type }, node.type)),
    h('span', { class: 'c-dims' + (dims ? '' : ' muted') }, dims || '—'),
    h('span', { class: 'c-mat', title: mat }, mat || '—'),
    h('span', { class: 'c-app', title: app }, app || '—'),
    h('span', { class: 'c-qty' }, String(node.qty)),
    h('span', { class: 'c-unit' + (unitTxt ? '' : ' muted') }, unitTxt || '—'),
    h('span', { class: 'c-cost' + costClass, title: costTitle }, costTxt),
    h('span', { class: 'c-code', title: node.code || '' }, node.code || '—')
  );
}

function toggle(node) { if (collapsed.has(node)) collapsed.delete(node); else collapsed.add(node); render(); }

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
let toastTimer = null;
function toast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = 'toast hidden'; }, 3600);
}

window.addEventListener('DOMContentLoaded', init);
