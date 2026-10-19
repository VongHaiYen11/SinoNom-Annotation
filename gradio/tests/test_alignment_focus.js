const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync(path.join(__dirname, '../ui/assets/editor.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../ui/assets/editor.css'), 'utf8');
function node(dataset = {}) {
  const classes = new Set();
  return { dataset, classes, classList: {
    contains: key => classes.has(key),
    toggle: (key, on) => on ? classes.add(key) : classes.delete(key),
  } };
}
const groups = ['1', '2', '3', '4', '5'].map(boxId => {
  const group = node({ boxId });
  group.rect = { attrs: {}, dataset: {}, setAttribute(key, value) { this.attrs[key] = value; } };
  group.querySelector = () => group.rect;
  return group;
});
// Duplicate characters and placeholders must be resolved by box ID, not text.
const chips = ['永', '永', 'MISS', '□', '@', '寺'].map((character, i) =>
  node({ character, ...(i < 5 ? { assignedBoxId: String(i + 1) } : {}) }));
const boxes = Object.fromEntries(groups.map(group => [group.dataset.boxId, {
  status: 'damaged', damage_level: 2, unknown: false, unavailable_font: false,
  expert_prediction: false, suspicious: false, bbox: [10, 20, 30, 40],
}]));
boxes['4'].unknown = true; boxes['5'].unavailable_font = true;
const before = JSON.stringify(boxes);
let syncs = 0;
const context = { props: { value: { step: 4 } }, activeBoxId: '1',
  localBoxes: boxes, selectedIds: new Set(['1']),
  statusFillOpacity: () => '.04', syncExternalControls: () => { syncs++; },
  element: { querySelectorAll: selector => selector.startsWith('.annotation-canvas') ? groups : chips },
};
vm.createContext(context);
vm.runInContext(script.slice(script.indexOf('function renderAlignmentFocus()'), script.indexOf('const updateCanvasLabels =')), context);
const run = code => vm.runInContext(code, context);
function check(id) {
  groups.forEach(group => assert.equal(group.classes.has('focus-dimmed'), Boolean(id && group.dataset.boxId !== id)));
  chips.forEach(chip => {
    const active = Boolean(id && chip.dataset.assignedBoxId === id);
    assert.equal(chip.classes.has('selected-chip'), active);
    assert.equal(chip.classes.has('focus-dimmed'), Boolean(id && !active));
  });
  assert.equal(JSON.stringify(boxes), before, 'focus must not mutate annotation data');
}
for (const id of Object.keys(boxes)) {
  context.activeBoxId = id; context.selectedIds = new Set([id]);
  run('renderSelection(false)'); check(id);
}
assert.equal(syncs, 0);
// The selected box remains fixed while its assigned chip changes after reorder.
context.activeBoxId = '1'; context.selectedIds = new Set(['1']);
[chips[0].dataset.assignedBoxId, chips[1].dataset.assignedBoxId] = ['2', '1'];
run('renderSelection()'); check('1'); assert.equal(syncs, 1);
context.activeBoxId = null; context.selectedIds.clear();
run('renderSelection(false)'); check(null);
// Invalid/deleted active IDs and all other steps must clear focus styling.
context.activeBoxId = 'deleted'; run('renderSelection(false)'); check(null);
context.activeBoxId = '1';
for (const step of [3, 5, 6, 7]) {
  context.props.value.step = step; run('renderSelection(false)'); check(null);
}
context.props.value.step = 4; run('renderSelection(false)'); check('1');
// Styling affects entire box groups/cards, with no image selector or disabled
// hit targets. Dragged cards retain the existing drag opacity.
const focusRule = css.match(/\.status-order-board \.annotation-canvas \[data-box-id\]\.focus-dimmed,[\s\S]*?\}/)?.[0];
assert.ok(focusRule);
assert.match(focusRule, /\.order-chip\.focus-dimmed:not\(\.dragging\)/);
assert.match(focusRule, /opacity:\s*\.25/);
assert.doesNotMatch(focusRule, /pointer-events|image-only|visibility|filter/);
assert.match(css, /\.annotation-canvas\.image-only > :not\(image\)[\s\S]*?visibility: hidden !important/);
console.log('PASS: focus by box ID, duplicate/MISS/placeholder chips, reorder, deselect, step isolation and unchanged annotation data');
