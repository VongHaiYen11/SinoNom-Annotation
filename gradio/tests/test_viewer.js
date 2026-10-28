// Run the focused viewer with replaceable template children, without a browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const script=fs.readFileSync(require('node:path').join(__dirname,'../ui/assets/viewer.js'),'utf8');
class Node {
  constructor(){this.listeners={};this.style={};this.dataset={};this.scrollLeft=0;this.scrollTop=0;this.attrs={};}
  addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}
  setAttribute(key,value){this.attrs[key]=value;}
  getBoundingClientRect(){return {left:0,top:0,width:200,height:100};}
  dispatchEvent(){}
}
class Input extends Node {get value(){return this._value;}set value(value){this._value=value;}}
const input=new Input(),root=new Node(),host=new Node(),win=new Node();
root.querySelector=()=>input;
host.isConnected=true;host.closest=()=>root;host.setPointerCapture=()=>{};host.hasPointerCapture=()=>false;
const view=new Node(),canvas=new Node(),rect=new Node(),label=new Node(),cropGroup=new Node();
const handles=[0,1,2,3].map(index=>Object.assign(new Node(),{dataset:{corner:String(index)}}));
canvas.createSVGPoint=()=>({x:0,y:0,matrixTransform(){return {x:this.x,y:this.y};}});
canvas.getScreenCTM=()=>({inverse:()=>({})});
cropGroup.querySelector=()=>rect;cropGroup.querySelectorAll=()=>handles;
host.querySelector=selector=>({'.image-viewport':view,'.annotation-canvas':canvas,'.zoom-label':label,
  '[data-box-id="crop"]':cropGroup}[selector] || null);
let saved=null;const writes=[];
win.vietnamicaDraftRecovery={read:()=>saved,write:(meta,record)=>{saved=record;writes.push(structuredClone(record));}};
const props={value:{step:6,image:'1.png',width:200,height:100,crop:[10,10,60,60],recovery:{generation:'g'}}};
let watcher;
vm.runInNewContext(script,{element:host,props,window:win,document:root,AbortController,Event,
  HTMLInputElement:Input,HTMLTextAreaElement:Input,watch:(name,fn)=>{watcher=fn;}});
const api=win.vietnamicaViewer;
assert.equal(api.active(),true);assert.deepEqual(Array.from(api.snapshot().crop),[10,10,60,60]);
const target={closest:selector=>selector==='.annotation-canvas'?canvas:
  selector==='[data-box-id="crop"]'?cropGroup:null};
const down=(x,y)=>host.listeners.pointerdown[0]({target,clientX:x,clientY:y,button:0,pointerId:1,preventDefault(){}});
down(20,20);host.listeners.pointermove[0]({clientX:30,clientY:25});
assert.deepEqual(Array.from(api.snapshot().crop),[20,15,70,65]);
assert.equal(writes.length,0,'pointer previews must not checkpoint incomplete operations');
host.listeners.pointerup[0]({pointerId:1});
assert.equal(writes.length,1);assert.equal(input.value,'[20,15,70,65]');
// Cancel restores the starting geometry rather than keeping a preview.
down(30,20);host.listeners.pointermove[0]({clientX:40,clientY:30});
host.listeners.pointercancel[0]();
assert.deepEqual(Array.from(api.snapshot().crop),[20,15,70,65]);
// Coordinates remain draft input until valid; invalid input is surfaced to Python.
input._value='not JSON';input.closest=()=>true;
root.listeners.input[0]({isTrusted:true,target:input});
assert.equal(api.snapshot().crop,'not JSON');
input._value='[5,6,80,90]';root.listeners.input[0]({isTrusted:true,target:input});
assert.deepEqual(Array.from(api.snapshot().crop),[5,6,80,90]);
watcher();assert.equal(input.value,'[5,6,80,90]');
// Resizing a corner clamps to the image and updates only the crop frame.
const cornerTarget={closest:selector=>selector==='.annotation-canvas'?canvas:
  selector==='[data-corner]'?handles[0]:selector==='[data-box-id="crop"]'?cropGroup:null};
host.listeners.pointerdown[0]({target:cornerTarget,clientX:5,clientY:6,button:0,pointerId:2,preventDefault(){}});
host.listeners.pointermove[0]({clientX:-10,clientY:-10});
host.listeners.pointerup[0]({pointerId:2});
assert.deepEqual(Array.from(api.snapshot().crop),[0,0,80,90]);
assert.equal(handles[0].attrs.cx,0);assert.equal(handles[0].attrs.cy,0);
// Review is read-only and does not capture Delete/Enter or content/status changes.
props.value={...props.value,step:7,recovery:{generation:'review'}};watcher();
assert.equal(api.active(),false);
const before=rect.attrs.x;
down(10,10);host.listeners.pointermove[0]({clientX:50,clientY:50});
assert.equal(rect.attrs.x,before);
const writesBefore=writes.length;
input._value='[1,2,3,4]';root.listeners.input[0]({isTrusted:true,target:input});
assert.equal(writes.length,writesBefore);
assert.equal(win.listeners.keydown.length,1);
// Switching to the annotation workspace disables all viewer interactions.
props.value={step:3,image:'1.png'};watcher();assert.equal(api.active(),false);
console.log('PASS: Crop drag/cancel, raw coordinate recovery, Review read-only, and scoped viewer lifecycle');
