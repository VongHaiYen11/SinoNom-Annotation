// Crop editing and read-only Review. All listeners are scoped and disposable.
const host=element;
const controller=new AbortController();
window.vietnamicaViewerController?.abort();
window.vietnamicaViewerController=controller;
let value=props.value, context='', crop=null, zoom=100, gesture=null, space=false, draft=null;
const active=()=>host.isConnected && [6,7].includes(value?.step);
const editable=()=>active() && value.step===6;
const root=host.closest('.gradio-container') || document;
const viewport=()=>host.querySelector('.image-viewport');
const svg=()=>host.querySelector('.annotation-canvas');
const record=()=>window.vietnamicaDraftRecovery?.read(value?.recovery)?.viewer;
const persist=()=>{
  if(editable()) window.vietnamicaDraftRecovery?.write(value.recovery,{viewer:{crop,zoom,draft}});
};
const setCoordinates=()=>{
  const input=root.querySelector('#crop-coordinates textarea, #crop-coordinates input');
  if(!input) return;
  const prototype=input.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,draft ?? JSON.stringify(crop));
  input.dispatchEvent(new Event('input',{bubbles:true}));
};
const draw=()=>{
  const canvas=svg();if(!canvas)return;
  canvas.style.width=`${zoom}%`;canvas.style.maxWidth='none';
  host.querySelector('.zoom-label').textContent=`${zoom}%`;
  const group=host.querySelector('[data-box-id="crop"]');
  if(!group || !crop)return;
  const [x1,y1,x2,y2]=crop,rect=group.querySelector('rect');
  for(const [key,val] of Object.entries({x:x1,y:y1,width:x2-x1,height:y2-y1}))rect.setAttribute(key,val);
  const corners=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]];
  group.querySelectorAll('[data-corner]').forEach(handle=>{
    const point=corners[Number(handle.dataset.corner)];handle.setAttribute('cx',point[0]);handle.setAttribute('cy',point[1]);
  });
};
const valid=box=>Array.isArray(box) && box.length===4 && box.every(Number.isFinite)
  && box[0]>=0 && box[1]>=0 && box[2]>box[0] && box[3]>box[1] && box[2]<=value.width && box[3]<=value.height;
const point=event=>{
  const p=svg().createSVGPoint();p.x=event.clientX;p.y=event.clientY;
  const q=p.matrixTransform(svg().getScreenCTM().inverse());
  return [Math.max(0,Math.min(value.width,q.x)),Math.max(0,Math.min(value.height,q.y))];
};
const load=()=>{
  value=props.value;if(!active())return;
  const next=JSON.stringify([value.image,value.step,value.recovery?.generation]);
  if(context!==next){
    context=next;const saved=editable()?record():null;
    crop=saved && valid(saved.crop)?[...saved.crop]:value.crop;
    zoom=Math.max(25,Math.min(500,Number(saved?.zoom)||100));draft=saved?.draft ?? null;
  }
  gesture=null;draw();if(editable())setCoordinates();
};
const zoomTo=(next,at)=>{
  const view=viewport();if(!view)return;
  const rect=view.getBoundingClientRect();
  const x=at?at.clientX-rect.left:rect.width/2,y=at?at.clientY-rect.top:rect.height/2;
  const ratio=next/zoom, left=(view.scrollLeft+x)*ratio-x,top=(view.scrollTop+y)*ratio-y;
  zoom=next;draw();view.scrollLeft=left;view.scrollTop=top;persist();
};
host.addEventListener('click',event=>{
  if(!active())return;const button=event.target.closest('[data-zoom]');if(!button)return;
  zoomTo(Math.max(25,Math.min(500,zoom+(button.dataset.zoom==='in'?15:-15))));
},{signal:controller.signal});
host.addEventListener('wheel',event=>{
  if(!active() || !event.ctrlKey || !event.target.closest('.image-viewport'))return;
  event.preventDefault();zoomTo(Math.max(25,Math.min(500,zoom+(event.deltaY<0?15:-15))),event);
},{passive:false,signal:controller.signal});
host.addEventListener('pointerdown',event=>{
  if(!active() || !event.target.closest('.annotation-canvas') || ![0,1].includes(event.button))return;
  if(space || event.button===1){
    gesture={kind:'pan',client:[event.clientX,event.clientY],left:viewport().scrollLeft,top:viewport().scrollTop};
  }else if(editable()){
    const handle=event.target.closest('[data-corner]'),group=event.target.closest('[data-box-id="crop"]');
    gesture={kind:handle?'resize':group?'move':'new',corner:Number(handle?.dataset.corner),start:point(event),box:[...crop]};
  }else return;
  event.preventDefault();host.setPointerCapture(event.pointerId);
},{signal:controller.signal});
host.addEventListener('pointermove',event=>{
  if(!gesture)return;
  if(gesture.kind==='pan'){
    viewport().scrollLeft=gesture.left+gesture.client[0]-event.clientX;
    viewport().scrollTop=gesture.top+gesture.client[1]-event.clientY;return;
  }
  const p=point(event),old=gesture.box;let box;
  if(gesture.kind==='new')box=[Math.min(p[0],gesture.start[0]),Math.min(p[1],gesture.start[1]),Math.max(p[0],gesture.start[0]),Math.max(p[1],gesture.start[1])];
  else if(gesture.kind==='move'){
    const dx=Math.max(-old[0],Math.min(value.width-old[2],p[0]-gesture.start[0]));
    const dy=Math.max(-old[1],Math.min(value.height-old[3],p[1]-gesture.start[1]));
    box=[old[0]+dx,old[1]+dy,old[2]+dx,old[3]+dy];
  }else{
    box=[...old];box[[0,3].includes(gesture.corner)?0:2]=p[0];box[gesture.corner<2?1:3]=p[1];
  }
  if(valid(box)){crop=box;draw();}
},{signal:controller.signal});
host.addEventListener('pointerup',event=>{
  if(!gesture)return;const kind=gesture.kind;gesture=null;
  if(host.hasPointerCapture(event.pointerId))host.releasePointerCapture(event.pointerId);
  if(kind!=='pan'){draft=null;setCoordinates();persist();}
},{signal:controller.signal});
host.addEventListener('pointercancel',()=>{
  if(gesture?.box){crop=gesture.box;draw();}gesture=null;
},{signal:controller.signal});
root.addEventListener('input',event=>{
  if(!editable() || !event.isTrusted || !event.target.closest('#crop-coordinates'))return;
  draft=event.target.value;
  try{const box=JSON.parse(draft);if(valid(box)){crop=box;draw();}}catch(_){}
  persist();
},{signal:controller.signal});
window.addEventListener('keydown',event=>{
  if(!active() || event.target.closest('input,textarea,select,[contenteditable=true]'))return;
  if(event.code==='Space'){space=true;event.preventDefault();}
},{signal:controller.signal});
window.addEventListener('keyup',event=>{if(event.code==='Space')space=false;},{signal:controller.signal});
window.addEventListener('pagehide',persist,{signal:controller.signal});
window.vietnamicaViewer={active:editable,snapshot:()=>{
  if(draft!==null){try{return {crop:JSON.parse(draft)};}catch(_){return {crop:draft};}}
  return {crop:[...crop]};
}};
watch('value',load);load();
