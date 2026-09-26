"""Render the canvas and cards from the accepted Python state snapshot."""
import html
from pathlib import Path
from annotation.reading_order import build_text_sequence
from crop.crop import MAX_CROP_SIDE
from .icons import ARROW_RIGHT, DOCUMENT

SCRIPT = (Path(__file__).parent / 'assets/editor.js').read_text()
CSS = (Path(__file__).parent / 'assets/editor.css').read_text()


def snapshot(s):
    if not s.get('image'):
        return dict(markup=f'''<div class="empty-workspace"><span class="empty-icon">{DOCUMENT}</span>
            <h2>Select an image</h2></div>''',
            revision=s['revision'], image=None, step=1)
    step=s['current_step']; w,h=s['image_size']
    if step == 6:
        boxes = {'crop': dict(bbox=s['crop'], status='intact')}
        selected_id = 'crop'
        selected_ids = {'crop'}
    elif step in (3, 4):
        boxes = s['regions']
        selected_id = s['selected_region_uid'] if s['selected_region_uid'] in boxes else next(iter(boxes), None)
        selected_ids = set(s.get('selected_region_uids', [])) or ({selected_id} if selected_id else set())
    else:
        boxes = s['bounding_boxes']
        selected_id = s['selected_box_id'] if s['selected_box_id'] in boxes else next(iter(boxes), None)
        selected_ids = {selected_id} if selected_id else set()
    filename=html.escape(s['image'])
    markup=f'''<div class="workbench-board"><div class="workspace-toolbar">
        <div class="workspace-context"><span class="file-icon">{DOCUMENT}</span><strong>{filename}</strong><span class="dimensions">{w} × {h} px</span></div>
        <div class="toolbar-tools"><span class="zoom-label" aria-live="polite">100%</span>
        <button type="button" data-zoom="out" aria-label="Zoom out"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button>
        <button type="button" data-zoom="in" aria-label="Zoom in"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3v10"/></svg></button>
        <button type="button" data-zoom="fit" aria-label="Fit image to view"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3H3v3M10 3h3v3M6 13H3v-3M10 13h3v-3"/></svg></button></div></div>
        <div class="image-viewport"><svg class="annotation-canvas" viewBox="0 0 {w} {h}" role="img" aria-label="{filename} · annotation canvas" style="aspect-ratio:{w}/{h}">
        <image href="{html.escape(s['image_url'], quote=True)}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="none"/>'''
    # Scale labels/handles to image size so full-resolution scans remain editable.
    unit=max(w,h)/900
    for key,b in boxes.items():
        x1,y1,x2,y2=b['bbox']; selected=key==selected_id or step==6; multi_selected=key in selected_ids
        color='#ff7a1a' if step==6 else '#ef4444' if b['status']=='damaged' else '#22c55e'
        public_box = step not in (3, 4, 6)
        label=html.escape(key+' '+s['annotations'].get(key,'')) if public_box else ''
        dashed=' stroke-dasharray="5 4"' if b['status']=='damaged' else ''
        identity_attr = f'data-region-uid="{key}"' if step in (3, 4) else f'data-box-id="{key}"'
        markup+=f'''<g {identity_attr} class="{'selected-region' if multi_selected else ''}"><title>{'Region' if not public_box else label} · {b['status']}</title>
            <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="{color}" fill-opacity="{'.16' if multi_selected else '.04'}" stroke="{color}" stroke-width="{'2.5' if multi_selected else '1.5'}" vector-effect="non-scaling-stroke"{dashed}/>
            {f'<text x="{x1+2*unit}" y="{max(15*unit,y1-4*unit)}" fill="{color}" font-size="{15*unit}" pointer-events="none" paint-order="stroke" stroke="#17191c" stroke-width="{2*unit}">{label}</text>' if label else ''}'''
        # Resize handles belong only to the active region. Rendering handles on
        # every region makes the canvas look as though all boxes are selected.
        if step == 6 or (step == 3 and selected):
            for n,(x,y) in enumerate([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]):
                markup+=f'<circle data-corner="{n}" cx="{x}" cy="{y}" r="{6*unit}" fill="{color}" stroke="#17191c" stroke-width="{1.5*unit}"/>'
        markup+='</g>'
    markup+='</svg></div>'
    if step in (3,4,5,7):
        markup+='<div class="status-legend"><span class="intact">Intact</span><span class="damaged">Damaged</span></div>'
    if step in (5,7):
        source=html.escape(s['annotation_text'])
        verified=s['workflow']['content_verified']
        source_label='Verified annotation text' if verified else 'Unverified annotation text'
        markup+=f'<section class="source-preview"><span class="eyebrow">{source_label}</span><p>{source}</p></section>'
        if step != 7:
            cards=[]
            for pos,key in enumerate(s['reading_order'],1):
                key=str(key)
                char=html.escape(s['annotations'].get(key,'?'))
                condition=s['bounding_boxes'][key]['status']
                active=' active' if key==selected_id else ''
                cards.append(f'''<button type="button" class="card{active} {condition}" data-card="1" data-box-id="{key}"
                    draggable="{str(step==5).lower()}" aria-pressed="{str(key==selected_id).lower()}" aria-label="Box {key}: {char}, {condition}" title="ID {key} · {condition}">
                    <span class="tile-character">{char}</span><small>{key}</small></button>''')
            title='Reading Order'
            markup+=f'''<section class="order-editor"><div class="order-heading"><div><span class="eyebrow">CHARACTER ANNOTATION</span><h2>{title}</h2></div>
</div>
                <div class="cards">{''.join(cards)}</div></section>'''
        if step==7:
            rows=[]
            for pos,key in enumerate(s['reading_order'],1):
                box=s['bounding_boxes'][str(key)]
                rows.append(f'<tr><td>{pos}</td><td>{key}</td><td>{box["bbox"]}</td><td><span class="table-status {box["status"]}">{box["status"]}</span></td><td class="table-character">{html.escape(s["annotations"][str(key)])}</td></tr>')
            order_separator = ARROW_RIGHT
            markup+='<section class="review-detail"><div class="review-text"><span class="eyebrow">FINAL TEXT</span><p>'+html.escape(build_text_sequence(s))+'</p></div><p class="order-sequence"><span>Reading order:</span> '+ order_separator.join(map(str,s['reading_order']))+'</p><div class="review-table-wrap"><table><thead><tr><th>Order</th><th>Box ID</th><th>BBox</th><th>Status</th><th>Annotation</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section>'
    markup+='</div>'
    return dict(markup=markup,revision=s['revision'], image=s['image'], step=step,
                width=w,height=h,boxes=boxes,selected=selected_id,selectedIds=list(selected_ids),
                max_crop_side=MAX_CROP_SIDE)
