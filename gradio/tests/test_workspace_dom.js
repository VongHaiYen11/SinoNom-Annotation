// Execute the complete HTML-component script at its DOM/event boundary. This
// fixture deliberately replaces template children on each server response.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const script=fs.readFileSync(require('node:path').join(__dirname,'../ui/assets/workspace.js'),'utf8');
class Node {
  constructor(){this.listeners={};this.style={};this.dataset={};this.scrollTop=0;this.scrollLeft=0;this.hidden=true;this.classList={add:()=>{}};this.isConnected=true;}
  addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}
  getBoundingClientRect(){return {left:0,top:0,width:280,height:400,bottom:400};}
  focus(){} click(){} close(){this.open=false;} showModal(){this.open=true;}
  querySelector(){return new Node();}
  setAttribute(key,value){this[key]=value;} remove(){this.removed=true;}
}
class Host extends Node {
  constructor(){super();this.nodes={};}
  set innerHTML(value){
    this.html=value;this.nodes={};
    for(const key of ['.u-viewport','.u-content-list','.u-reference','.u-message','.u-menu','dialog','.u-canvas']) this.nodes[key]=new Node();
    this.nodes['.u-canvas'].createSVGPoint=()=>({x:0,y:0,matrixTransform(){return {x:this.x,y:this.y};}});
    this.nodes['.u-canvas'].getScreenCTM=()=>({inverse:()=>({})});
    this.nodes['.u-canvas'].appendChild=node=>{this.nodes['.u-geometry-preview']=node;};
  }
  querySelector(selector){const node=this.nodes[selector];return node?.removed?null:node || null;}
  querySelectorAll(selector){
    if(selector==='[data-char]') return [...(this.html || '').matchAll(/data-char="([^"]+)"/g)].map(match=>{
      const node=new Node();node.dataset.char=match[1];return node;
    });
    return [];
  }
  hasPointerCapture(){return false;} setPointerCapture(){} releasePointerCapture(){}
}
const host=new Host(), windowNode=new Node(), events=[], timers=new Map(), writes=[], downloads=[];
const model={entries:[{char_id:'c1',value:'甲',source_index:1,type:'original',excluded:false},
  {char_id:'c2',value:'乙',source_index:2,type:'original',excluded:false}],boxes:{},confirmed:{},
  preferences:{reference_open:true,reference_width:280,reference_scroll:0,zoom:100,visibility:'dim'},
  selected_box:'b1',selected_char:'c1',selected_boxes:['b1'],undo:[],redo:[],version:0};
for(let i=1;i<=2;i++) model.boxes[`b${i}`]={order:i,bbox:[i*10,0,i*10+8,8],status:'intact',damage_level:null,
  unknown:false,unavailable_font:false,expert_prediction:false,suspicious:false};
const props={value:{step:3,model,image:'1.png',image_url:'/image.png',size:[200,100],
  recovery:{application:'app',tab:'tab',generation:'g'},issues:[],report:'',can_detect:false}};
let watchValue, timerId=0, uuid=0;
windowNode.innerWidth=1440;windowNode.innerHeight=900;windowNode.confirm=()=>true;
windowNode.vietnamicaDraftRecovery={read:()=>null,write:(meta,value)=>writes.push(structuredClone(value))};
const context={element:host,props,window:windowNode,structuredClone,AbortController,Blob,
  URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:issues';},revokeObjectURL:()=>{}},
  crypto:{randomUUID:()=>`new-${++uuid}`},
  ResizeObserver:class{observe(){}disconnect(){}},
  setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
  document:{createElementNS:()=>new Node(),createElement:()=>new Node(),body:{appendChild:()=>{}}},
  trigger:(name,data)=>events.push({name,data:structuredClone(data)}),watch:(key,fn)=>{watchValue=fn;}};
vm.createContext(context);vm.runInContext(script,context);
const snapshot=()=>windowNode.vietnamicaWorkspace.snapshot();
const click=action=>{
  const button={dataset:{action}};
  const target={closest:selector=>selector==='[data-action]'?button:null};
  host.listeners.click[0]({target});
};
const flush=()=>{const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());};
const respond=(event,extra={})=>{
  props.value={...props.value,model:structuredClone(event.data.model),...extra};
  host.innerHTML='<div>Replaced by Gradio</div>';
  watchValue();
};
assert.match(host.html,/aria-label="Hide Reference"/);
assert.match(host.html,/Add MISS|Reference Content/);
click('toggle-reference');
assert.equal(snapshot().preferences.reference_open,false);
assert.match(host.html,/aria-label="Show Reference"/);
assert.match(host.html,/u-reference-closed/);
flush();assert.equal(events.at(-1).data.action,'checkpoint');
respond(events.at(-1));
click('toggle-reference');
assert.equal(snapshot().preferences.reference_open,true,'delegated listeners must survive template replacement');

// A confirmed box keeps its identity while exclusion flags the relationship.
click('confirm');assert.equal(snapshot().confirmed.b1,'c1');
const card={dataset:{char:'c1'}};
host.listeners.contextmenu[0]({target:{closest:()=>card},clientX:20,clientY:50,preventDefault(){}});
assert.match(host.querySelector('.u-menu').innerHTML,/Add MISS to Left/);
click('exclude');
assert.equal(snapshot().entries[0].excluded,true);
assert.equal(snapshot().confirmed.b1,'c1');
assert.match(host.html,/Conflict/);
assert.equal(snapshot().boxes.b1.order,1);
flush();respond(events.at(-1));
// Re-inclusion and insertion keep the original source IDs intact.
host.listeners.contextmenu[0]({target:{closest:()=>card},clientX:20,clientY:50,preventDefault(){}});
assert.match(host.querySelector('.u-menu').innerHTML,/Include in Alignment/);
click('exclude');click('miss-right');
assert.equal(snapshot().entries[1].value,'MISS');
assert.equal(snapshot().entries[2].char_id,'c2');
click('undo');assert.equal(snapshot().entries.length,2);
click('redo');assert.equal(snapshot().entries[1].value,'MISS');

// Continue can be queued behind an in-flight checkpoint and sends the latest model.
flush();const inFlight=events.at(-1);
click('continue');const count=events.length;
respond(inFlight);
assert.equal(events.length,count+1);
assert.equal(events.at(-1).data.action,'continue');
const issue={box_id:'b1',char_id:'c1',reading_order:1,bbox:[10,0,18,8],reason:'Resolve the alignment.'};
respond(events.at(-1),{issues:[issue],report:'Annotation issues — 1.png\nResolve the alignment.'});
assert.equal(host.querySelector('dialog').open,true);
assert.match(host.html,/Cannot Continue/);
assert.match(host.html,/Download Issues \(.txt\)/);
click('download-issues');
assert.equal(downloads[0].size,Buffer.byteLength(props.value.report,'utf8'));
assert.equal(downloads[0].type,'text/plain;charset=utf-8');
click('close-issues');assert.equal(host.querySelector('dialog').open,false);

// Navigation selects the matching box and preserves zoom.
const input={dataset:{jump:'character'},value:'3',closest:()=>true};
windowNode.listeners.keydown[0]({key:'Enter',target:input,preventDefault(){}});
assert.equal(snapshot().selected_char,'c2');
assert.equal(snapshot().preferences.zoom,100);

// Geometry is stable in the snapshot until the pointer operation is completed.
flush();respond(events.at(-1),{issues:[],report:''});
const canvasTarget={closest:selector=>selector==='.u-canvas'?host.querySelector('.u-canvas'):null};
host.listeners.pointerdown[0]({target:canvasTarget,button:0,altKey:true,clientX:50,clientY:30,pointerId:1,preventDefault(){}});
host.listeners.pointermove[0]({clientX:70,clientY:50,pointerId:1});
assert.equal(Object.keys(snapshot().boxes).length,2);
host.listeners.pointerup[0]({pointerId:1});
assert.equal(Object.keys(snapshot().boxes).length,3);
assert.equal(events.at(-1).data.action,'insert');
const newId=events.at(-1).data.box_id;
assert.deepEqual(Array.from(snapshot().boxes[newId].bbox),[50,30,70,50]);
assert.equal(snapshot().confirmed.b1,'c1');
assert.ok(writes.length>0);
console.log('PASS: full workspace DOM lifecycle, icon sidebar, content menus, confirmation/conflicts, queued Continue, warning and pointer drawing');
