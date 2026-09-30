// Python owns persisted data. Browser-local state owns direct manipulation.
let pending = false, pendingAction = null, moving = null, orderDrag = null;
let syncingStatusControl = false;
let syncingCoordinateControls = false;
let isDirty = false, pendingSortSelectedRange = null;
let image = props.value.image, localContext = '';
let localBoxes = {}, selectedIds = new Set(), activeBoxId = null, activeTokenId = null;
let localTextSequence = [], localTokenOrder = [], localSuspiciousTokenIds = new Set();
let annotationColor = '#f4f4f5';
const annotationColors = {
  White:'#f4f4f5', Cyan:'#22d3ee', Amber:'#f59e0b',
  Violet:'#a78bfa', Pink:'#f472b6',
};
const chipReflowAnimations = new WeakMap();
const imageTransform = {zoom: 100, width: props.value.width, height: props.value.height};

const canEditReadingOrder = () => {
  const step = props.value?.step || 1;
  const bboxValid = Boolean(props.value?.bboxValid);
  const mismatchConfirmed = Boolean(props.value?.mismatchConfirmed);
  return step >= 3 && (bboxValid || mismatchConfirmed);
};

const cloneBoxes = boxes => Object.fromEntries(Object.entries(boxes || {}).map(
  ([id, box]) => [id, {...box, bbox: [...box.bbox], unknown: Boolean(box.unknown), order: box.order ?? null}]
));
const groupFor = id => [...element.querySelectorAll('.annotation-canvas [data-box-id]')].find(
  group => group.dataset.boxId === String(id)
);
const root = element.closest('.gradio-container') || document;
const statusColor = (status, unknown=false) => status === 'damaged' ? (unknown ? '#f59e0b' : '#ef4444') : '#22c55e';
const applyAnnotationColor = () => {
  if (props.value.step !== 3) return;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group=>{
    const rect=group.querySelector('rect:not([data-image-resize-handle])');
    if(rect){rect.setAttribute('fill',annotationColor);rect.setAttribute('stroke',annotationColor);}
    const label=group.querySelector('text');
    if(label)label.setAttribute('fill',annotationColor);
    group.querySelectorAll('[data-corner]').forEach(handle=>handle.setAttribute('fill',annotationColor));
  });
};
const readAnnotationColor = () => {
  const selected=root.querySelector('#bbox-color-palette input, #bbox-color-palette select');
  if(selected && annotationColors[selected.value]) annotationColor=annotationColors[selected.value];
};
const handleAnnotationColor = target => {
  const color=target.closest('#bbox-color-palette input, #bbox-color-palette select');
  if(!color)return false;
  if(annotationColors[color.value])annotationColor=annotationColors[color.value];
  applyAnnotationColor();
  return true;
};
root.addEventListener('bbox-color-change', event => {
  const value=event.detail;
  if(!annotationColors[value])return;
  annotationColor=annotationColors[value];
  applyAnnotationColor();
});
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
    unknowns: Object.fromEntries(Object.entries(localBoxes).map(
      ([id, box]) => [id, Boolean(box.status === 'damaged' && box.unknown)]
    )),
    boxes: Object.fromEntries(Object.entries(localBoxes).map(
      ([id, box]) => [id, [...box.bbox]]
    )),
    orders: Object.fromEntries(Object.entries(localBoxes).map(
      ([id, box]) => [id, box.order ?? null]
    )),
    crop: localBoxes.crop?.bbox || null,
    textSequence: [...localTextSequence],
    tokenOrder: [...(element.querySelectorAll('.order-chips [data-order-chip]') || [])]
      .map(chip=>chip.dataset.tokenId),
    suspiciousTokenIds: [...localSuspiciousTokenIds],
  }));
  const active = activeBoxId && localBoxes[activeBoxId];
  if (props.value.step === 4) {
    const suspicious = root.querySelector('#suspicious-toggle input[type="checkbox"]');
    if (suspicious) {
      const chip = activeBoxId && element.querySelector(
        `[data-order-chip][data-assigned-box-id="${activeBoxId}"]`);
      activeTokenId = chip?.dataset.tokenId || null;
      const isMissing = Boolean(chip?.classList.contains('missing') || chip?.dataset.character === '[MISS]');
      const isExcluded = Boolean(chip?.classList.contains('excluded'));
      if (isMissing && activeTokenId) {
        localSuspiciousTokenIds.delete(activeTokenId);
      }
      suspicious.disabled = !chip || isExcluded || isMissing;
      suspicious.checked = Boolean(chip && !isMissing && !isExcluded && localSuspiciousTokenIds.has(activeTokenId));
    }
  }
  if (!active) return;
  if (props.value.step === 3) {
    syncingCoordinateControls = true;
    try {
      ['#bbox-x1','#bbox-y1','#bbox-x2','#bbox-y2'].forEach(
        (selector, index) => setInputValue(selector, active.bbox[index])
      );
      setInputValue('#manual-box-order', active.order ?? '');
    } finally {
      syncingCoordinateControls = false;
    }
  }
  if (props.value.step === 4) {
    const statusRadio = root.querySelector(`#status-radio input[value="${active.status}"]`);
    if (statusRadio && !statusRadio.checked) {
      syncingStatusControl = true;
      try { statusRadio.click(); } finally { syncingStatusControl = false; }
    }
    const activeChip = activeBoxId && element.querySelector(`[data-order-chip][data-assigned-box-id="${activeBoxId}"]`);
    const isMissing = Boolean(activeChip?.classList.contains('missing') || activeChip?.dataset.character === '[MISS]');
    if (isMissing && active.unknown) {
      active.unknown = false;
      renderLocalStatus(activeBoxId, active.status, false);
    }
    const unknownRadioInputs = root.querySelectorAll('#unknown-radio input');
    const unknownContainer = root.querySelector('#unknown-radio');
    const isDamaged = active.status === 'damaged';
    const canBeUnknown = isDamaged && !isMissing;
    const targetValue = canBeUnknown && active.unknown ? 'True' : 'False';
    if (unknownContainer) {
      unknownContainer.classList.toggle('disabled', !canBeUnknown);
      unknownContainer.style.pointerEvents = canBeUnknown ? 'auto' : 'none';
      unknownContainer.style.opacity = canBeUnknown ? '1' : '0.6';
    }
    unknownRadioInputs.forEach(input => {
      const isTarget = input.value === targetValue;
      if (isTarget && !input.checked) {
        input.disabled = false;
        syncingStatusControl = true;
        try { input.click(); } finally { syncingStatusControl = false; }
      }
      input.disabled = !canBeUnknown;
      const label = input.closest('label');
      if (label) {
        label.classList.toggle('disabled', !canBeUnknown);
        label.style.pointerEvents = canBeUnknown ? 'auto' : 'none';
      }
    });
  }
  if (props.value.step === 6 && localBoxes.crop) {
    setInputValue('#crop-coordinates', JSON.stringify(localBoxes.crop.bbox));
  }
};
const renderLocalStatus = (id, status, unknown=null) => {
  const box = localBoxes[id];
  const group = groupFor(id);
  if (!box || !group) return;
  box.status = status;
  if (unknown !== null) {
    box.unknown = Boolean(unknown && status === 'damaged');
  } else if (status !== 'damaged') {
    box.unknown = false;
  }
  group.dataset.status = status;
  group.dataset.unknown = String(Boolean(box.unknown));
  const revealStatus = props.value.step >= 4;
  const color = !revealStatus ? annotationColor : statusColor(status, box.unknown);
  const rect = group.querySelector('rect:not([data-image-resize-handle])');
  if (rect) {
    const missing = rect.dataset.missing === '1';
    const suspicious = group.classList.contains('suspicious-region');
    rect.setAttribute('fill', suspicious ? '#facc15' : missing ? '#e5e7eb' : color);
    rect.setAttribute('stroke', color);
    rect.removeAttribute('stroke-dasharray');
    rect.setAttribute('fill-opacity', suspicious ? '.20' : missing ? '.30' : '.04');
  }
  const label = group.querySelector('text');
  if (label) label.setAttribute('fill', color);
};
const renderSelection = (sync=true) => {
  const showResizeHandles = selectedIds.size === 1;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
    const id = group.dataset.boxId;
    const selected = selectedIds.has(id);
    const active = id === activeBoxId;
    group.classList.toggle('selected-region', selected);
    group.classList.toggle('active-region', active && showResizeHandles);
    const rect = group.querySelector('rect:not([data-image-resize-handle])');
    if (rect) {
      const suspicious=group.classList.contains('suspicious-region');
      const missing=rect.dataset.missing === '1';
      rect.setAttribute('fill-opacity', props.value.step >= 4
        ? suspicious ? '.20' : missing ? '.30' : '.04'
        : selected ? '.16' : '.04');
      rect.setAttribute('stroke-width', suspicious && active ? '3' : suspicious ? '2' : active ? '2.5' : selected ? '2' : '1.5');
    }
  });
  element.querySelectorAll('[data-order-chip]').forEach(chip => {
    chip.classList.remove('selected-chip');
  });
  if (sync) syncExternalControls();
};
const hydrateLocalState = () => {
  const context = `${props.value.image || ''}:${props.value.step}`;
  const preserveSelection = context === localContext;
  const preserveOrder = preserveSelection && ['select','suspicious'].includes(pendingAction);
  const previousBoxes = localBoxes;
  localBoxes = cloneBoxes(props.value.boxes);

  Object.entries(localBoxes).forEach(([id, box]) => {
    if (props.value.readingOrder && Array.isArray(props.value.readingOrder)) {
      const idx = props.value.readingOrder.indexOf(Number(id));
      if (idx !== -1) box.order = idx + 1;
    }
    if (previousBoxes[id]?.order !== undefined && preserveSelection) {
      box.order = previousBoxes[id].order;
    }
  });

  if (props.value.calcSortedBoxIds && Array.isArray(props.value.calcSortedBoxIds)) {
    const sortedIds = props.value.calcSortedBoxIds;
    if (pendingSortSelectedRange) {
      const [start, count] = pendingSortSelectedRange;
      pendingSortSelectedRange = null;
      sortedIds.forEach((id, idx) => {
        if (localBoxes[id]) localBoxes[id].order = start + idx;
      });
    } else {
      sortedIds.forEach((id, idx) => {
        if (localBoxes[id]) localBoxes[id].order = idx + 1;
      });
    }
    isDirty = true;
    Object.entries(localBoxes).forEach(([id, b]) => {
      const g = groupFor(id);
      const text = g?.querySelector('text');
      if (text) {
        const publicBox = props.value.step !== 6;
        const labelText = publicBox ? String(b.order ?? id) : '';
        text.textContent = labelText;
      }
    });
  }

  if (props.value.step !== 4) {
    element.querySelectorAll('[data-miss-mark]').forEach(mark => mark.remove());
  }
  if (!preserveOrder) {
    localTextSequence = [...(props.value.orderedAnnotations || [])].map(String);
    localTokenOrder = [];
    localSuspiciousTokenIds = new Set(
      (props.value.suspiciousTokenIds || []).map(String));
  }
  imageTransform.width = props.value.width;
  imageTransform.height = props.value.height;
  if (preserveSelection) {
    selectedIds = new Set([...selectedIds].filter(id => localBoxes[id]));
    if (!localBoxes[activeBoxId]) activeBoxId = selectedIds.values().next().value || null;
  } else {
    selectedIds = new Set((props.value.selectedIds || []).map(String).filter(id => localBoxes[id]));
    activeBoxId = localBoxes[props.value.selected] ? String(props.value.selected) : selectedIds.values().next().value || null;
    activeTokenId = null;
    localContext = context;
  }
  element.querySelectorAll('.order-chips').forEach(container => {
    if (preserveOrder && localTokenOrder.length) arrangeOrder(container, localTokenOrder);
    updateExcludedChips(container);
  });
  if (props.value.step === 4) {
    Object.entries(localBoxes).forEach(([id, box]) => renderLocalStatus(id, box.status, box.unknown));
  }
  renderSelection();
  readAnnotationColor();
  applyAnnotationColor();
};

const fitCanvas = (width, height) => {
  const svg = element.querySelector('.annotation-canvas');
  const viewport = element.querySelector('.image-viewport');
  if (!svg || !viewport) return;

  const viewBox = (svg.getAttribute('viewBox') || '').split(' ').map(Number);
  const w = width || (viewBox.length === 4 && viewBox[2]) || imageTransform.width || props.value?.width || 1000;
  const h = height || (viewBox.length === 4 && viewBox[3]) || imageTransform.height || props.value?.height || 1000;
  if (!w || !h) return;

  const style = getComputedStyle(viewport);
  const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);

  const availW = Math.max(100, (viewport.clientWidth || 400) - padX);

  const baselineWidth = availW;
  const baselineHeight = h * (baselineWidth / w);

  const zoomFactor = Math.max(25, Math.min(150, imageTransform.zoom || 100)) / 100;
  const renderedWidth = Math.round(baselineWidth * zoomFactor);
  const renderedHeight = Math.round(baselineHeight * zoomFactor);

  svg.style.width = `${renderedWidth}px`;
  svg.style.height = `${renderedHeight}px`;
  svg.style.maxWidth = 'none';
  svg.style.maxHeight = 'none';

  const label = element.querySelector('.zoom-label');
  if (label) label.textContent = `${imageTransform.zoom}%`;
};
const applyZoom = () => fitCanvas();
const send = (action, payload={}) => {
  if (pending) return;
  pending = true;
  pendingAction = action;
  element.setAttribute('aria-busy', 'true');
  trigger('action', {action, payload: {
    ...payload, revision: props.value.revision, image: props.value.image,
  }});
};
watch('value', () => {
  pending = false; moving = null;
  if (orderDrag?.ghost) orderDrag.ghost.remove();
  orderDrag = null;
  element.setAttribute('aria-busy', 'false');
  if (image !== props.value.image) {
    imageTransform.zoom = 100;
    image = props.value.image;
  }
  hydrateLocalState();
  pendingAction = null;
  requestAnimationFrame(applyZoom);
});
const resizeObserver = new ResizeObserver(() => requestAnimationFrame(applyZoom));
resizeObserver.observe(element);
const sidebar = root.querySelector('#control-panel');
if (sidebar) resizeObserver.observe(sidebar);

root.addEventListener('change', event => {
  if (syncingStatusControl) return;
  if(handleAnnotationColor(event.target))return;
  const suspicious = event.target.closest('#suspicious-toggle input[type="checkbox"]');
  if (suspicious && props.value.step === 4 && activeTokenId) {
    if(suspicious.checked)localSuspiciousTokenIds.add(activeTokenId);
    else localSuspiciousTokenIds.delete(activeTokenId);
    element.querySelectorAll('[data-order-chip]').forEach(chip=>
      chip.classList.toggle('suspicious',localSuspiciousTokenIds.has(chip.dataset.tokenId)));
    renderSuspiciousPreview();
    renderSelection();
    return;
  }
  const input = event.target.closest('#status-radio input');
  if (input && props.value.step === 4 && activeBoxId) {
    const currentBox = localBoxes[activeBoxId];
    renderLocalStatus(activeBoxId, input.value, currentBox?.unknown);
    syncExternalControls();
    return;
  }
  const unknownInput = event.target.closest('#unknown-radio input');
  if (unknownInput && props.value.step === 4 && activeBoxId) {
    const currentBox = localBoxes[activeBoxId];
    if (currentBox && currentBox.status === 'damaged') {
      const isUnknown = unknownInput.value === 'True' || unknownInput.value === 'true';
      renderLocalStatus(activeBoxId, 'damaged', isUnknown);
      syncExternalControls();
    }
    return;
  }
});

root.addEventListener('input', event => {
  if(handleAnnotationColor(event.target))return;
  const manualOrderInput = event.target.closest('#manual-box-order input');
  if (manualOrderInput && activeBoxId && localBoxes[activeBoxId]) {
    const val = manualOrderInput.value.trim();
    const errorEl = root.querySelector('#manual-box-order-error');
    if (!val) {
      localBoxes[activeBoxId].order = null;
      if (errorEl) errorEl.textContent = '';
      isDirty = true;
      const group = groupFor(activeBoxId);
      const text = group?.querySelector('text');
      if (text) text.textContent = activeBoxId;
      return;
    }
    const num = parseInt(val, 10);
    if (isNaN(num) || num < 1) {
      if (errorEl) errorEl.textContent = 'Order must be a positive integer.';
      return;
    }
    const conflict = Object.entries(localBoxes).find(([id, box]) => id !== activeBoxId && box.order === num);
    if (conflict) {
      if (errorEl) errorEl.textContent = `Order ${num} is used by box ${conflict[0]}.`;
      return;
    }
    if (errorEl) errorEl.textContent = '';
    localBoxes[activeBoxId].order = num;
    isDirty = true;
    const group = groupFor(activeBoxId);
    const text = group?.querySelector('text');
    if (text) text.textContent = String(num);
    return;
  }
  const modalStartInput = event.target.closest('#sort-modal-start');
  if (modalStartInput) {
    updateSortModalPreview();
    return;
  }
  if (syncingCoordinateControls || props.value.step !== 3 || !activeBoxId
      || !event.target.closest('#bbox-x1 input, #bbox-y1 input, #bbox-x2 input, #bbox-y2 input')) return;
  const rawValues=['#bbox-x1','#bbox-y1','#bbox-x2','#bbox-y2'].map(selector =>
    root.querySelector(`${selector} input`)?.value ?? '');
  if (rawValues.some(value => !value.trim())) return;
  const values=rawValues.map(Number);
  const [x1,y1,x2,y2]=values;
  if (!values.every(Number.isFinite) || x1<0 || y1<0 || x1>=x2 || y1>=y2
      || x2>props.value.width || y2>props.value.height) return;
  localBoxes[activeBoxId].bbox=[x1,y1,x2,y2];
  isDirty = true;
  drawLocalBox(activeBoxId,localBoxes[activeBoxId].bbox);
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
  const missMark=group.querySelector('[data-miss-mark]');
  if(missMark){
    const lines=missMark.querySelectorAll('line');
    [[box[0],box[1],box[2],box[3]],[box[2],box[1],box[0],box[3]]]
      .forEach((coords,index)=>{
        const line=lines[index];
        if(line) ['x1','y1','x2','y2'].forEach((attr,pos)=>line.setAttribute(attr,coords[pos]));
      });
  }
  const label=group.querySelector('text');
  if(label){
    const bw = box[2] - box[0];
    const bh = box[3] - box[1];
    const fontSize = Math.min(bw, bh) * 0.30;
    const strokeWidth = Math.max(0.5, fontSize * 0.1);
    const unit = Math.max(props.value.width, props.value.height) / 900;
    label.setAttribute('x', box[0] + 2 * unit);
    label.setAttribute('y', Math.max(fontSize, box[1] - 4 * unit));
    label.setAttribute('font-size', fontSize);
    label.setAttribute('stroke-width', strokeWidth);
  }
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

const tokenOrderFromDOM = container => [...container.querySelectorAll('[data-order-chip]')]
  .map(chip => chip.dataset.tokenId);
const textSequenceFromDOM = container => [...container.querySelectorAll('[data-order-chip]')]
  .map(chip => chip.dataset.character);
const updateExcludedChips = container => {
  const chips=[...container.querySelectorAll('[data-order-chip]')];
  const count=Number(container.dataset.excludedCount || 0);
  chips.forEach((chip,index)=>{
    const excluded=count>0 && index>=chips.length-count;
    chip.classList.toggle('excluded',excluded);
    chip.title=excluded?'Excluded from annotation data':chip.dataset.character;
    const boxId=excluded?'':String((props.value.spatialBoxOrder || [])[index] || '');
    if(boxId)chip.dataset.assignedBoxId=boxId;else delete chip.dataset.assignedBoxId;
    chip.classList.toggle('suspicious',localSuspiciousTokenIds.has(chip.dataset.tokenId));
  });
  renderSuspiciousPreview();
};

function renderSuspiciousPreview(){
  if(props.value.step!==4)return;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group=>{
    const chip=element.querySelector(`[data-order-chip][data-assigned-box-id="${group.dataset.boxId}"]`);
    const suspicious=Boolean(chip?.classList.contains('suspicious'));
    group.classList.toggle('suspicious-region',suspicious);
    const status=localBoxes[group.dataset.boxId]?.status || 'intact';
    const unknown=Boolean(localBoxes[group.dataset.boxId]?.unknown);
    const stroke=statusColor(status, unknown);
    const rect=group.querySelector('rect:not([data-image-resize-handle])');
    if(rect){
      const missing=rect.dataset.missing === '1';
      rect.setAttribute('fill',suspicious?'#facc15':missing?'#e5e7eb':stroke);
      rect.setAttribute('fill-opacity',suspicious?'.20':missing?'.30':'.04');
      rect.setAttribute('stroke',stroke);
    }
    const label=group.querySelector('text');if(label)label.setAttribute('fill',stroke);
  });
}
const orderRows = chips => {
  const rows=[];
  chips.forEach(chip => {
    const rect=chip.getBoundingClientRect();
    let row=rows.find(candidate => Math.abs(candidate.top-rect.top) < Math.max(8,rect.height/2));
    if(!row){row={top:rect.top,bottom:rect.bottom,items:[]};rows.push(row);}
    row.top=Math.min(row.top,rect.top);row.bottom=Math.max(row.bottom,rect.bottom);
    row.items.push({chip,rect});
  });
  rows.sort((a,b)=>a.top-b.top);
  rows.forEach(row=>row.items.sort((a,b)=>a.rect.left-b.rect.left));
  return rows;
};
const insertionReference = (container, x, y) => {
  const chips=[...container.querySelectorAll('[data-order-chip]')]
    .filter(chip=>chip!==orderDrag.chip);
  if(!chips.length)return null;
  const rows=orderRows(chips);
  let row=rows.find(candidate=>y>=candidate.top && y<=candidate.bottom);
  if(!row)row=rows.reduce((best,candidate)=>{
    const distance=Math.abs(y-(candidate.top+candidate.bottom)/2);
    return !best || distance<best.distance?{row:candidate,distance}:best;
  },null).row;
  const before=row.items.find(item=>x<item.rect.left+item.rect.width/2);
  if(before)return before.chip;
  const flattened=rows.flatMap(candidate=>candidate.items.map(item=>item.chip));
  const last=row.items.at(-1).chip;
  return flattened[flattened.indexOf(last)+1] || null;
};
const captureChipRects = container => {
  const first=new Map();
  container.querySelectorAll('[data-order-chip]').forEach(chip=>{
    first.set(chip,chip.getBoundingClientRect());
    chipReflowAnimations.get(chip)?.cancel();
    chipReflowAnimations.delete(chip);
  });
  return first;
};
const animateChipReflow = (container, first) => {
  container.querySelectorAll('[data-order-chip]').forEach(chip=>{
    if(chip===orderDrag.chip)return;
    const old=first.get(chip),now=chip.getBoundingClientRect();
    if(!old)return;
    const dx=old.left-now.left,dy=old.top-now.top;
    if(Math.abs(dx)<.5 && Math.abs(dy)<.5)return;
    const animation=chip.animate(
      [{transform:`translate3d(${dx}px, ${dy}px, 0)`},
       {transform:'translate3d(0, 0, 0)'}],
      {duration:180,easing:'cubic-bezier(.22, 1, .36, 1)',fill:'both'});
    chipReflowAnimations.set(chip,animation);
    animation.onfinish=()=>{
      if(chipReflowAnimations.get(chip)===animation){
        animation.cancel();
        chipReflowAnimations.delete(chip);
      }
    };
  });
};
const beginOrderDrag = event => {
  const state=orderDrag,rect=state.chip.getBoundingClientRect();
  state.started=true;state.offsetX=event.clientX-rect.left;state.offsetY=event.clientY-rect.top;
  state.originalOrder=tokenOrderFromDOM(state.container);
  state.ghost=state.chip.cloneNode(true);
  state.ghost.classList.remove('active');state.ghost.classList.add('order-chip-ghost');
  state.ghost.removeAttribute('data-order-chip');state.ghost.removeAttribute('id');
  state.ghost.style.width=`${rect.width}px`;state.ghost.style.height=`${rect.height}px`;
  document.body.appendChild(state.ghost);
  state.container.classList.add('is-sorting');state.chip.classList.add('dragging');
};
const moveOrderGhost = event => {
  const x=event.clientX-orderDrag.offsetX,y=event.clientY-orderDrag.offsetY;
  orderDrag.ghost.style.transform=`translate3d(${x}px, ${y}px, 0) rotate(1deg) scale(1.03)`;
};
const arrangeOrder = (container, order) => order.forEach(tokenId=>{
  const chip=[...container.querySelectorAll('[data-order-chip]')].find(
    item=>item.dataset.tokenId===String(tokenId));
  if(chip)container.appendChild(chip);
});
const finishOrderDrag = (commit=true) => {
  if(!orderDrag)return;
  const state=orderDrag;
  if(state.started){
    if(!commit){
      const first=captureChipRects(state.container);
      arrangeOrder(state.container,state.originalOrder);
      updateExcludedChips(state.container);
      animateChipReflow(state.container,first);
    }
    state.ghost?.remove();state.chip.classList.remove('dragging');
    state.container.classList.remove('is-sorting');
    if(commit){
      updateExcludedChips(state.container);
      localTextSequence=textSequenceFromDOM(state.container);
      localTokenOrder=tokenOrderFromDOM(state.container);
      renderSelection();
    }
  } else if(commit) {
    renderSelection();
  }
  orderDrag=null;
};

element.addEventListener('pointerdown', event => {
  if (pending || event.button !== 0) return;
  const chip=event.target.closest('[data-order-chip]');
  if(chip && props.value.step===4){
    orderDrag={chip,container:chip.closest('.order-chips'),pointerId:event.pointerId,
      startX:event.clientX,startY:event.clientY,started:false};
    chip.setPointerCapture(event.pointerId);event.preventDefault();return;
  }
  const svg=event.target.closest('.annotation-canvas'); if(!svg) return;
  const mode=props.value.step;
  const group=event.target.closest('[data-box-id]');
  const id=group?.dataset.boxId;
  const toggle=event.ctrlKey || event.metaKey;
  if ([3,4,5,7].includes(mode)) {
    if (group) {
      if (toggle && mode === 3) {
        const next=new Set(selectedIds);
        if (next.has(id)) next.delete(id); else next.add(id);
        setSelection([...next],next.has(id)?id:[...next].at(-1));
        event.preventDefault(); return;
      }
      if (!selectedIds.has(id)) setSelection([id],id);
      else {activeBoxId=id; renderSelection();}
      if (mode !== 3) {
        event.preventDefault(); return;
      }
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
      if(mode===4){setSelection([],null);event.preventDefault();return;}
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
  if(orderDrag && event.pointerId===orderDrag.pointerId){
    if(!orderDrag.started && Math.hypot(event.clientX-orderDrag.startX,event.clientY-orderDrag.startY)<4)return;
    if(!orderDrag.started)beginOrderDrag(event);
    moveOrderGhost(event);
    const container=orderDrag.container;
    const reference=insertionReference(container,event.clientX,event.clientY);
    if(reference!==orderDrag.chip.nextElementSibling){
      const first=captureChipRects(container);
      if(reference)container.insertBefore(orderDrag.chip,reference);else container.appendChild(orderDrag.chip);
      updateExcludedChips(container);
      animateChipReflow(container,first);
    }
    event.preventDefault();return;
  }
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
      isDirty = true;
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
  if(state.kind==='resize') {
    isDirty = true;
    drawLocalBox(state.id,box);
  } else drawPreview(groupFor('crop'),box);
});

element.addEventListener('pointerup', event => {
  if(orderDrag && event.pointerId===orderDrag.pointerId){finishOrderDrag(true);return;}
  if(!moving)return;
  const state=moving; moving=null;
  if(state.kind==='marquee'){
    state.rect.remove(); syncExternalControls(); return;
  }
  if(state.kind==='add'){
    state.rect.remove();
    if(state.result && state.result[2]>state.result[0] && state.result[3]>state.result[1]){
      const bbox = state.result;
      const newId = 'box_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
      localBoxes[newId] = { bbox: [...bbox], status: 'intact', unknown: false, order: null };
      
      const svg = state.svg;
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.setAttribute('data-box-id', newId);
      group.setAttribute('data-region-uid', newId);
      group.setAttribute('data-status', 'intact');
      group.setAttribute('data-unknown', 'false');
      
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', bbox[0]); rect.setAttribute('y', bbox[1]);
      rect.setAttribute('width', bbox[2] - bbox[0]); rect.setAttribute('height', bbox[3] - bbox[1]);
      rect.setAttribute('fill', annotationColor); rect.setAttribute('stroke', annotationColor);
      rect.setAttribute('fill-opacity', '.04'); rect.setAttribute('stroke-width', '1.5');
      rect.setAttribute('vector-effect', 'non-scaling-stroke');
      group.appendChild(rect);

      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      const bw = bbox[2] - bbox[0], bh = bbox[3] - bbox[1];
      const fontSize = Math.min(bw, bh) * 0.30;
      const strokeWidth = Math.max(0.5, fontSize * 0.1);
      const unit = Math.max(props.value.width, props.value.height) / 900;
      text.setAttribute('x', bbox[0] + 2 * unit);
      text.setAttribute('y', Math.max(fontSize, bbox[1] - 4 * unit));
      text.setAttribute('fill', annotationColor);
      text.setAttribute('font-size', fontSize);
      text.setAttribute('stroke', '#17191c');
      text.setAttribute('stroke-width', strokeWidth);
      text.setAttribute('pointer-events', 'none');
      text.setAttribute('paint-order', 'stroke');
      group.appendChild(text);

      svg.appendChild(group);

      isDirty = true;
      setSelection([newId], newId);
    }
    return;
  }
  if(state.kind==='drag' && state.result){
    Object.entries(state.result).forEach(([id,box]) => {
      localBoxes[id].bbox=[...box];
    });
    isDirty = true;
    syncExternalControls(); return;
  }
  if(state.kind==='resize' && state.result && state.result[2]>state.result[0] && state.result[3]>state.result[1]){
    localBoxes[state.id].bbox=[...state.result];
    isDirty = true;
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
  if(orderDrag){finishOrderDrag(false);return;}
  if (!moving) return;
  const state=moving; moving=null;
  if(state.kind==='drag') Object.entries(state.boxes).forEach(([id,box])=>drawLocalBox(id,box));
  else if(state.kind==='resize') drawLocalBox(state.id,state.box);
  else if(state.kind==='crop') drawPreview(groupFor('crop'),state.box);
  else state.rect?.remove();
  if(state.kind==='marquee') setSelection([...state.baseline],[...state.baseline].at(-1));
});

const openSortSelectedModal = () => {
  const modal = root.querySelector('#sort-selected-modal');
  if (!modal) return;
  const count = selectedIds.size;
  const countEl = modal.querySelector('#sort-modal-count');
  if (countEl) countEl.textContent = count;
  const startInput = modal.querySelector('#sort-modal-start');
  if (startInput) startInput.value = '1';
  modal.style.display = 'flex';
  updateSortModalPreview();
};

const updateSortModalPreview = () => {
  const modal = root.querySelector('#sort-selected-modal');
  if (!modal) return;
  const count = selectedIds.size;
  const startInput = modal.querySelector('#sort-modal-start');
  const start = parseInt(startInput?.value || '1', 10);
  const rangeEl = modal.querySelector('#sort-modal-range');
  const errorEl = modal.querySelector('#sort-modal-error');
  const confirmBtn = modal.querySelector('#sort-modal-confirm');

  if (isNaN(start) || start < 1) {
    if (rangeEl) rangeEl.textContent = 'Invalid start number';
    if (errorEl) { errorEl.textContent = 'Start number must be a positive integer.'; errorEl.style.display = 'block'; }
    if (confirmBtn) confirmBtn.disabled = true;
    return;
  }

  const end = start + count - 1;
  if (rangeEl) rangeEl.textContent = `${start} – ${end}`;

  const rangeSet = new Set();
  for (let i = start; i <= end; i++) rangeSet.add(i);

  const conflicts = Object.entries(localBoxes)
    .filter(([id]) => !selectedIds.has(id))
    .filter(([, box]) => box.order !== null && box.order !== undefined && rangeSet.has(box.order));

  if (conflicts.length) {
    const conflictOrders = conflicts.map(([, b]) => b.order).sort((a, b) => a - b);
    if (errorEl) {
      errorEl.textContent = `Orders ${conflictOrders.join(', ')} are already used by boxes outside this selection. Choose another starting number.`;
      errorEl.style.display = 'block';
    }
    if (confirmBtn) confirmBtn.disabled = true;
  } else {
    if (errorEl) errorEl.style.display = 'none';
    if (confirmBtn) confirmBtn.disabled = false;
  }
};

const validateDraftState = (strictReadingOrder = false) => {
  const boxes = Object.entries(localBoxes);
  if (!boxes.length) return { valid: true };

  for (const [id, box] of boxes) {
    if (!box.bbox || box.bbox.length !== 4 || box.bbox[0] >= box.bbox[2] || box.bbox[1] >= box.bbox[3]) {
      return { valid: false, error: `Box ${id} has invalid coordinates.` };
    }
  }

  if (!strictReadingOrder) return { valid: true };

  const N = boxes.length;
  const missing = [];
  const duplicates = [];
  const counts = {};

  for (let i = 1; i <= N; i++) counts[i] = 0;

  for (const [id, box] of boxes) {
    if (box.order === null || box.order === undefined || isNaN(box.order) || box.order < 1) {
      missing.push(`Box ${id}`);
    } else {
      counts[box.order] = (counts[box.order] || 0) + 1;
    }
  }

  for (let i = 1; i <= N; i++) {
    if (!counts[i] || counts[i] === 0) {
      missing.push(`Order ${i}`);
    } else if (counts[i] > 1) {
      duplicates.push(`Order ${i}`);
    }
  }

  if (missing.length || duplicates.length) {
    const parts = ['Reading order is invalid for Step 4.'];
    parts.push(`Expected continuous sequence: 1–${N}.`);
    if (missing.length) parts.push(`Missing / unassigned: ${missing.join(', ')}.`);
    if (duplicates.length) parts.push(`Duplicates: ${duplicates.join(', ')}.`);
    parts.push('Please review reading order before continuing.');
    return { valid: false, error: parts.join('<br>') };
  }

  return { valid: true };
};

const commitDraftState = (navigateNext = false) => {
  const res = validateDraftState(navigateNext);
  if (!res.valid) {
    const modal = root.querySelector('#order-validation-modal');
    const body = root.querySelector('#order-alert-body');
    if (modal && body) {
      body.innerHTML = res.error;
      modal.style.display = 'flex';
    } else {
      alert(res.error.replace(/<br>/g, '\n'));
    }
    return false;
  }
  isDirty = false;
  send(navigateNext ? 'next' : 'commit_boxes', {
    boxes: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.bbox])),
    orders: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.order])),
    statuses: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.status])),
    unknowns: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, Boolean(b.unknown)])),
    active: activeBoxId,
    selected: [...selectedIds],
  });
  return true;
};

element.addEventListener('click', event => {
  const control=event.target.closest('[data-zoom]');
  if(control){
    imageTransform.zoom=control.dataset.zoom==='fit'?100:Math.max(25,Math.min(150,
      imageTransform.zoom+(control.dataset.zoom==='in'?25:-25)));
    applyZoom();return;
  }
  const deleteBtn = event.target.closest('#delete-box');
  if (deleteBtn) {
    if (!selectedIds.size) return;
    selectedIds.forEach(id => {
      delete localBoxes[id];
      groupFor(id)?.remove();
    });
    selectedIds.clear();
    activeBoxId = Object.keys(localBoxes)[0] || null;
    if (activeBoxId) selectedIds.add(activeBoxId);
    isDirty = true;
    renderSelection();
    event.preventDefault();
    return;
  }
  const sortBtn = event.target.closest('#sort-boxes');
  if (sortBtn) {
    if (!canEditReadingOrder()) {
      alert('Confirm the source mismatch before editing reading order.');
      event.preventDefault();
      return;
    }
    if (!selectedIds.size) {
      send('sort_boxes_calc', {
        boxes: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.bbox]))
      });
    } else {
      openSortSelectedModal();
    }
    event.preventDefault();
    return;
  }
  const applyBtn = event.target.closest('#apply-bbox-changes');
  if (applyBtn) {
    commitDraftState(false);
    event.preventDefault();
    return;
  }
  const cancelSortModal = event.target.closest('#sort-modal-cancel');
  if (cancelSortModal) {
    const modal = root.querySelector('#sort-selected-modal');
    if (modal) modal.style.display = 'none';
    event.preventDefault();
    return;
  }
  const confirmSortModal = event.target.closest('#sort-modal-confirm');
  if (confirmSortModal) {
    const startInput = root.querySelector('#sort-modal-start');
    const start = parseInt(startInput?.value || '1', 10);
    const modal = root.querySelector('#sort-selected-modal');
    if (modal) modal.style.display = 'none';
    pendingSortSelectedRange = [start, selectedIds.size];
    send('sort_boxes_calc', {
      boxes: Object.fromEntries([...selectedIds].map(id => [id, localBoxes[id].bbox])),
      selectedIds: [...selectedIds]
    });
    event.preventDefault();
    return;
  }
  const closeAlertModal = event.target.closest('#order-alert-close');
  if (closeAlertModal) {
    const modal = root.querySelector('#order-validation-modal');
    if (modal) modal.style.display = 'none';
    event.preventDefault();
    return;
  }
});

hydrateLocalState();
