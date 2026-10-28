"""Crop and read-only Review rendering. Annotation lives in the unified workspace."""
import html
import hashlib
from pathlib import Path
from annotation.reading_order import build_text_sequence, suspicious_box_ids
from annotation.state import source_mismatch_confirmed, spatial_box_order
from annotation.text_alignment import MISSING_ANNOTATION
from .icons import DOCUMENT

SCRIPT = (Path(__file__).parent / 'assets/viewer.js').read_text()
RECOVERY_SCRIPT = (Path(__file__).parent / 'assets/recovery.js').read_text()
WORKSPACE_SCRIPT = (Path(__file__).parent / 'assets/workspace.js').read_text()
WORKSPACE_CSS = (Path(__file__).parent / 'assets/workspace.css').read_text()
CSS = (Path(__file__).parent / 'assets/viewer.css').read_text()


def _review_point(point, crop, scale_x, scale_y):
    """Convert one original-image point into the processed Review image."""
    return ((point[0] - crop[0]) * scale_x,
            (point[1] - crop[1]) * scale_y)


def _review_box(bbox, crop, scale_x, scale_y):
    """Apply the shared Review transform to every corner of a rectangular box."""
    x1,y1,x2,y2=bbox
    points=(
        _review_point((x1,y1),crop,scale_x,scale_y),
        _review_point((x2,y1),crop,scale_x,scale_y),
        _review_point((x2,y2),crop,scale_x,scale_y),
        _review_point((x1,y2),crop,scale_x,scale_y),
    )
    return (min(point[0] for point in points),min(point[1] for point in points),
            max(point[0] for point in points),max(point[1] for point in points))



def review_result_text(state):
    """Format MISS tokens for display without changing persisted annotations."""
    build_text_sequence(state)  # Keep the existing reading-order validation.
    order = state.get('reading_order') or spatial_box_order(state)
    parts = []
    previous_missing = False
    for box_id in order:
        token = state['annotations'][str(box_id)]
        missing = token == MISSING_ANNOTATION
        if missing and previous_missing:
            parts.append(' ')
        parts.append('<miss>' if missing else token)
        previous_missing = missing
    return ''.join(parts)


def snapshot(s):
    if not s.get('image') or s['current_step'] not in (6,7):
        return dict(markup=f'''<div class="empty-workspace"><span class="empty-icon">{DOCUMENT}</span>
            <h2>Select an image</h2></div>''',
            revision=s['revision'], image=None, step=1)
    step=s['current_step']; source_w,source_h=s['image_size']
    source_mismatch=source_mismatch_confirmed(s)
    w,h=s['image_size']
    draw_w,draw_h=w,h
    scale_x=scale_y=1.0
    canvas_w,canvas_h=w,h
    review_image_url=s['image_url']
    review_crop=None
    if step == 7:
        from annotation.io import crop_export_geometry
        scaled_crop,resized_size=crop_export_geometry(s)
        draw_w,draw_h=resized_size
        scale_x,scale_y=draw_w/w,draw_h/h
        review_crop=tuple(s.get('crop') or (0,0,w,h))
        canvas_w=(review_crop[2]-review_crop[0])*scale_x
        canvas_h=(review_crop[3]-review_crop[1])*scale_y
        # Review uses a real crop preview. The overlay coordinates are local
        # to that crop, while source boxes remain stored in original pixels.
        if s.get('image_path'):
            from PIL import Image
            from urllib.parse import quote
            preview_dir=Path(s.get('preview_dir') or Path(s['image_path']).parent)
            preview_dir.mkdir(parents=True,exist_ok=True)
            cache_key=hashlib.sha256(
                f"{s['image_path']}:{scaled_crop}:{resized_size}".encode()).hexdigest()
            crop_preview=preview_dir/(cache_key+'-review.jpg')
            if not crop_preview.exists():
                with Image.open(s['image_path']) as source:
                    if list(source.size)!=list(resized_size):
                        source=source.resize(tuple(resized_size),Image.Resampling.LANCZOS)
                    source.crop(tuple(scaled_crop)).convert('RGB').save(
                        crop_preview,format='JPEG',quality=95,subsampling=0)
            review_image_url='gradio_api/file='+quote(str(crop_preview),safe='/')
    other_mismatch=(source_mismatch and s['source_mismatch']['issue_type']=='other')
    if step == 6:
        boxes = {'crop': dict(bbox=s['crop'], status='intact')}
        selected_id = 'crop'
        selected_ids = {'crop'}
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
    board_class = ' review-board' if step == 7 else ''
    markup=f'''<div class="workbench-board{board_class}" data-viewer="1"><div class="workspace-toolbar">
        <div class="workspace-context"><span class="file-icon">{DOCUMENT}</span><strong>{filename}</strong><span class="dimensions">{dimensions}</span></div>
        <div class="toolbar-tools"><span class="zoom-label" aria-live="polite">100%</span>
        <button type="button" data-zoom="out" aria-label="Zoom out"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button>
        <button type="button" data-zoom="in" aria-label="Zoom in"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3v10"/></svg></button></div></div>
        <div class="image-viewport"><svg class="annotation-canvas" viewBox="0 0 {canvas_w} {canvas_h}" role="img" aria-label="{filename} · {'cropped review' if step == 7 else 'annotation canvas'}" style="aspect-ratio:{canvas_w}/{canvas_h}">
        <image href="{html.escape(review_image_url, quote=True)}" x="0" y="0" width="{canvas_w if step == 7 else draw_w}" height="{canvas_h if step == 7 else draw_h}" preserveAspectRatio="none"/>
        '''
    # Scale labels/handles to image size so full-resolution scans remain editable.
    unit=max(draw_w,draw_h)/900
    suspicious_boxes=set(suspicious_box_ids(s)) if step == 7 else set()
    for key,b in boxes.items():
        if step == 7:
            x1,y1,x2,y2=_review_box(b['bbox'],review_crop,scale_x,scale_y)
        else:
            x1,y1,x2,y2=b['bbox']
            x1,y1,x2,y2=x1*scale_x,y1*scale_y,x2*scale_x,y2*scale_y
        selected=key==selected_id or step==6; multi_selected=key in selected_ids
        bw = x2 - x1; bh = y2 - y1
        miss_x1,miss_x2=x1+bw*0.2,x2-bw*0.2
        miss_y1,miss_y2=y1+bh*0.2,y2-bh*0.2
        font_size = max(10 * unit, min(bw, bh) * 0.30)
        stroke_width = max(0.5, font_size * 0.1)
        suspicious = key in suspicious_boxes
        reveal_status = step == 7 and not other_mismatch
        is_unknown = bool(b.get('unknown', False)) and b['status'] == 'damaged'
        unavailable_font = bool(b.get('unavailable_font', False))
        expert_prediction = bool(b.get('expert_prediction', False))
        status_color = '#facc15' if expert_prediction else '#ef4444' if b['status'] == 'damaged' else '#22c55e'
        text_color = '#ec4899' if unavailable_font else '#facc15' if expert_prediction else '#ffffff'
        stroke_color=('#ff7a1a' if step==6 else '#f4f4f5' if not reveal_status
                      else status_color)
        missing_annotation = (step == 7 and s.get('annotations', {}).get(str(key)) == MISSING_ANNOTATION)
        fill_color = ('#ff7a1a' if step==6 else '#ec4899' if reveal_status and unavailable_font else '#facc15' if suspicious
                      else '#e5e7eb' if missing_annotation else stroke_color)
        fill_opacity = ('.16' if multi_selected and step == 6 else
                        '.20' if reveal_status and unavailable_font else
                        '.20' if suspicious else
                        '.30' if missing_annotation else
                        '.04')
        public_box = step not in (6,) and not other_mismatch
        label=html.escape(key+' '+s['annotations'].get(key,'')) if public_box else ''
        dashed=''
        identity_attr = f'data-box-id="{key}"'
        identity_attr += f' data-status="{b["status"]}" data-unknown="{str(is_unknown).lower()}"'
        identity_attr += f' data-unavailable-font="{str(unavailable_font).lower()}" data-expert-prediction="{str(expert_prediction).lower()}"'
        identity_attr += f' data-suspicious="{str(suspicious).lower()}"'
        group_classes=' '.join(filter(None,(
            'selected-region' if multi_selected else '',
            'active-region' if key==selected_id else '',
            'suspicious-region' if suspicious else '',
        )))
        missing_attr = ' data-missing="1"' if missing_annotation else ''
        markup+=f'''<g {identity_attr} class="{group_classes}"><title>{'Region' if not public_box else label} · {b['status']}{' · unknown' if is_unknown else ''}{' · unavailable_font' if unavailable_font else ''}{' · Expert Prediction' if expert_prediction else ''}{' · suspicious' if suspicious else ''}</title>
            <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="{fill_color}" fill-opacity="{fill_opacity}" stroke="{stroke_color}" stroke-width="{'3' if suspicious and multi_selected else '2' if suspicious else '2.5' if multi_selected else '1.5'}" vector-effect="non-scaling-stroke"{missing_attr}{dashed}/>
            {f'<g data-miss-mark="1" stroke="#ef4444" stroke-width="2.25" stroke-linecap="round" pointer-events="none"><line x1="{miss_x1}" y1="{miss_y1}" x2="{miss_x2}" y2="{miss_y2}" vector-effect="non-scaling-stroke"/><line x1="{miss_x2}" y1="{miss_y1}" x2="{miss_x1}" y2="{miss_y2}" vector-effect="non-scaling-stroke"/></g>' if missing_annotation else ''}
            {f'<text data-unknown-mark="1" x="{(x1+x2)/2}" y="{(y1+y2)/2}" text-anchor="middle" dominant-baseline="central" fill="#ef4444" font-family="sans-serif" font-size="{min(bw,bh)*0.80}" font-weight="700" pointer-events="none">?</text>' if reveal_status and is_unknown and not missing_annotation else ''}
            {f'<text data-box-order-label="1" x="{(x1+x2)/2}" y="{max(font_size, y1-3*unit)}" text-anchor="middle" fill="{text_color if reveal_status else stroke_color}" font-size="{font_size}" font-family="var(--han-nom-font, &quot;Vietnamica NomNaTong&quot;, &quot;Vietnamica DengXian&quot;, sans-serif)" pointer-events="none" paint-order="stroke" stroke="#17191c" stroke-width="{stroke_width}">{label}</text>' if label else ''}'''
        # Crop is the only editable geometry in this viewer.
        if step == 6:
            for n, (cx, cy) in enumerate([(x1,y1),(x2,y1),(x2,y2),(x1,y2)]):
                markup += f'<circle data-corner="{n}" cx="{cx}" cy="{cy}" r="{max(10*unit, 16)}" fill="#000" stroke="none" opacity="0" pointer-events="all"/>'
        markup+='</g>'
    markup+='</svg></div>'
    if step == 7 and not other_mismatch:
        suspicious_legend=('<span class="suspicious">Suspicious content</span>'
                           if suspicious_boxes else '')
        markup+=f'<div class="status-legend"><span class="intact">Intact</span><span class="damaged">Damaged</span><span class="unknown">Unknown (?)</span><span class="unavailable-font">Unavailable Font</span><span class="expert-prediction">Expert Prediction</span><span class="missing">MISS content</span>{suspicious_legend}</div>'
    if step == 7 and not other_mismatch:
        if source_mismatch:
            issue=s['source_mismatch']
            note=(f'<small>Note: {html.escape(issue["note"])}</small>'
                  if issue['note'] else '')
            final_result=issue['issue_type'] in ('missing_text','extra_text','mixed')
            mismatch_text = (html.escape(review_result_text(s))
                             if issue['issue_type'] in ('missing_text','extra_text','mixed') else
                             'No character annotations will be generated for this image.')
            review_class='review-text' if final_result else 'review-text source-mismatch-review'
            review=f'''<div class="{review_class}">
                <p>{mismatch_text}</p>
                <small>{html.escape(issue['issue_type'])} · {issue['source_character_count']} characters · {issue['bounding_box_count']} boxes</small>
                {note}</div>'''
        else:
            review='<div class="review-text"><p>'+html.escape(review_result_text(s))+'</p></div>'
        markup+=f'''<section class="review-editor"><div class="order-heading"><div><span class="eyebrow">REVIEW & VERIFICATION</span><h2>Final Result</h2></div></div>
            <div class="review-detail">{review}</div></section>'''
    markup+='</div>'
    return dict(markup=markup,revision=s['revision'],image=s['image'],step=step,
                width=canvas_w,height=canvas_h,boxes=boxes,crop=s.get('crop'))
