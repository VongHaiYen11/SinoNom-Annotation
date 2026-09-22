"""Gradio presentation layer for manually correcting character annotations."""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
from typing import Any

import gradio as gr
from PIL import Image

from .annotation_editor import apply_pending, current_record, load_annotation, move_to_image, save_annotation, save_current_annotation


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
        {
            "editor_id": index,
            "bbox_xyxy": item["bbox_xyxy"],
            "confidence": item.get("confidence"),
        }
        for index, item in enumerate(detections)
    ]
    return (
        '<div class="annotation-host" data-source="%s" data-width="%d" data-height="%d" '
        'data-boxes="%s"><div class="annotation-toolbar">'
        '<button type="button" data-action="select" class="active">Select / move</button>'
        '<button type="button" data-action="add">+ Add box</button>'
        '<button type="button" data-action="delete">Delete selected</button>'
        '</div><canvas aria-label="Character bounding-box editor"></canvas>'
        '<p class="annotation-help">Click a box to select it; drag inside to move; drag a corner to resize. '
        'Choose <strong>Add box</strong>, then click the image to add a character box. Changes are pending until Save.</p>'
        '<p class="annotation-status"></p></div>'
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
    return session, _editor(session), _summary(session), _boxes(session), previous, next_


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
    return updated, _editor(updated), _summary(updated, saved="current" if current_only else "all"), _boxes(updated), previous, next_


def navigate(session: dict[str, Any], edited_boxes: str, direction: int):
    if not session:
        raise gr.Error("Load an annotation JSON first.")
    try:
        pending = apply_pending(session, _edited_detections(edited_boxes))
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    updated = move_to_image(pending, pending["current_index"] + direction)
    previous, next_ = _navigation(updated)
    return updated, _editor(updated), _summary(updated), _boxes(updated), previous, next_


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
  const boxAt=p=>{for(let i=boxes.length-1;i>=0;i--){const [l,t,r,b]=boxes[i].bbox_xyxy;if(p.x>=l&&p.x<=r&&p.y>=t&&p.y<=b)return i;}return -1;};
  const point=e=>{const rect=canvas.getBoundingClientRect(),s=scale();return {x:(e.clientX-rect.left)/s,y:(e.clientY-rect.top)/s};};
  const status=()=>{const el=host.querySelector('.annotation-status');el.textContent=selected<0?`${boxes.length} boxes`: `Selected box ${selected+1} of ${boxes.length}`;};
  const sync=()=>{host._annotationBoxes=boxes;const field=document.querySelector('#annotation_boxes_json textarea,#annotation_boxes_json input');if(field){const value=JSON.stringify(boxes);const proto=field.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));}};
  const draw=()=>{const s=scale(),dw=Math.round(W*s),dh=Math.round(H*s);canvas.width=dw;canvas.height=dh;ctx.drawImage(image,0,0,dw,dh);ctx.lineWidth=2;ctx.font='13px sans-serif';
    boxes.forEach((item,i)=>{const [l,t,r,b]=item.bbox_xyxy,x=l*s,y=t*s,w=(r-l)*s,h=(b-t)*s,isSelected=i===selected;ctx.strokeStyle=isSelected?'#f97316':'#22c55e';ctx.fillStyle=isSelected?'rgba(249,115,22,.14)':'rgba(34,197,94,.10)';ctx.fillRect(x,y,w,h);ctx.strokeRect(x,y,w,h);ctx.fillStyle=isSelected?'#f97316':'#15803d';ctx.fillText(String(i+1),x+3,Math.max(13,y+13));if(isSelected){ctx.fillStyle='#f97316';[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].forEach(p=>ctx.fillRect(p[0]-4,p[1]-4,8,8));}});status();};
  const setTool=value=>{tool=value;host.querySelectorAll('[data-action]').forEach(button=>button.classList.toggle('active',button.dataset.action===value));canvas.style.cursor=value==='add'?'crosshair':'default';};
  host.querySelector('[data-action="select"]').onclick=()=>setTool('select');
  host.querySelector('[data-action="add"]').onclick=()=>setTool('add');
  host.querySelector('[data-action="delete"]').onclick=()=>{if(selected<0)return;boxes.splice(selected,1);selected=-1;sync();draw();};
  canvas.onpointerdown=e=>{const p=point(e);if(tool==='add'){const size=Math.max(12,Math.round(Math.min(W,H)*.025));const l=clamp(Math.round(p.x-size/2),0,W-1),t=clamp(Math.round(p.y-size/2),0,H-1);boxes.push({editor_id:`manual-${Date.now()}`,bbox_xyxy:[l,t,clamp(l+size,l+1,W),clamp(t+size,t+1,H)],confidence:null,annotation_source:'manual'});selected=boxes.length-1;sync();draw();setTool('select');return;}
    selected=boxAt(p);if(selected<0){draw();return;}const box=boxes[selected].bbox_xyxy,[l,t,r,b]=box,handle=18;const corner=[[l,t,'tl'],[r,t,'tr'],[l,b,'bl'],[r,b,'br']].find(c=>Math.hypot(p.x-c[0],p.y-c[1])<=handle);drag={start:p,box:[...box],corner:corner&&corner[2]};canvas.setPointerCapture(e.pointerId);draw();};
  canvas.onpointermove=e=>{if(!drag||selected<0)return;const p=point(e),[l,t,r,b]=drag.box,dx=Math.round(p.x-drag.start.x),dy=Math.round(p.y-drag.start.y);let next;
    if(drag.corner){let nl=l,nt=t,nr=r,nb=b;if(drag.corner.includes('l'))nl=clamp(l+dx,0,r-1);else nr=clamp(r+dx,l+1,W);if(drag.corner.includes('t'))nt=clamp(t+dy,0,b-1);else nb=clamp(b+dy,t+1,H);next=[nl,nt,nr,nb];}
    else {const w=r-l,h=b-t,nl=clamp(l+dx,0,W-w),nt=clamp(t+dy,0,H-h);next=[nl,nt,nl+w,nt+h];}boxes[selected].bbox_xyxy=next;sync();draw();};
  canvas.onpointerup=e=>{if(!drag)return;drag=null;canvas.releasePointerCapture(e.pointerId);sync();draw();};
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

CSS = """
.annotation-host canvas{display:block;max-width:100%;border:1px solid #d1d5db;border-radius:8px;background:#111}
.annotation-toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}.annotation-toolbar button{border:1px solid #cbd5e1;border-radius:6px;padding:7px 10px;background:#fff;color:#1f2937;cursor:pointer}.annotation-toolbar button.active{background:#2563eb;color:#fff;border-color:#2563eb}.annotation-help,.annotation-status{font-size:.9rem;color:#4b5563;margin:8px 0}
"""


def build_app(initial_annotation: str | None = None) -> gr.Blocks:
    with gr.Blocks(title="Character Annotation Editor") as demo:
        gr.Markdown("# Character Annotation Editor\nOpen an existing `*.characters.json`, correct its character bounding boxes, then explicitly save to overwrite that same JSON file.")
        state = gr.State({})
        with gr.Row():
            with gr.Column(scale=1):
                annotation_path = gr.Textbox(label="Annotation JSON path", value=initial_annotation or "", placeholder="output/book/page_003/final/book.001.characters.json")
                image_override = gr.Textbox(label="Image path override (optional)", placeholder="Use only if source_image in JSON is unavailable")
                load = gr.Button("Load annotation", variant="primary")
                with gr.Row(equal_height=True):
                    previous = gr.Button("← Previous image", interactive=False)
                    next_ = gr.Button("Next image →", interactive=False)
                save_current = gr.Button("Save current image")
                save_all = gr.Button("Save all annotations", variant="primary")
                status = gr.Markdown("Load an annotation JSON to begin.")
                with gr.Accordion("How to annotate", open=False):
                    gr.Markdown("- **Select / move:** click a box, drag inside it to move, or drag a corner to resize.\n- **Add box:** select it, then click the image.\n- **Delete selected:** removes the active box.\n- **Save current image:** writes only the image currently shown.\n- **Save all annotations:** writes every pending edit in the current collection. Until either Save button is pressed, the original file is unchanged.")
                with gr.Accordion("Pending box data", open=False):
                    boxes = gr.Textbox(
                        label="Boxes (updated by the canvas)",
                        lines=8,
                        interactive=False,
                        elem_id="annotation_boxes_json",
                    )
            with gr.Column(scale=2):
                editor = gr.HTML("Load an annotation JSON to show its source image and character boxes.")
        load.click(load_session, [annotation_path, image_override], [state, editor, status, boxes, previous, next_])
        save_current.click(
            lambda session, pending: save_session(session, pending, True),
            [state, boxes],
            [state, editor, status, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        save_all.click(
            lambda session, pending: save_session(session, pending, False),
            [state, boxes],
            [state, editor, status, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        previous.click(
            lambda session, pending: navigate(session, pending, -1),
            [state, boxes],
            [state, editor, status, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        next_.click(
            lambda session, pending: navigate(session, pending, 1),
            [state, boxes],
            [state, editor, status, boxes, previous, next_],
            js=READ_BOXES_JS,
        )
        if initial_annotation:
            demo.load(
                lambda: load_session(initial_annotation, None),
                outputs=[state, editor, status, boxes, previous, next_],
            )
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Gradio editor for character-detection JSON sidecars.")
    parser.add_argument("annotation_json", nargs="?", help="Optional .characters.json file to load when the UI opens.")
    args = parser.parse_args(argv)
    initial = str(Path(args.annotation_json).expanduser().resolve()) if args.annotation_json else None
    build_app(initial).launch(server_name="127.0.0.1", head=HEAD, css=CSS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
