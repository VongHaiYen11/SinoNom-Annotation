// Execute the production storage coordinator with a fresh JS context per reload.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../ui/assets/recovery.js'), 'utf8');
const storage = new Map();
const meta = {version: 1, application: 'app', tab: 'tab', image: '/1.png', step: 4,
  generation: 'g1', discardImage: null};
function mount(metadata = meta, blocked = false) {
  const nodes = new Map();
  const listeners = {};
  const status = {textContent: ''};
  const context = {
    sessionStorage: {getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => {if (blocked) throw Error('quota'); storage.set(key, value);}},
    window: {addEventListener: () => {}},
    document: {querySelector: selector => selector === '#draft-recovery-status' ? status : nodes.get(selector),
      addEventListener: (type, handler) => {listeners[type] = handler;}},
    AbortController, structuredClone, queueMicrotask: fn => fn(), requestAnimationFrame: () => {},
    props: {value: metadata}, watch: () => {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, nodes, listeners, status,
    run: code => vm.runInContext(code, context)};
}
let page = mount();
page.run(`draftRecovery.write(props.value, {workspace: {
  boxes: {'1': {bbox:[1,2,3,4], status:'damaged', damage_level:null, suspicious:true}},
  active:'1', selected:['1'], tokenOrder:['t2','t1']}})`);
page = mount();
assert.equal(page.run('draftRecovery.read(props.value).workspace.boxes["1"].status'), 'damaged');
assert.equal(page.run('draftRecovery.read(props.value).workspace.boxes["1"].damage_level'), null);
assert.equal(page.run('draftRecovery.read(props.value).workspace.active'), '1');
assert.equal(page.run('draftRecovery.read(props.value).workspace.tokenOrder.join()'), 't2,t1');

// Actual typing and fields never sent to Python survive a new page context.
const contentMeta = {...meta, step: 2, defaultSection: '[0]'};
page = mount(contentMeta);
page.nodes.set('#content-value input, #content-value textarea', {value: 'typing unfinished'});
page.listeners.input({isTrusted: true});
page = mount(contentMeta);
assert.equal(page.run('draftRecovery.read(props.value).typing["[0]"]'), 'typing unfinished');
assert.equal(page.run('window.vietnamicaRecovery.section("[0]", "{}")'), 'typing unfinished');
// Programmatic synchronization must not replace raw input with an older value.
page.nodes.set('#content-value input, #content-value textarea', {value: 'older backend'});
page.listeners.input({isTrusted: false});
assert.equal(page.run('draftRecovery.read(props.value).typing["[0]"]'), 'typing unfinished');

// Per-image drafts survive switching, but superseded generations do not.
page = mount({...meta, image: '/2.png'});
page.run('draftRecovery.write(props.value, {workspace:{boxes:{}}})');
page = mount({...meta, generation: 'g2'});
assert.equal(page.run('draftRecovery.read(props.value)'), null);
assert.ok([...storage.values()][0].includes('/2.png'));
page = mount({...meta, image: null, discardImage: '/1.png'});
assert.ok(![...storage.values()][0].includes('/1.png'));
assert.ok([...storage.values()][0].includes('/2.png'));

// Restart, corrupt data, and unavailable storage have explicit recovery behavior.
page = mount({...meta, application: 'new-app'});
assert.equal(page.run('draftRecovery.read(props.value)'), null);
assert.match(page.status.textContent, /earlier application/);
storage.set('vietnamica-drafts-v1', '{broken');
page = mount();
assert.match(page.status.textContent, /unavailable/);
page = mount(meta, true);
assert.match(page.status.textContent, /unavailable/);
// Imports replace stale generations, but must not replace newer edits on reload.
storage.clear();
const importedMeta={...meta, generation:'imported',step:2,defaultSection:'[0]'};
const importedRecord={metadata:importedMeta,section:'[0]',typing:{'[0]':'imported text'}};
const imported={...importedMeta,progressImport:{id:'import-1',records:{
  [JSON.stringify([meta.application,meta.tab,meta.image,2])]:importedRecord}}};
page=mount(imported);
assert.equal(page.run('draftRecovery.read(props.value).typing["[0]"]'),'imported text');
page.run('draftRecovery.write(props.value,{typing:{"[0]":"edited after import"}})');
page=mount(imported);
assert.equal(page.run('draftRecovery.read(props.value).typing["[0]"]'),'edited after import');
page.context.window.vietnamicaWorkspace={active:()=>true,snapshot:()=>({boxes:{latest:{bbox:[1,2,3,4]}}})};
page.nodes.set('#content-value input, #content-value textarea',{value:'still typing'});
const exported=page.run('draftRecovery.exportProgress()');
const latest=Object.values(exported.drafts)[0];
assert.equal(latest.typing['[0]'],'still typing');
assert.deepEqual(Array.from(latest.workspace.boxes.latest.bbox),[1,2,3,4]);
page=mount({...imported,progressImport:{id:'import-2',records:imported.progressImport.records}});
assert.equal(page.run('draftRecovery.read(props.value).typing["[0]"]'),'imported text');
console.log('PASS: portable import/export, post-import reload, reload, unfinished labels/content, generations, per-image drafts and storage failures');
