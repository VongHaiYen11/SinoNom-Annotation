// Python owns persisted data. Browser-local state owns direct manipulation.
let pending = false, pendingAction = null, moving = null, orderDrag = null;
let syncingStatusControl = false;
let syncingCoordinateControls = false;
let isDirty = false, pendingSortSelectedRange = null;
let image = props.value.image, localContext = '';
let localBoxes = {}, selectedIds = new Set(), activeBoxId = null, activeTokenId = null;
let localTextSequence = [], localTokenOrder = [], localSuspiciousTokenIds = new Set();
let localMismatchConfirmed = false, pendingMismatchAction = null;
let nextTemporaryBoxId = 1;
let annotationColor = '#f4f4f5';
const annotationColors = {
  White: '#f4f4f5', Cyan: '#22d3ee', Amber: '#f59e0b',
  Violet: '#a78bfa', Pink: '#f472b6',
};
const chipReflowAnimations = new WeakMap();
const imageTransform = { zoom: 100, width: props.value.width, height: props.value.height };

const canEditReadingOrder = () => {
  const step = props.value?.step || 1;
  const dds = root.querySelectorAll('#validation-summary-host dl dd');
  const boxCount = Object.keys(localBoxes).length;
  const charCount = dds.length >= 2 ? (parseInt(dds[1].textContent.trim(), 10) || 0) : 0;
  const bboxValid = boxCount === charCount && boxCount > 0;
  const mismatchConfirmed = Boolean(props.value?.mismatchConfirmed) || localMismatchConfirmed;
  return step >= 3 && (bboxValid || mismatchConfirmed);
};

const openMismatchConfirmModal = (action) => {
  pendingMismatchAction = action;
  const modal = root.querySelector('#mismatch-confirm-modal');
  if (modal) modal.style.display = 'flex';
};

const updateValidationSummary = () => {
  const summaryHost = root.querySelector('#validation-summary-host');
  if (!summaryHost) return;
  const dds = summaryHost.querySelectorAll('dl dd');
  if (dds.length < 2) return;

  const boxCount = Object.keys(localBoxes).length;
  const charCount = parseInt(dds[1].textContent.trim(), 10) || 0;
  const diff = boxCount - charCount;

  dds[0].textContent = String(boxCount);
  if (dds.length >= 3) {
    dds[2].textContent = (diff > 0 ? '+' : '') + diff;
  }

  const contentVerified = Boolean(props.value.contentVerified ?? true);
  const mismatchConfirmed = Boolean(props.value.mismatchConfirmed) || localMismatchConfirmed;
  const matched = contentVerified && boxCount === charCount && charCount > 0;
  const canOrder = matched || mismatchConfirmed;

  if (!matched && !mismatchConfirmed) {
    let hasOrder = false;
    Object.values(localBoxes).forEach(box => {
      if (box.order !== null && box.order !== undefined) {
        box.order = null;
        hasOrder = true;
      }
    });
    if (hasOrder) {
      element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
        const text = group.querySelector('text');
        if (text) text.textContent = '';
      });
      isDirty = true;
    }
  }

  const badge = summaryHost.querySelector('.validation-badge');
  if (badge) {
    const label = mismatchConfirmed ? 'Source mismatch confirmed'
      : matched ? 'Counts match'
        : !contentVerified ? 'Content not verified'
          : 'Count mismatch';
    const span = badge.querySelector('span');
    if (span) span.textContent = label;

    const svgCheck = '<svg class="ui-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8 3 3 7-7"/></svg>';
    const svgAlert = '<svg class="ui-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.5"/><path d="M8 4.75v4M8 11.25h.01"/></svg>';

    const svgContainer = badge.querySelector('svg');
    if (svgContainer) {
      svgContainer.outerHTML = (matched || mismatchConfirmed) ? svgCheck : svgAlert;
    }
  }

  const mismatchGroup = root.querySelector('.mismatch-panel') || root.querySelector('#mismatch_group');
  if (mismatchGroup && props.value.step === 3) {
    mismatchGroup.style.display = matched ? 'none' : 'block';
  }
  const reason = canOrder ? '' : `Reading order is unavailable: ${boxCount} boxes for ${charCount} characters.`;
  ['#sort-boxes', '#clear-box-orders'].forEach(selector => {
    const control = root.querySelector(selector);
    if (control) { control.disabled = !canOrder; control.title = reason; }
  });
};

const cloneBoxes = boxes => Object.fromEntries(Object.entries(boxes || {}).map(([id, box]) => {
  const copy = structuredClone(box);
  copy.bbox = [...box.bbox];
  copy.unknown = Boolean(box.unknown);
  copy.order = box.order ?? null;
  return [String(id), copy];
}));
const assertUniqueBoxIds = (action) => {
  const ids = Object.keys(localBoxes);
  if (new Set(ids).size !== ids.length) throw new Error(`${action}: duplicate bounding-box IDs.`);
};
const traceTransition = (action, beforeIds) => {
  const afterIds = Object.keys(localBoxes);
  console.debug('BBOX STATE', { action, beforeCount: beforeIds.length, beforeIds,
    afterCount: afterIds.length, afterIds });
  assertUniqueBoxIds(action);
};
const serializeLocalBoxes = () => cloneBoxes(localBoxes);
const groupFor = id => [...element.querySelectorAll('.annotation-canvas [data-box-id]')].find(
  group => (group.dataset?.boxId || group.getAttribute('data-box-id')) === String(id)
);
const root = element.closest('.gradio-container') || document;
const statusColor = (status, unknown = false) => status === 'damaged' ? (unknown ? '#f59e0b' : '#ef4444') : '#22c55e';
const applyAnnotationColor = () => {
  if (props.value.step !== 3) return;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
    const rect = group.querySelector('rect:not([data-image-resize-handle])');
    if (rect) { rect.setAttribute('fill', annotationColor); rect.setAttribute('stroke', annotationColor); }
    const label = group.querySelector('text');
    if (label) label.setAttribute('fill', annotationColor);
  });
};
const readAnnotationColor = () => {
  const selected = root.querySelector('#bbox-color-palette input, #bbox-color-palette select');
  if (selected && annotationColors[selected.value]) annotationColor = annotationColors[selected.value];
};
const handleAnnotationColor = target => {
  const color = target.closest('#bbox-color-palette input, #bbox-color-palette select');
  if (!color) return false;
  if (annotationColors[color.value]) annotationColor = annotationColors[color.value];
  applyAnnotationColor();
  return true;
};
root.addEventListener('bbox-color-change', event => {
  const value = event.detail;
  if (!annotationColors[value]) return;
  annotationColor = annotationColors[value];
  applyAnnotationColor();
});
const setInputValue = (selector, value) => {
  const input = root.querySelector(`${selector} input, ${selector} textarea`);
  if (!input) return;
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  if (setter) setter.call(input, String(value)); else input.value = String(value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
};
const syncExternalControls = () => {
  updateValidationSummary();
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
      .map(chip => chip.dataset.tokenId),
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
  if (props.value.step === 3) {
    const manualOrderInput = root.querySelector('#manual-box-order input');
    const isSingleSelection = selectedIds.size === 1 && activeBoxId && localBoxes[activeBoxId];
    const allowed = canEditReadingOrder();
    if (manualOrderInput) {
      if (isSingleSelection && allowed) {
        manualOrderInput.disabled = false;
        manualOrderInput.placeholder = 'Enter order number';
        syncingCoordinateControls = true;
        try {
          setInputValue('#manual-box-order', localBoxes[activeBoxId].order ?? '');
        } finally {
          syncingCoordinateControls = false;
        }
      } else {
        manualOrderInput.disabled = true;
        syncingCoordinateControls = true;
        try {
          setInputValue('#manual-box-order', isSingleSelection ? (localBoxes[activeBoxId].order ?? '') : '');
        } finally {
          syncingCoordinateControls = false;
        }
        if (!allowed) {
          manualOrderInput.placeholder = 'Confirm source mismatch to edit order';
        } else if (selectedIds.size > 1) {
          manualOrderInput.placeholder = 'Select 1 box to edit order';
        } else {
          manualOrderInput.placeholder = 'Select a box to edit order';
        }
        const errorEl = root.querySelector('#manual-box-order-error');
        if (errorEl) errorEl.textContent = '';
      }
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
const renderLocalStatus = (id, status, unknown = null) => {
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
const renderSelection = (sync = true) => {
  const showResizeHandles = selectedIds.size === 1;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
    const id = group.dataset.boxId;
    const selected = selectedIds.has(id);
    const active = id === activeBoxId;
    group.classList.toggle('selected-region', selected);
    group.classList.toggle('active-region', active && showResizeHandles);
    const rect = group.querySelector('rect:not([data-image-resize-handle])');
    if (rect) {
      const suspicious = group.classList.contains('suspicious-region');
      const missing = rect.dataset.missing === '1';
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
const updateCanvasLabels = () => {
  Object.entries(localBoxes).forEach(([id, b]) => {
    const g = groupFor(id);
    if (!g) return;
    let text = g.querySelector(':scope > [data-box-order-label]');
    const hasOrder = b.order !== null && b.order !== undefined && b.order !== '';
    if (hasOrder || text) {
      if (!text) {
        text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('data-box-order-label', '1');
        text.setAttribute('pointer-events', 'none');
        text.setAttribute('paint-order', 'stroke');
        text.setAttribute('stroke', '#17191c');
        g.appendChild(text);
      }
      const box = b.bbox;
      const bw = Math.max(1, box[2] - box[0]);
      const bh = Math.max(1, box[3] - box[1]);
      const unit = Math.max(props.value.width, props.value.height) / 900;
      const fontSize = Math.max(10 * unit, Math.min(bw, bh) * 0.30);
      const strokeWidth = Math.max(0.5, fontSize * 0.1);
      const centerX = (box[0] + box[2]) / 2;
      text.setAttribute('x', centerX);
      text.setAttribute('y', Math.max(fontSize, box[1] - 3 * unit));
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', fontSize);
      text.setAttribute('stroke-width', strokeWidth);
      text.setAttribute('fill', annotationColor || '#ffffff');
      const publicBox = props.value.step !== 6;
      const labelText = publicBox ? (hasOrder ? String(b.order) : '') : '';
      text.textContent = labelText;
      g.dataset.order = hasOrder ? String(b.order) : '';
      const title = g.querySelector(':scope > title');
      if (title && props.value.step === 3) {
        title.textContent = hasOrder ? `Region · order ${b.order}` : 'Region · order unassigned';
      }
    }
  });
};

const hydrateLocalState = () => {
  const context = `${props.value.image || ''}:${props.value.step}`;
  const preserveSelection = context === localContext;
  const preserveOrder = preserveSelection && ['select', 'suspicious'].includes(pendingAction);
  const previousBoxes = localBoxes;
  if (['sort_boxes_calc', 'commit_boxes'].includes(pendingAction) && preserveSelection) {
    localBoxes = previousBoxes;
  } else {
    localBoxes = cloneBoxes(props.value.boxes);
  }

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
  }
  updateCanvasLabels();

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
  assertUniqueBoxIds('hydrate');
  readAnnotationColor();
  applyAnnotationColor();
};

const fitCanvas = (width, height, focalPoint = null) => {
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

  const prevZoomFactor = imageTransform.currentZoomFactor || (Math.max(25, Math.min(500, imageTransform.zoom || 100)) / 100);
  const newZoomFactor = Math.max(0.25, Math.min(5.0, (imageTransform.zoom || 100) / 100));
  imageTransform.currentZoomFactor = newZoomFactor;

  const renderedWidth = Math.round(baselineWidth * newZoomFactor);
  const renderedHeight = Math.round(baselineHeight * newZoomFactor);

  let targetScrollLeft = null, targetScrollTop = null;
  if (focalPoint) {
    const vRect = viewport.getBoundingClientRect();
    const cursorX = focalPoint.clientX - vRect.left;
    const cursorY = focalPoint.clientY - vRect.top;
    const contentX = viewport.scrollLeft + cursorX;
    const contentY = viewport.scrollTop + cursorY;
    const ratio = newZoomFactor / prevZoomFactor;
    targetScrollLeft = contentX * ratio - cursorX;
    targetScrollTop = contentY * ratio - cursorY;
  }

  svg.style.width = `${renderedWidth}px`;
  svg.style.height = `${renderedHeight}px`;
  svg.style.maxWidth = 'none';
  svg.style.maxHeight = 'none';

  if (targetScrollLeft !== null && targetScrollTop !== null) {
    viewport.scrollLeft = targetScrollLeft;
    viewport.scrollTop = targetScrollTop;
  }

  const label = element.querySelector('.zoom-label');
  if (label) label.textContent = `${Math.round(imageTransform.zoom)}%`;
};
const applyZoom = (focalPoint = null) => fitCanvas(undefined, undefined, focalPoint);
let spacePressed = false;
window.addEventListener('keydown', event => {
  if (event.code === 'Space' && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
    spacePressed = true;
    element.querySelector('.image-viewport')?.classList.add('is-panning');
  }
});
window.addEventListener('keyup', event => {
  if (event.code === 'Space') {
    spacePressed = false;
    element.querySelector('.image-viewport')?.classList.remove('is-panning');
  }
});
element.addEventListener('wheel', event => {
  if (event.ctrlKey || event.metaKey || event.altKey) {
    event.preventDefault();
    const delta = event.deltaY < 0 ? 15 : -15;
    const nextZoom = Math.max(25, Math.min(500, imageTransform.zoom + delta));
    if (nextZoom !== imageTransform.zoom) {
      imageTransform.zoom = nextZoom;
      fitCanvas(undefined, undefined, { clientX: event.clientX, clientY: event.clientY });
    }
  }
}, { passive: false });
const showSortingOverlay = () => {
  const el = root.querySelector('#global-loading') || document.getElementById('global-loading');
  if (el) {
    const label = el.querySelector('span:not(.global-loading-spinner)');
    if (label) label.textContent = 'Sorting…';
    el.classList.add('is-visible');
  }
};
const hideSortingOverlay = () => {
  const el = root.querySelector('#global-loading') || document.getElementById('global-loading');
  if (el) {
    el.classList.remove('is-visible');
  }
};
const send = (action, payload = {}) => {
  if (pending) return;
  if (action === 'next') {
    setSelection([], null);
  }
  pending = true;
  pendingAction = action;
  if (action === 'sort_boxes_calc') showSortingOverlay();
  element.setAttribute('aria-busy', 'true');
  trigger('action', {
    action, payload: {
      ...payload, revision: props.value.revision, image: props.value.image,
    }
  });
};
watch('value', () => {
  pending = false; moving = null;
  hideSortingOverlay();
  if (orderDrag?.ghost) orderDrag.ghost.remove();
  orderDrag = null;
  element.setAttribute('aria-busy', 'false');
  if (image !== props.value.image) {
    imageTransform.zoom = 100;
    image = props.value.image;
  }
  hydrateLocalState();
  if (pendingAction === 'commit_boxes') isDirty = false;
  pendingAction = null;
  requestAnimationFrame(applyZoom);
});
const resizeObserver = new ResizeObserver(() => requestAnimationFrame(applyZoom));
resizeObserver.observe(element);
const sidebar = root.querySelector('#control-panel');
if (sidebar) resizeObserver.observe(sidebar);

root.addEventListener('change', event => {
  if (syncingStatusControl) return;
  if (handleAnnotationColor(event.target)) return;
  const suspicious = event.target.closest('#suspicious-toggle input[type="checkbox"]');
  if (suspicious && props.value.step === 4 && activeTokenId) {
    if (suspicious.checked) localSuspiciousTokenIds.add(activeTokenId);
    else localSuspiciousTokenIds.delete(activeTokenId);
    element.querySelectorAll('[data-order-chip]').forEach(chip =>
      chip.classList.toggle('suspicious', localSuspiciousTokenIds.has(chip.dataset.tokenId)));
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
  if (syncingCoordinateControls) return;
  if (handleAnnotationColor(event.target)) return;
  const manualOrderInput = event.target.closest('#manual-box-order input');
  if (manualOrderInput) {
    if (!canEditReadingOrder() || selectedIds.size !== 1 || !activeBoxId || !localBoxes[activeBoxId]) {
      event.preventDefault();
      return;
    }
    const val = manualOrderInput.value.trim();
    const errorEl = root.querySelector('#manual-box-order-error');
    if (!val) {
      localBoxes[activeBoxId].order = null;
      if (errorEl) errorEl.textContent = '';
      isDirty = true;
      updateCanvasLabels();
      syncExternalControls();
      return;
    }
    const num = parseInt(val, 10);
    if (!/^\d+$/.test(val) || isNaN(num) || num < 1) {
      if (errorEl) errorEl.textContent = 'Order must be a positive integer.';
      return;
    }
    const conflict = Object.entries(localBoxes).find(([id, box]) => id !== activeBoxId && box.order === num);
    if (conflict) {
      if (errorEl) errorEl.textContent = `Order ${num} is already used by box ${conflict[0]}.`;
      return;
    }
    if (errorEl) errorEl.textContent = '';
    localBoxes[activeBoxId].order = num;
    isDirty = true;
    updateCanvasLabels();
    syncExternalControls();
    return;
  }
  const modalStartInput = event.target.closest('#sort-modal-start');
  if (modalStartInput) {
    updateSortModalPreview();
    return;
  }
  if (syncingCoordinateControls || props.value.step !== 3 || !activeBoxId
    || !event.target.closest('#bbox-x1 input, #bbox-y1 input, #bbox-x2 input, #bbox-y2 input')) return;
  const rawValues = ['#bbox-x1', '#bbox-y1', '#bbox-x2', '#bbox-y2'].map(selector =>
    root.querySelector(`${selector} input`)?.value ?? '');
  if (rawValues.some(value => !value.trim())) return;
  const values = rawValues.map(Number);
  const [x1, y1, x2, y2] = values;
  if (!values.every(Number.isFinite) || x1 < 0 || y1 < 0 || x1 >= x2 || y1 >= y2
    || x2 > props.value.width || y2 > props.value.height) return;
  localBoxes[activeBoxId].bbox = [x1, y1, x2, y2];
  isDirty = true;
  drawLocalBox(activeBoxId, localBoxes[activeBoxId].bbox);
});

const point = (event, svg, width = props.value.width, height = props.value.height) => {
  const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
  const at = p.matrixTransform(svg.getScreenCTM().inverse());
  return {
    x: Math.max(0, Math.min(at.x, width)),
    y: Math.max(0, Math.min(at.y, height))
  };
};
const drawPreview = (group, box) => {
  const rect = group?.querySelector('rect:not([data-image-resize-handle])');
  if (!rect) return;
  rect.setAttribute('x', box[0]); rect.setAttribute('y', box[1]);
  rect.setAttribute('width', Math.max(0, box[2] - box[0]));
  rect.setAttribute('height', Math.max(0, box[3] - box[1]));
  const missMark = group.querySelector('[data-miss-mark]');
  if (missMark) {
    const lines = missMark.querySelectorAll('line');
    [[box[0], box[1], box[2], box[3]], [box[2], box[1], box[0], box[3]]]
      .forEach((coords, index) => {
        const line = lines[index];
        if (line) ['x1', 'y1', 'x2', 'y2'].forEach((attr, pos) => line.setAttribute(attr, coords[pos]));
      });
  }
  const label = group.querySelector('text');
  if (label) {
    const bw = box[2] - box[0];
    const bh = box[3] - box[1];
    const unit = Math.max(props.value.width, props.value.height) / 900;
    const fontSize = Math.max(10 * unit, Math.min(bw, bh) * 0.30);
    const strokeWidth = Math.max(0.5, fontSize * 0.1);
    const centerX = (box[0] + box[2]) / 2;
    label.setAttribute('x', centerX);
    label.setAttribute('y', Math.max(fontSize, box[1] - 3 * unit));
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('font-size', fontSize);
    label.setAttribute('stroke-width', strokeWidth);
  }
  const corners = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]];
  group.querySelectorAll('[data-corner]').forEach(handle => {
    const attr = handle.getAttribute('data-corner') ?? handle.dataset?.corner;
    const n = Number(attr);
    const [x, y] = corners[n];
    handle.setAttribute('cx', x); handle.setAttribute('cy', y);
  });
};
const drawLocalBox = (id, box) => {
  if (localBoxes[id]) localBoxes[id].bbox = [...box];
  drawPreview(groupFor(id), box);
};
const constrainCrop = (box, width, height) => {
  const cropWidth = Math.min(Math.max(1, box[2] - box[0]), width, props.value.max_crop_side);
  const cropHeight = Math.min(Math.max(1, box[3] - box[1]), height, props.value.max_crop_side);
  const x1 = Math.min(Math.max(0, box[0]), width - cropWidth);
  const y1 = Math.min(Math.max(0, box[1]), height - cropHeight);
  return [x1, y1, x1 + cropWidth, y1 + cropHeight];
};
const drawImageResizePreview = (state, size) => {
  const [width, height] = size;
  imageTransform.width = width; imageTransform.height = height;
  state.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  state.svg.style.aspectRatio = `${width}/${height}`;
  const source = state.svg.querySelector('image');
  source?.setAttribute('width', width); source?.setAttribute('height', height);
  const outline = state.svg.querySelector('.source-image-outline');
  outline?.setAttribute('width', width); outline?.setAttribute('height', height);
  state.handle.setAttribute('x', Math.max(0, width - state.inset));
  state.handle.setAttribute('y', Math.max(0, height - state.inset));
  state.crop = constrainCrop(state.box, width, height);
  drawPreview(groupFor('crop'), state.crop);
  fitCanvas(width, height);
};
const setSelection = (ids, active = null, sync = true) => {
  selectedIds = new Set(ids.filter(id => localBoxes[id]));
  activeBoxId = active && localBoxes[active] ? active : selectedIds.values().next().value || null;
  renderSelection(sync);
};
const createOverlayRect = (svg, className) => {
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rect.setAttribute('class', className); rect.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.appendChild(rect); return rect;
};
const normalizedRect = (start, end) => [
  Math.min(start.x, end.x), Math.min(start.y, end.y),
  Math.max(start.x, end.x), Math.max(start.y, end.y),
];
const drawOverlayRect = (rect, box) => {
  rect.setAttribute('x', box[0]); rect.setAttribute('y', box[1]);
  rect.setAttribute('width', box[2] - box[0]); rect.setAttribute('height', box[3] - box[1]);
};

const tokenOrderFromDOM = container => [...container.querySelectorAll('[data-order-chip]')]
  .map(chip => chip.dataset.tokenId);
const textSequenceFromDOM = container => [...container.querySelectorAll('[data-order-chip]')]
  .map(chip => chip.dataset.character);
const updateExcludedChips = container => {
  const chips = [...container.querySelectorAll('[data-order-chip]')];
  const count = Number(container.dataset.excludedCount || 0);
  chips.forEach((chip, index) => {
    const excluded = count > 0 && index >= chips.length - count;
    chip.classList.toggle('excluded', excluded);
    chip.title = excluded ? 'Excluded from annotation data' : chip.dataset.character;
    const boxId = excluded ? '' : String((props.value.spatialBoxOrder || [])[index] || '');
    if (boxId) chip.dataset.assignedBoxId = boxId; else delete chip.dataset.assignedBoxId;
    chip.classList.toggle('suspicious', localSuspiciousTokenIds.has(chip.dataset.tokenId));
  });
  renderSuspiciousPreview();
};

function renderSuspiciousPreview() {
  if (props.value.step !== 4) return;
  element.querySelectorAll('.annotation-canvas [data-box-id]').forEach(group => {
    const chip = element.querySelector(`[data-order-chip][data-assigned-box-id="${group.dataset.boxId}"]`);
    const suspicious = Boolean(chip?.classList.contains('suspicious'));
    group.classList.toggle('suspicious-region', suspicious);
    const status = localBoxes[group.dataset.boxId]?.status || 'intact';
    const unknown = Boolean(localBoxes[group.dataset.boxId]?.unknown);
    const stroke = statusColor(status, unknown);
    const rect = group.querySelector('rect:not([data-image-resize-handle])');
    if (rect) {
      const missing = rect.dataset.missing === '1';
      rect.setAttribute('fill', suspicious ? '#facc15' : missing ? '#e5e7eb' : stroke);
      rect.setAttribute('fill-opacity', suspicious ? '.20' : missing ? '.30' : '.04');
      rect.setAttribute('stroke', stroke);
    }
    const label = group.querySelector('text'); if (label) label.setAttribute('fill', stroke);
  });
}
const orderRows = chips => {
  const rows = [];
  chips.forEach(chip => {
    const rect = chip.getBoundingClientRect();
    let row = rows.find(candidate => Math.abs(candidate.top - rect.top) < Math.max(8, rect.height / 2));
    if (!row) { row = { top: rect.top, bottom: rect.bottom, items: [] }; rows.push(row); }
    row.top = Math.min(row.top, rect.top); row.bottom = Math.max(row.bottom, rect.bottom);
    row.items.push({ chip, rect });
  });
  rows.sort((a, b) => a.top - b.top);
  rows.forEach(row => row.items.sort((a, b) => a.rect.left - b.rect.left));
  return rows;
};
const insertionReference = (container, x, y) => {
  const chips = [...container.querySelectorAll('[data-order-chip]')]
    .filter(chip => chip !== orderDrag.chip);
  if (!chips.length) return null;
  const rows = orderRows(chips);
  let row = rows.find(candidate => y >= candidate.top && y <= candidate.bottom);
  if (!row) row = rows.reduce((best, candidate) => {
    const distance = Math.abs(y - (candidate.top + candidate.bottom) / 2);
    return !best || distance < best.distance ? { row: candidate, distance } : best;
  }, null).row;
  const before = row.items.find(item => x < item.rect.left + item.rect.width / 2);
  if (before) return before.chip;
  const flattened = rows.flatMap(candidate => candidate.items.map(item => item.chip));
  const last = row.items.at(-1).chip;
  return flattened[flattened.indexOf(last) + 1] || null;
};
const captureChipRects = container => {
  const first = new Map();
  container.querySelectorAll('[data-order-chip]').forEach(chip => {
    first.set(chip, chip.getBoundingClientRect());
    chipReflowAnimations.get(chip)?.cancel();
    chipReflowAnimations.delete(chip);
  });
  return first;
};
const animateChipReflow = (container, first) => {
  container.querySelectorAll('[data-order-chip]').forEach(chip => {
    if (chip === orderDrag.chip) return;
    const old = first.get(chip), now = chip.getBoundingClientRect();
    if (!old) return;
    const dx = old.left - now.left, dy = old.top - now.top;
    if (Math.abs(dx) < .5 && Math.abs(dy) < .5) return;
    const animation = chip.animate(
      [{ transform: `translate3d(${dx}px, ${dy}px, 0)` },
      { transform: 'translate3d(0, 0, 0)' }],
      { duration: 180, easing: 'cubic-bezier(.22, 1, .36, 1)', fill: 'both' });
    chipReflowAnimations.set(chip, animation);
    animation.onfinish = () => {
      if (chipReflowAnimations.get(chip) === animation) {
        animation.cancel();
        chipReflowAnimations.delete(chip);
      }
    };
  });
};
const beginOrderDrag = event => {
  const state = orderDrag, rect = state.chip.getBoundingClientRect();
  state.started = true; state.offsetX = event.clientX - rect.left; state.offsetY = event.clientY - rect.top;
  state.originalOrder = tokenOrderFromDOM(state.container);
  state.ghost = state.chip.cloneNode(true);
  state.ghost.classList.remove('active'); state.ghost.classList.add('order-chip-ghost');
  state.ghost.removeAttribute('data-order-chip'); state.ghost.removeAttribute('id');
  state.ghost.style.width = `${rect.width}px`; state.ghost.style.height = `${rect.height}px`;
  document.body.appendChild(state.ghost);
  state.container.classList.add('is-sorting'); state.chip.classList.add('dragging');
};
const moveOrderGhost = event => {
  const x = event.clientX - orderDrag.offsetX, y = event.clientY - orderDrag.offsetY;
  orderDrag.ghost.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(1deg) scale(1.03)`;
};
const arrangeOrder = (container, order) => order.forEach(tokenId => {
  const chip = [...container.querySelectorAll('[data-order-chip]')].find(
    item => item.dataset.tokenId === String(tokenId));
  if (chip) container.appendChild(chip);
});
const finishOrderDrag = (commit = true) => {
  if (!orderDrag) return;
  const state = orderDrag;
  if (state.started) {
    if (!commit) {
      const first = captureChipRects(state.container);
      arrangeOrder(state.container, state.originalOrder);
      updateExcludedChips(state.container);
      animateChipReflow(state.container, first);
    }
    state.ghost?.remove(); state.chip.classList.remove('dragging');
    state.container.classList.remove('is-sorting');
    if (commit) {
      updateExcludedChips(state.container);
      localTextSequence = textSequenceFromDOM(state.container);
      localTokenOrder = tokenOrderFromDOM(state.container);
      renderSelection();
    }
  } else if (commit) {
    renderSelection();
  }
  orderDrag = null;
};

element.addEventListener('pointerdown', event => {
  if (pending) return;
  const isPan = event.button === 1 || (event.button === 0 && (spacePressed || (event.shiftKey && !event.target.closest('[data-box-id]'))));
  if (isPan) {
    const viewport = element.querySelector('.image-viewport');
    if (viewport) {
      moving = {
        kind: 'pan', viewport,
        startX: event.clientX, startY: event.clientY,
        scrollLeft: viewport.scrollLeft, scrollTop: viewport.scrollTop
      };
      element.setPointerCapture(event.pointerId);
      event.preventDefault();
      return;
    }
  }
  if (event.button !== 0) return;
  const chip = event.target.closest('[data-order-chip]');
  if (chip && props.value.step === 4) {
    orderDrag = {
      chip, container: chip.closest('.order-chips'), pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY, started: false
    };
    chip.setPointerCapture(event.pointerId); event.preventDefault(); return;
  }
  const svg = event.target.closest('.annotation-canvas'); if (!svg) return;
  const mode = props.value.step;
  const group = event.target.closest('[data-box-id]');
  const id = group?.dataset?.boxId || group?.getAttribute('data-box-id');
  const toggle = event.ctrlKey || event.metaKey;
  if ([3, 4, 5, 7].includes(mode)) {
    if (group) {
      if (toggle && mode === 3) {
        const next = new Set(selectedIds);
        if (next.has(id)) next.delete(id); else next.add(id);
        setSelection([...next], next.has(id) ? id : [...next].at(-1));
        event.preventDefault(); return;
      }
      if (!selectedIds.has(id)) setSelection([id], id);
      else { activeBoxId = id; renderSelection(); }
      if (mode !== 3) {
        event.preventDefault(); return;
      }
      const p = point(event, svg);
      const cornerAttr = event.target.getAttribute('data-corner') ?? event.target.dataset?.corner;
      if (cornerAttr !== null && cornerAttr !== undefined && cornerAttr !== '') {
        moving = { kind: 'resize', svg, id, corner: Number(cornerAttr), p, box: [...localBoxes[id].bbox] };
      } else {
        const ids = [...selectedIds];
        moving = {
          kind: 'drag', svg, p, ids, boxes: Object.fromEntries(ids.map(
            boxId => [boxId, [...localBoxes[boxId].bbox]]
          ))
        };
      }
    } else {
      if (mode === 4) { setSelection([], null); event.preventDefault(); return; }
      const p = point(event, svg);
      if (mode === 3 && event.altKey) {
        moving = { kind: 'add', svg, p, rect: createOverlayRect(svg, 'selection-marquee') };
      } else {
        moving = {
          kind: 'marquee', svg, p, baseline: toggle ? new Set(selectedIds) : new Set(),
          rect: createOverlayRect(svg, 'selection-marquee')
        };
        if (!toggle) setSelection([], null);
      }
    }
    svg.setPointerCapture(event.pointerId); event.preventDefault(); return;
  }

  if (mode !== 6) return;
  const p = point(event, svg);
  if (group) {
    moving = {
      kind: 'crop', svg, id: 'crop', p, box: [...localBoxes.crop.bbox],
      corner: event.target.getAttribute('data-corner') ?? event.target.dataset?.corner
    };
  } else {
    moving = { kind: 'crop-new', svg, p, rect: createOverlayRect(svg, 'selection-marquee') };
  }
  svg.setPointerCapture(event.pointerId); event.preventDefault();
});

element.addEventListener('pointermove', event => {
  if (orderDrag && event.pointerId === orderDrag.pointerId) {
    if (!orderDrag.started && Math.hypot(event.clientX - orderDrag.startX, event.clientY - orderDrag.startY) < 4) return;
    if (!orderDrag.started) beginOrderDrag(event);
    moveOrderGhost(event);
    const container = orderDrag.container;
    const reference = insertionReference(container, event.clientX, event.clientY);
    if (reference !== orderDrag.chip.nextElementSibling) {
      const first = captureChipRects(container);
      if (reference) container.insertBefore(orderDrag.chip, reference); else container.appendChild(orderDrag.chip);
      updateExcludedChips(container);
      animateChipReflow(container, first);
    }
    event.preventDefault(); return;
  }
  if (!moving) return;
  if (moving.kind === 'pan') {
    const dx = event.clientX - moving.startX;
    const dy = event.clientY - moving.startY;
    moving.viewport.scrollLeft = moving.scrollLeft - dx;
    moving.viewport.scrollTop = moving.scrollTop - dy;
    event.preventDefault();
    return;
  }
  if (moving.kind === 'image') {
    const width = Math.max(1, Math.round(moving.size[0] + (event.clientX - moving.start[0]) * moving.units[0]));
    const height = Math.max(1, Math.round(moving.size[1] + (event.clientY - moving.start[1]) * moving.units[1]));
    moving.result = [width, height]; drawImageResizePreview(moving, moving.result); return;
  }
  const state = moving, p = point(event, state.svg), dx = p.x - state.p.x, dy = p.y - state.p.y;
  const width = props.value.width, height = props.value.height;
  if (state.kind === 'marquee' || state.kind === 'add' || state.kind === 'crop-new') {
    const box = normalizedRect(state.p, p);
    state.result = box; drawOverlayRect(state.rect, box);
    if (state.kind === 'marquee') {
      const hits = Object.entries(localBoxes).filter(([, candidate]) => {
        const b = candidate.bbox;
        return b[0] <= box[2] && b[2] >= box[0] && b[1] <= box[3] && b[3] >= box[1];
      }).map(([id]) => id);
      setSelection([...new Set([...state.baseline, ...hits])], hits.at(-1) || [...state.baseline].at(-1), false);
    }
    return;
  }
  if (state.kind === 'drag') {
    const boxes = Object.values(state.boxes);
    const tx = Math.max(-Math.min(...boxes.map(b => b[0])), Math.min(dx, width - Math.max(...boxes.map(b => b[2]))));
    const ty = Math.max(-Math.min(...boxes.map(b => b[1])), Math.min(dy, height - Math.max(...boxes.map(b => b[3]))));
    state.result = {};
    state.ids.forEach(id => {
      const b = state.boxes[id];
      state.result[id] = [b[0] + tx, b[1] + ty, b[2] + tx, b[3] + ty];
      isDirty = true;
      drawLocalBox(id, state.result[id]);
    });
    return;
  }
  let box = [...state.box];
  if (state.kind === 'resize') {
    const corner = state.corner;
    if (corner === 0 || corner === 3) box[0] += dx; else box[2] += dx;
    if (corner === 0 || corner === 1) box[1] += dy; else box[3] += dy;
  } else if (state.kind === 'crop') {
    if (state.corner !== undefined) {
      const corner = Number(state.corner);
      if (corner === 0 || corner === 3) box[0] += dx; else box[2] += dx;
      if (corner === 0 || corner === 1) box[1] += dy; else box[3] += dy;
    } else {
      const tx = Math.max(-box[0], Math.min(dx, width - box[2]));
      const ty = Math.max(-box[1], Math.min(dy, height - box[3]));
      box = [box[0] + tx, box[1] + ty, box[2] + tx, box[3] + ty];
    }
  }
  box = box.map((value, index) => Math.max(0, Math.min(value, index % 2 ? height : width)));
  if (state.kind === 'resize' || (state.kind === 'crop' && state.corner !== undefined)) {
    const corner = Number(state.corner);
    if (corner === 0 || corner === 3) box[0] = Math.min(box[0], box[2] - 1); else box[2] = Math.max(box[2], box[0] + 1);
    if (corner === 0 || corner === 1) box[1] = Math.min(box[1], box[3] - 1); else box[3] = Math.max(box[3], box[1] + 1);
  }
  state.result = box;
  if (state.kind === 'resize') {
    isDirty = true;
    drawLocalBox(state.id, box);
  } else drawPreview(groupFor('crop'), box);
});

element.addEventListener('pointerup', event => {
  if (orderDrag && event.pointerId === orderDrag.pointerId) { finishOrderDrag(true); return; }
  if (!moving) return;
  const state = moving; moving = null;
  if (state.kind === 'marquee') {
    state.rect.remove(); syncExternalControls(); return;
  }
  if (state.kind === 'add') {
    const beforeIds = Object.keys(localBoxes);
    state.rect.remove();
    if (state.result && state.result[2] > state.result[0] && state.result[3] > state.result[1]) {
      const bbox = state.result;
      let newId;
      do { newId = `box_new_${nextTemporaryBoxId++}`; } while (localBoxes[newId]);
      localBoxes[newId] = { bbox: [...bbox], status: 'intact', unknown: false, order: null };
      localMismatchConfirmed = false;

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
      text.setAttribute('data-box-order-label', '1');
      const bw = bbox[2] - bbox[0], bh = bbox[3] - bbox[1];
      const unit = Math.max(props.value.width, props.value.height) / 900;
      const fontSize = Math.max(10 * unit, Math.min(bw, bh) * 0.30);
      const strokeWidth = Math.max(0.5, fontSize * 0.1);
      const centerX = (bbox[0] + bbox[2]) / 2;
      text.setAttribute('x', centerX);
      text.setAttribute('y', Math.max(fontSize, bbox[1] - 3 * unit));
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('fill', annotationColor);
      text.setAttribute('font-size', fontSize);
      text.setAttribute('stroke', '#17191c');
      text.setAttribute('stroke-width', strokeWidth);
      text.setAttribute('pointer-events', 'none');
      text.setAttribute('paint-order', 'stroke');
      group.appendChild(text);

      const corners = [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]];
      corners.forEach(([cx, cy], n) => {
        const handle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        handle.setAttribute('data-corner', n);
        handle.setAttribute('cx', cx); handle.setAttribute('cy', cy);
        handle.setAttribute('r', Math.max(10 * unit, 16));
        handle.setAttribute('fill', '#000');
        handle.setAttribute('stroke', 'none');
        handle.setAttribute('opacity', '0');
        handle.setAttribute('pointer-events', 'all');
        group.appendChild(handle);
      });

      svg.appendChild(group);

      isDirty = true;
      setSelection([newId], newId);
      traceTransition('ADD', beforeIds);
    }
    return;
  }
  if (state.kind === 'drag' && state.result) {
    const beforeIds = Object.keys(localBoxes);
    Object.entries(state.result).forEach(([id, box]) => {
      localBoxes[id].bbox = [...box];
    });
    isDirty = true;
    syncExternalControls(); traceTransition('MOVE', beforeIds); return;
  }
  if (state.kind === 'resize' && state.result && state.result[2] > state.result[0] && state.result[3] > state.result[1]) {
    const beforeIds = Object.keys(localBoxes);
    localBoxes[state.id].bbox = [...state.result];
    isDirty = true;
    syncExternalControls();
    traceTransition('RESIZE', beforeIds); return;
  }
  if (state.kind === 'crop-new') {
    state.rect.remove();
    if (state.result && state.result[2] > state.result[0] && state.result[3] > state.result[1]) {
      localBoxes.crop.bbox = [...state.result];
      drawPreview(groupFor('crop'), state.result);
      syncExternalControls();
    }
    return;
  }
  if (state.kind === 'crop' && state.result) {
    localBoxes.crop.bbox = [...state.result];
    syncExternalControls();
  }
});

element.addEventListener('pointercancel', () => {
  if (orderDrag) { finishOrderDrag(false); return; }
  if (!moving) return;
  const state = moving; moving = null;
  if (state.kind === 'drag') Object.entries(state.boxes).forEach(([id, box]) => drawLocalBox(id, box));
  else if (state.kind === 'resize') drawLocalBox(state.id, state.box);
  else if (state.kind === 'crop') drawPreview(groupFor('crop'), state.box);
  else state.rect?.remove();
  if (state.kind === 'marquee') setSelection([...state.baseline], [...state.baseline].at(-1));
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
  const snapshot = serializeLocalBoxes();
  console.info(navigateNext ? 'NEXT SNAPSHOT' : 'APPLY SNAPSHOT', {
    frontendCount: Object.keys(snapshot).length, frontendIDs: Object.keys(snapshot)
  });
  send(navigateNext ? 'next' : 'commit_boxes', {
    boxes: snapshot,
    orders: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.order])),
    statuses: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.status])),
    unknowns: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, Boolean(b.unknown)])),
    active: activeBoxId,
    selected: [...selectedIds],
  });
  return true;
};

root.addEventListener('click', event => {
  const nextBtn = event.target.closest('#next-button, #next-step, .next-button, [elem_id="next-button"]');
  if (nextBtn) {
    setSelection([], null);
  }
  const control = event.target.closest('[data-zoom]');
  if (control) {
    imageTransform.zoom = control.dataset.zoom === 'fit' ? 100 : Math.max(25, Math.min(300,
      imageTransform.zoom + (control.dataset.zoom === 'in' ? 25 : -25)));
    applyZoom(); return;
  }
  const deleteBtn = event.target.closest('#delete-box');
  if (deleteBtn) {
    event.preventDefault();
    event.stopPropagation();
    if (!selectedIds.size) return;
    const beforeIds = Object.keys(localBoxes);
    const deletedCount = selectedIds.size;
    selectedIds.forEach(id => {
      delete localBoxes[id];
      groupFor(id)?.remove();
    });
    selectedIds.clear();
    activeBoxId = null;
    localMismatchConfirmed = false;
    isDirty = true;
    renderSelection();
    traceTransition(`DELETE ${deletedCount}`, beforeIds);
    return;
  }
  const manualOrderContainer = event.target.closest('#manual-box-order');
  if (manualOrderContainer && !canEditReadingOrder()) {
    openMismatchConfirmModal('input');
    event.preventDefault();
    return;
  }
  const clearOrderBtn = event.target.closest('#clear-box-orders');
  if (clearOrderBtn) {
    if (!canEditReadingOrder()) {
      openMismatchConfirmModal('clear');
      event.preventDefault();
      return;
    }
    const modal = root.querySelector('#clear-order-modal');
    const msg = modal?.querySelector('#clear-modal-message');
    if (modal && msg) {
      if (selectedIds.size > 0) {
        msg.textContent = `Are you sure you want to clear the reading order for the ${selectedIds.size} selected box(es)?`;
      } else {
        msg.textContent = 'Are you sure you want to clear the reading order for ALL bounding boxes?';
      }
      modal.style.display = 'flex';
    }
    event.preventDefault();
    return;
  }
  const sortBtn = event.target.closest('#sort-boxes');
  if (sortBtn) {
    if (!canEditReadingOrder()) {
      openMismatchConfirmModal('sort');
      event.preventDefault();
      return;
    }
    if (!selectedIds.size) {
      console.log('SORT REQUEST', {
        frontendCount: Object.keys(localBoxes).length,
        frontendIDs: Object.keys(localBoxes)
      });
      send('sort_boxes_calc', {
        boxes: Object.fromEntries(Object.entries(localBoxes).map(([id, b]) => [id, b.bbox])),
        allBoxes: serializeLocalBoxes()
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
  const cancelMismatchModal = event.target.closest('#mismatch-modal-cancel');
  if (cancelMismatchModal) {
    const modal = root.querySelector('#mismatch-confirm-modal');
    if (modal) modal.style.display = 'none';
    pendingMismatchAction = null;
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
    console.log('SORT REQUEST (SELECTED)', {
      frontendCount: selectedIds.size,
      frontendIDs: [...selectedIds]
    });
    send('sort_boxes_calc', {
      boxes: Object.fromEntries([...selectedIds].map(id => [id, localBoxes[id].bbox])),
      allBoxes: serializeLocalBoxes(),
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
  const cancelClearModal = event.target.closest('#clear-modal-cancel');
  if (cancelClearModal) {
    const modal = root.querySelector('#clear-order-modal');
    if (modal) modal.style.display = 'none';
    event.preventDefault();
    return;
  }
  const confirmClearModal = event.target.closest('#clear-modal-confirm');
  if (confirmClearModal) {
    const beforeIds = Object.keys(localBoxes);
    const modal = root.querySelector('#clear-order-modal');
    if (modal) modal.style.display = 'none';
    const targetIds = selectedIds.size > 0 ? [...selectedIds] : Object.keys(localBoxes);
    targetIds.forEach(id => {
      if (localBoxes[id]) {
        localBoxes[id].order = null;
      }
    });
    const manualOrderInput = root.querySelector('#manual-box-order input');
    if (manualOrderInput) manualOrderInput.value = '';
    const errorEl = root.querySelector('#manual-box-order-error');
    if (errorEl) errorEl.textContent = '';
    isDirty = true;
    updateCanvasLabels();
    renderSelection();
    traceTransition('CLEAR ORDER', beforeIds);
    event.preventDefault();
    return;
  }
});

window.addEventListener('keydown', event => {
  if (event.key === 'Delete' || event.key === 'Backspace') {
    const activeElem = document.activeElement;
    if (activeElem && (activeElem.tagName === 'INPUT' || activeElem.tagName === 'TEXTAREA' || activeElem.isContentEditable)) {
      return;
    }
    if (!selectedIds.size) return;
    const beforeIds = Object.keys(localBoxes);
    const deletedCount = selectedIds.size;
    selectedIds.forEach(id => {
      delete localBoxes[id];
      groupFor(id)?.remove();
    });
    selectedIds.clear();
    activeBoxId = null;
    isDirty = true;
    renderSelection();
    traceTransition(`DELETE ${deletedCount}`, beforeIds);
    event.preventDefault();
  }
});

hydrateLocalState();
