let pending = false;
const send = (action, payload={}) => {
  if (pending) return;
  pending = true;
  element.style.opacity = '.65';
  trigger('action', {action, payload: {...payload, revision: props.value.revision, image: props.value.image}});
};
watch('value', () => { pending = false; element.style.opacity = '1'; });
let moving = null, dragged = null;
const point = (e, svg) => {
  const p = svg.createSVGPoint(); p.x=e.clientX; p.y=e.clientY;
  return p.matrixTransform(svg.getScreenCTM().inverse());
};
element.addEventListener('pointerdown', e => {
  if (pending) return;
  const svg=e.target.closest('svg'); if(!svg) return;
  const group=e.target.closest('[data-box-id]');
  const mode=props.value.step;
  if(group && ![3,8].includes(mode)) {send('select',{id:group.dataset.boxId}); return;}
  if(![3,8].includes(mode)) return;
  const p=point(e,svg), id=group?.dataset.boxId;
  const box=id ? [...props.value.boxes[id].bbox] : [p.x,p.y,p.x,p.y];
  moving={svg,id,box,p,corner:e.target.dataset.corner, rect:group?.querySelector('rect')};
  if(!id){ moving.rect=document.createElementNS('http://www.w3.org/2000/svg','rect'); moving.rect.setAttribute('fill','none'); moving.rect.setAttribute('stroke','#f59e0b'); moving.rect.setAttribute('stroke-width','3'); svg.appendChild(moving.rect); }
  svg.setPointerCapture(e.pointerId); e.preventDefault();
});
element.addEventListener('pointermove', e => {
  if(!moving) return;
  const m=moving, p=point(e,m.svg), dx=p.x-m.p.x, dy=p.y-m.p.y;
  const w=props.value.width,h=props.value.height;
  let b=[...m.box];
  if(!m.id) b=[Math.min(m.p.x,p.x),Math.min(m.p.y,p.y),Math.max(m.p.x,p.x),Math.max(m.p.y,p.y)];
  else if(m.corner){const n=Number(m.corner); if(n===0||n===3)b[0]+=dx;else b[2]+=dx; if(n===0||n===1)b[1]+=dy;else b[3]+=dy;}
  else {const tx=Math.max(-b[0],Math.min(dx,w-b[2])),ty=Math.max(-b[1],Math.min(dy,h-b[3]));b=[b[0]+tx,b[1]+ty,b[2]+tx,b[3]+ty];}
  b=b.map((v,i)=>Math.max(0,Math.min(v,i%2?h:w)));
  m.result=b;
  m.rect.setAttribute('x',b[0]);m.rect.setAttribute('y',b[1]);m.rect.setAttribute('width',Math.max(0,b[2]-b[0]));m.rect.setAttribute('height',Math.max(0,b[3]-b[1]));
});
element.addEventListener('pointerup', () => {
  if(!moving)return;const m=moving;moving=null;
  if(m.result) send(props.value.step===8?'crop':m.id?'update':'add',{id:m.id,bbox:m.result});
  else if(m.id && props.value.step!==8)send('select',{id:m.id});
});
element.addEventListener('pointercancel',()=>{moving=null;send('select',{id:props.value.selected});});
element.addEventListener('dragstart',e=>{const card=e.target.closest('[data-card]');if(!card||pending)return;dragged=card; e.dataTransfer.setData('text/plain',card.dataset.boxId);});
element.addEventListener('dragover',e=>{if(e.target.closest('[data-card]'))e.preventDefault();});
element.addEventListener('drop',e=>{e.preventDefault();const target=e.target.closest('[data-card]');if(!target||!dragged)return;target.parentNode.insertBefore(dragged,target);send('reorder',{order:[...element.querySelectorAll('[data-card]')].map(c=>Number(c.dataset.boxId))});dragged=null;});

element.addEventListener('click', e => {
  const card=e.target.closest('[data-card]');
  if(card && !pending && props.value.selected!==card.dataset.boxId) send('select',{id:card.dataset.boxId});
});
