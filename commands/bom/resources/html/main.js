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
const state = { tree: [], design: '', config: '' };
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
  nodes.forEach(n => { if (n.children && n.children.length) { collapsed.add(n); collapseAll(n.children); } });
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
  }
  document.getElementById('pathNote').textContent =
    'Part numbers come from each component’s Fusion property. Export writes a native .xlsx.';

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
    const open = !collapsed.has(node);
    box.append(rowEl(node, level, hasChildren, open));
    if (hasChildren && open) renderRows(box, node.children, level + 1);
  });
}

function rowEl(node, level, hasChildren, open) {
  const isAsm = node.type === 'Assembly';
  const caret = h('span', {
    class: 'caret' + (hasChildren ? '' : ' leaf'),
    onclick: hasChildren ? (() => { toggle(node); }) : null
  }, hasChildren ? (open ? '▾' : '▸') : '•');
  caret.style.marginLeft = (level * 16) + 'px';

  const dims = (!isAsm && node.L > 0)
    ? (fmt(node.L) + ' × ' + fmt(node.W) + ' × ' + fmt(node.T))
    : '';
  const mat = node.material || '';
  const part = node.part_number || '';

  return h('div', { class: 'row grid' + (isAsm ? ' asm' : '') },
    h('span', { class: 'c-name' }, caret, h('span', { class: 'nm', title: node.name }, node.name)),
    h('span', { class: 'c-type' }, h('span', { class: 'badge ' + node.type }, node.type)),
    h('span', { class: 'c-dims' + (dims ? '' : ' muted') }, dims || '—'),
    h('span', { class: 'c-mat', title: mat }, mat || '—'),
    h('span', { class: 'c-qty' }, String(node.qty)),
    h('span', { class: 'c-part', title: part }, part || '—')
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
