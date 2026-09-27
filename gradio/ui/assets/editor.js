// Python owns persisted data. Browser-local state owns direct manipulation.
let pending = false, moving = null, dragged = null;
let image = props.value.image, localContext = '';
let localBoxes = {}, selectedIds = new Set(), activeBoxId = null;
let localReadingOrder = [];
const imageTransform = {zoom: 100, width: props.value.width, height: props.value.height};

const cloneBoxes = boxes => Object.fromEntries(Object.entries(boxes || {}).map(
  ([id, box]) => [id, {...box, bbox: [...box.bbox]}]
));
const groupFor = id => [...element.querySelectorAll('.annotation-canvas [data-box-id]')].find(
  group => group.dataset.boxId === String(id)
);
const root = element.closest('.gradio-container') || document;
const setInputValue = (selector, value) => {
  const input = root.querySelector(`${selector} input, ${selector} textarea`);
  if (!input) return;
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  if (setter) setter.call(input, String(value)); else input.value = String(value);
  input.dispatchEvent(new Event('input', {bubbles: true}));
  input.dispatchEvent(new Event('change', {bubbles: true}));
};
const syncExternalControls = () => {
  setInputValue('#selection-bridge', JSON.stringify({
    active: activeBoxId,
    selected: [...selectedIds],
    statuses: Object.fromEntries(Object.entries(localBoxes).map(
      ([id, box]) => [id, box.status]
    )),
    boxes: Object.fromEntries(Object.entries(localBoxes).map(
      ([id, box]) => [id, [...box.bbox]]
    )),
    crop: localBoxes.crop?.bbox || null,
    readingOrder: [...localReadingOrder],
  }));
  const active = activeBoxId && localBoxes[activeBoxId];
  if (!active) return;
  if (props.value.step === 3) {
    ['#bbox-x1','#bbox-y1','#bbox-x2','#bbox-y2'].forEach(
      (selector, index) => setInputValue(selector, active.bbox[index])
    );
  }
  if (props.value.step === 4) {
    const status = root.querySelector(`#status-radio input[value="${active.status}"]`);
    if (status && !status.checked) status.click();
  }
  if (props.value.step === 6 && localBoxes.crop) {
    setInputValue('#crop-coordinates', JSON.stringify(localBoxes.crop.bbox));
  }
};
const renderLocalStatus = (id, status) => {
  const box = localBoxes[id];
  const group = groupFor(id);
  if (!box || !group) return;
  box.status = status;
  const color = status === 'damaged' ? '#ef4444' : '#22c55e';
  const rect = group.querySelector('rect:not([data-image-resize-handle])');
  if (rect) {
    rect.setAttribute('fill', color);
    rect.setAttribute('stroke', color);
    if (status === 'damaged') rect.setAttribute('stroke-dasharray', '5 4');
    else rect.removeAttribute('stroke-dasharray');
  }
};
const renderSelection = (sync=true) => {
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
    const id = group.dataset.boxId;
    const selected = selectedIds.has(id);
    const active = id === activeBoxId;
    group.classList.toggle('selected-region', selected);
    group.classList.toggle('active-region', active);
    const rect = group.querySelector('rect:not([data-image-resize-handle])');
    if (rect) {
      rect.setAttribute('fill-opacity', selected ? '.16' : '.04');
      rect.setAttribute('stroke-width', active ? '2.5' : selected ? '2' : '1.5');
    }
  });
  element.querySelectorAll('[data-card]').forEach(card => {
    card.classList.toggle('active', card.dataset.boxId === activeBoxId);
    card.setAttribute('aria-pressed', String(card.dataset.boxId === activeBoxId));
  });
  if (sync) syncExternalControls();
};
const hydrateLocalState = () => {
  const context = `${props.value.image || ''}:${props.value.step}`;
  const preserveSelection = context === localContext;
  localBoxes = cloneBoxes(props.value.boxes);
  localReadingOrder = [...(props.value.readingOrder || [])].map(Number);
  imageTransform.width = props.value.width;
  imageTransform.height = props.value.height;
  if (preserveSelection) {
    selectedIds = new Set([...selectedIds].filter(id => localBoxes[id]));
    if (!localBoxes[activeBoxId]) activeBoxId = selectedIds.values().next().value || null;
  } else {
    selectedIds = new Set((props.value.selectedIds || []).map(String).filter(id => localBoxes[id]));
    activeBoxId = localBoxes[props.value.selected] ? String(props.value.selected) : selectedIds.values().next().value || null;
    localContext = context;
  }
  renderSelection();
};

const renderLocalAnnotations = () => {
  const labels=props.value.orderedAnnotations || [];
  localReadingOrder.forEach((boxId,index) => {
    const card=[...element.querySelectorAll('[data-card]')].find(
      item => item.dataset.boxId === String(boxId));
    if(!card)return;
    const label=labels[index] ?? '';
    const status=localBoxes[String(boxId)]?.status || 'intact';
    const text=card.querySelector('.tile-character');
    if(text)text.textContent=label;
    card.classList.toggle('missing',label==='MISS');
    card.setAttribute('aria-label',`Box ${boxId}: ${label}, ${status}`);
    card.title=`ID ${boxId} · ${status}`;
  });
};

const fitCanvas = (width=imageTransform.width, height=imageTransform.height) => {
  const svg = element.querySelector('.annotation-canvas');
  const viewport = element.querySelector('.image-viewport');
  if (!svg || !viewport) return;
  const fit = Math.min((viewport.clientWidth - 40) / width,
                       (viewport.clientHeight - 40) / height);
  svg.style.width = `${width * fit * imageTransform.zoom / 100}px`;
  svg.style.height = `${height * fit * imageTransform.zoom / 100}px`;
  svg.style.maxWidth = 'none';
  const label = element.querySelector('.zoom-label');
  if (label) label.textContent = `${imageTransform.zoom}%`;
};
const applyZoom = () => fitCanvas();
const send = (action, payload={}) => {
  if (pending) return;
  pending = true;
  element.setAttribute('aria-busy', 'true');
  trigger('action', {action, payload: {
    ...payload, revision: props.value.revision, image: props.value.image,
  }});
};
watch('value', () => {
  pending = false; moving = null; dragged = null;
  element.setAttribute('aria-busy', 'false');
  if (image !== props.value.image) {
    imageTransform.zoom = 100;
    image = props.value.image;
  }
  hydrateLocalState();
  requestAnimationFrame(applyZoom);
});
hydrateLocalState();
const resizeObserver = new ResizeObserver(() => requestAnimationFrame(applyZoom));
resizeObserver.observe(element);

root.addEventListener('change', event => {
  const input = event.target.closest('#status-radio input');
  if (!input || props.value.step !== 4 || !activeBoxId) return;
  renderLocalStatus(activeBoxId, input.value);
  syncExternalControls();
});

const point = (event, svg, width=props.value.width, height=props.value.height) => {
  const p = svg.createSVGPoint(); p.x=event.clientX; p.y=event.clientY;
  const at = p.matrixTransform(svg.getScreenCTM().inverse());
  return {x: Math.max(0, Math.min(at.x, width)),
          y: Math.max(0, Math.min(at.y, height))};
};
const drawPreview = (group, box) => {
  const rect = group?.querySelector('rect:not([data-image-resize-handle])');
  if (!rect) return;
  rect.setAttribute('x',box[0]); rect.setAttribute('y',box[1]);
  rect.setAttribute('width',Math.max(0,box[2]-box[0]));
  rect.setAttribute('height',Math.max(0,box[3]-box[1]));
  const corners = [[box[0],box[1]], [box[2],box[1]], [box[2],box[3]], [box[0],box[3]]];
  group.querySelectorAll('[data-corner]').forEach(handle => {
    const [x,y] = corners[Number(handle.dataset.corner)];
    handle.setAttribute('cx',x); handle.setAttribute('cy',y);
  });
};
const drawLocalBox = (id, box) => {
  if (localBoxes[id]) localBoxes[id].bbox = [...box];
  drawPreview(groupFor(id), box);
};
const constrainCrop = (box, width, height) => {
  const cropWidth=Math.min(Math.max(1,box[2]-box[0]),width,props.value.max_crop_side);
  const cropHeight=Math.min(Math.max(1,box[3]-box[1]),height,props.value.max_crop_side);
  const x1=Math.min(Math.max(0,box[0]),width-cropWidth);
  const y1=Math.min(Math.max(0,box[1]),height-cropHeight);
  return [x1,y1,x1+cropWidth,y1+cropHeight];
};
const drawImageResizePreview = (state, size) => {
  const [width,height]=size;
  imageTransform.width=width; imageTransform.height=height;
  state.svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  state.svg.style.aspectRatio=`${width}/${height}`;
  const source=state.svg.querySelector('image');
  source?.setAttribute('width',width); source?.setAttribute('height',height);
  const outline=state.svg.querySelector('.source-image-outline');
  outline?.setAttribute('width',width); outline?.setAttribute('height',height);
  state.handle.setAttribute('x',Math.max(0,width-state.inset));
  state.handle.setAttribute('y',Math.max(0,height-state.inset));
  state.crop=constrainCrop(state.box,width,height);
  drawPreview(groupFor('crop'),state.crop);
  fitCanvas(width,height);
};
const setSelection = (ids, active=null, sync=true) => {
  selectedIds = new Set(ids.filter(id => localBoxes[id]));
  activeBoxId = active && localBoxes[active] ? active : selectedIds.values().next().value || null;
  renderSelection(sync);
};
const createOverlayRect = (svg, className) => {
  const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
  rect.setAttribute('class',className); rect.setAttribute('vector-effect','non-scaling-stroke');
  svg.appendChild(rect); return rect;
};
const normalizedRect = (start,end) => [
  Math.min(start.x,end.x),Math.min(start.y,end.y),
  Math.max(start.x,end.x),Math.max(start.y,end.y),
];
const drawOverlayRect = (rect, box) => {
  rect.setAttribute('x',box[0]); rect.setAttribute('y',box[1]);
  rect.setAttribute('width',box[2]-box[0]); rect.setAttribute('height',box[3]-box[1]);
};

element.addEventListener('pointerdown', event => {
  if (pending || event.button !== 0) return;
  const svg=event.target.closest('.annotation-canvas'); if(!svg) return;
  const mode=props.value.step;
  const group=event.target.closest('[data-box-id]');
  const id=group?.dataset.boxId;
  const toggle=event.ctrlKey || event.metaKey;
  if ([3,4,5,7].includes(mode)) {
    if (group) {
      if (toggle) {
        const next=new Set(selectedIds);
        if (next.has(id)) next.delete(id); else next.add(id);
        setSelection([...next],next.has(id)?id:[...next].at(-1));
        event.preventDefault(); return;
      }
      if (!selectedIds.has(id)) setSelection([id],id);
      else {activeBoxId=id; renderSelection();}
      if (mode !== 3) {event.preventDefault(); return;}
      const p=point(event,svg);
      const corner=event.target.dataset.corner;
      if (corner !== undefined) {
        moving={kind:'resize',svg,id,corner:Number(corner),p,box:[...localBoxes[id].bbox]};
      } else {
        const ids=[...selectedIds];
        moving={kind:'drag',svg,p,ids,boxes:Object.fromEntries(ids.map(
          boxId => [boxId,[...localBoxes[boxId].bbox]]
        ))};
      }
    } else {
      const p=point(event,svg);
      if (mode===3 && event.altKey) {
        moving={kind:'add',svg,p,rect:createOverlayRect(svg,'selection-marquee')};
      } else {
        moving={kind:'marquee',svg,p,baseline:toggle?new Set(selectedIds):new Set(),
          rect:createOverlayRect(svg,'selection-marquee')};
        if (!toggle) setSelection([],null);
      }
    }
    svg.setPointerCapture(event.pointerId); event.preventDefault(); return;
  }

  if (mode!==6) return;
  const p=point(event,svg);
  if (group) {
    moving={kind:'crop',svg,id:'crop',p,box:[...localBoxes.crop.bbox],
      corner:event.target.dataset.corner};
  } else {
    moving={kind:'crop-new',svg,p,rect:createOverlayRect(svg,'selection-marquee')};
  }
  svg.setPointerCapture(event.pointerId); event.preventDefault();
});

element.addEventListener('pointermove', event => {
  if(!moving) return;
  if(moving.kind==='image'){
    const width=Math.max(1,Math.round(moving.size[0]+(event.clientX-moving.start[0])*moving.units[0]));
    const height=Math.max(1,Math.round(moving.size[1]+(event.clientY-moving.start[1])*moving.units[1]));
    moving.result=[width,height]; drawImageResizePreview(moving,moving.result); return;
  }
  const state=moving, p=point(event,state.svg), dx=p.x-state.p.x, dy=p.y-state.p.y;
  const width=props.value.width,height=props.value.height;
  if(state.kind==='marquee' || state.kind==='add' || state.kind==='crop-new'){
    const box=normalizedRect(state.p,p);
    state.result=box; drawOverlayRect(state.rect,box);
    if(state.kind==='marquee'){
      const hits=Object.entries(localBoxes).filter(([,candidate])=>{
        const b=candidate.bbox;
        return b[0]<=box[2] && b[2]>=box[0] && b[1]<=box[3] && b[3]>=box[1];
      }).map(([id])=>id);
      setSelection([...new Set([...state.baseline,...hits])],hits.at(-1)||[...state.baseline].at(-1),false);
    }
    return;
  }
  if(state.kind==='drag'){
    const boxes=Object.values(state.boxes);
    const tx=Math.max(-Math.min(...boxes.map(b=>b[0])),Math.min(dx,width-Math.max(...boxes.map(b=>b[2]))));
    const ty=Math.max(-Math.min(...boxes.map(b=>b[1])),Math.min(dy,height-Math.max(...boxes.map(b=>b[3]))));
    state.result={};
    state.ids.forEach(id=>{
      const b=state.boxes[id];
      state.result[id]=[b[0]+tx,b[1]+ty,b[2]+tx,b[3]+ty];
      drawLocalBox(id,state.result[id]);
    });
    return;
  }
  let box=[...state.box];
  if(state.kind==='resize'){
    const corner=state.corner;
    if(corner===0||corner===3)box[0]+=dx;else box[2]+=dx;
    if(corner===0||corner===1)box[1]+=dy;else box[3]+=dy;
  } else if(state.kind==='crop'){
    if(state.corner!==undefined){
      const corner=Number(state.corner);
      if(corner===0||corner===3)box[0]+=dx;else box[2]+=dx;
      if(corner===0||corner===1)box[1]+=dy;else box[3]+=dy;
    } else {
      const tx=Math.max(-box[0],Math.min(dx,width-box[2]));
      const ty=Math.max(-box[1],Math.min(dy,height-box[3]));
      box=[box[0]+tx,box[1]+ty,box[2]+tx,box[3]+ty];
    }
  }
  box=box.map((value,index)=>Math.max(0,Math.min(value,index%2?height:width)));
  if(state.kind==='resize' || (state.kind==='crop' && state.corner!==undefined)){
    const corner=Number(state.corner);
    if(corner===0||corner===3)box[0]=Math.min(box[0],box[2]-1);else box[2]=Math.max(box[2],box[0]+1);
    if(corner===0||corner===1)box[1]=Math.min(box[1],box[3]-1);else box[3]=Math.max(box[3],box[1]+1);
  }
  state.result=box;
  if(state.kind==='resize') drawLocalBox(state.id,box); else drawPreview(groupFor('crop'),box);
});

element.addEventListener('pointerup', () => {
  if(!moving)return;
  const state=moving; moving=null;
  if(state.kind==='marquee'){
    state.rect.remove(); syncExternalControls(); return;
  }
  if(state.kind==='add'){
    state.rect.remove();
    if(state.result && state.result[2]>state.result[0] && state.result[3]>state.result[1]) send('add',{bbox:state.result});
    return;
  }
  if(state.kind==='drag' && state.result){
    Object.entries(state.result).forEach(([id,box]) => {
      localBoxes[id].bbox=[...box];
    });
    syncExternalControls(); return;
  }
  if(state.kind==='resize' && state.result && state.result[2]>state.result[0] && state.result[3]>state.result[1]){
    localBoxes[state.id].bbox=[...state.result];
    syncExternalControls();
    return;
  }
  if(state.kind==='crop-new'){
    state.rect.remove();
    if(state.result && state.result[2]>state.result[0] && state.result[3]>state.result[1]) {
      localBoxes.crop.bbox=[...state.result];
      drawPreview(groupFor('crop'),state.result);
      syncExternalControls();
    }
    return;
  }
  if(state.kind==='crop' && state.result) {
    localBoxes.crop.bbox=[...state.result];
    syncExternalControls();
  }
});

element.addEventListener('pointercancel',()=>{
  if (!moving) return;
  const state=moving; moving=null;
  if(state.kind==='drag') Object.entries(state.boxes).forEach(([id,box])=>drawLocalBox(id,box));
  else if(state.kind==='resize') drawLocalBox(state.id,state.box);
  else if(state.kind==='crop') drawPreview(groupFor('crop'),state.box);
  else state.rect?.remove();
  if(state.kind==='marquee') setSelection([...state.baseline],[...state.baseline].at(-1));
});

const clearDrag = () => {
  element.querySelectorAll('.dragging,.drop-target').forEach(card=>card.classList.remove('dragging','drop-target'));
  dragged=null;
};
element.addEventListener('dragstart',event=>{
  const card=event.target.closest('[data-card]');
  if(!card || pending || props.value.step!==5){event.preventDefault();return;}
  dragged=card; card.classList.add('dragging'); event.dataTransfer.effectAllowed='move';
  event.dataTransfer.setData('text/plain',card.dataset.boxId);
});
element.addEventListener('dragover',event=>{
  const target=event.target.closest('[data-card]');
  if(!target || !dragged || pending)return;
  event.preventDefault(); event.dataTransfer.dropEffect='move';
  element.querySelectorAll('.drop-target').forEach(card=>card.classList.remove('drop-target'));
  target.classList.add('drop-target');
});
element.addEventListener('drop',event=>{
  const target=event.target.closest('[data-card]');
  if(!target || !dragged || pending || props.value.step!==5)return;
  event.preventDefault();
  if(target===dragged){clearDrag();return;}
  // Cards are fixed physical Box ID slots. The movable item is the annotation
  // currently assigned through readingOrder, so insertion must start from the
  // persisted order rather than the visual DOM order.
  const order=[...localReadingOrder];
  const sourcePosition=order.indexOf(Number(dragged.dataset.boxId));
  const targetPosition=order.indexOf(Number(target.dataset.boxId));
  if(sourcePosition<0 || targetPosition<0){clearDrag();return;}
  // To place the dragged annotation into a fixed target slot, move the target
  // Box ID to the dragged annotation's source position. Re-alignment then
  // shifts every intervening annotation while all physical slots stay put.
  const [targetId]=order.splice(targetPosition,1);
  order.splice(sourcePosition,0,targetId);
  localReadingOrder=order;
  clearDrag();renderLocalAnnotations();syncExternalControls();
});
element.addEventListener('dragend',clearDrag);
element.addEventListener('click', event => {
  const control=event.target.closest('[data-zoom]');
  if(control){
    imageTransform.zoom=control.dataset.zoom==='fit'?100:Math.max(50,Math.min(300,
      imageTransform.zoom+(control.dataset.zoom==='in'?25:-25)));
    applyZoom();return;
  }
  const card=event.target.closest('[data-card]');
  if(card && !pending)setSelection([card.dataset.boxId],card.dataset.boxId);
});
