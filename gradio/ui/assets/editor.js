// Only viewport zoom and in-progress gestures are local; Python owns all data.
let pending = false, moving = null, dragged = null;
let zoom = 100, image = props.value.image;
const applyZoom = () => {
  const svg = element.querySelector('.annotation-canvas');
  const viewport = element.querySelector('.image-viewport');
  if (!svg || !viewport) return;
  const fit = Math.min((viewport.clientWidth - 40) / props.value.width,
                       (viewport.clientHeight - 40) / props.value.height);
  svg.style.width = `${props.value.width * fit * zoom / 100}px`;
  svg.style.height = `${props.value.height * fit * zoom / 100}px`;
  svg.style.maxWidth = 'none';
  const label = element.querySelector('.zoom-label');
  if (label) label.textContent = `${zoom}%`;
};
const send = (action, payload={}) => {
  if (pending) return;
  pending = true;
  element.style.opacity = '.65';
  element.setAttribute('aria-busy', 'true');
  trigger('action', {action, payload: {...payload, revision: props.value.revision, image: props.value.image}});
};
const showLocalSelection = (group, toggle=false) => {
  if (!group) return;
  element.querySelectorAll('[data-region-uid],[data-box-id]').forEach(candidate => {
    const active = toggle && candidate === group ? !candidate.classList.contains('selected-region') : candidate === group;
    candidate.classList.toggle('selected-region', active);
    const rect = candidate.querySelector('rect');
    if (rect) {
      rect.setAttribute('fill-opacity', active ? '.16' : '.04');
      rect.setAttribute('stroke-width', active ? '2.5' : '1.5');
    }
  });
};
watch('value', () => {
  pending = false; moving = null; dragged = null;
  element.style.opacity = '1'; element.setAttribute('aria-busy', 'false');
  if (image !== props.value.image) { zoom = 100; image = props.value.image; }
  requestAnimationFrame(applyZoom);
});
const resizeObserver = new ResizeObserver(() => requestAnimationFrame(applyZoom));
resizeObserver.observe(element);
const point = (e, svg) => {
  const p = svg.createSVGPoint(); p.x=e.clientX; p.y=e.clientY;
  const at = p.matrixTransform(svg.getScreenCTM().inverse());
  return {x: Math.max(0, Math.min(at.x, props.value.width)),
          y: Math.max(0, Math.min(at.y, props.value.height))};
};
const drawPreview = (m, b) => {
  m.rect.setAttribute('x',b[0]); m.rect.setAttribute('y',b[1]);
  m.rect.setAttribute('width',Math.max(0,b[2]-b[0])); m.rect.setAttribute('height',Math.max(0,b[3]-b[1]));
  const corners = [[b[0],b[1]], [b[2],b[1]], [b[2],b[3]], [b[0],b[3]]];
  m.group?.querySelectorAll('[data-corner]').forEach(handle => {
    const [x,y] = corners[Number(handle.dataset.corner)];
    handle.setAttribute('cx', x); handle.setAttribute('cy', y);
  });
};
element.addEventListener('pointerdown', e => {
  if (pending || e.button !== 0) return;
  const svg=e.target.closest('.annotation-canvas'); if(!svg) return;
  const group=e.target.closest('[data-region-uid],[data-box-id]');
  const mode=props.value.step;
  const regionUid=group?.dataset.regionUid, id=regionUid || group?.dataset.boxId;
  const toggle = mode === 3 && (e.shiftKey || e.metaKey || e.ctrlKey);
  if (group && mode !== 6) showLocalSelection(group, toggle);
  if (group && mode === 3 && (toggle || id !== props.value.selected)) {
    send('select', {...(regionUid?{uid:regionUid}:{id}), ...(toggle?{toggle:true}:{})});
    return;
  }
  if(group && ![3,6].includes(mode)) {
    send('select',regionUid?{uid:regionUid}:{id}); return;
  }
  if(![3,6].includes(mode)) return;
  const p=point(e,svg);
  const box=id ? [...props.value.boxes[id].bbox] : [p.x,p.y,p.x,p.y];
  moving={svg,id,regionUid,group,box,p,corner:e.target.dataset.corner,rect:group?.querySelector('rect')};
  if(!id){
    moving.rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
    moving.rect.setAttribute('fill','#ff7a1a22'); moving.rect.setAttribute('stroke','#ff7a1a');
    moving.rect.setAttribute('stroke-width','2'); moving.rect.setAttribute('vector-effect','non-scaling-stroke');
    svg.appendChild(moving.rect);
  }
  svg.setPointerCapture(e.pointerId); e.preventDefault();
});
element.addEventListener('pointermove', e => {
  if(!moving) return;
  const m=moving, p=point(e,m.svg), dx=p.x-m.p.x, dy=p.y-m.p.y;
  const w=props.value.width,h=props.value.height;
  let b=[...m.box];
  if(!m.id) b=[Math.min(m.p.x,p.x),Math.min(m.p.y,p.y),Math.max(m.p.x,p.x),Math.max(m.p.y,p.y)];
  else if(m.corner !== undefined){const n=Number(m.corner); if(n===0||n===3)b[0]+=dx;else b[2]+=dx; if(n===0||n===1)b[1]+=dy;else b[3]+=dy;}
  else {const tx=Math.max(-b[0],Math.min(dx,w-b[2])),ty=Math.max(-b[1],Math.min(dy,h-b[3]));b=[b[0]+tx,b[1]+ty,b[2]+tx,b[3]+ty];}
  b=b.map((v,i)=>Math.max(0,Math.min(v,i%2?h:w)));
  if(props.value.step===6){
    const limit=props.value.max_crop_side;
    if(!m.id){
      if(b[2]-b[0]>limit) {if(p.x<m.p.x)b[0]=b[2]-limit;else b[2]=b[0]+limit;}
      if(b[3]-b[1]>limit) {if(p.y<m.p.y)b[1]=b[3]-limit;else b[3]=b[1]+limit;}
    } else if(m.corner!==undefined){
      const n=Number(m.corner);
      if(b[2]-b[0]>limit) {if(n===0||n===3)b[0]=b[2]-limit;else b[2]=b[0]+limit;}
      if(b[3]-b[1]>limit) {if(n===0||n===1)b[1]=b[3]-limit;else b[3]=b[1]+limit;}
    }
  }
  m.result=b; drawPreview(m,b);
});
element.addEventListener('pointerup', () => {
  if(!moving)return; const m=moving; moving=null;
  if(m.result) send(props.value.step===6?'crop':m.id?'update':'add',
                    {...(m.regionUid?{uid:m.regionUid}:{id:m.id}),bbox:m.result});
  else if(m.id && props.value.step!==6) send('select',m.regionUid?{uid:m.regionUid}:{id:m.id});
  else if(!m.id) m.rect.remove();
});
element.addEventListener('pointercancel',()=>{
  if (!moving) return;
  if (moving.id) drawPreview(moving,moving.box); else moving.rect.remove();
  moving=null;
});
const clearDrag = () => {
  element.querySelectorAll('.dragging,.drop-target').forEach(card=>card.classList.remove('dragging','drop-target'));
  dragged=null;
};
element.addEventListener('dragstart',e=>{
  const card=e.target.closest('[data-card]');
  if(!card || pending || props.value.step!==5) {e.preventDefault();return;}
  dragged=card; card.classList.add('dragging'); e.dataTransfer.effectAllowed='move';
  e.dataTransfer.setData('text/plain',card.dataset.boxId);
});
element.addEventListener('dragover',e=>{
  const target=e.target.closest('[data-card]');
  if (!target || !dragged || pending) return;
  e.preventDefault(); e.dataTransfer.dropEffect='move';
  element.querySelectorAll('.drop-target').forEach(card=>card.classList.remove('drop-target'));
  target.classList.add('drop-target');
});
element.addEventListener('drop',e=>{
  const target=e.target.closest('[data-card]');
  if(!target || !dragged || pending || props.value.step!==5) return;
  e.preventDefault();
  if (target === dragged) {clearDrag(); return;}
  const order=[...element.querySelectorAll('[data-card]')].map(c=>Number(c.dataset.boxId));
  const from=order.indexOf(Number(dragged.dataset.boxId)), to=order.indexOf(Number(target.dataset.boxId));
  const [id]=order.splice(from,1); order.splice(to,0,id);
  clearDrag();
  // Do not reorder the DOM until the server accepts this ID sequence.
  send('reorder',{order});
});
element.addEventListener('dragend',clearDrag);
element.addEventListener('click', e => {
  const control=e.target.closest('[data-zoom]');
  if (control) {
    zoom=control.dataset.zoom==='fit'?100:Math.max(50,Math.min(300,zoom+(control.dataset.zoom==='in'?25:-25)));
    applyZoom(); return;
  }
  const card=e.target.closest('[data-card]');
  if(card && !pending && props.value.selected!==card.dataset.boxId) send('select',{id:card.dataset.boxId});
});
