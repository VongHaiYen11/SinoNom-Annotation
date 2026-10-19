// Run the production alignment/overlay code against a small replaceable SVG DOM.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync(path.join(__dirname, '../ui/assets/editor.js'), 'utf8');
const extract = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));
class Node {
  constructor() {
    this.dataset = {}; this.attrs = {}; this.children = []; this.style = {};
    this.classes = new Set();
    this.classList = {
      contains: key => this.classes.has(key),
      toggle: (key, on) => on ? this.classes.add(key) : this.classes.delete(key),
      remove: key => this.classes.delete(key),
      add: key => this.classes.add(key),
    };
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  appendChild(node) { node.remove(); node.parent = this; this.children.push(node); }
  insertBefore(node, before) {
    node.remove(); node.parent = this;
    const index = this.children.indexOf(before);
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this);
    this.parent = null;
  }
  querySelector(selector) {
    if (selector.startsWith('rect')) return this.rect;
    if (selector.includes('[data-box-order-label]')) return this.label;
    if (selector === '[data-miss-mark]') return this.children.find(node => node.attrs['data-miss-mark']);
    if (selector === '[data-unknown-mark]') return this.children.find(node => node.dataset.unknownMark);
    return null;
  }
  querySelectorAll(selector) {
    if (selector.startsWith('[data-order-chip]')) {
      return this.children.filter(node => !selector.includes('[data-assigned-box-id]') || node.dataset.assignedBoxId);
    }
    return [];
  }
}
const makeChip = (id, character) => {
  const chip = new Node(); chip.dataset = { tokenId: id, character }; return chip;
};
const makeGroup = id => {
  const group = new Node(); group.dataset.boxId = id;
  group.rect = new Node(); group.label = new Node(); group.appendChild(group.label);
  return group;
};
let container = new Node(), canvas = new Node();
let groups = ['1', '2', '3'].map(makeGroup);
const tokens = [makeChip('a', '永'), makeChip('b', 'MISS'), makeChip('c', 'MISS')];
tokens.forEach(chip => container.appendChild(chip));
const boxes = Object.fromEntries(groups.map((group, index) => [group.dataset.boxId, {
  bbox: [index * 30, 10, index * 30 + 20, 30], order: index + 1,
  status: 'intact', unknown: false, unavailable_font: false, expert_prediction: false, suspicious: false,
}]));
const chipsFor = selector => {
  const match = selector.match(/data-assigned-box-id="([^"]+)"/);
  return container.children.filter(chip => !match || chip.dataset.assignedBoxId === match[1]);
};
const element = {
  querySelector: selector => selector === '.order-chips' ? container
    : selector === '.annotation-canvas' ? canvas
    : selector.startsWith('[data-order-chip]') ? chipsFor(selector)[0] : null,
  querySelectorAll: selector => selector.startsWith('.annotation-canvas') ? groups
    : selector.includes('.tile-character') ? [] : chipsFor(selector),
};
let observerCallback;
const context = {
  element, localBoxes: boxes, groupFor: id => groups.find(group => group.dataset.boxId === id),
  props: { value: { step: 4, width: 100, height: 100,
    alignmentTokenIds: ['a', 'b', 'c'], spatialBoxOrder: [1, 2, 3] } },
  document: { createElementNS: () => new Node() },
  alignmentStateReady: false, alignmentContainer: null, alignmentCanvas: null, alignmentBoxGroups: [],
  localTextSequence: [], localTokenOrder: [], annotationColor: '#ffffff', applyAnnotationColor: () => {},
  orderDrag: null,
  activeBoxId: '1',
  MutationObserver: class { constructor(callback) { observerCallback = callback; } observe() {} },
};
vm.createContext(context);
vm.runInContext(
  extract('const statusColor =', 'const applyAnnotationColor =')
  + extract('const renderLocalStatus =', 'const renderSelection =')
  + extract('const updateCanvasLabels =', 'const hydrateLocalState =')
  + extract('const missMarkLines =', 'const drawPreview =')
  + extract('const tokenOrderFromDOM =', 'const orderRows =')
  + extract('const alignmentObserver =', '\nhydrateLocalState();'), context);
const run = code => vm.runInContext(code, context);
function check(expected) {
  groups.forEach((group, index) => {
    const missing = expected.includes(index + 1);
    assert.equal(group.classList.contains('focus-dimmed'), index !== 0);
    assert.equal(group.rect.dataset.missing === '1', missing);
    const marks = group.children.filter(node => node.attrs['data-miss-mark']);
    assert.equal(marks.length, Number(missing));
    assert.equal(group.rect.attrs.fill, missing ? '#e5e7eb' : '#22c55e');
    assert.equal(group.rect.attrs['fill-opacity'], missing ? '.30' : '.04');
    assert.equal(group.label.textContent, `${index + 1} ${container.children[index].dataset.character}`);
    if (missing) {
      assert.equal(marks[0].children.length, 2);
      const x = boxes[group.dataset.boxId].bbox[0];
      assert.equal(marks[0].children[0].attrs.x1, String(x + 4));
      assert.equal(marks[0].children[0].attrs.y1, '14');
    }
  });
  container.children.forEach(chip => {
    assert.equal(chip.classList.contains('selected-chip'), chip.dataset.assignedBoxId === '1');
    assert.equal(chip.classList.contains('focus-dimmed'), chip.dataset.assignedBoxId !== '1');
  });
}
assert.equal(run('initializeAlignmentStateFromDOM()'), true);
check([2, 3]);
// Same-token duplicate MISS values must keep separate overlays through reorders.
container.insertBefore(tokens[1], tokens[0]);
run('updateExcludedChips(alignmentContainer)'); check([1, 3]);
const unchangedMark = groups[0].querySelector('[data-miss-mark]');
for (let i = 0; i < 3; i++) run('updateExcludedChips(alignmentContainer)');
check([1, 3]);
assert.equal(groups[0].querySelector('[data-miss-mark]'), unchangedMark);
// Cancellation restores the original DOM order via the real drag cleanup path.
Object.assign(context, {
  orderDrag: { started: true, container, originalOrder: ['a', 'b', 'c'], chip: tokens[1] },
  captureChipRects: () => new Map(), animateChipReflow: () => {},
  handleOrderPointerMove: () => {}, handleOrderPointerUp: () => {},
  handleOrderPointerCancel: () => {}, handleOrderLostPointerCapture: () => {},
});
container.isConnected = true;
context.document.removeEventListener = () => {};
vm.runInContext(extract('const beginOrderDrag =', 'const finishOrderDrag ='), context);
run("cleanupOrderDrag('cancel', false)"); check([2, 3]);
// A MISS passing over a flagged box must not erase flags when it moves away,
// and cancelling the drag must restore all status fields, not only the X.
for (const flags of [
  { unknown: true }, { unavailable_font: true },
  { expert_prediction: true }, { suspicious: true },
]) {
  Object.assign(boxes['1'], { status: 'damaged', damage_level: 2,
    unknown: false, unavailable_font: false, expert_prediction: false, suspicious: false }, flags);
  run('updateExcludedChips(alignmentContainer)');
  const before = JSON.stringify(boxes);
  context.orderDrag = { active: true, pointerId: 1, container, chip: tokens[1] };
  run('beginOrderDrag({pointerId: 1})');
  container.insertBefore(tokens[1], tokens[0]);
  run('updateExcludedChips(alignmentContainer)');
  run("arrangeOrder(alignmentContainer, ['a','b','c']); updateExcludedChips(alignmentContainer)");
  assert.equal(JSON.stringify(boxes), before, 'moving MISS away must restore the original flags');
  container.insertBefore(tokens[1], tokens[0]);
  run('updateExcludedChips(alignmentContainer)');
  run("cleanupOrderDrag('cancel', false)");
  assert.equal(JSON.stringify(boxes), before, 'cancel must preserve status/level/flags');
  context.orderDrag = { active: true, pointerId: 2, container, chip: tokens[1] };
  run('beginOrderDrag({pointerId: 2})');
  container.insertBefore(tokens[1], tokens[0]);
  run('updateExcludedChips(alignmentContainer)');
  run("arrangeOrder(alignmentContainer, ['a','b','c']); updateExcludedChips(alignmentContainer)");
  context.renderSelection = () => {};
  run("cleanupOrderDrag('pointerup', true)");
  assert.equal(JSON.stringify(boxes), before, 'drop must preserve flags on boxes MISS only passed over');
}
Object.assign(boxes['1'], { status: 'intact', damage_level: null,
  unknown: false, unavailable_font: false, expert_prediction: false, suspicious: false });
run('updateExcludedChips(alignmentContainer)'); check([2, 3]);
// Value arrives before the new chips/canvas. Do not paint mismatched token sets.
context.props.value.alignmentTokenIds = ['d', 'e', 'f'];
assert.equal(run('initializeAlignmentStateFromDOM()'), false);
check([2, 3]);
container = new Node();
[makeChip('d', 'MISS'), makeChip('e', '永'), makeChip('f', '寺')].forEach(chip => container.appendChild(chip));
canvas = new Node(); groups = ['1', '2', '3'].map(makeGroup);
observerCallback(); check([1]);
assert.equal(context.alignmentStateReady, true);
// Replacing only the canvas, or its box groups, must resynchronize overlays too.
canvas = new Node(); groups = ['1', '2', '3'].map(makeGroup);
observerCallback(); check([1]);
groups = ['1', '2', '3'].map(makeGroup);
observerCallback(); check([1]);
const markAfterReplacement = groups[0].querySelector('[data-miss-mark]');
observerCallback();
assert.equal(groups[0].querySelector('[data-miss-mark]'), markAfterReplacement);
// Patching children inside existing groups must not strand a stale X either.
groups[0].querySelector('[data-miss-mark]').remove();
groups[0].rect = new Node();
observerCallback(); check([1]);
const repairedMark = groups[0].querySelector('[data-miss-mark]');
observerCallback();
assert.equal(groups[0].querySelector('[data-miss-mark]'), repairedMark);
// Excluded source tokens have no box and cannot leave an X in the last slot.
container.appendChild(makeChip('g', 'MISS'));
container.dataset.excludedCount = '1';
context.props.value.alignmentTokenIds.push('g');
run('initializeAlignmentStateFromDOM()'); check([1]);
assert.equal(container.children[3].dataset.assignedBoxId, undefined);
assert.equal(container.children[3].classList.contains('excluded'), true);
// Review keeps its backend-generated marks, independent of draft chip order.
context.props.value.step = 7;
container.insertBefore(container.children[1], container.children[0]);
run('updateExcludedChips(alignmentContainer)');
assert.equal(groups[0].querySelector('[data-miss-mark]'), repairedMark);
console.log('PASS: live MISS overlays, duplicate tokens, cancel/drop preserve flags and geometry, delayed/replaced DOM, exclusions and Review isolation');
