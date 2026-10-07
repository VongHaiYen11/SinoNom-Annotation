// Execute the production preview and radio handlers against a small SVG DOM fixture.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = fs.readFileSync(require('node:path').join(__dirname, '../ui/assets/editor.js'), 'utf8');
const extract = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));
class Node {
  constructor() { this.attrs = {}; this.dataset = {}; this.style = {}; this.children = []; this.classList = {contains:()=>false}; }
  setAttribute(k,v) {this.attrs[k]=String(v);}
  getAttribute(k) {return this.attrs[k];}
  removeAttribute(k) {delete this.attrs[k];}
  appendChild(n) {n.parent=this;this.children.push(n);}
  remove() {this.parent.children=this.parent.children.filter(n=>n!==this);}
  querySelector(selector) {
    if (selector.startsWith('rect')) return this.rect;
    if (selector === '[data-box-order-label]') return this.label;
    if (selector === '[data-unknown-mark]') return this.children.find(n=>n.dataset.unknownMark);
    return null;
  }
}
const group = new Node();group.rect=new Node();group.label=new Node();
const chip=new Node();const box={bbox:[10,20,40,60],status:'intact',unknown:false,unavailable_font:false,expert_prediction:false};
const context = {localBoxes:{'1':box},groupFor:()=>group,props:{value:{step:4}},
  annotationColor:'#22d3ee', element:{querySelectorAll:()=>[chip]}, document:{createElementNS:()=>new Node()},
  activeBoxId:'1',syncExternalControls:()=>{},assert};
vm.createContext(context);
vm.runInContext(extract('const statusColor =', 'const applyAnnotationColor =') +
  extract('const renderLocalStatus =', 'const renderSelection ='), context);
const run = code => vm.runInContext(code,context);
const radioHandlers=script.slice(script.indexOf("  const input = event.target.closest('#status-radio input');"),
  script.indexOf("\n});",script.indexOf("  const input = event.target.closest('#status-radio input');")));
run(`function radio(selector,value) { const event={target:{closest:s=>s===selector?{value}:null}}; ${radioHandlers} }`);
run("renderLocalStatus('1','intact',false)");
assert.equal(group.rect.attrs.stroke,'#22c55e');assert.equal(group.label.attrs.fill,'#ffffff');
run("radio('#unavailable-font-radio input','True')");
assert.equal(group.label.attrs.fill,'#ec4899');assert.equal(group.rect.attrs['fill-opacity'],'.20');
assert.equal(box.status,'intact');
run("radio('#expert-prediction-radio input','True')");
assert.equal(box.status,'damaged');assert.equal(group.rect.attrs.stroke,'#facc15');assert.equal(group.label.attrs.fill,'#ec4899');
run("radio('#status-radio input','intact')");
assert.equal(box.status,'intact');assert.equal(group.rect.attrs.stroke,'#facc15');
run("radio('#unavailable-font-radio input','False')");
assert.equal(group.label.attrs.fill,'#facc15');assert.equal(chip.style.color,'#facc15');
run("radio('#status-radio input','damaged'); radio('#unknown-radio input','True')");
assert.equal(box.expert_prediction,false);assert.equal(box.unavailable_font,false);
assert.equal(group.rect.attrs.stroke,'#ef4444');assert.equal(group.label.attrs.fill,'#ffffff');
assert.equal(group.querySelector('[data-unknown-mark]').textContent,'?');
run("radio('#unavailable-font-radio input','True')");
assert.equal(box.unknown,false);assert.equal(group.querySelector('[data-unknown-mark]'),undefined);
run("radio('#expert-prediction-radio input','True'); radio('#expert-prediction-radio input','False')");
assert.equal(box.status,'damaged');assert.equal(box.unavailable_font,true);
group.rect.dataset.missing='1';
run("radio('#expert-prediction-radio input','True'); renderLocalStatus('1','damaged',true)");
assert.equal(box.expert_prediction,false);assert.equal(box.unavailable_font,false);assert.equal(box.unknown,false);
// Physical palette changes must be scoped to the geometry editor (step 3).
assert.match(extract('const applyAnnotationColor =','const readAnnotationColor ='), /props.value.step !== 3/);
console.log('PASS: production radio handlers and SVG preview, exclusivity, combined flags, intact override, MISS and white text');
