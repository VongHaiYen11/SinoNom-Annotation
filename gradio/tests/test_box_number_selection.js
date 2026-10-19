const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync(path.join(__dirname, '../ui/assets/editor.js'), 'utf8');
const extract = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));
function node(dataset = {}) {
  const classes = new Set(), attrs = {};
  return { dataset, attrs, value: '', classList: {
    toggle: (key, on) => on ? classes.add(key) : classes.delete(key),
    contains: key => classes.has(key),
  }, setAttribute: (key, value) => { attrs[key] = String(value); },
  removeAttribute: key => { delete attrs[key]; } };
}
function field() {
  const input = node();
  input.closest = selector => selector === '#select-box-number' ? input : null;
  return input;
}
let input = field(), error = { textContent: '' };
const listeners = new Map();
const ids = ['1', '2', '123'];
const boxes = Object.fromEntries(ids.map(id => [id, { status: 'damaged', damage_level: 2,
  unknown: false, unavailable_font: false, expert_prediction: false, suspicious: false,
  bbox: [0, 0, 20, 20], order: Number(id) }]));
const before = JSON.stringify(boxes);
const chips = ids.map((id, index) => node({ assignedBoxId: id, character: index === 2 ? 'MISS' : '永' }));
chips[2].classList.toggle('missing', true);
const groups = ids.map(id => {
  const group = node({ boxId: id }), rect = node();
  group.querySelector = () => rect;
  return group;
});
let bridge;
const context = {
  root: {
    querySelector: selector => selector === '#select-box-number' ? input : selector === '#select-box-number-error' ? error : null,
    querySelectorAll: () => [],
    addEventListener: (type, handler, capture) => {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push({ handler, capture });
    },
  },
  element: {
    querySelector: selector => chips.find(chip => selector.includes(`data-assigned-box-id="${chip.dataset.assignedBoxId}"`)),
    querySelectorAll: selector => selector.startsWith('.annotation-canvas') ? groups : chips,
  },
  document: { activeElement: null }, props: { value: { step: 4 } },
  localBoxes: boxes, activeBoxId: null, activeTokenId: null, selectedIds: new Set(),
  boxNumberInputElement: null, boxNumberSelectedId: null, pending: false,
  localTextSequence: ['永', '永', 'MISS'],
  updateValidationSummary: () => {}, serializeLocalBoxes: () => boxes,
  setInputValue: (selector, value) => { if (selector === '#selection-bridge') bridge = JSON.parse(value); },
  statusFillOpacity: () => '.04',
};
vm.createContext(context);
vm.runInContext(extract('function setBoxNumberError(', 'const renderLocalStatus =')
  + extract('function renderAlignmentFocus()', 'const updateCanvasLabels =')
  + extract('const setSelection =', 'const createOverlayRect ='), context);
const run = code => vm.runInContext(code, context);
function key(value, key = 'Enter', overrides = {}) {
  input.value = value; context.document.activeElement = input;
  const event = { target: input, key, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; },
    stopImmediatePropagation() { this.stopped = true; }, ...overrides };
  listeners.get('keydown')[0].handler(event);
  return event;
}
function selected(id) {
  assert.equal(context.activeBoxId, id);
  assert.deepEqual([...context.selectedIds], id ? [id] : []);
  groups.forEach(group => assert.equal(group.classList.contains('focus-dimmed'), Boolean(id && group.dataset.boxId !== id)));
  chips.forEach(chip => assert.equal(chip.classList.contains('selected-chip'), Boolean(id && chip.dataset.assignedBoxId === id)));
  assert.equal(JSON.stringify(boxes), before, 'selecting must preserve box metadata');
}
run('syncExternalControls()'); selected(null); // no active.status exception
assert.equal(listeners.get('keydown')[0].capture, true);
for (const id of ids) {
  const event = key(id);
  assert.equal(event.prevented, true); assert.equal(event.stopped, true);
  selected(id); assert.equal(bridge.active, id);
}
key(' 0002 '); selected('2'); assert.equal(input.value, '2');
for (const invalid of ['0', '-1', '1.5', '1e2', 'abc', '12', '9007199254740993']) {
  key(invalid); selected('2');
  assert.ok(error.textContent); assert.equal(input.attrs['aria-invalid'], 'true');
}
assert.equal(key('123', '3').prevented, false); selected('2');
listeners.get('input')[0].handler({ target: input });
assert.equal(error.textContent, ''); assert.equal(input.attrs['aria-invalid'], undefined);
// Updates while typing must preserve the number draft until Enter.
input.value = '12'; run('syncExternalControls()');
assert.equal(input.value, '12'); selected('2');
run("setSelection(['1'], '1')");
assert.equal(input.value, '1'); selected('1');
key('   '); selected(null); assert.equal(input.value, ''); assert.equal(bridge.active, null);
// The delegated listener must use the replacement input, not a stale reference.
run("setSelection(['123'], '123')");
input = field(); error = { textContent: '' };
context.document.activeElement = input;
listeners.get('focusin')[0].handler({ target: input });
assert.equal(input.value, '123'); key('1'); selected('1');
context.pending = true; key('2'); selected('1'); context.pending = false;
context.props.value.step = 7; key('2'); assert.equal(context.activeBoxId, '1');
context.props.value.step = 4;
key('2', 'Enter', { isComposing: true }); selected('1');
console.log('PASS: Enter selection/focus/bridge, normalization, invalid and empty values, mouse sync, typing preservation and delegated DOM replacement');
