"""Render the canvas and cards from the accepted Python state snapshot."""
import html
from pathlib import Path
from annotation.reading_order import build_text_sequence

SCRIPT = (Path(__file__).parent / 'assets/editor.js').read_text()
CSS = (Path(__file__).parent / 'assets/editor.css').read_text()


def snapshot(s):
    if not s.get('image'):
        return dict(markup='''<div class="empty-workspace"><span class="empty-icon">▧</span>
            <h2>Select an image</h2></div>''',
            revision=s['revision'], image=None, step=1)
    step=s['current_step']; w,h=s['image_size']
    boxes = {'crop':dict(bbox=s['crop'],status='intact')} if step==6 else s['bounding_boxes']
    selected_id = s['selected_box_id'] if s['selected_box_id'] in s['bounding_boxes'] else next(iter(s['bounding_boxes']), None)
    filename=html.escape(s['image'])
    markup=f'''<div class="workbench-board"><div class="workspace-toolbar">
        <div class="workspace-context"><span class="file-icon">▧</span><strong>{filename}</strong><span class="dimensions">{w} × {h} px</span></div>
        <div class="toolbar-tools"><span class="zoom-label" aria-live="polite">100%</span>
        <button type="button" data-zoom="out" aria-label="Zoom out">−</button>
        <button type="button" data-zoom="in" aria-label="Zoom in">＋</button>
        <button type="button" data-zoom="fit" aria-label="Fit image to view">⛶</button></div></div>
        <div class="image-viewport"><svg class="annotation-canvas" viewBox="0 0 {w} {h}" role="img" aria-label="{filename} · annotation canvas" style="aspect-ratio:{w}/{h}">
        <image href="{s['image_url']}" width="{w}" height="{h}"/>'''
    # Scale labels/handles to image size so full-resolution scans remain editable.
    unit=max(w,h)/900
    for key,b in boxes.items():
        x1,y1,x2,y2=b['bbox']; selected=key==selected_id or step==6
        color='#ff7a1a' if step==6 else '#ef4444' if b['status']=='damaged' else '#22c55e'
        label=html.escape(key if step==4 else key+' '+s['annotations'].get(key,''))
        dashed=' stroke-dasharray="5 4"' if b['status']=='damaged' else ''
        markup+=f'''<g data-box-id="{key}" class="{'selected-region' if selected else ''}"><title>{label} · {b['status']}</title>
            <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="{color}" fill-opacity="{'.16' if selected else '.04'}" stroke="{color}" stroke-width="{'2.5' if selected else '1.5'}" vector-effect="non-scaling-stroke"{dashed}/>
            <text x="{x1+2*unit}" y="{max(15*unit,y1-4*unit)}" fill="{color}" font-size="{15*unit}" pointer-events="none" paint-order="stroke" stroke="#17191c" stroke-width="{2*unit}">{label}</text>'''
        if step in (3,6):
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
            markup+='<section class="review-detail"><div class="review-text"><span class="eyebrow">FINAL TEXT</span><p>'+html.escape(build_text_sequence(s))+'</p></div><p class="order-sequence">Reading order: '+ ' → '.join(map(str,s['reading_order']))+'</p><div class="review-table-wrap"><table><thead><tr><th>Order</th><th>Box ID</th><th>BBox</th><th>Status</th><th>Annotation</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></section>'
    markup+='</div>'
    return dict(markup=markup,revision=s['revision'], image=s['image'], step=step,
                width=w,height=h,boxes=boxes,selected=selected_id)
