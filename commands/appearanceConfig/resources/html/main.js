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
// Fusion <-> JS bridge. Outside Fusion (no adsk object) a tiny mock answers so
// the layout can be previewed in a plain browser.
// ---------------------------------------------------------------------------
async function bridge(action, payload) {
  if (typeof adsk === 'undefined' || !adsk.fusionSendData) {
    return mockBridge(action, payload);
  }
  try {
    const res = await adsk.fusionSendData(action, JSON.stringify(payload || {}));
    return res ? JSON.parse(res) : {};
  } catch (e) {
    console.error('bridge error', action, e);
    return { ok: false, error: String(e) };
  }
}

// Fusion calls this for messages pushed from Python (sendInfoToHTML). We don't
// need pushes today, but the handler must exist.
window.fusionJavaScriptHandler = {
  handle: function (action, data) { return 'OK'; }
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  data: null,               // last scan payload from Python
  roleOverrides: {},        // item key -> role
  groupOverrides: {},       // top-level occurrence name -> 'include' | 'exclude'
  collapsed: new Set(),     // group names folded shut
  report: null,             // last build/fix/check report (rendered on top)
  busy: false,
};

const ROLE_LABELS = { door: 'Door', front: 'Front', carcass: 'Carcass', skip: 'Skip' };

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  attrs = attrs || {};
  for (const k in attrs) {
    if (k === 'class') e.className = attrs[k];
    else if (k === 'text') e.textContent = attrs[k];
    else if (k === 'value') e.value = attrs[k];
    else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
  }
  for (const kid of kids) {
    if (kid == null) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return e;
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), isErr ? 7000 : 3500);
}

function overridesPayload() {
  return {
    roleOverrides: state.roleOverrides,
    groupOverrides: state.groupOverrides,
    persist: document.getElementById('chkPersist').checked,
  };
}

function setBusy(b) {
  state.busy = b;
  for (const id of ['btnScan', 'btnBuild', 'btnFix', 'btnCheck', 'btnPreview', 'btnRestore']) {
    document.getElementById(id).disabled = b;
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function rescan(quiet) {
  setBusy(true);
  const p = await bridge('scan', overridesPayload());
  setBusy(false);
  if (!p.ok) { toast(p.error || 'Scan failed', true); return; }
  state.data = p;
  render();
  if (!quiet) toast('Scanned ' + (p.plan ? p.plan.items.length : 0) + ' parts');
}

async function runApply(action) {
  const label = action === 'build' ? 'Build' : 'Verify & Fix';
  setBusy(true);
  toast(label + ' running — watch the Fusion progress dialog…');
  const r = await bridge(action, overridesPayload());
  setBusy(false);
  state.report = { kind: label, data: r };
  if (r.state && r.state.ok) state.data = r.state;
  render();
  if (r.ok) toast(label + ' done — ' + (r.cellsFilled || 0) + ' cells written');
  else toast(r.error || label + ' failed', true);
}

async function runCheck() {
  setBusy(true);
  const r = await bridge('verify', overridesPayload());
  setBusy(false);
  state.report = { kind: 'Check', data: r };
  render();
  if (!r.ok) toast(r.error || 'Check failed', true);
}

async function runPreview() {
  const row = document.getElementById('previewRow').value;
  if (!row) return;
  const r = await bridge('preview', { row });
  if (r.ok) toast('Previewing ' + row + ' on configuration ' + (r.configuration || ''));
  else toast(r.error || 'Preview failed', true);
}

async function runRestore() {
  const r = await bridge('restore', {});
  if (r.ok) toast(r.note || 'Restored ' + (r.row || ''));
  else toast(r.error || 'Restore failed', true);
}

async function openSource() {
  setBusy(true);
  toast('Opening the appearance source document (cloud — may take a moment)…');
  const r = await bridge('open_source', {});
  setBusy(false);
  if (r.ok) { toast('Opened ' + r.opened + ' — switch back to your assembly, then Rescan'); }
  else toast(r.error || 'Could not open the source document', true);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function render() {
  const d = state.data;
  const content = document.getElementById('content');
  content.innerHTML = '';
  if (!d || !d.ok) {
    content.append(h('div', { class: 'empty', text: 'No scan yet — open the assembly document in Fusion and click Rescan.' }));
    return;
  }

  document.getElementById('docName').textContent = d.doc || '—';
  const t = d.table || {};
  document.getElementById('tableInfo').textContent = !t.configured
    ? 'not a configured design yet'
    : (t.exists ? t.rows + ' rows × ' + t.cols + ' cols'
                : 'configured, no appearance table yet');
  document.getElementById('btnBuild').disabled = state.busy || !!t.problem;
  document.getElementById('footNote').textContent = d.profilePath ? 'Profile: ' + d.profilePath : '';

  if (state.report) content.append(renderReport());
  content.append(...renderStatusCards(d));
  content.append(...renderPlan(d));
  fillPreviewRows(d);
}

function renderStatusCards(d) {
  const cards = [];
  const t = d.table || {};
  const a = d.appearances || {};
  const groups = (d.plan && d.plan.groups) || [];

  if (t.problem) {
    cards.push(h('div', { class: 'card err' },
      h('h4', { text: 'Table mapping problem' }),
      h('div', { class: 'note', text: t.problem })));
  }

  const flattened = groups.filter(g => g.kind === 'flattened');
  if (flattened.length) {
    cards.push(h('div', { class: 'card warn' },
      h('h4', { text: 'Flattened — cannot be configured' }),
      h('ul', {}, ...flattened.map(g => h('li', { text: g.name + ' — ' + g.reason }))),
      h('div', { class: 'note', text: 'These have bodies but no occurrence tree, so door and carcass cannot get separate columns. They are left out of the table (listed here so nothing ships half-configured silently).' })));
  }

  if (a.missing && a.missing.length) {
    const srcName = (d.sourceDoc && d.sourceDoc.name) || 'source document';
    cards.push(h('div', { class: 'card warn' },
      h('h4', { text: 'Missing appearances (' + a.missing.length + ')' }),
      h('ul', {}, ...a.missing.map(n => h('li', { text: n }))),
      h('div', { class: 'note' },
        a.libraryOk ? 'They will be copied from the appearance library at build time. '
          : (a.libraryPath ? 'Appearance library not found at ' + a.libraryPath + '. '
                           : 'No local appearance library is set in the profile. '),
        a.openDocs && a.openDocs.length
          ? 'Open documents that can donate: ' + a.openDocs.join(', ') + '. ' : '',
        h('button', { class: 'tiny', onclick: openSource, title: 'Search the cloud project and open the appearance source document' },
          'Open ' + srcName)),
    ));
  } else if (t.configured || (a.have && a.have.length)) {
    cards.push(h('div', { class: 'card ok' },
      h('h4', { text: 'Appearances' }),
      h('div', { class: 'note', text: 'All ' + ((a.have && a.have.length) || 0) + ' scheme appearances are available in this design.' })));
  }

  if (t.orphans && t.orphans.length) {
    cards.push(h('div', { class: 'card warn' },
      h('h4', { text: 'Orphan columns (' + t.orphans.length + ')' }),
      h('ul', {}, ...t.orphans.map(k => h('li', { text: k }))),
      h('div', { class: 'note', text: 'Table columns with no matching part in the plan — a renamed or unclassified part, or a deleted occurrence. Their cells are left untouched. If the part is listed below (e.g. as Skip), set its role with the dropdown and rescan: the column re-matches by name and comes back under management.' })));
  }

  if (t.retiring && t.retiring.length) {
    cards.push(h('div', { class: 'card' },
      h('h4', { text: 'Excluded parts still wired to the table (' + t.retiring.length + ')' }),
      h('ul', {}, ...t.retiring.slice(0, 12).map(k => h('li', { text: k }))),
      h('div', { class: 'note', text: 'Build or Verify & Fix will empty and remove their columns so they stop following the theme (they keep their current look).' })));
  }

  if (t.exists && t.newParts && t.newParts.length) {
    cards.push(h('div', { class: 'card' },
      h('h4', { text: 'New parts since last build (' + t.newParts.length + ')' }),
      h('ul', {}, ...t.newParts.slice(0, 12).map(k => h('li', { text: k }))),
      t.newParts.length > 12 ? h('div', { class: 'note', text: '…and ' + (t.newParts.length - 12) + ' more.' }) : null,
      h('div', { class: 'note', text: 'Build or Verify & Fix will add their columns and fill all rows.' })));
  }
  return cards;
}

function renderReport() {
  const r = state.report;
  const lines = [];
  const d = r.data || {};
  if (d.error) lines.push('ERROR: ' + d.error);
  for (const k of ['notes', 'warnings']) {
    for (const n of d[k] || []) lines.push(n);
  }
  if (d.columnsAdded != null) lines.push('Columns added: ' + d.columnsAdded + ' (total ' + d.columns + ')');
  if (d.columnsAlreadyCovered) lines.push('Placements already covered (no-op re-adds): ' + d.columnsAlreadyCovered);
  if (d.columnsRetired && d.columnsRetired.length) {
    lines.push('Columns detached for excluded parts: ' + d.columnsRetired.length);
    for (const s of d.columnsRetired) lines.push('  ' + s);
  }
  if (d.rowsAdded != null) lines.push('Rows added: ' + d.rowsAdded + ' (total ' + d.rows + ')');
  if (d.cellsFilled != null) lines.push('Cells written: ' + d.cellsFilled);
  if (d.rowsSkipped && d.rowsSkipped.length) lines.push('Rows left alone (non-scheme names): ' + d.rowsSkipped.join(', '));
  if (d.appearances && d.appearances.copied && d.appearances.copied.length)
    lines.push('Appearances copied:\n  ' + d.appearances.copied.join('\n  '));
  if (d.persisted) lines.push('Overrides persisted: ' + d.persisted.written +
    (d.persisted.failed.length ? ' (failed: ' + d.persisted.failed.join(', ') + ')' : ''));
  const rep = d.verify;
  if (rep && rep.cells != null) {
    lines.push('Sweep: ' + rep.cells + ' cells, ' + rep.empty + ' empty, ' + rep.wrongCount + ' wrong');
    for (const w of rep.wrong || []) lines.push('  ' + w);
  }
  const strays = d.strays || (rep && rep.strays);
  if (strays) {
    const total = (strays.cabinetPaints || []).length + (strays.bodyOverrides || []).length
      + (strays.faceOverrides || []).length + (strays.wrapperPaints || []).length;
    if (total || strays.cleared) {
      lines.push('Stray paints beating the theme: ' + total + (d.strays ? ' (cleared ' + strays.cleared + ')' : ' — run Verify & Fix to clear them'));
      for (const s of strays.cabinetPaints || []) lines.push('  cabinet: ' + s);
      for (const s of strays.bodyOverrides || []) lines.push('  body: ' + s);
      for (const s of strays.wrapperPaints || []) lines.push('  wrapper: ' + s);
      for (const s of (strays.faceOverrides || []).slice(0, 8)) lines.push('  face: ' + s);
    } else {
      lines.push('No stray body/face/wrapper paints.');
    }
    if ((strays.hardwarePaints || []).length) {
      lines.push('Painted hardware (left alone — clear by hand if unwanted):');
      for (const s of strays.hardwarePaints.slice(0, 10)) lines.push('  ' + s);
    }
  }
  if (!lines.length) lines.push(d.ok ? 'OK' : 'No details');
  return h('div', { class: 'card ' + (d.ok ? 'ok' : 'err') },
    h('h4', { text: r.kind + ' report' }),
    h('pre', { class: 'report', text: lines.join('\n') }),
    h('button', { class: 'tiny', onclick: () => { state.report = null; render(); } }, 'Dismiss'));
}

function renderPlan(d) {
  const plan = d.plan || { groups: [], items: [] };
  const byGroup = {};
  for (const it of plan.items) {
    (byGroup[it.group] = byGroup[it.group] || []).push(it);
  }
  const out = [];
  for (const g of plan.groups) {
    out.push(renderGroup(g, byGroup[g.name] || [], d.roles || []));
  }
  if (!plan.groups.length) {
    out.push(h('div', { class: 'empty', text: 'No top-level occurrences found in this design.' }));
  }
  return out;
}

function renderGroup(g, items, roles) {
  const folded = state.collapsed.has(g.name);
  const head = h('div', { class: 'group-row', onclick: () => {
    if (folded) state.collapsed.delete(g.name); else state.collapsed.add(g.name);
    render();
  } },
    h('span', { class: 'caret', text: folded ? '▸' : '▾' }),
    h('span', { class: 'group-name', text: g.name, title: g.reason || '' }));

  if (g.kind === 'excluded') {
    head.append(h('span', { class: 'badge excluded', text: 'excluded — ' + (g.reason || '') }));
    head.append(h('button', { class: 'tiny', onclick: (ev) => {
      ev.stopPropagation();
      state.groupOverrides[g.name] = 'include';
      rescan(true);
    }, title: 'Classify this occurrence after all' }, 'Include'));
  } else if (g.kind === 'flattened') {
    head.append(h('span', { class: 'badge flattened', text: 'flattened · ' + (g.bodies || '?') + ' bodies' }));
  } else {
    if (g.doors) head.append(h('span', { class: 'badge doors', text: g.doors + ' door' + (g.doors === 1 ? '' : 's') }));
    head.append(h('span', { class: 'badge', text: g.parts + ' col' + (g.parts === 1 ? '' : 's') }));
    head.append(h('button', { class: 'tiny', onclick: (ev) => {
      ev.stopPropagation();
      state.groupOverrides[g.name] = 'exclude';
      rescan(true);
    }, title: 'Leave this occurrence out of the appearance table' }, 'Exclude'));
  }

  const box = h('div', { class: 'group' }, head);
  if (!folded && items.length && g.kind !== 'excluded') {
    box.append(h('div', { class: 'items' }, ...items.map(it => renderItem(it, g, roles))));
  }
  return box;
}

function renderItem(it, g, roles) {
  // Show the path inside the group (the group name is already the header).
  const rel = it.path.length > 1 && it.path[0] === g.name ? it.path.slice(1) : it.path;
  const sel = h('select', { onchange: (ev) => {
    state.roleOverrides[it.key] = ev.target.value;
    rescan(true);
  } });
  for (const role of roles) {
    sel.append(h('option', { value: role, text: ROLE_LABELS[role] || role }));
  }
  sel.value = it.source === 'override' && state.roleOverrides[it.key]
    ? state.roleOverrides[it.key] : it.role;
  const row = h('div', { class: 'item' + (it.source === 'override' ? ' overridden' : '') },
    h('span', { class: 'name role-' + it.role },
      rel.slice(0, -1).map(p => p + ' › ').join(''),
      rel[rel.length - 1]),
    h('span', { class: 'reason', text: it.reason, title: it.reason }),
    sel);
  return row;
}

function fillPreviewRows(d) {
  const sel = document.getElementById('previewRow');
  const current = sel.value;
  sel.innerHTML = '';
  for (const name of d.expectedRows || []) {
    sel.append(h('option', { value: name, text: name }));
  }
  // Default to a high-contrast row: a dark wood finish from the LAST carcass
  // block (Grey carcass + Blackwood door makes doors vs carcass unmistakable).
  const rows = d.expectedRows || [];
  const darks = rows.filter(n => /blackwood|walnut|castello/i.test(n));
  const dark = darks.length ? darks[darks.length - 1] : rows[rows.length - 1];
  sel.value = current && rows.includes(current) ? current : (dark || '');
}

// ---------------------------------------------------------------------------
// Mock bridge (browser preview only — Fusion never hits this path)
// ---------------------------------------------------------------------------
function mockBridge(action, payload) {
  console.warn('mock bridge:', action, payload);
  if (action !== 'scan' && action !== 'ready') return { ok: true, note: 'mock' };
  const items = [
    { path: ['BC_S2:1', 'Left Door:1'], key: 'BC_S2:1 > Left Door:1', group: 'BC_S2:1', role: 'door', source: 'keyword', reason: "door keyword 'door'" },
    { path: ['BC_S2:1', 'Right Door:1'], key: 'BC_S2:1 > Right Door:1', group: 'BC_S2:1', role: 'door', source: 'keyword', reason: "door keyword 'door'" },
    { path: ['BC_S2:1', 'Back Panel:1'], key: 'BC_S2:1 > Back Panel:1', group: 'BC_S2:1', role: 'carcass', source: 'keyword', reason: "carcass keyword 'panel'" },
    { path: ['BC_S2:1', 'Hinge Assembly:1'], key: 'BC_S2:1 > Hinge Assembly:1', group: 'BC_S2:1', role: 'skip', source: 'keyword', reason: "hardware keyword 'hinge assembly'" },
    { path: ['WC_CR_S1:1', 'Door Panel:1'], key: 'WC_CR_S1:1 > Door Panel:1', group: 'WC_CR_S1:1', role: 'door', source: 'keyword', reason: "door keyword 'door'" },
    { path: ['WC_CR_S1:1', 'Fixed Panel:1'], key: 'WC_CR_S1:1 > Fixed Panel:1', group: 'WC_CR_S1:1', role: 'door', source: 'keyword', reason: "front keyword 'fixed panel' → door (1 door(s) in group)" },
  ];
  return {
    ok: true, doc: 'VILLA-C Kitchen (mock)',
    plan: {
      groups: [
        { name: 'BC_S2:1', kind: 'cabinet', doors: 2, parts: 3, reason: '' },
        { name: 'WC_CR_S1:1', kind: 'cabinet', doors: 1, parts: 2, reason: '' },
        { name: 'kitchen sink:1', kind: 'excluded', reason: "exclude keyword 'sink'", doors: 0, parts: 0 },
        { name: 'Old Larder:1', kind: 'flattened', reason: '129 bodies, no child occurrences — cannot be split into door vs carcass', bodies: 129, doors: 0, parts: 0 },
      ],
      items,
      parts: items.filter(i => i.role === 'door' || i.role === 'carcass'),
    },
    table: { configured: true, exists: true, rows: 32, cols: 6, newParts: ['WC_CR_S1:1 > Shelf:3'], orphans: [], problem: null },
    appearances: { have: ['8685 PE - Snow White'], missing: ['K022 SN - Satin Blackwood'], libraryPath: '', libraryOk: false, openDocs: ['WC_S2 v12'] },
    expectedRows: ['#1-White-0101 PE - Front White', '#25-Grey-K022 SN - Satin Blackwood'],
    roles: ['door', 'front', 'carcass', 'skip'],
    profilePath: 'C:/Users/mock/AppData/Roaming/WoodCraft/config_tables.json',
    sourceDoc: { name: 'WC_S2' },
  };
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
function wireButtons() {
  document.getElementById('btnScan').addEventListener('click', () => rescan(false));
  document.getElementById('btnBuild').addEventListener('click', () => runApply('build'));
  document.getElementById('btnFix').addEventListener('click', () => runApply('fix'));
  document.getElementById('btnCheck').addEventListener('click', runCheck);
  document.getElementById('btnPreview').addEventListener('click', runPreview);
  document.getElementById('btnRestore').addEventListener('click', runRestore);
}

async function init() {
  wireButtons();
  await rescan(true);
}

window.addEventListener('DOMContentLoaded', init);
