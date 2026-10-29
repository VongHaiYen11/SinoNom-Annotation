// Pure editor operations; IDs never depend on display positions.
const workspaceCore = (() => {
  const clone = value => structuredClone(value);
  const active = model => model.entries.filter(entry => !entry.excluded);
  const derive = model => {
    const confirmedByChar=new Map(), counts=new Map();
    for (const [uid,id] of Object.entries(model.confirmed)) {
      counts.set(id,(counts.get(id)||0)+1);
      if (model.boxes[uid]) confirmedByChar.set(id,uid);
    }
    return {active:active(model), entries:new Map(model.entries.map(entry=>[entry.char_id,entry])),
      byOrder:new Map(Object.entries(model.boxes).map(([uid,box])=>[box.order,uid])),confirmedByChar,counts};
  };
  const suggested = (model, uid, lookup) => (lookup?.active || active(model))[model.boxes[uid]?.order - 1] || null;
  const related = (model, uid, lookup) => (lookup ? lookup.entries.get(model.confirmed[uid])
    : model.entries.find(entry => entry.char_id === model.confirmed[uid])) || suggested(model, uid, lookup);
  const relation = (model, uid, lookup) => {
    const id = model.confirmed[uid];
    if (!id) {
      const entry=suggested(model,uid,lookup);
      if (!entry) return 'Unaligned';
      return (lookup ? lookup.counts.get(entry.char_id)>0 : Object.entries(model.confirmed).some(([other,value])=>other!==uid && value===entry.char_id)) ? 'Conflict' : 'Suggested';
    }
    const entry = lookup ? lookup.entries.get(id) : model.entries.find(item => item.char_id === id);
    const duplicate = lookup ? lookup.counts.get(id)>1 : Object.values(model.confirmed).filter(value => value === id).length > 1;
    return !entry || entry.excluded || suggested(model, uid, lookup)?.char_id !== id || duplicate ? 'Conflict' : 'Confirmed';
  };
  const frame = model => clone(Object.fromEntries(
    ['entries','boxes','confirmed','selected_box','selected_char','selected_boxes'].map(key => [key, model[key]])));
  const trimHistory = model => {
    // Full editor frames keep undo atomic; bound their storage cost for long inscriptions.
    for (const key of ['undo','redo']) {
      while (model[key].length>1 && JSON.stringify(model[key]).length>750000) model[key].shift();
    }
  };
  const mutate = (model, action) => {
    model.undo = [...(model.undo || []), frame(model)].slice(-50);
    model.redo = [];
    action(model);
    model.version = (model.version || 0) + 1;
    trimHistory(model);
  };
  const history = (model, direction) => {
    const from = direction === 'undo' ? 'undo' : 'redo';
    const to = direction === 'undo' ? 'redo' : 'undo';
    if (!model[from]?.length) return false;
    const target = model[from].pop();
    model[to] = [...(model[to] || []), frame(model)].slice(-50);
    Object.assign(model, clone(target));
    model.version = (model.version || 0) + 1;
    trimHistory(model);
    return true;
  };
  const reorder = (model, uid, position) => {
    if (!Number.isInteger(position) || position < 1 || position > Object.keys(model.boxes).length) {
      model.boxes[uid].order = null;
      return;
    }
    const ids = Object.keys(model.boxes).filter(id => id !== uid)
      .sort((a,b) => (model.boxes[a].order || Infinity) - (model.boxes[b].order || Infinity));
    ids.splice(position-1, 0, uid);
    ids.forEach((id,index) => {model.boxes[id].order = index+1;});
  };
  const insertMiss = (model, id, side, newId) => {
    const index = model.entries.findIndex(entry => entry.char_id === id);
    if (index < 0) return;
    model.entries.splice(index + (side === 'right' ? 1 : 0), 0,
      {char_id:newId, value:'MISS', source_index:null, type:'missing', excluded:false});
    model.selected_char = newId;
  };
  const rules = (box, character) => {
    const result = clone(box);
    if (character === '□') Object.assign(result, {status:'damaged', unknown:true,
      unavailable_font:false, expert_prediction:false, suspicious:false});
    if (character === '@') Object.assign(result, {unknown:false, unavailable_font:true});
    if (character === 'MISS') Object.assign(result, {unknown:false, unavailable_font:false,
      expert_prediction:false, suspicious:false});
    if (result.status !== 'damaged') {result.damage_level=null; result.unknown=false;}
    return result;
  };
  const confirm = (model, uid) => {
    const entry = suggested(model, uid);
    if (!entry) throw Error('This box has no suggested character.');
    if (Object.entries(model.confirmed).some(([other,id]) => other !== uid && id === entry.char_id)) {
      throw Error('This character is confirmed with another box. Remove that confirmation first.');
    }
    const box = rules(model.boxes[uid], entry.value);
    if (!['intact','damaged'].includes(box.status)) throw Error('Assign intact or damaged before confirming.');
    if (box.status === 'damaged' && ![1,2,3].includes(box.damage_level)) {
      throw Error('Select damage level 1, 2 or 3 before confirming.');
    }
    if (box.unknown && (box.unavailable_font || box.expert_prediction || box.suspicious)) {
      throw Error('Unknown cannot coexist with font, expert or suspicious flags.');
    }
    model.boxes[uid] = box;
    model.confirmed[uid] = entry.char_id;
  };
  return {active, derive, suggested, related, relation, frame, mutate, history, reorder, insertMiss, rules, confirm};
})();

// Browser host. Geometry previews stay local until the pointer operation ends.
// The template children are replaced by Gradio on value updates; delegate to
// the stable component element so callbacks never retain a detached root.
const host = element;
host.classList.add('unified-workspace');
let payload = props.value, model = null, context = '', selectedMenu = null, derived = null;
let pending = false, blocking = false, queuedAction = null, syncTimer = null, scrollTimer = null, drawing = false, gesture = null, panning = false;
let issues = [], report = '', controller = new AbortController(), referenceObserver = null;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const panelIcon = '<svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2" y="3" width="16" height="14" rx="2"/><path d="M8 3v14m5-10-3 3 3 3"/></svg>';
const running = () => payload?.step === 3 && !!model && host?.isConnected;
const recovery = () => window.vietnamicaDraftRecovery;
const persist = () => {if (running()) recovery()?.write(payload.recovery, {workspace:structuredClone(model)});};
const checkpoint = (action='checkpoint', extra={}) => {
  clearTimeout(syncTimer);
  if (!running()) return;
  if (pending) {if(action!=='checkpoint') queuedAction={action,extra};return;}
  pending = true;
  blocking = action !== 'checkpoint';
  host.inert=blocking;
  trigger('action', {action, model:structuredClone(model), ...extra});
};
const schedule = () => {persist(); clearTimeout(syncTimer); syncTimer=setTimeout(() => checkpoint(),250);};
const hint = message => {
  const target = host?.querySelector('.u-message');
  if (target) {target.textContent=message; target.hidden=!message;}
};
const viewport = () => host.querySelector('.u-viewport');
const preserveViewport = () => {
  const view = viewport();
  return view ? {left:view.scrollLeft,top:view.scrollTop} : {left:0,top:0};
};
const selectedBox = () => model.boxes[model.selected_box];
const chooseBox = (uid, multi=false, reveal=true) => {
  if (!model.boxes[uid]) return;
  if (multi) {
    const set=new Set(model.selected_boxes || []);
    set.has(uid) ? set.delete(uid) : set.add(uid);
    model.selected_boxes=[...set];
  } else model.selected_boxes=[uid];
  model.selected_box=uid;
  model.selected_char=workspaceCore.related(model,uid)?.char_id || null;
  model.version=(model.version || 0)+1;
  render(); schedule();
  if (reveal && model.preferences.reference_open) {revealReference();persist();}
};
const chooseChar = id => {
  model.selected_char=id;
  const entry=model.entries.find(item=>item.char_id===id);
  const confirmed=Object.keys(model.confirmed).find(uid=>model.confirmed[uid]===id && model.boxes[uid]);
  const index=workspaceCore.active(model).findIndex(item=>item.char_id===id)+1;
  const suggested=!entry?.excluded && Object.keys(model.boxes).find(uid=>model.boxes[uid].order===index);
  model.selected_box=confirmed || suggested || null;
  model.selected_boxes=model.selected_box ? [model.selected_box] : [];
  model.version=(model.version || 0)+1;
  render(); schedule();
};
const edit = action => {
  if (blocking) {hint('Please wait for the current update.');return false;}
  const previous=model.selected_char;
  workspaceCore.mutate(model,action);
  if (model.boxes[model.selected_box]) model.selected_char=workspaceCore.related(model,model.selected_box)?.char_id || null;
  issues=[]; report=''; render();
  if (model.preferences.reference_open && (model.selected_box || previous!==model.selected_char)) revealReference();
  schedule(); return true;
};
const revealReference = () => {
  const card=[...host.querySelectorAll('[data-char]')].find(item=>item.dataset.char===model.selected_char);
  const list=host.querySelector('.u-content-list');
  if (!card || !list) return;
  const a=card.getBoundingClientRect(), b=list.getBoundingClientRect();
  if (a.top<b.top || a.bottom>b.bottom) list.scrollTop += a.top-b.top-b.height/2+a.height/2;
  model.preferences.reference_scroll=list.scrollTop;
};
const focusBox = () => {
  const uid=model.selected_box;
  const group=[...host.querySelectorAll('[data-region]')].find(item=>item.dataset.region===uid);
  if (!group) {hint('Select a box to focus.');return;}
  const view=viewport(), a=group.getBoundingClientRect(), b=view.getBoundingClientRect();
  view.scrollLeft += a.left+a.width/2-b.left-b.width/2;
  view.scrollTop += a.top+a.height/2-b.top-b.height/2;
};
const cardsMarkup = () => {
  let index=0;
  return model.entries.map(entry=>{
    const effective=entry.excluded ? '—' : ++index;
    const uid=derived.confirmedByChar.get(entry.char_id);
    const box=uid || (!entry.excluded && derived.byOrder.get(effective));
    const state=entry.excluded ? (uid ? 'Conflict' : 'Excluded') : box ? workspaceCore.relation(model,box,derived) : 'Unaligned';
    return `<div class="u-card ${state.toLowerCase()} ${entry.char_id===model.selected_char?'selected':''}" data-char="${esc(entry.char_id)}">
      <button type="button" class="u-char-select" data-action="char" aria-pressed="${entry.char_id===model.selected_char}" aria-label="Character ${effective}: ${esc(entry.value)}, ${state}">
      <span class="u-index">${effective}</span><span class="u-glyph">${esc(entry.value)}</span>
      <span class="u-relation">${state==='Confirmed'?'✓ ':''}${state}</span></button>
      <button type="button" class="u-card-menu" data-action="menu" title="Character actions" aria-label="Character actions">⋯</button></div>`;
  }).join('');
};
const svgMarkup = () => {
  const [width,height]=payload.size;
  const unit=Math.max(width,height)/900;
  return `<svg class="u-canvas" viewBox="0 0 ${width} ${height}" style="width:${model.preferences.zoom}%" aria-label="Document annotation canvas">
    <image href="${esc(payload.image_url)}" width="${width}" height="${height}"/>
    ${Object.entries(model.boxes).map(([uid,box])=>{
      const [x1,y1,x2,y2]=box.bbox, chosen=uid===model.selected_box;
      const selected=(model.selected_boxes || []).includes(uid);
      const relation=workspaceCore.relation(model,uid,derived), entry=workspaceCore.related(model,uid,derived);
      const color=relation==='Conflict'?'#fb923c':box.suspicious?'#facc15':box.unavailable_font?'#ec4899':box.expert_prediction?'#facc15':box.status==='damaged'?'#ef4444':'#22c55e';
      const opacity=chosen || selected || !model.selected_box || model.preferences.visibility==='all' ? 1 : model.preferences.visibility==='selected' ? 0 : .2;
      const labelSize=Math.max(11*unit,Math.min(x2-x1,y2-y1)*.3);
      return `<g data-region="${esc(uid)}" style="opacity:${opacity};pointer-events:${opacity===0?'none':'auto'}" class="${chosen?'u-active':''}">
        <title>${box.order ?? 'Unnumbered'} · ${esc(entry?.value || 'Unaligned')} · ${relation}</title>
        <rect x="${x1}" y="${y1}" width="${x2-x1}" height="${y2-y1}" fill="${color}" fill-opacity="${chosen ? .18 : .04}" stroke="${color}" stroke-width="${chosen?3:1.5}" vector-effect="non-scaling-stroke"/>
        <text x="${x1}" y="${Math.max(labelSize,y1-3*unit)}" font-size="${labelSize}" fill="${color}" stroke="#17191c" stroke-width="${labelSize*.08}" paint-order="stroke" pointer-events="none">${box.order ?? '?'} ${esc(entry?.value || '')}</text>
        ${box.unknown?`<text x="${(x1+x2)/2}" y="${(y1+y2)/2}" font-size="${Math.min(x2-x1,y2-y1)*.75}" fill="#ef4444" text-anchor="middle" dominant-baseline="central" pointer-events="none">?</text>`:''}
        ${entry?.value==='MISS'?`<path d="M${x1} ${y1}L${x2} ${y2}M${x2} ${y1}L${x1} ${y2}" stroke="#ef4444" stroke-width="2" vector-effect="non-scaling-stroke" pointer-events="none"/>`:''}
        ${chosen?[[x1,y1],[x2,y1],[x2,y2],[x1,y2]].map(([x,y],corner)=>`<circle data-corner="${corner}" cx="${x}" cy="${y}" r="${Math.max(5*unit,8)}" fill="#fff" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`).join(''):''}</g>`;
    }).join('')}</svg>`;
};
const inspectorMarkup = () => {
  const uid=model.selected_box, box=model.boxes[uid];
  if (!box) return `<h3>Selected Box</h3><p>Select a box or draw a new one.</p><p>${model.selected_char?'This content entry has no corresponding box.':''}</p>`;
  const entry=workspaceCore.related(model,uid,derived), suggestion=workspaceCore.suggested(model,uid,derived);
  return `<h3>Selected Box</h3><small class="u-id" title="${esc(uid)}">${esc(uid)}</small>
    <label>Reading order<input data-field="order" type="number" min="1" max="${Object.keys(model.boxes).length}" value="${box.order ?? ''}"/></label>
    <div class="u-assignment"><span class="u-large-glyph">${esc(entry?.value || '—')}</span><span>${workspaceCore.relation(model,uid)}</span></div>
    ${workspaceCore.relation(model,uid)==='Conflict'?`<p class="u-conflict">Suggested: ${esc(suggestion?.value || 'Unaligned')}</p><button type="button" data-action="use-suggestion">Use Suggested Alignment</button>`:''}
    <button type="button" data-action="reveal">Reveal in Reference</button>
    <fieldset><legend>Status</legend>${['intact','damaged'].map(value=>`<label class="u-inline"><input type="radio" name="u-status" data-field="status" value="${value}" ${box.status===value?'checked':''}/> ${value==='intact'?'Intact':'Damaged'}</label>`).join('')}</fieldset>
    <fieldset><legend>Damage level</legend>${[1,2,3].map(value=>`<label class="u-inline"><input type="radio" name="u-level" data-field="damage_level" value="${value}" ${box.damage_level===value?'checked':''} ${box.status!=='damaged'?'disabled':''}/> ${value}</label>`).join('')}</fieldset>
    ${[['unknown','Unknown'],['unavailable_font','Unavailable Font'],['expert_prediction','Expert Prediction'],['suspicious','Suspicious']].map(([key,label])=>`<label class="u-check"><input type="checkbox" data-field="${key}" ${box[key]?'checked':''}/> ${label}</label>`).join('')}
    <details><summary>Coordinates</summary>${['x1','y1','x2','y2'].map((key,index)=>`<label>${key}<input type="number" data-coordinate="${index}" value="${box.bbox[index]}"/></label>`).join('')}</details>
    <button type="button" data-action="confirm">Confirm Alignment</button>
    <button type="button" class="u-primary" data-action="confirm-next">Confirm &amp; Next</button>
    ${model.confirmed[uid]?'<button type="button" data-action="unconfirm">Remove Confirmation</button>':''}
    <button type="button" data-action="delete" class="u-danger">Delete Box</button>`;
};
const render = () => {
  if (!running()) return;
  derived=workspaceCore.derive(model);
  const savedView=preserveViewport();
  const oldList=host.querySelector('.u-content-list');
  if (oldList) model.preferences.reference_scroll=oldList.scrollTop;
  const prefs=model.preferences, n=Object.keys(model.boxes).length;
  const confirmed=Object.keys(model.boxes).filter(uid=>workspaceCore.relation(model,uid,derived)==='Confirmed').length;
  const conflicts=Object.keys(model.boxes).filter(uid=>workspaceCore.relation(model,uid,derived)==='Conflict').length;
  host.innerHTML=`<div class="u-workbench ${prefs.reference_open?'':'u-reference-closed'}">
    <aside class="u-reference" style="width:${prefs.reference_open?prefs.reference_width:44}px">
      <header><h3>Reference Content</h3><button type="button" class="u-icon" data-action="toggle-reference" title="${prefs.reference_open?'Hide Reference':'Show Reference'}" aria-label="${prefs.reference_open?'Hide Reference':'Show Reference'}">${panelIcon}</button></header>
      <div class="u-reference-body"><label class="u-jump">Go to character<input type="number" min="1" data-jump="character" placeholder="Number + Enter"/></label>
      <div class="u-content-list">${cardsMarkup()}</div></div>
    </aside>
    <section class="u-image-panel"><div class="u-toolbar">
      <button type="button" data-action="draw" aria-pressed="${drawing}">${drawing?'Drawing…':'Draw Box'}</button>
      <button type="button" data-action="sort">Sort Boxes</button>
      <button type="button" data-action="detect" ${!payload.can_detect?'disabled':''}>Run Detection</button>
      <button type="button" data-action="undo" ${!model.undo?.length?'disabled':''} title="Undo (Ctrl/Cmd+Z)">↶</button>
      <button type="button" data-action="redo" ${!model.redo?.length?'disabled':''} title="Redo (Ctrl/Cmd+Shift+Z)">↷</button>
      <button type="button" data-action="zoom-out" aria-label="Zoom out">−</button><span>${prefs.zoom}%</span><button type="button" data-action="zoom-in" aria-label="Zoom in">+</button>
      <button type="button" data-action="fit">Fit</button><button type="button" data-action="focus">Focus</button>
      <select data-field="visibility" aria-label="Show boxes"><option value="all" ${prefs.visibility==='all'?'selected':''}>All Boxes</option><option value="dim" ${prefs.visibility==='dim'?'selected':''}>Dim Others</option><option value="selected" ${prefs.visibility==='selected'?'selected':''}>Selected Only</option></select>
      <label class="u-jump">Box<input type="number" min="1" data-jump="box" placeholder="Number + Enter"/></label>
    </div><p class="u-help">Alt + drag to draw · Drag to move · Corner handles to resize · Shift + click to select multiple · Space + drag to pan</p>
    <div class="u-message" role="status" hidden></div>
    <div class="u-viewport ${drawing?'u-drawing':''}">${svgMarkup()}</div></section>
    <aside class="u-inspector">${inspectorMarkup()}</aside>
    <footer class="u-workspace-footer"><span>Confirmed ${confirmed}/${n} · Active entries ${workspaceCore.active(model).length} · Conflicts ${conflicts}</span>
      <button type="button" data-action="confirm-selected">Confirm Selected</button><button type="button" data-action="confirm-all">Confirm All Suggestions</button>
      <button type="button" data-action="next-unresolved">Next Unresolved</button><button type="button" class="u-primary" data-action="continue">Continue</button></footer>
    <div class="u-menu" role="menu" hidden></div>
    <dialog class="u-issues" aria-labelledby="u-issues-title"><h2 id="u-issues-title">Cannot Continue</h2><p>${issues.length} issue${issues.length===1?'':'s'} must be resolved.</p>
      <ol>${issues.map((issue,index)=>`<li><button type="button" data-issue="${index}">${issue.reading_order ? `Box ${issue.reading_order}: `:''}${esc(issue.reason)}</button></li>`).join('')}</ol>
      <div class="u-dialog-actions"><button type="button" data-action="download-issues">Download Issues (.txt)</button><button type="button" class="u-primary" data-action="close-issues">Back to Annotation</button></div></dialog>
    </div>`;
  viewport().scrollLeft=savedView.left; viewport().scrollTop=savedView.top;
  const list=host.querySelector('.u-content-list');
  list.scrollTop=prefs.reference_scroll || 0;
  referenceObserver?.disconnect();
  referenceObserver=new ResizeObserver(()=>{
    if (!running() || !model.preferences.reference_open) return;
    const width=Math.round(host.querySelector('.u-reference').getBoundingClientRect().width);
    if (width>=220 && width!==model.preferences.reference_width) {
      model.preferences.reference_width=width; schedule();
    }
  });
  referenceObserver.observe(host.querySelector('.u-reference'));
};
const openMenu = (id,x,y) => {
  selectedMenu=id;
  const entry=model.entries.find(item=>item.char_id===id), menu=host.querySelector('.u-menu');
  menu.innerHTML=`<button type="button" role="menuitem" data-action="miss-left">Add MISS to Left</button><button type="button" role="menuitem" data-action="miss-right">Add MISS to Right</button><hr/><button type="button" role="menuitem" data-action="exclude">${entry.excluded?'Include in Alignment':'Exclude from Alignment'}</button>${entry.type==='missing'?'<button type="button" role="menuitem" data-action="remove-miss">Remove MISS</button>':''}`;
  menu.hidden=false;
  menu.style.left=`${Math.max(8,Math.min(x,window.innerWidth-245))}px`;
  menu.style.top=`${Math.max(8,Math.min(y,window.innerHeight-menu.offsetHeight-8))}px`;
  menu.querySelector('button')?.focus();
};
const confirmBoxes = (ids,next=false) => {
  if (!ids.length) {hint('Select at least one box.');return;}
  const candidate=structuredClone(model), changes=[];
  try {
    for (const uid of ids) {
      const box=candidate.boxes[uid], entry=workspaceCore.suggested(candidate,uid);
      const updated=entry && workspaceCore.rules(box,entry.value);
      if (updated && ['status','unknown','unavailable_font','expert_prediction','suspicious','damage_level'].some(key=>box[key]!==updated[key])) {
        changes.push(`Box ${box.order}: apply ${entry.value} character rules`);
      }
      workspaceCore.confirm(candidate,uid);
    }
    if (changes.length && !window.confirm(`${changes.join('\n')}\n\nApply these mandatory annotation rules?`)) return;
    const changed=edit(current=>{current.boxes=candidate.boxes;current.confirmed=candidate.confirmed;});
    if (changed && next) nextUnresolved();
  } catch (error) {hint(error.message);}
};
const nextUnresolved = () => {
  const ids=Object.keys(model.boxes).sort((a,b)=>(model.boxes[a].order || Infinity)-(model.boxes[b].order || Infinity));
  const after=ids.indexOf(model.selected_box)+1;
  const uid=[...ids.slice(after),...ids.slice(0,after)].find(id=>workspaceCore.relation(model,id)!=='Confirmed'
    || !['intact','damaged'].includes(model.boxes[id].status)
    || (model.boxes[id].status==='damaged' && ![1,2,3].includes(model.boxes[id].damage_level)));
  if (uid) chooseBox(uid); else hint('No unresolved box alignments. Continue to validate all content entries.');
};
const downloadReport = () => {
  const url=URL.createObjectURL(new Blob([report],{type:'text/plain;charset=utf-8'}));
  const a=document.createElement('a'); a.href=url;
  a.download=`${payload.image.replace(/\.[^.]+$/,'')}-annotation-issues.txt`;
  document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
host.addEventListener('click',event=>{
  if (!running()) return;
  const issue=event.target.closest('[data-issue]');
  if (issue) {
    const item=issues[Number(issue.dataset.issue)];host.querySelector('dialog').close();
    if (item.box_id && model.boxes[item.box_id]) {chooseBox(item.box_id);focusBox();}
    else if (item.char_id) {model.preferences.reference_open=true;chooseChar(item.char_id);revealReference();}
    return;
  }
  const button=event.target.closest('[data-action]');
  if (!button) return;
  const action=button.dataset.action, uid=model.selected_box;
  if (action==='menu') {const rect=button.getBoundingClientRect();openMenu(button.closest('[data-char]').dataset.char,rect.left,rect.bottom);return;}
  host.querySelector('.u-menu').hidden=true;
  if (action==='char') {chooseChar(button.closest('[data-char]').dataset.char);return;}
  if (action==='toggle-reference') {model.preferences.reference_open=!model.preferences.reference_open;render();if(model.preferences.reference_open) revealReference();schedule();}
  if (action==='reveal') {model.preferences.reference_open=true;render();revealReference();schedule();}
  if (action==='focus') focusBox();
  if (action==='draw') {drawing=!drawing;render();}
  if (['zoom-in','zoom-out','fit'].includes(action)) {
    model.preferences.zoom=action==='fit'?100:Math.max(25,Math.min(500,model.preferences.zoom+(action==='zoom-in'?15:-15)));render();schedule();
  }
  if (['undo','redo'].includes(action) && !blocking && workspaceCore.history(model,action)) {issues=[];render();schedule();}
  if (['miss-left','miss-right'].includes(action)) edit(current=>workspaceCore.insertMiss(current,selectedMenu,action==='miss-left'?'left':'right',crypto.randomUUID()));
  if (action==='exclude') edit(current=>{const entry=current.entries.find(item=>item.char_id===selectedMenu);entry.excluded=!entry.excluded;});
  if (action==='remove-miss') edit(current=>{current.entries=current.entries.filter(entry=>entry.char_id!==selectedMenu || entry.type!=='missing');});
  if (action==='unconfirm' && uid) edit(current=>{delete current.confirmed[uid];});
  if (action==='delete') deleteSelected();
  if (action==='confirm' || action==='use-suggestion') confirmBoxes(uid?[uid]:[]);
  if (action==='confirm-next') confirmBoxes(uid?[uid]:[],true);
  if (action==='confirm-selected') confirmBoxes((model.selected_boxes || []).filter(id=>model.boxes[id]));
  if (action==='confirm-all' && window.confirm('Confirm all suggested pairs and apply any mandatory character rules?')) confirmBoxes(Object.keys(model.boxes));
  if (action==='next-unresolved') nextUnresolved();
  if (action==='continue') checkpoint('continue');
  if (action==='sort' && !pending && window.confirm('Recalculate reading order for all boxes? Confirmed relationships will be kept and conflicts flagged.')) {
    workspaceCore.mutate(model,()=>{});persist();checkpoint('sort');
  }
  if (action==='detect' && !pending && window.confirm('Run detection and replace existing boxes? Existing box confirmations will be removed.')) checkpoint('detect');
  if (action==='download-issues') downloadReport();
  if (action==='close-issues') host.querySelector('dialog').close();
},{signal:controller.signal});
host.addEventListener('contextmenu',event=>{
  const card=event.target.closest('[data-char]');
  if (card) {event.preventDefault();openMenu(card.dataset.char,event.clientX,event.clientY);}
},{signal:controller.signal});
host.addEventListener('scroll',event=>{
  if (!running() || !event.target.matches?.('.u-content-list')) return;
  model.preferences.reference_scroll=event.target.scrollTop;
  clearTimeout(scrollTimer);scrollTimer=setTimeout(persist,150);
},{capture:true,signal:controller.signal});
host.addEventListener('change',event=>{
  if (!running()) return;
  const field=event.target.dataset.field;
  if (field==='visibility') {model.preferences.visibility=event.target.value;render();schedule();return;}
  if (!selectedBox()) return;
  if (field) edit(current=>{
    const box=current.boxes[current.selected_box];
    if (field==='order') {
      workspaceCore.reorder(current,current.selected_box,Number(event.target.value));
      current.selected_char=workspaceCore.suggested(current,current.selected_box)?.char_id || null;
      return;
    }
    if (field==='status') {box.status=event.target.value;if (box.status==='intact') {box.damage_level=null;box.unknown=false;}}
    else if (field==='damage_level') box.damage_level=Number(event.target.value);
    else {
      box[field]=event.target.checked;
      if (box[field] && field==='unknown') Object.assign(box,{status:'damaged',unavailable_font:false,expert_prediction:false,suspicious:false});
      else if (box[field]) {box.unknown=false;if (field==='expert_prediction') box.status='damaged';}
    }
  });
  if (event.target.dataset.coordinate !== undefined) {
    const bbox=[...host.querySelectorAll('[data-coordinate]')].map(input=>Number(input.value));
    if (bbox.every(Number.isFinite) && bbox[0]>=0 && bbox[1]>=0 && bbox[2]>bbox[0] && bbox[3]>bbox[1]
        && bbox[2]<=payload.size[0] && bbox[3]<=payload.size[1]) edit(current=>{current.boxes[current.selected_box].bbox=bbox;});
    else hint('Coordinates must form a non-empty box inside the image.');
  }
},{signal:controller.signal});
const deleteSelected = () => {
  const ids=(model.selected_boxes?.length?model.selected_boxes:[model.selected_box]).filter(uid=>model.boxes[uid]);
  if (!ids.length) return;
  edit(current=>{
    ids.forEach(uid=>{delete current.boxes[uid];delete current.confirmed[uid];});
    const ordered=Object.keys(current.boxes).sort((a,b)=>(current.boxes[a].order || Infinity)-(current.boxes[b].order || Infinity));
    ordered.forEach((uid,index)=>{current.boxes[uid].order=index+1;});
    current.selected_box=null;current.selected_boxes=[];
  });
};
const imagePoint = event => {
  const svg=host.querySelector('.u-canvas'), point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
  const value=point.matrixTransform(svg.getScreenCTM().inverse());
  return [Math.max(0,Math.min(payload.size[0],value.x)),Math.max(0,Math.min(payload.size[1],value.y))];
};
host.addEventListener('pointerdown',event=>{
  if (!running() || blocking || !event.target.closest('.u-canvas') || ![0,1].includes(event.button)) return;
  event.preventDefault();
  if (panning || event.button===1) {
    gesture={kind:'pan',client:[event.clientX,event.clientY],...preserveViewport()};host.setPointerCapture(event.pointerId);return;
  }
  const group=event.target.closest('[data-region]'), point=imagePoint(event);
  if (drawing || event.altKey) {
    gesture={kind:'add',point};
  } else if (group) {
    const uid=group.dataset.region, corner=event.target.dataset.corner;
    if (event.shiftKey) {chooseBox(uid,true);return;}
    chooseBox(uid,false);
    gesture={kind:corner===undefined?'move':'resize',uid,corner:Number(corner),point,bbox:[...model.boxes[uid].bbox]};
  } else {model.selected_box=null;model.selected_boxes=[];render();schedule();return;}
  host.setPointerCapture(event.pointerId);
},{signal:controller.signal});
host.addEventListener('pointermove',event=>{
  if (!gesture) return;
  if (gesture.kind==='pan') {viewport().scrollLeft=gesture.left+gesture.client[0]-event.clientX;viewport().scrollTop=gesture.top+gesture.client[1]-event.clientY;return;}
  const at=imagePoint(event), [width,height]=payload.size;
  let bbox;
  if (gesture.kind==='add') bbox=[Math.min(at[0],gesture.point[0]),Math.min(at[1],gesture.point[1]),Math.max(at[0],gesture.point[0]),Math.max(at[1],gesture.point[1])];
  else if (gesture.kind==='move') {
    const old=gesture.bbox, dx=Math.max(-old[0],Math.min(width-old[2],at[0]-gesture.point[0])),dy=Math.max(-old[1],Math.min(height-old[3],at[1]-gesture.point[1]));
    bbox=[old[0]+dx,old[1]+dy,old[2]+dx,old[3]+dy];
  } else {
    bbox=[...gesture.bbox];const corner=gesture.corner;
    bbox[corner===0 || corner===3 ? 0:2]=at[0];bbox[corner<2?1:3]=at[1];
  }
  gesture.result=bbox;
  let preview=host.querySelector('.u-geometry-preview');
  if (!preview) {preview=document.createElementNS('http://www.w3.org/2000/svg','rect');preview.classList.add('u-geometry-preview');host.querySelector('.u-canvas').appendChild(preview);}
  ['x','y','width','height'].forEach((key,index)=>preview.setAttribute(key,[bbox[0],bbox[1],Math.max(0,bbox[2]-bbox[0]),Math.max(0,bbox[3]-bbox[1])][index]));
},{signal:controller.signal});
host.addEventListener('pointerup',event=>{
  if (!gesture) return;
  const state=gesture;gesture=null;host.querySelector('.u-geometry-preview')?.remove();
  if (host.hasPointerCapture(event.pointerId)) host.releasePointerCapture(event.pointerId);
  if (state.kind==='pan' || !state.result || state.result[2]<=state.result[0] || state.result[3]<=state.result[1]) return;
  if (state.kind==='add') {
    const uid=crypto.randomUUID();
    if (edit(current=>{
      current.boxes[uid]={bbox:state.result,order:Object.keys(current.boxes).length+1,status:'intact',damage_level:null,
        unknown:false,unavailable_font:false,expert_prediction:false,suspicious:false};
      current.selected_box=uid;current.selected_boxes=[uid];
    })) {drawing=false;checkpoint('insert',{box_id:uid});}
  } else edit(current=>{current.boxes[state.uid].bbox=state.result;});
},{signal:controller.signal});
host.addEventListener('pointercancel',()=>{gesture=null;host.querySelector('.u-geometry-preview')?.remove();},{signal:controller.signal});
host.addEventListener('wheel',event=>{
  if (!running() || !event.ctrlKey || !event.target.closest('.u-viewport')) return;
  event.preventDefault();model.preferences.zoom=Math.max(25,Math.min(500,model.preferences.zoom+(event.deltaY<0?10:-10)));render();schedule();
},{passive:false,signal:controller.signal});
window.vietnamicaWorkspaceController?.abort();
window.vietnamicaWorkspaceController=controller;
window.addEventListener('keydown',event=>{
  if (!running() || blocking) return;
  const typing=event.target.closest('input,textarea,select,[contenteditable=true]');
  if (event.key==='Enter' && event.target.dataset.jump) {
    event.preventDefault();const index=Number(event.target.value);
    if (event.target.dataset.jump==='character') {
      const entry=workspaceCore.active(model)[index-1];if (entry) {chooseChar(entry.char_id);revealReference();}else hint('Character number is outside the active sequence.');
    } else {const uid=Object.keys(model.boxes).find(key=>model.boxes[key].order===index);if (uid) chooseBox(uid);else hint('No box has that reading order.');}
    return;
  }
  if (typing) return;
  if (event.code==='Space') {panning=true;event.preventDefault();}
  if ((event.ctrlKey || event.metaKey) && ['z','y'].includes(event.key.toLowerCase())) {
    event.preventDefault();const direction=event.key.toLowerCase()==='y' || event.shiftKey?'redo':'undo';
    if (!blocking && workspaceCore.history(model,direction)) {issues=[];render();schedule();}
  } else if (['Delete','Backspace'].includes(event.key)) {event.preventDefault();deleteSelected();}
  else if (event.key==='Escape') {host.querySelector('.u-menu').hidden=true;drawing=false;gesture=null;render();}
  else if (event.key==='Enter' && model.selected_box) {event.preventDefault();confirmBoxes([model.selected_box],true);}
},{signal:controller.signal});
window.addEventListener('keyup',event=>{if(event.code==='Space') panning=false;},{signal:controller.signal});
window.addEventListener('pagehide',persist,{signal:controller.signal});
const load = () => {
  const previousContext=context, previousChar=model?.selected_char;
  payload=props.value;
  if (!payload?.model || payload.step!==3) {clearTimeout(syncTimer);pending=false;blocking=false;queuedAction=null;host.inert=false;host.innerHTML='';return;}
  const nextContext=JSON.stringify([payload.recovery?.application,payload.recovery?.tab,payload.image,payload.recovery?.generation]);
  const incoming=payload.model, recovering=recovery()?.read(payload.recovery)?.workspace;
  if (nextContext!==context) {
    context=nextContext;
    const originals=value=>value.entries.filter(entry=>entry.type==='original').map(entry=>[entry.char_id,entry.value]);
    const valid=recovering && Array.isArray(recovering.entries)
      && recovering.entries.every(entry=>entry && typeof entry.char_id==='string' && typeof entry.value==='string' && typeof entry.excluded==='boolean')
      && recovering.boxes && !Array.isArray(recovering.boxes) && recovering.confirmed && !Array.isArray(recovering.confirmed)
      && Object.values(recovering.boxes).every(box=>box && Array.isArray(box.bbox) && box.bbox.length===4 && box.bbox.every(Number.isFinite))
      && ['undo','redo'].every(key=>Array.isArray(recovering[key]) && recovering[key].every(frame=>frame && Array.isArray(frame.entries) && frame.boxes && frame.confirmed))
      && JSON.stringify(originals(recovering))===JSON.stringify(originals(incoming));
    model=structuredClone(valid && (recovering.version || 0)>=(incoming.version || 0) ? recovering : incoming);
    pending=false;blocking=false;
  } else {
    pending=false;blocking=false;
    if ((incoming.version || 0)>(model?.version || 0)) model=structuredClone(incoming);
  }
  host.inert=false;
  model.preferences={reference_open:true,reference_width:280,reference_scroll:0,zoom:100,visibility:'dim',...model.preferences};
  model.preferences.reference_width=Math.max(130,Math.min(480,Number(model.preferences.reference_width)||280));
  model.preferences.zoom=Math.max(25,Math.min(500,Number(model.preferences.zoom)||100));
  model.undo ||= [];model.redo ||= [];model.selected_boxes ||= [];
  issues=payload.issues || [];report=payload.report || '';
  render();
  if (model.preferences.reference_open && (model.selected_box || previousContext===context && previousChar!==model.selected_char)) revealReference();
  persist();
  if (issues.length) host.querySelector('dialog').showModal();
  if (queuedAction) {const next=queuedAction;queuedAction=null;checkpoint(next.action,next.extra);}
  else if ((model.version || 0)>(incoming.version || 0)) schedule();
};
window.vietnamicaWorkspace={active:running,snapshot:()=>structuredClone(model),
  ready:()=>new Promise(resolve=>{
    const check=()=>{if(!pending && !queuedAction) resolve();else setTimeout(check,30);};check();
  })};
controller.signal.addEventListener('abort',()=>{clearTimeout(syncTimer);clearTimeout(scrollTimer);referenceObserver?.disconnect();});
watch('value',load);
load();
