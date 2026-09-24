import html
import json
from pathlib import Path
from annotation.reading_order import build_text_sequence
from annotation.text_alignment import normalize_annotation_text, count_annotation_characters
from annotation.io import final_document

SCRIPT = (Path(__file__).parent / 'assets/editor.js').read_text()
CSS = '''.board{display:grid;grid-template-columns:minmax(280px,1fr) minmax(220px,1fr);gap:16px}svg{width:100%;max-height:70vh;touch-action:none;background:#222}.cards{display:flex;flex-wrap:wrap;align-content:start;gap:8px}.card{padding:12px;border:2px solid #64748b;border-radius:8px;font-size:28px;cursor:grab}.active{border-color:#f59e0b}.card small{display:block;font-size:12px}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #888}pre{white-space:pre-wrap}'''


def snapshot(s):
    if not s.get('image'):
        return dict(markup='<p>Chọn ảnh để bắt đầu.</p>', revision=s['revision'], image=None, step=1)
    step=s['current_step']; w,h=s['image_size']
    boxes = {'crop':dict(bbox=s['crop'],status='intact')} if step==8 else s['bounding_boxes']
    chunks=[f'<svg viewBox="0 0 {w} {h}"><image href="{s["image_url"]}" width="{w}" height="{h}"/>']
    for key,b in boxes.items():
        x1,y1,x2,y2=b['bbox']; selected=key==s['selected_box_id'] or step==8
        color='#f59e0b' if selected else '#ef4444' if b['status']=='damaged' else '#22c55e'
        label=html.escape(key+' '+s['annotations'].get(key,''))
        chunks.append(f'<g data-box-id="{key}"><rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="transparent" stroke="{color}" stroke-width="3"/><text x="{x1}" y="{max(18,y1)}" fill="{color}" font-size="18" pointer-events="none">{label}</text>')
        if step in (3,8):
            for n,(x,y) in enumerate([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]):
                chunks.append(f'<circle data-corner="{n}" cx="{x}" cy="{y}" r="7" fill="{color}"/>')
        chunks.append('</g>')
    chunks.append('</svg>')
    cards=[]
    for key in s['reading_order']:
        key=str(key)
        char=html.escape(s['annotations'].get(key,'?'))
        cards.append(f'<div class="card {"active" if key==s["selected_box_id"] else ""}" data-card="1" data-box-id="{key}" draggable="{str(step==6).lower()}">{char}<small>{key} · {s["bounding_boxes"][key]["status"]}</small></div>')
    source=html.escape(s['annotation_text'])
    markup='<div class="board"><div>'+''.join(chunks)+'</div><div><p>Verified annotation text:</p><pre>'+source+'</pre><div class="cards">'+''.join(cards)+'</div></div></div>'
    if step==7:
        rows=[]
        for pos,key in enumerate(s['reading_order'],1):
            box=s['bounding_boxes'][str(key)]
            rows.append(f'<tr><td>{pos}</td><td>{key}</td><td>{box["bbox"]}</td><td>{box["status"]}</td><td>{html.escape(s["annotations"][str(key)])}</td></tr>')
        markup+='<p>Reading order: '+ ' → '.join(map(str,s['reading_order']))+'</p><table><tr><th>Order</th><th>ID</th><th>BBox</th><th>Status</th><th>Annotation</th></tr>'+''.join(rows)+'</table><h3>'+html.escape(build_text_sequence(s))+'</h3>'
    return dict(markup=markup,revision=s['revision'], image=s['image'], step=step,
                width=w,height=h,boxes=boxes,selected=s['selected_box_id'])
