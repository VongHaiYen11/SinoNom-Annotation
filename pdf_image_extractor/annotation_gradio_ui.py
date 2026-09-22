"""Gradio presentation layer for manually correcting character annotations."""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
from pathlib import Path
from typing import Any

import gradio as gr
from PIL import Image

from .annotation_editor import apply_pending, current_record, load_annotation, move_to_image, save_annotation, save_current_annotation
from .ui_styles import WORKSPACE_CSS, WORKSPACE_THEME
from .workspace_paths import annotation_collection_path, local_pdf_choices


_TEXT_FIELDS = ("text", "character", "transcription", "label", "char", "content")


def _detection_text(detection: dict[str, Any]) -> str:
    """Use an optional transcription without assuming the detector recognizes text."""
    for field in _TEXT_FIELDS:
        value = detection.get(field)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _reading_order(session: dict[str, Any]) -> str:
    """Render the current list order; the canvas keeps the same order live."""
    tokens = [_detection_text(detection) or "□" for detection in current_record(session)["detections"]]
    rendered = " ".join(html.escape(token) for token in tokens) or "—"
    unknown = any(token == "□" for token in tokens)
    note = (
        "`□` marks a box with no transcription. The bundled detector finds character geometry, not character identities."
        if unknown
        else "Text follows the numbered box order shown on the canvas."
    )
    return f"### Reading order\n\n<code>{rendered}</code>\n\n{note}"


def _image_data(path: str) -> str:
    with Image.open(path) as original:
        image = original.copy()
    image.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _editor(session: dict[str, Any]) -> str:
    record = current_record(session)
    detections = record["detections"]
    boxes = [
        {**item, "editor_id": index, "rotation_degrees": item.get("rotation_degrees", 0)}
        for index, item in enumerate(detections)
    ]
    return (
        '<div class="annotation-host" data-source="%s" data-width="%d" data-height="%d" '
        'data-boxes="%s"><div class="annotation-toolbar">'
        '<button type="button" data-action="select" class="active">Select / move</button>'
        '<button type="button" data-action="add">+ Add box</button>'
        '<button type="button" data-action="delete">Delete selected</button>'
        '<button type="button" data-action="earlier">← Earlier</button>'
        '<button type="button" data-action="later">Later →</button>'
        '<label class="annotation-order-swap">Swap with #'
        '<input type="number" min="1" step="1" inputmode="numeric" data-action="target-order" aria-label="Target reading-order number">'
        '<button type="button" data-action="swap-to-order">Swap order</button></label>'
        '</div><canvas aria-label="Character bounding-box editor"></canvas>'
        '<p class="annotation-help">Click a box to select it; drag inside to move; drag a corner to resize; '
        'drag the round handle above it to rotate. Use Earlier / Later, or enter an order number and choose Swap order, to correct reading order. '
        'Choose <strong>Add box</strong>, then click the image to add a character box. Changes are pending until Save.</p>'
        '<p class="annotation-status"></p><div class="annotation-reading">'
        '<span>Reading order text</span><output></output></div></div>'
        % (
            _image_data(record["_resolved_image_path"]),
            record["image_width"],
            record["image_height"],
            json.dumps(boxes).replace('"', '&quot;'),
        )
    )


def _summary(session: dict[str, Any], saved: str | None = None) -> str:
    record = current_record(session)
    total = len(session["payload"]["images"]) if session["collection"] else 1
    position = session["current_index"] + 1
    name = record.get("image_name") or Path(record["_resolved_image_path"]).name
    action = {
        "current": "**Current image saved.** Other image edits remain pending.",
        "all": "**All pending image edits saved and overwritten.**",
    }.get(saved, "Edit boxes, then save the current image or all pending image edits.")
    return (
        f"### Character annotation — image {position}/{total}\n\nImage: `{name}`  \n"
        f"Original pixels: **{record['image_width']}×{record['image_height']}**  \n"
        f"Character boxes: **{len(record['detections'])}**  \n"
        f"{action}"
    )


def _boxes(session: dict[str, Any]) -> str:
    return json.dumps(current_record(session)["detections"], ensure_ascii=False)


def _navigation(session: dict[str, Any]):
    total = len(session["payload"]["images"]) if session["collection"] else 1
    index = session["current_index"]
    return gr.update(interactive=index > 0), gr.update(interactive=index < total - 1)


def load_session(annotation_path: str, image_override: str | None):
    if not annotation_path.strip():
        raise gr.Error("Enter the path to a character-annotation JSON file.")
    try:
        session = load_annotation(annotation_path.strip(), image_override.strip() if image_override else None)
    except (FileNotFoundError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc
    previous, next_ = _navigation(session)
    return session, _editor(session), _summary(session), _reading_order(session), _boxes(session), previous, next_


def load_session_for_pdf(pdf_path: str | None):
    """Load the established PDF-level collection, if character boxes exist."""
    if not pdf_path:
        return (
            gr.update(value=""), {}, "Load an annotation JSON or choose a local PDF to begin.",
            "Load an annotation JSON to show its source image and character boxes.", "Reading order unavailable.", "",
            gr.update(interactive=False), gr.update(interactive=False),
        )
    annotation_path = annotation_collection_path(pdf_path)
    if not annotation_path.is_file():
        return (
            gr.update(value=str(annotation_path)), {},
            f"### Annotation unavailable\n\nNo character annotation JSON exists yet for `{Path(pdf_path).name}`.  \nExpected: `{annotation_path.relative_to(annotation_path.parents[2])}`",
            "No character annotation JSON was found for this PDF.", "Reading order unavailable.", "",
            gr.update(interactive=False), gr.update(interactive=False),
        )
    session, editor, status, reading_order, boxes, previous, next_ = load_session(str(annotation_path), None)
    return gr.update(value=str(annotation_path)), session, status, editor, reading_order, boxes, previous, next_


def refresh_local_pdfs():
    return gr.update(choices=local_pdf_choices(), value=None)


def _edited_detections(value: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise gr.Error("The browser sent invalid box data; reload the annotation and try again.") from exc
    if not isinstance(data, list):
        raise gr.Error("Edited box data must be a list.")
    return data


def save_session(session: dict[str, Any], edited_boxes: str, current_only: bool):
    if not session:
        raise gr.Error("Load an annotation JSON first.")
    try:
        pending = apply_pending(session, _edited_detections(edited_boxes))
        updated = save_current_annotation(pending) if current_only else save_annotation(pending)
    except (OSError, ValueError) as exc:
        raise gr.Error(f"Could not save annotation JSON: {exc}") from exc
    previous, next_ = _navigation(updated)
    return updated, _editor(updated), _summary(updated, saved="current" if current_only else "all"), _reading_order(updated), _boxes(updated), previous, next_


def navigate(session: dict[str, Any], edited_boxes: str, direction: int):
    if not session:
        raise gr.Error("Load an annotation JSON first.")
    try:
        pending = apply_pending(session, _edited_detections(edited_boxes))
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    updated = move_to_image(pending, pending["current_index"] + direction)
    previous, next_ = _navigation(updated)
    return updated, _editor(updated), _summary(updated), _reading_order(updated), _boxes(updated), previous, next_


HEAD = r"""
<script>
(() => {
 const init = host => {
  if (host.dataset.ready) return; host.dataset.ready = 'yes';
  const canvas=host.querySelector('canvas'), ctx=canvas.getContext('2d'), image=new Image();
  const W=+host.dataset.width,H=+host.dataset.height; let boxes=JSON.parse(host.dataset.boxes), selected=-1, tool='select', drag=null;
  host._annotationBoxes=boxes;
  const scale=()=>Math.min(1100/W,760/H,1);
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  const normalAngle=value=>((Number(value)||0)+540)%360-180;
  const geometry=item=>{const [l,t,r,b]=item.bbox_xyxy.map(Number),angle=normalAngle(item.rotation_degrees),rad=angle*Math.PI/180,c=Math.cos(rad),s=Math.sin(rad),cx=(l+r)/2,cy=(t+b)/2,w=r-l,h=b-t;
    const world=(x,y)=>({x:cx+x*c-y*s,y:cy+x*s+y*c});
    return {cx,cy,w,h,angle,c,s,world,corners:[world(-w/2,-h/2),world(w/2,-h/2),world(w/2,h/2),world(-w/2,h/2)]};};
  const local=(g,p)=>{const x=p.x-g.cx,y=p.y-g.cy;return {x:x*g.c+y*g.s,y:-x*g.s+y*g.c};};
  const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
  const rotationHandle=(g,s=scale())=>g.world(0,-g.h/2-28/s);
  const boxAt=p=>{for(let i=boxes.length-1;i>=0;i--){const g=geometry(boxes[i]),q=local(g,p);if(Math.abs(q.x)<=g.w/2&&Math.abs(q.y)<=g.h/2)return i;}return -1;};
  const point=e=>{const rect=canvas.getBoundingClientRect(),s=scale();return {x:(e.clientX-rect.left)/s,y:(e.clientY-rect.top)/s};};
  const status=()=>{const el=host.querySelector('.annotation-status'),target=host.querySelector('[data-action="target-order"]');if(target)target.value=selected<0?'':String(selected+1);el.textContent=selected<0?`${boxes.length} boxes`: `Selected reading-order box ${selected+1} of ${boxes.length} · ${Math.round(normalAngle(boxes[selected].rotation_degrees))}°`;};
  const textFor=item=>String(item.text||item.character||item.transcription||item.label||item.char||item.content||'□');
  const reading=()=>{const output=host.querySelector('.annotation-reading output');if(output)output.textContent=boxes.length?boxes.map(textFor).join(' '):'—';};
  const sync=()=>{host._annotationBoxes=boxes;const field=document.querySelector('#annotation_boxes_json textarea,#annotation_boxes_json input');if(field){const value=JSON.stringify(boxes);const proto=field.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));}};
  const draw=()=>{const s=scale(),dw=Math.round(W*s),dh=Math.round(H*s),canvasPoint=p=>({x:p.x*s,y:p.y*s});canvas.width=dw;canvas.height=dh;ctx.drawImage(image,0,0,dw,dh);ctx.lineWidth=2;ctx.font='700 13px sans-serif';
    boxes.forEach((item,i)=>{const g=geometry(item),points=g.corners.map(canvasPoint),isSelected=i===selected;ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);points.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));ctx.closePath();ctx.strokeStyle=isSelected?'#f97316':'#22c55e';ctx.fillStyle=isSelected?'rgba(249,115,22,.14)':'rgba(34,197,94,.10)';ctx.fill();ctx.stroke();
      const label=String(i+1),anchor=points[0];ctx.lineWidth=3;ctx.strokeStyle='rgba(9,9,11,.9)';ctx.strokeText(label,anchor.x+4,Math.max(14,anchor.y+15));ctx.fillStyle='#ef4444';ctx.fillText(label,anchor.x+4,Math.max(14,anchor.y+15));ctx.lineWidth=2;
      if(isSelected){ctx.fillStyle='#f97316';points.forEach(p=>ctx.fillRect(p.x-4,p.y-4,8,8));const top=g.world(0,-g.h/2),handle=rotationHandle(g,s),tp=canvasPoint(top),hp=canvasPoint(handle);ctx.strokeStyle='#f97316';ctx.beginPath();ctx.moveTo(tp.x,tp.y);ctx.lineTo(hp.x,hp.y);ctx.stroke();ctx.beginPath();ctx.arc(hp.x,hp.y,6,0,Math.PI*2);ctx.fill();}});status();reading();};
  const setTool=value=>{tool=value;host.querySelectorAll('[data-action]').forEach(button=>button.classList.toggle('active',button.dataset.action===value));canvas.style.cursor=value==='add'?'crosshair':'default';};
  host.querySelector('[data-action="select"]').onclick=()=>setTool('select');
  host.querySelector('[data-action="add"]').onclick=()=>setTool('add');
  host.querySelector('[data-action="delete"]').onclick=()=>{if(selected<0)return;boxes.splice(selected,1);selected=-1;sync();draw();};
  const swapOrder=target=>{if(selected<0||target<0||target>=boxes.length||target===selected)return false;[boxes[selected],boxes[target]]=[boxes[target],boxes[selected]];selected=target;sync();draw();return true;};
  const moveOrder=direction=>swapOrder(selected+direction);
  host.querySelector('[data-action="earlier"]').onclick=()=>moveOrder(-1);
  host.querySelector('[data-action="later"]').onclick=()=>moveOrder(1);
  host.querySelector('[data-action="swap-to-order"]').onclick=()=>{const input=host.querySelector('[data-action="target-order"]'),target=Number.parseInt(input.value,10)-1;if(!Number.isInteger(target)||target<0||target>=boxes.length){input.setCustomValidity(`Enter an order from 1 to ${boxes.length}.`);input.reportValidity();return;}input.setCustomValidity('');swapOrder(target);};
  canvas.onpointerdown=e=>{const p=point(e);if(tool==='add'){const size=Math.max(12,Math.round(Math.min(W,H)*.025));const l=clamp(Math.round(p.x-size/2),0,W-1),t=clamp(Math.round(p.y-size/2),0,H-1);boxes.push({editor_id:`manual-${Date.now()}`,bbox_xyxy:[l,t,clamp(l+size,l+1,W),clamp(t+size,t+1,H)],rotation_degrees:0,confidence:null,annotation_source:'manual'});selected=boxes.length-1;sync();draw();setTool('select');return;}
    selected=boxAt(p);if(selected<0){draw();return;}const item=boxes[selected],g=geometry(item),handle=16/scale(),rotate=distance(p,rotationHandle(g))<=handle,corner=[[-1,-1,'tl'],[1,-1,'tr'],[-1,1,'bl'],[1,1,'br']].find(([x,y])=>distance(p,g.world(x*g.w/2,y*g.h/2))<=handle);drag={start:p,item:{...item,bbox_xyxy:[...item.bbox_xyxy]},kind:rotate?'rotate':corner?'resize':'move',corner:corner&&corner[2]};canvas.setPointerCapture(e.pointerId);draw();};
  canvas.onpointermove=e=>{if(!drag||selected<0)return;const p=point(e),source=drag.item,g=geometry(source),[l,t,r,b]=source.bbox_xyxy,dx=p.x-drag.start.x,dy=p.y-drag.start.y;
    if(drag.kind==='rotate'){boxes[selected].rotation_degrees=normalAngle(Math.atan2(p.y-g.cy,p.x-g.cx)*180/Math.PI+90);}
    else if(drag.kind==='resize'){const q=local(g,p),signX=drag.corner.includes('l')?-1:1,signY=drag.corner.includes('t')?-1:1,opposite={x:-signX*g.w/2,y:-signY*g.h/2};q.x=signX>0?Math.max(opposite.x+12,q.x):Math.min(opposite.x-12,q.x);q.y=signY>0?Math.max(opposite.y+12,q.y):Math.min(opposite.y-12,q.y);const center=g.world((q.x+opposite.x)/2,(q.y+opposite.y)/2),w=Math.abs(q.x-opposite.x),h=Math.abs(q.y-opposite.y),cx=clamp(center.x,w/2,W-w/2),cy=clamp(center.y,h/2,H-h/2);boxes[selected].bbox_xyxy=[cx-w/2,cy-h/2,cx+w/2,cy+h/2];}
    else {const w=r-l,h=b-t,nl=clamp(l+dx,0,W-w),nt=clamp(t+dy,0,H-h);boxes[selected].bbox_xyxy=[nl,nt,nl+w,nt+h];}sync();draw();};
  canvas.onpointerup=e=>{if(!drag)return;const box=boxes[selected];box.bbox_xyxy=box.bbox_xyxy.map(value=>Math.round(value));box.rotation_degrees=Math.round(normalAngle(box.rotation_degrees)*10)/10;drag=null;canvas.releasePointerCapture(e.pointerId);sync();draw();};
  image.onload=draw;image.src=host.dataset.source;
 };
 const scan=()=>document.querySelectorAll('.annotation-host').forEach(init);new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});window.addEventListener('load',scan);scan();
})();
</script>
"""

READ_BOXES_JS = """
(session, boxes) => {
  const host = document.querySelector('.annotation-host');
  return [session, host && host._annotationBoxes ? JSON.stringify(host._annotationBoxes) : boxes];
}
"""

CSS = WORKSPACE_CSS + """
.annotation-host { min-width: 0; }
.annotation-host canvas { display:block; max-width:100%; border:1px solid #4b5563; border-radius:var(--radius); background:var(--canvas-bg); }
.annotation-toolbar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid var(--border); }
.annotation-toolbar button { min-height:34px; border:1px solid var(--border-strong); border-radius:var(--radius); padding:6px 10px; background:var(--control-bg); color:var(--text); cursor:pointer; font:600 12px/1.2 Inter,ui-sans-serif,system-ui,sans-serif; }
.annotation-toolbar button:hover { background:var(--control-hover); }
.annotation-toolbar button.active { background:var(--accent); color:var(--accent-text); border-color:var(--accent); }
.annotation-order-swap { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:12px; font-weight:600; }
.annotation-order-swap input { width:56px; min-height:34px; padding:5px 7px; background:var(--canvas-bg); color:var(--text); border:1px solid var(--border-strong); border-radius:var(--radius); font:600 12px/1.2 Inter,ui-sans-serif,system-ui,sans-serif; }
.annotation-help,.annotation-status { font-size:12px; color:var(--muted); margin:8px 0; line-height:1.5; }
.annotation-status { color:var(--success); font-weight:600; }
.annotation-reading { display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; margin-top:10px; padding:9px 10px; border:1px solid var(--border); border-radius:var(--radius); background:var(--canvas-bg); font-size:12px; line-height:1.5; }
.annotation-reading span { color:var(--muted); font-weight:600; }
.annotation-reading output { color:var(--text); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }
"""


def build_app(initial_annotation: str | None = None) -> gr.Blocks:
    with gr.Blocks(title="Character Annotation Editor") as demo:
        gr.HTML("""<header class="workspace-header"><div><div class="workspace-title">Character Annotation Editor</div><div class="workspace-subtitle">Review and correct character bounding boxes without changing the source workflow.</div></div><div class="workspace-badge">Annotation workspace</div></header>""")
        state = gr.State({})
        with gr.Row(elem_classes="workspace-grid"):
            with gr.Column(scale=2, min_width=260, elem_classes="workspace-sidebar"):
                gr.HTML('<div class="section-kicker">Dataset</div>')
                with gr.Row(equal_height=True):
                    local_pdf = gr.Dropdown(
                        label="PDF from local input/",
                        choices=local_pdf_choices(),
                        value=None,
                        scale=5,
                    )
                    refresh_pdfs = gr.Button("Refresh", scale=1)
                annotation_path = gr.Textbox(label="Annotation JSON path", value=initial_annotation or "", placeholder="output/book/page_003/final/book.001.characters.json")
                image_override = gr.Textbox(label="Image path override (optional)", placeholder="Use only if source_image in JSON is unavailable")
                load = gr.Button("Load annotation", variant="primary")
                gr.HTML('<div class="section-kicker">Navigation</div>')
                with gr.Row(equal_height=True):
                    previous = gr.Button("← Previous image", interactive=False)
                    next_ = gr.Button("Next image →", interactive=False)
                gr.HTML('<div class="section-kicker">Save</div>')
                save_current = gr.Button("Save current image")
                save_all = gr.Button("Save all annotations", variant="primary")
            with gr.Column(scale=6, min_width=480, elem_classes="workspace-canvas"):
                gr.HTML('<div class="section-kicker">Annotation canvas</div>')
                editor = gr.HTML("Load an annotation JSON to show its source image and character boxes.")
            with gr.Column(scale=2, min_width=250, elem_classes="workspace-inspector"):
                gr.HTML('<div class="section-kicker">Current item</div>')
                status = gr.Markdown("Load an annotation JSON to begin.", elem_classes="status-panel workspace-section")
                reading_order = gr.Markdown("Reading order unavailable.", elem_classes="status-panel workspace-section")
                with gr.Accordion("How to annotate", open=False):
                    gr.Markdown("- **Select / move:** click a box, drag inside it to move, drag a corner to resize, or drag its round handle to rotate.\n- **Earlier / Later:** moves a selected box one position in reading order.\n- **Swap with #:** select a box, enter another red order number, then choose **Swap order** to exchange those two boxes.\n- **Add box:** select it, then click the image.\n- **Delete selected:** removes the active box.\n- **Save current image:** writes only the image currently shown.\n- **Save all annotations:** writes every pending edit in the current collection. Until either Save button is pressed, the original file is unchanged.")
                with gr.Accordion("Pending box data", open=False):
                    boxes = gr.Textbox(
                        label="Boxes (updated by the canvas)",
                        lines=8,
                        interactive=False,
                        elem_id="annotation_boxes_json",
                    )
        local_pdf.change(
            load_session_for_pdf,
            [local_pdf],
            [annotation_path, state, status, editor, reading_order, boxes, previous, next_],
        )
        refresh_pdfs.click(refresh_local_pdfs, outputs=[local_pdf])
        load.click(load_session, [annotation_path, image_override], [state, editor, status, reading_order, boxes, previous, next_])
        save_current.click(
            lambda session, pending: save_session(session, pending, True),
            [state, boxes],
            [state, editor, status, reading_order, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        save_all.click(
            lambda session, pending: save_session(session, pending, False),
            [state, boxes],
            [state, editor, status, reading_order, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        previous.click(
            lambda session, pending: navigate(session, pending, -1),
            [state, boxes],
            [state, editor, status, reading_order, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        next_.click(
            lambda session, pending: navigate(session, pending, 1),
            [state, boxes],
            [state, editor, status, reading_order, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        if initial_annotation:
            demo.load(
                lambda: load_session(initial_annotation, None),
                outputs=[state, editor, status, reading_order, boxes, previous, next_],
            )
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Gradio editor for character-detection JSON sidecars.")
    parser.add_argument("annotation_json", nargs="?", help="Optional .characters.json file to load when the UI opens.")
    args = parser.parse_args(argv)
    initial = str(Path(args.annotation_json).expanduser().resolve()) if args.annotation_json else None
    build_app(initial).launch(server_name="127.0.0.1", theme=WORKSPACE_THEME, head=HEAD, css=CSS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
