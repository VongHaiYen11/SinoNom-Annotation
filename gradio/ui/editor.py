"""Render the canvas and cards from the accepted Python state snapshot."""
import html
from pathlib import Path
from annotation.reading_order import build_text_sequence, suspicious_box_ids
from annotation.state import source_mismatch_confirmed, spatial_box_order
from annotation.text_alignment import MISSING_ANNOTATION
from .icons import DOCUMENT

SCRIPT = (Path(__file__).parent / 'assets/editor.js').read_text()
CSS = (Path(__file__).parent / 'assets/editor.css').read_text()


def source_text(s):
    """Render the Status & Order reference text for the sidebar."""
    if not s.get('image') or s.get('current_step') not in (4, 7):
        return ''
    source_mismatch = source_mismatch_confirmed(s)
    label = ('Source text' if source_mismatch else
             'Verified annotation text' if s['workflow']['content_verified'] else
             'Unverified annotation text')
    return (f'<section class="sidebar-source-text"><span class="eyebrow">'
            f'{html.escape(label)}</span><p>{html.escape(s["annotation_text"])}</p></section>')


def snapshot(s):
    if not s.get('image'):
        return dict(markup=f'''<div class="empty-workspace"><span class="empty-icon">{DOCUMENT}</span>
            <h2>Select an image</h2></div>''',
            revision=s['revision'], image=None, step=1)
    step=s['current_step']; source_w,source_h=s['image_size']
    source_mismatch=source_mismatch_confirmed(s)
    w,h=s['image_size']
    canvas_x=canvas_y=0
    canvas_w,canvas_h=w,h
    if step == 7:
        canvas_x,canvas_y,crop_x2,crop_y2=s.get('crop') or [0,0,w,h]
        canvas_w,canvas_h=crop_x2-canvas_x,crop_y2-canvas_y
    other_mismatch=(source_mismatch and s['source_mismatch']['issue_type']=='other')
    if step == 6:
        boxes = {'crop': dict(bbox=s['crop'], status='intact')}
        selected_id = 'crop'
        selected_ids = {'crop'}
    elif step == 3:
        boxes = s['regions']
        selected_id = s['selected_region_uid'] if s['selected_region_uid'] in boxes else next(iter(boxes), None)
        selected_ids = set(s.get('selected_region_uids', [])) or ({selected_id} if selected_id else set())
    elif step == 7 and other_mismatch:
        boxes=s['regions'];selected_id=None;selected_ids=set()
    else:
        boxes = s['bounding_boxes']
        selected_id = s['selected_box_id'] if (s['selected_box_id'] and s['selected_box_id'] in boxes) else None
        selected_ids = {selected_id} if selected_id else set()
    filename=html.escape(s['image'])
    dimensions = (f'{source_w} × {source_h} px · crop {canvas_w} × {canvas_h} px'
                  if step == 7 else
                  f'{source_w} × {source_h} px → {w} × {h} px'
                  if step == 6 and [w,h] != [source_w,source_h]
                  else f'{w} × {h} px')
    board_class = ' status-order-board review-board' if step == 7 else ' status-order-board' if step == 4 else ''
    markup=f'''<div class="workbench-board{board_class}"><div class="workspace-toolbar">
        <div class="workspace-context"><span class="file-icon">{DOCUMENT}</span><strong>{filename}</strong><span class="dimensions">{dimensions}</span></div>
        <div class="toolbar-tools"><span class="zoom-label" aria-live="polite">100%</span>
        <button type="button" data-zoom="out" aria-label="Zoom out"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button>
        <button type="button" data-zoom="in" aria-label="Zoom in"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3v10"/></svg></button></div></div>
        <div class="image-viewport"><svg class="annotation-canvas" viewBox="{canvas_x} {canvas_y} {canvas_w} {canvas_h}" role="img" aria-label="{filename} · {'cropped review' if step == 7 else 'annotation canvas'}" style="aspect-ratio:{canvas_w}/{canvas_h}">
        <image href="{html.escape(s['image_url'], quote=True)}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="none"/>
        '''
    # Scale labels/handles to image size so full-resolution scans remain editable.
    unit=max(w,h)/900
    suspicious_boxes=set(suspicious_box_ids(s)) if step in (4,7) else set()
    for key,b in boxes.items():
        x1,y1,x2,y2=b['bbox']; selected=key==selected_id or step==6; multi_selected=key in selected_ids
        bw = x2 - x1; bh = y2 - y1
        font_size = min(bw, bh) * 0.65
        stroke_width = max(0.5, font_size * 0.1)
        suspicious = key in suspicious_boxes
        reveal_status = step >= 4 and not other_mismatch
        is_unknown = bool(b.get('unknown', False)) and b['status'] == 'damaged'
        status_color = ('#f59e0b' if is_unknown else '#ef4444') if b['status'] == 'damaged' else '#22c55e'
        stroke_color=('#ff7a1a' if step==6 else '#f4f4f5' if not reveal_status
                      else status_color)
        missing_annotation = (step in (4, 5, 7) and s.get('annotations', {}).get(str(key)) == MISSING_ANNOTATION)
        fill_color = ('#ff7a1a' if step==6 else '#facc15' if suspicious
                      else '#e5e7eb' if missing_annotation else stroke_color)
        fill_opacity = ('.16' if multi_selected and step in (3,6) else
                        '.20' if suspicious else
                        '.30' if missing_annotation else
                        '.04')
        public_box = step not in (6,) and not other_mismatch
        if step == 3:
            public_id = s.get('box_id_by_region', {}).get(key)
            label = html.escape(public_id) if public_id else ''
        else:
            label=html.escape(key+' '+s['annotations'].get(key,'')) if public_box else ''
        dashed=''
        identity_attr = (f'data-box-id="{key}" data-region-uid="{key}"'
                         if step == 3 else f'data-box-id="{key}"')
        identity_attr += f' data-status="{b["status"]}" data-unknown="{str(is_unknown).lower()}"'
        group_classes=' '.join(filter(None,(
            'selected-region' if multi_selected else '',
            'active-region' if key==selected_id else '',
            'suspicious-region' if suspicious else '',
        )))
        missing_attr = ' data-missing="1"' if missing_annotation else ''
        markup+=f'''<g {identity_attr} class="{group_classes}"><title>{'Region' if not public_box else label} · {b['status']}{' · unknown' if is_unknown else ''}{' · suspicious' if suspicious else ''}</title>
            <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="{fill_color}" fill-opacity="{fill_opacity}" stroke="{stroke_color}" stroke-width="{'3' if suspicious and multi_selected else '2' if suspicious else '2.5' if multi_selected else '1.5'}" vector-effect="non-scaling-stroke"{missing_attr}{dashed}/>
            {f'<g data-miss-mark="1" stroke="#ef4444" stroke-width="{max(2*unit, 2)}" vector-effect="non-scaling-stroke" pointer-events="none"><line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/><line x1="{x2}" y1="{y1}" x2="{x1}" y2="{y2}"/></g>' if missing_annotation else ''}
            {f'<text x="{x1+2*unit}" y="{y1+font_size}" fill="{stroke_color}" font-size="{font_size}" font-family="var(--han-nom-font, &quot;Vietnamica NomNaTong&quot;, &quot;Vietnamica DengXian&quot;, &quot;Vietnamica PMingLiU&quot;, &quot;Vietnamica PMingLiU ExtB&quot;, sans-serif)" pointer-events="none" paint-order="stroke" stroke="#17191c" stroke-width="{stroke_width}">{label}</text>' if label else ''}'''
        # Handles are pre-rendered for local selection changes; CSS exposes
        # them only on the browser-local active region.
        if step in (3, 6):
            for n, (cx, cy) in enumerate([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]):
                markup += f'<circle data-corner="{n}" cx="{cx}" cy="{cy}" r="{max(10*unit, 16)}" fill="#000" stroke="none" opacity="0" pointer-events="all"/>'
        markup+='</g>'
    markup+='</svg></div>'
    if step in (4, 5) or (step == 7 and not other_mismatch):
        suspicious_legend=('<span class="suspicious">Suspicious content</span>'
                           if suspicious_boxes else '')
        markup+=f'<div class="status-legend"><span class="intact">Intact</span><span class="damaged">Damaged</span><span class="unknown">Unknown</span><span class="missing">MISS content</span>{suspicious_legend}</div>'
    if step in (4,7) and not (step==7 and other_mismatch):
        if step == 4:
            chips=[]
            extra=(source_mismatch and s['source_mismatch']['issue_type']=='extra_text')
            values=(s['text_sequence'] if extra else
                    [s['annotations'][str(box_id)] for box_id in s['reading_order']]
                    if s['annotations'] else [])
            excluded_count=(len(values)-len(s['bounding_boxes']) if extra else 0)
            spatial_ids=list(map(str,spatial_box_order(s)))
            token_ids=list(map(str,s.get('text_token_ids',[])))
            suspicious_tokens=set(map(str,s.get('suspicious_token_ids',[])))
            for position,value in enumerate(values,1):
                char=html.escape(value)
                missing=' missing' if value == MISSING_ANNOTATION else ''
                excluded=' excluded' if excluded_count and position>len(values)-excluded_count else ''
                attribute_char=html.escape(value,quote=True)
                box_id=(spatial_ids[position-1] if position<=len(spatial_ids) else '')
                token_id=(token_ids[position-1] if position<=len(token_ids) else str(position))
                suspicious=' suspicious' if token_id in suspicious_tokens else ''
                box_attribute=(f' data-assigned-box-id="{box_id}"' if box_id else '')
                chips.append(f'''<button type="button" class="order-chip{missing}{excluded}{suspicious}" data-order-chip="1" data-token-id="{token_id}" data-character="{attribute_char}"{box_attribute}
                    draggable="false" aria-label="Reading position {position}: {char}" title="{char}">
                    <span class="tile-character">{char}</span></button>''')
            title='Character Assignment'
            help_text=('Drag the text cards into the sequence that should be assigned to the spatially sorted boxes.'
                       if chips else 'This confirmed source mismatch has no character mapping to arrange.')
            markup+=f'''<section class="order-editor"><div class="order-heading"><div><span class="eyebrow">CHARACTER ANNOTATION</span><h2>{title}</h2></div>
</div>
                <p class="order-help">{help_text}</p>
                <div class="order-chips" data-excluded-count="{excluded_count}" role="list" aria-label="Sortable character assignment">{''.join(chips)}</div>
                <p class="order-sync-note" aria-live="polite">Order changes stay local until you apply them or continue.</p></section>'''
        if step==7:
            source=html.escape(s['annotation_text'])
            source_label=('Source text' if source_mismatch else
                          'Verified annotation text' if s['workflow']['content_verified']
                          else 'Unverified annotation text')
            if source_mismatch:
                issue=s['source_mismatch']
                note=(f'<small>Note: {html.escape(issue["note"])}</small>'
                      if issue['note'] else '')
                final_result=issue['issue_type'] in ('missing_text','extra_text')
                mismatch_text = (html.escape(build_text_sequence(s))
                                 if issue['issue_type'] in ('missing_text','extra_text') else
                                 'No character annotations will be generated for this image.')
                review_label='FINAL RESULT' if final_result else 'SOURCE MISMATCH'
                review_class='review-text' if final_result else 'review-text source-mismatch-review'
                review=f'''<div class="{review_class}">
                    <p>{mismatch_text}</p>
                    <small>{html.escape(issue['issue_type'])} · {issue['source_character_count']} characters · {issue['bounding_box_count']} boxes</small>
                    {note}</div>'''
            else:
                review='<div class="review-text"><p>'+html.escape(build_text_sequence(s))+'</p></div>'
            markup+=f'''<section class="review-editor"><div class="order-heading"><div><span class="eyebrow">REVIEW & VERIFICATION</span><h2>Final Result</h2></div></div>
                <div class="review-detail">{review}</div></section>'''
    markup += '''
    <div id="sort-selected-modal" class="modal-backdrop" style="display:none;" role="dialog" aria-modal="true" aria-labelledby="sort-modal-title">
      <div class="modal-card">
        <h3 id="sort-modal-title">Sort Selected Boxes</h3>
        <p class="modal-subtitle">Selected boxes: <strong id="sort-modal-count">0</strong></p>
        <div class="modal-form-group">
          <label for="sort-modal-start">Sort from (start number):</label>
          <input type="number" id="sort-modal-start" min="1" value="1" step="1" />
          <p class="modal-range-preview">Will assign: <span id="sort-modal-range">1 – 1</span></p>
        </div>
        <div id="sort-modal-error" class="modal-error-alert" style="display:none;"></div>
        <div class="modal-actions">
          <button type="button" id="sort-modal-cancel" class="btn btn-secondary">Cancel</button>
          <button type="button" id="sort-modal-confirm" class="btn btn-primary">Confirm</button>
        </div>
      </div>
    </div>
    <div id="clear-order-modal" class="modal-backdrop" style="display:none;" role="dialog" aria-modal="true" aria-labelledby="clear-modal-title">
      <div class="modal-card">
        <h3 id="clear-modal-title">Clear Reading Order</h3>
        <p id="clear-modal-message" class="modal-subtitle">Are you sure you want to clear the reading order for all boxes?</p>
        <div class="modal-actions">
          <button type="button" id="clear-modal-cancel" class="btn btn-secondary">Cancel</button>
          <button type="button" id="clear-modal-confirm" class="btn btn-primary">Confirm</button>
        </div>
      </div>
    </div>
    <div id="mismatch-confirm-modal" class="modal-backdrop" style="display:none;" role="dialog" aria-modal="true" aria-labelledby="mismatch-modal-title">
      <div class="modal-card">
        <h3 id="mismatch-modal-title">Confirm Source Mismatch First</h3>
        <p id="mismatch-modal-message" class="modal-subtitle">Bounding-box count and character count do not match. Please confirm the source mismatch before editing reading order.</p>
        <div class="modal-actions">
          <button type="button" id="mismatch-modal-cancel" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
    <div id="order-validation-modal" class="modal-backdrop" style="display:none;" role="dialog" aria-modal="true" aria-labelledby="order-alert-title">
      <div class="modal-card modal-card-error">
        <h3 id="order-alert-title">Reading Order Invalid</h3>
        <div id="order-alert-body" class="modal-error-body"></div>
        <div class="modal-actions">
          <button type="button" id="order-alert-close" class="btn btn-primary">Close & Review</button>
        </div>
      </div>
    </div>
    '''
    markup+='</div>'
    calc_sorted = s.pop('calc_sorted_box_ids', None)
    return dict(markup=markup,revision=s['revision'], image=s['image'], step=step,
                width=canvas_w,height=canvas_h,boxes=boxes,selected=selected_id,selectedIds=list(selected_ids),
                calcSortedBoxIds=calc_sorted,
                bboxValid=s['workflow'].get('bbox_valid', False),
                mismatchConfirmed=source_mismatch_confirmed(s),
                readingOrder=list(s['reading_order']),
                spatialBoxOrder=(list(s.get('reading_order', [])) if s.get('bounding_boxes') else []),
                suspiciousTokenIds=list(map(str,s.get('suspicious_token_ids',[]))),
                selectedTokenId=(str(s['selected_token_id'])
                                 if s.get('selected_token_id') is not None else None),
                orderedAnnotations=([s['annotations'][str(box_id)]
                                     for box_id in s['reading_order']]
                                    if s['annotations'] else []),
                max_crop_side=max(w,h), image_handle_inset=0)
