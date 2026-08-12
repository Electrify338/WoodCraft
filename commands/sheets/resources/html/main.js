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
// string Python put in args.returnData. We parse it back to an object.
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

// Fusion calls this for messages pushed from Python (sendInfoToHTML). We don't
// need pushes today, but the handler must exist.
window.fusionJavaScriptHandler = {
  handle: function (action, data) { return 'OK'; }
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  library: { materials: [], edgebands: [] },
  designMaterials: [],          // distinct Fusion material names on the design's panels
  designGroups: [],             // [{material, thickness, count}] detected in the design
  rotations: ['all', 'none', '90_270', '180'],
  // si === null => a material is selected; ebi !== null => an edgeband is selected
  sel: { mi: -1, si: null, ebi: null },
};
const expanded = new WeakSet();   // materials whose sheets are shown (not serialized)
let ebOpen = true;                // Edgebands group expanded?

const ROT_LABELS = {
  all: 'All rotations', none: 'None (grain locked)',
  '90_270': '90° & 270°', '180': '180° only'
};
const DEFAULT_COLOR = '#C9A86A';
// Distinct-ish swatches auto-assigned to new materials so the report reads well.
const PALETTE = ['#C9A86A', '#A36B2E', '#7FA37A', '#6E93B8', '#B07AA1', '#C0564B',
                 '#D6B894', '#8C8C8C', '#5B8C5A', '#4F7CAC', '#9C6B3F', '#3F6F6F'];
function nextColor() { return PALETTE[state.library.materials.length % PALETTE.length]; }
function round1(x) { const v = parseFloat(x); return isNaN(v) ? 0 : Math.round(v * 10) / 10; }
function defaultSheet() {
  return { name: 'Standard', length: 2440, width: 1220, form: 'Rectangular',
           cost: 0, rotation: 'all', separation: 3, trim: 10, comment: '' };
}

// Small DOM builder (avoids manual HTML escaping of material names).
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  attrs = attrs || {};
  for (const k in attrs) {
    if (k === 'class') e.className = attrs[k];
    else if (k === 'text') e.textContent = attrs[k];
    else if (k === 'html') e.innerHTML = attrs[k];
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

const materials = () => state.library.materials;
const edgebands = () => state.library.edgebands;
const selMat = () => materials()[state.sel.mi];
const selBand = () => (state.sel.ebi == null ? undefined : edgebands()[state.sel.ebi]);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  wireButtons();
  const p = await bridge('ready', {});
  state.library = (p.library && Array.isArray(p.library.materials)) ? p.library : { materials: [] };
  if (!Array.isArray(state.library.edgebands)) state.library.edgebands = [];
  state.designMaterials = p.designMaterials || [];
  state.designGroups = p.designGroups || [];
  state.rotations = p.rotations || state.rotations;
  document.getElementById('pathNote').textContent =
    (p.path ? 'Library: ' + p.path + '  ·  ' : '') + 'Changes apply when you click Save.';
  fillDesignMaterials();
  if (materials().length) { state.sel = { mi: 0, si: null, ebi: null }; expanded.add(materials()[0]); }
  render();
}

function fillDesignMaterials() {
  const dl = document.getElementById('designMaterials');
  dl.innerHTML = '';
  state.designMaterials.forEach(name => dl.append(h('option', { value: name })));
}

function wireButtons() {
  document.getElementById('btnSave').addEventListener('click', onSave);
  document.getElementById('btnRefresh').addEventListener('click', onRefresh);
  document.getElementById('btnExport').addEventListener('click', onExport);
  document.getElementById('btnImport').addEventListener('click', onImport);
  document.getElementById('btnAddMaterial').addEventListener('click', onAddMaterial);
  document.getElementById('btnFromDesign').addEventListener('click', onFromDesign);
  document.getElementById('btnAddEdgeband').addEventListener('click', onAddEdgeband);
  document.getElementById('categoryFilter').addEventListener('change', renderTree);
}

async function onRefresh() {
  const p = await bridge('ready', {});
  if (p && p.library && Array.isArray(p.library.materials)) {
    state.library = p.library;
    if (!Array.isArray(state.library.edgebands)) state.library.edgebands = [];
    state.designMaterials = p.designMaterials || [];
    state.designGroups = p.designGroups || [];
    fillDesignMaterials();
    state.sel = { mi: state.library.materials.length ? 0 : -1, si: null, ebi: null };
    if (state.library.materials.length) expanded.add(state.library.materials[0]);
    render();
    toast('Reloaded from disk · ' + state.designMaterials.length + ' design material(s) detected.');
  } else {
    toast('Refresh failed.', true);
  }
}

// Add every (material, thickness) detected in the design that isn't already in the
// library — this is the "detect materials in the current design" core feature.
function onFromDesign() {
  if (!state.designGroups.length) { toast('No panel materials detected in the active design.', true); return; }
  const have = new Set(materials().map(m => (m.name || '').trim().toLowerCase() + '@' + round1(m.thickness)));
  let added = 0;
  state.designGroups.forEach(g => {
    const name = (g.material || '').trim();
    if (!name || name === 'Unassigned') return;     // skip parts with no Fusion material
    const key = name.toLowerCase() + '@' + round1(g.thickness);
    if (have.has(key)) return;
    materials().push({ name: name, thickness: round1(g.thickness), category: '', color: nextColor(), comment: '', sheets: [defaultSheet()] });
    have.add(key);
    added++;
  });
  if (added) {
    state.sel = { mi: materials().length - 1, si: null };
    render();
    toast('Added ' + added + ' material(s) from the design. Set sizes/colour, then Save.');
  } else {
    toast('All detected design materials are already in the library.');
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------
function render() { renderCategoryFilter(); renderTree(); renderDetail(); }

function renderCategoryFilter() {
  const sel = document.getElementById('categoryFilter');
  const cur = sel.value;
  const cats = [...new Set(materials().map(m => (m.category || '').trim()).filter(Boolean))].sort();
  sel.innerHTML = '';
  sel.append(h('option', { value: '' }, 'All'));
  cats.forEach(c => sel.append(h('option', { value: c }, c)));
  sel.value = cats.includes(cur) ? cur : '';
}

function renderTree() {
  const tree = document.getElementById('tree');
  tree.innerHTML = '';
  const filter = document.getElementById('categoryFilter').value;

  materials().forEach((m, mi) => {
    if (filter && (m.category || '').trim() !== filter) return;
    const isSelMat = state.sel.mi === mi && state.sel.si === null;
    const open = expanded.has(m);

    const matBox = h('div', { class: 'mat' + (isSelMat ? ' sel' : '') });
    const row = h('div', { class: 'mat-row', onclick: () => selectMaterial(mi) },
      h('span', { class: 'caret', onclick: (e) => { e.stopPropagation(); toggle(m); } }, open ? '▾' : '▸'),
      h('span', { class: 'swatch', style: 'background:' + (m.color || DEFAULT_COLOR) }),
      h('span', { class: 'mat-name', title: m.name || '(unnamed)' }, m.name || '(unnamed material)'),
      h('span', { class: 'mat-th' }, fmt(m.thickness) + ' mm'),
      h('span', { class: 'mat-tools' },
        h('button', { class: 'tiny', title: 'Add a sheet', onclick: (e) => { e.stopPropagation(); onAddSheet(mi); } }, '+'),
        h('button', { class: 'tiny danger', title: 'Delete material', onclick: (e) => { e.stopPropagation(); onDeleteMaterial(mi); } }, '✕'))
    );
    matBox.append(row);

    if (open) {
      const sheets = h('div', { class: 'sheets' });
      (m.sheets || []).forEach((s, si) => {
        const isSel = state.sel.mi === mi && state.sel.si === si;
        sheets.append(h('div', { class: 'sheet-row' + (isSel ? ' sel' : ''), onclick: () => selectSheet(mi, si) },
          h('span', { class: 'sheet-name' }, s.name || 'Sheet'),
          h('span', { class: 'sheet-dim' }, fmt(s.length) + '×' + fmt(s.width)),
          h('span', { class: 'sheet-tools' },
            h('button', { class: 'tiny danger', title: 'Delete sheet', onclick: (e) => { e.stopPropagation(); onDeleteSheet(mi, si); } }, '✕'))
        ));
      });
      sheets.append(h('div', { class: 'sheet-row addsheet', onclick: () => onAddSheet(mi) }, '+ add sheet'));
      matBox.append(sheets);
    }
    tree.append(matBox);
  });

  if (!tree.children.length) {
    tree.append(h('div', { class: 'empty' }, filter ? 'No materials in this category.' : 'No materials yet — click “+ Material”.'));
  }

  renderEdgebandTree(tree);
}

// The Edgebands group sits under the materials: one flat list of band types
// (used by the Edgeband command; priced per metre in the BOM).
function renderEdgebandTree(tree) {
  const box = h('div', { class: 'mat ebgroup' });
  box.append(h('div', { class: 'mat-row', onclick: () => { ebOpen = !ebOpen; renderTree(); } },
    h('span', { class: 'caret' }, ebOpen ? '▾' : '▸'),
    h('span', { class: 'mat-name' }, 'Edgebands'),
    h('span', { class: 'mat-th' }, String(edgebands().length)),
    h('span', { class: 'mat-tools' },
      h('button', { class: 'tiny', title: 'Add an edgeband', onclick: (e) => { e.stopPropagation(); onAddEdgeband(); } }, '+'))
  ));

  if (ebOpen) {
    const list = h('div', { class: 'sheets' });
    edgebands().forEach((b, ebi) => {
      const isSel = state.sel.ebi === ebi;
      list.append(h('div', { class: 'sheet-row' + (isSel ? ' sel' : ''), onclick: () => selectEdgeband(ebi) },
        h('span', { class: 'swatch', style: 'background:' + (b.color || DEFAULT_COLOR) }),
        h('span', { class: 'sheet-name', title: b.name || '(unnamed)' }, b.name || '(unnamed edgeband)'),
        h('span', { class: 'sheet-dim' }, (b.width ? fmt(b.width) + '×' + fmt(b.thickness) : '')),
        h('span', { class: 'sheet-tools' },
          h('button', { class: 'tiny danger', title: 'Delete edgeband', onclick: (e) => { e.stopPropagation(); onDeleteEdgeband(ebi); } }, '✕'))
      ));
    });
    list.append(h('div', { class: 'sheet-row addsheet', onclick: onAddEdgeband }, '+ add edgeband'));
    box.append(list);
  }
  tree.append(box);
}

function renderDetail() {
  const d = document.getElementById('detail');
  d.innerHTML = '';

  const b = selBand();
  if (b) { renderEdgebandForm(d, b); return; }

  const m = selMat();
  if (!m) { d.append(h('div', { class: 'empty' }, 'Select a material, sheet or edgeband to edit.')); return; }

  if (state.sel.si === null) { renderMaterialForm(d, m); }
  else {
    const s = (m.sheets || [])[state.sel.si];
    if (s) renderSheetForm(d, m, s);
    else renderMaterialForm(d, m);
  }
}

function renderEdgebandForm(d, b) {
  d.append(h('h3', {}, 'Edgeband'));
  d.append(field('Name', h('input', {
    type: 'text', value: b.name || '',
    placeholder: 'e.g. PVC White 0.8 mm — the Edgeband command tags faces by this name',
    oninput: e => { b.name = e.target.value; renderTree(); }
  }), true));
  d.append(field('Thickness (mm)', numInput(b, 'thickness', { renderTree: true })));
  d.append(field('Width (mm)', numInput(b, 'width', { renderTree: true })));
  d.append(field('Cost (per metre)', numInput(b, 'cost', {})));

  const colorPick = h('input', {
    type: 'color', value: toHex(b.color),
    oninput: e => { b.color = e.target.value; hexText.value = e.target.value; renderTree(); }
  });
  const hexText = h('input', {
    type: 'text', value: b.color || DEFAULT_COLOR, maxlength: 7,
    oninput: e => { b.color = e.target.value; if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) colorPick.value = e.target.value; renderTree(); }
  });
  d.append(field('Colour', h('span', { class: 'colorwrap' }, colorPick, hexText)));
  d.append(field('Comment', h('input', { type: 'text', value: b.comment || '', oninput: e => { b.comment = e.target.value; } })));

  d.append(h('div', { class: 'subhead' }, 'Used by'));
  d.append(h('div', { class: 'note' },
    'The Edgeband command tags panel edge faces with this band BY NAME; the BOM ' +
    'sums the tagged metres and multiplies by this cost per metre. Renaming a band ' +
    'does not retag already-tagged faces.'));
}

function renderMaterialForm(d, m) {
  d.append(h('h3', {}, 'Material'));

  // Plain text input (type a custom name) — no datalist: Fusion's webview renders
  // the datalist popup in-page, where the scrolling panel clips it. The "From
  // design" <select> below is the reliable picker (native popup, no clipping).
  const nameInput = h('input', {
    type: 'text', value: m.name || '',
    placeholder: 'Fusion material name (must match the part)',
    oninput: e => { m.name = e.target.value; renderTree(); }
  });
  d.append(field('Material', nameInput, true));

  // Explicit picker of the design's detected materials (datalist is unreliable in
  // Fusion's webview, so we give a real <select> that fills the name on choice).
  if (state.designMaterials.length) {
    const pick = h('select', {
      onchange: e => {
        if (e.target.value) { m.name = e.target.value; nameInput.value = e.target.value; renderTree(); e.target.value = ''; }
      }
    });
    pick.append(h('option', { value: '' }, '— pick a material from this design —'));
    state.designMaterials.forEach(n => pick.append(h('option', { value: n }, n)));
    d.append(field('From design', pick, true));
  }
  d.append(field('Thickness (mm)', numInput(m, 'thickness', { renderTree: true })));
  d.append(field('Category', h('input', {
    type: 'text', value: m.category || '', placeholder: 'e.g. Boards, Veneer',
    oninput: e => { m.category = e.target.value; renderCategoryFilter(); renderTree(); }
  })));

  const colorPick = h('input', {
    type: 'color', value: toHex(m.color),
    oninput: e => { m.color = e.target.value; hexText.value = e.target.value; renderTree(); }
  });
  const hexText = h('input', {
    type: 'text', value: m.color || DEFAULT_COLOR, maxlength: 7,
    oninput: e => { m.color = e.target.value; if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) colorPick.value = e.target.value; renderTree(); }
  });
  d.append(field('Colour', h('span', { class: 'colorwrap' }, colorPick, hexText)));
  d.append(field('Comment', h('input', { type: 'text', value: m.comment || '', oninput: e => { m.comment = e.target.value; } })));

  d.append(h('div', { class: 'subhead' }, (m.sheets || []).length + ' sheet(s)'));
  d.append(h('button', { onclick: () => onAddSheet(state.sel.mi) }, '+ Add sheet'));
}

function renderSheetForm(d, m, s) {
  d.append(h('h3', {}, (m.name || 'Material') + ' › ' + (s.name || 'Sheet')));

  d.append(field('Sheet name', h('input', {
    type: 'text', value: s.name || '', oninput: e => { s.name = e.target.value; renderTree(); }
  }), true));
  d.append(field('Length (mm)', numInput(s, 'length', { renderTree: true })));
  d.append(field('Width (mm)', numInput(s, 'width', { renderTree: true })));
  d.append(field('Form', h('input', { type: 'text', value: s.form || 'Rectangular', oninput: e => { s.form = e.target.value; } })));
  d.append(field('Cost (per sheet)', numInput(s, 'cost', {})));

  d.append(h('div', { class: 'subhead' }, 'Nesting'));
  const rot = h('select', { onchange: e => { s.rotation = e.target.value; } });
  state.rotations.forEach(code => rot.append(h('option', { value: code }, ROT_LABELS[code] || code)));
  rot.value = s.rotation || 'all';
  d.append(field('Rotation', rot));
  d.append(field('Item separation (mm)', numInput(s, 'separation', {})));
  d.append(field('Edge trim (mm)', numInput(s, 'trim', {})));
  d.append(field('Comment', h('input', { type: 'text', value: s.comment || '', oninput: e => { s.comment = e.target.value; } })));
}

// ---------------------------------------------------------------------------
// Small render helpers
// ---------------------------------------------------------------------------
function field(label, control, wide) {
  // wide => stack the control under the label so long values (e.g. a full Fusion
  // material name) aren't clipped by the narrow value column.
  return h('div', { class: 'field' + (wide ? ' wide' : '') }, h('label', {}, label), control);
}
function numInput(obj, key, opts) {
  return h('input', {
    type: 'number', step: 'any', value: (obj[key] != null ? obj[key] : ''),
    oninput: e => {
      const v = parseFloat(e.target.value);
      obj[key] = isNaN(v) ? 0 : v;
      if (opts && opts.renderTree) renderTree();
    }
  });
}
function fmt(n) { const v = parseFloat(n); return isNaN(v) ? '0' : (Math.round(v * 100) / 100).toString(); }
function toHex(c) { return (/^#[0-9a-fA-F]{6}$/.test(c || '')) ? c : DEFAULT_COLOR; }

// ---------------------------------------------------------------------------
// Selection + edits
// ---------------------------------------------------------------------------
function selectMaterial(mi) { state.sel = { mi, si: null, ebi: null }; expanded.add(materials()[mi]); render(); }
function selectSheet(mi, si) { state.sel = { mi, si, ebi: null }; render(); }
function selectEdgeband(ebi) { state.sel = { mi: -1, si: null, ebi }; render(); }
function toggle(m) { if (expanded.has(m)) expanded.delete(m); else expanded.add(m); renderTree(); }

function onAddMaterial() {
  const m = { name: '', thickness: 18, category: '', color: DEFAULT_COLOR, comment: '', sheets: [] };
  materials().push(m);
  expanded.add(m);
  state.sel = { mi: materials().length - 1, si: null, ebi: null };
  render();
}
function onDeleteMaterial(mi) {
  materials().splice(mi, 1);
  state.sel = { mi: Math.min(mi, materials().length - 1), si: null, ebi: null };
  render();
}
function onAddSheet(mi) {
  const m = materials()[mi];
  m.sheets = m.sheets || [];
  m.sheets.push({ name: 'Sheet ' + (m.sheets.length + 1), length: 2440, width: 1220, form: 'Rectangular', cost: 0, rotation: 'all', separation: 3, trim: 10, comment: '' });
  expanded.add(m);
  state.sel = { mi, si: m.sheets.length - 1, ebi: null };
  render();
}
function onDeleteSheet(mi, si) {
  materials()[mi].sheets.splice(si, 1);
  state.sel = { mi, si: null, ebi: null };
  render();
}
function onAddEdgeband() {
  edgebands().push({ name: 'Edgeband ' + (edgebands().length + 1), thickness: 1,
                     width: 22, cost: 0, color: nextColor(), comment: '' });
  ebOpen = true;
  state.sel = { mi: -1, si: null, ebi: edgebands().length - 1 };
  render();
}
function onDeleteEdgeband(ebi) {
  edgebands().splice(ebi, 1);
  state.sel = { mi: -1, si: null, ebi: edgebands().length ? Math.min(ebi, edgebands().length - 1) : null };
  render();
}

// ---------------------------------------------------------------------------
// Save / Export / Import
// ---------------------------------------------------------------------------
async function onSave() {
  const r = await bridge('save', { materials: materials(), edgebands: edgebands() });
  if (r && r.ok) toast('Saved ' + r.count + ' material(s) · ' + (r.bands || 0) + ' edgeband(s).');
  else toast('Save failed' + (r && r.error ? ': ' + r.error : ''), true);
}
async function onExport() {
  const r = await bridge('export', { materials: materials(), edgebands: edgebands() });
  if (r && r.ok) toast('Exported to ' + r.path);
  else if (r && r.cancelled) { /* no-op */ }
  else toast('Export failed' + (r && r.error ? ': ' + r.error : ''), true);
}
async function onImport() {
  const r = await bridge('import', {});
  if (r && r.ok && Array.isArray(r.materials)) {
    state.library.materials = r.materials;
    // edgebands null => the imported file had no band section; keep the current ones.
    if (Array.isArray(r.edgebands)) state.library.edgebands = r.edgebands;
    state.sel = { mi: r.materials.length ? 0 : -1, si: null, ebi: null };
    if (r.materials.length) expanded.add(r.materials[0]);
    render();
    toast('Imported ' + r.materials.length + ' material(s)' +
      (Array.isArray(r.edgebands) ? ' · ' + r.edgebands.length + ' edgeband(s)' : '') +
      '. Click Save to keep them.');
  } else if (r && r.cancelled) { /* no-op */ }
  else toast('Import failed' + (r && r.error ? ': ' + r.error : ''), true);
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = 'toast hidden'; }, 3200);
}

window.addEventListener('DOMContentLoaded', init);
