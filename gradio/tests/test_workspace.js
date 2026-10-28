const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../ui/assets/workspace.js'),'utf8');
const context={structuredClone};vm.createContext(context);
vm.runInContext(script.slice(0,script.indexOf('// Browser host.'))+'\nthis.core=workspaceCore;',context);
const core=context.core;
const entry=(id,value,index)=>({char_id:id,value,source_index:index,type:'original',excluded:false});
const box=(order)=>({order,bbox:[1,2,10,20],status:'intact',damage_level:null,
  unknown:false,unavailable_font:false,expert_prediction:false,suspicious:false});
const make=()=>({entries:[entry('c1','甲',1),entry('c2','甲',2),entry('c3','乙',3)],
  boxes:{a:box(1),b:box(2),c:box(3)},confirmed:{},undo:[],redo:[],selected_boxes:[],
  selected_box:'a',selected_char:'c1',version:0});
let model=make();
core.mutate(model,m=>core.insertMiss(m,'c2','left','miss1'));
core.mutate(model,m=>core.insertMiss(m,'c2','left','miss2'));
assert.equal(core.active(model).map(e=>e.value).join(','),'甲,MISS,MISS,甲,乙');
assert.equal(core.suggested(model,'b').char_id,'miss1');
assert.equal(model.entries.find(e=>e.char_id==='c2').source_index,2);
core.mutate(model,m=>{m.entries.find(e=>e.char_id==='c1').excluded=true;});
assert.equal(core.active(model).map(e=>e.char_id).join(','),'miss1,miss2,c2,c3');
core.history(model,'undo');
assert.equal(core.active(model)[0].char_id,'c1');
core.history(model,'undo');
assert.equal(core.active(model).map(e=>e.char_id).join(','),'c1,miss1,c2,c3');
core.history(model,'redo');
assert.equal(core.active(model).map(e=>e.char_id).join(','),'c1,miss1,miss2,c2,c3');
core.mutate(model,m=>{m.entries.find(e=>e.char_id==='c2').excluded=true;});
assert.equal(model.redo.length,0);

// Moving 65 to 180 inserts, preserving attributes and stable confirmed identity.
model=make();model.boxes={};
for(let i=1;i<=200;i++) model.boxes[`b${i}`]=box(i);
model.boxes.b65.status='damaged';model.boxes.b65.damage_level=2;model.boxes.b65.suspicious=true;
model.confirmed.b65='c1';
core.reorder(model,'b65',180);
assert.equal(model.boxes.b65.order,180);
assert.equal(model.boxes.b66.order,65);
assert.equal(model.boxes.b180.order,179);
assert.equal(model.boxes.b181.order,181);
assert.equal(model.boxes.b65.suspicious,true);
assert.equal(model.boxes.b65.damage_level,2);
assert.equal(model.confirmed.b65,'c1');
assert.equal(new Set(Object.values(model.boxes).map(b=>b.order)).size,200);

model=make();core.confirm(model,'a');
assert.equal(core.relation(model,'a'),'Confirmed');
core.insertMiss(model,'c1','left','miss');
assert.equal(core.relation(model,'a'),'Conflict');
assert.equal(model.confirmed.a,'c1');
assert.equal(core.relation(model,'b'),'Conflict');
assert.throws(()=>core.confirm(model,'b'),/another box/);
model.entries.find(e=>e.char_id==='c1').excluded=true;
assert.equal(core.relation(model,'a'),'Conflict');
assert.equal(core.active(model)[0].char_id,'miss');

// Mandatory rules run only upon an explicit confirmation, never on suggestions.
model=make();model.entries[0].value='□';
assert.equal(core.suggested(model,'a').value,'□');
assert.equal(model.boxes.a.status,'intact');
assert.throws(()=>core.confirm(model,'a'),/damage level/);
assert.equal(model.boxes.a.status,'intact');
model.boxes.a.status='damaged';model.boxes.a.damage_level=3;
core.confirm(model,'a');assert.equal(model.boxes.a.unknown,true);
model=make();model.entries[0].value='@';core.confirm(model,'a');
assert.equal(model.boxes.a.unavailable_font,true);assert.equal(model.boxes.a.status,'intact');
model=make();model.entries[0]={char_id:'miss',value:'MISS',type:'missing',source_index:null,excluded:false};
Object.assign(model.boxes.a,{status:'damaged',damage_level:1,suspicious:true,expert_prediction:true});
assert.equal(core.suggested(model,'a').value,'MISS');assert.equal(model.boxes.a.suspicious,true);
core.confirm(model,'a');
assert.equal(model.boxes.a.suspicious,false);assert.equal(model.boxes.a.expert_prediction,false);
assert.equal(model.boxes.a.status,'damaged');assert.equal(model.boxes.a.damage_level,1);

// Deletion undo restores complete box and confirmation; no character is excluded.
model=make();core.confirm(model,'b');const original=structuredClone(model.boxes.b);
core.mutate(model,m=>{delete m.boxes.b;delete m.confirmed.b;});
assert.equal(model.entries.filter(e=>e.excluded).length,0);
core.history(model,'undo');assert.deepEqual(model.boxes.b,original);assert.equal(model.confirmed.b,'c2');
console.log('PASS: stable IDs, MISS/exclude, 65→180 insertion, conflicts, Unicode identities, special rules and undo/redo');
