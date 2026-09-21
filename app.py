"""Run the local PDF embedded-image extractor with: python app.py"""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
from typing import Any

import gradio as gr
from PIL import Image

from pdf_image_extractor.core import (
    extract_image_pages,
    get_center_16_9_crop,
    load_embedded_image,
    process_image,
    save_processed_page,
)


def _label(entry: dict[str, Any]) -> str:
    return f"Page {entry['page']}"


def _entry(state: dict[str, Any], selection: str) -> dict[str, Any]:
    return next(item for item in state["pages"] if _label(item) == selection)


def _box(value: str | None, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    try:
        data = json.loads(value or "")
        return tuple(int(data[key]) for key in ("left", "top", "right", "bottom"))  # type: ignore[return-value]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return fallback


def _box_json(box: tuple[int, int, int, int]) -> str:
    return json.dumps(dict(zip(("left", "top", "right", "bottom"), box)))


def _thumbnail_data(image: Image.Image) -> str:
    view = image.copy()
    view.thumbnail((1200, 850), Image.Resampling.LANCZOS)
    if view.mode not in ("RGB", "RGBA"):
        view = view.convert("RGBA" if "A" in view.getbands() else "RGB")
    stream = io.BytesIO()
    view.save(stream, "PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _editor(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    return (
        '<div class="cropper-host" data-source="%s" data-width="%d" data-height="%d" '
        'data-box="%s"><canvas aria-label="Interactive 9:16 crop editor"></canvas>'
        '<p>Drag inside the frame to move it. Drag a corner to resize. Mouse wheel zooms the editor view.</p></div>'
        % (_thumbnail_data(image), image.width, image.height, _box_json(box).replace('"', '&quot;'))
    )


def _summary(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[Image.Image, str]:
    result = process_image(image, crop_mode="manual", crop_box=box)
    cw, ch = result["crop_size"]
    fw, fh = result["final_size"]
    info = (
        f"### Processing\n\nOriginal image: **{image.width}×{image.height}**  \n"
        f"Crop: **{cw}×{ch}** (9:16)  \nFinal: **{fw}×{fh}**  \n"
        f"Maximum frame: **2160×3840**  \nUpscaling: **Disabled (0%)**  \n"
        f"Processing: **Center/manual 9:16 crop + {'downscale' if result['downscaled'] else 'native resolution'}**"
    )
    return result["image"], info


def _analysis(entry: dict[str, Any]) -> str:
    rects = entry["display_rects"]
    rect_text = ", ".join(f"({r[0]:.1f}, {r[1]:.1f})–({r[2]:.1f}, {r[3]:.1f})" for r in rects) or "not reported"
    return (
        f"### Page {entry['page']}\n\n"
        f"- Page size: {entry['page_size'][0]:.1f}×{entry['page_size'][1]:.1f} pt\n"
        f"- Image XObjects: {entry['image_count']} (meaningful: {entry['meaningful_image_count']})\n"
        f"- Image size: {entry['width']}×{entry['height']} px; format: {entry['extension']}\n"
        f"- Display position/size: {rect_text}\n"
        f"- Transformation matrices: {entry['transforms'] or 'not reported'}\n"
        f"- Text blocks: {entry['text_blocks']}; vector drawings: {entry['drawings']}\n"
        f"- Dominant image: YES; confidence: {entry['confidence']:.0%}\n"
        f"- Extraction: {entry['extraction_method']}\n"
    )


def detect(pdf_path: str | None):
    if not pdf_path:
        raise gr.Error("Upload a PDF first.")
    pages = extract_image_pages(pdf_path)
    state = {"pdf": pdf_path, "pages": pages, "crops": {}}
    choices = [_label(item) for item in pages]
    if not pages:
        return state, gr.update(choices=[], value=None), "No dominant standalone image pages were detected.", None, "", "", "", "{}"
    first = choices[0]
    outputs = show_page(state, first)
    return state, gr.update(choices=choices, value=first), f"Detected image pages: **{len(pages)}**", *outputs


def detect_initial(pdf_path: str):
    """Load a PDF supplied on the command line when the browser first opens."""
    return (gr.update(value=pdf_path), *detect(pdf_path))


def show_page(state: dict[str, Any], page: str | None):
    if not state or not page:
        return None, "", "", "", "{}"
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    default = get_center_16_9_crop(*image.size)
    saved = state.get("crops", {}).get(str(entry["page"]))
    box = tuple(saved) if saved else default
    preview, summary = _summary(image, box)
    return _editor(image, box), preview, summary, _analysis(entry), _box_json(box)


def apply_crop(state: dict[str, Any], page: str, crop_value: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    box = _box(crop_value, get_center_16_9_crop(*image.size))
    # The editor has already kept the box in bounds and 9:16; persist its native coordinates.
    state = {**state, "crops": {**state.get("crops", {}), str(entry["page"]): list(box)}}
    preview, summary = _summary(image, box)
    return state, _editor(image, box), preview, summary, _box_json(box)


def auto_center(state: dict[str, Any], page: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    box = get_center_16_9_crop(*image.size)
    state = {**state, "crops": {**state.get("crops", {}), str(entry["page"]): list(box)}}
    preview, summary = _summary(image, box)
    return state, _editor(image, box), preview, summary, _box_json(box)


def move_page(state: dict[str, Any], page: str, direction: int):
    choices = [_label(item) for item in state.get("pages", [])]
    if not choices:
        return None
    index = min(len(choices) - 1, max(0, choices.index(page) + direction))
    return choices[index]


def save_one(state: dict[str, Any], page: str, crop_value: str, fmt: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    path = save_processed_page(state["pdf"], entry, _box(crop_value, get_center_16_9_crop(*image.size)), fmt)
    return f"Saved page {entry['page']} to `{path}`."


def apply_and_save(state: dict[str, Any], page: str, crop_value: str, fmt: str):
    """Persist the current original-pixel crop and write its final file now."""
    updated, editor, preview, summary, box_json = apply_crop(state, page, crop_value)
    message = save_one(updated, page, box_json, fmt)
    return updated, editor, preview, summary, box_json, message


def save_all(state: dict[str, Any], fmt: str):
    if not state or not state.get("pages"):
        raise gr.Error("Detect image pages first.")
    locations = []
    for entry in state["pages"]:
        custom = state.get("crops", {}).get(str(entry["page"]))
        locations.append(save_processed_page(state["pdf"], entry, tuple(custom) if custom else None, fmt))
    return f"Saved {len(locations)} pages under `{Path(locations[0]).parents[1]}`."


HEAD = """
<script>
(() => {
 const init = host => {
  if (host.dataset.ready) return; host.dataset.ready = 'yes';
  const canvas=host.querySelector('canvas'), ctx=canvas.getContext('2d'), img=new Image();
  const W=+host.dataset.width,H=+host.dataset.height; let b=JSON.parse(host.dataset.box), zoom=1, drag=null;
  const ratio=9/16; const toCanvas=()=>Math.min(900/(W*zoom),560/(H*zoom));
  const draw=()=>{const s=toCanvas(), dw=W*s,dh=H*s; canvas.width=dw;canvas.height=dh;ctx.drawImage(img,0,0,dw,dh);ctx.fillStyle='rgba(0,0,0,.42)';
   const x=b.left*s,y=b.top*s,w=(b.right-b.left)*s,h=(b.bottom-b.top)*s;ctx.fillRect(0,0,dw,y);ctx.fillRect(0,y,x,h);ctx.fillRect(x+w,y,dw-x-w,h);ctx.fillRect(0,y+h,dw,dh-y-h);ctx.strokeStyle='#ffb000';ctx.lineWidth=3;ctx.strokeRect(x,y,w,h);ctx.fillStyle='#ffb000';[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].forEach(p=>ctx.fillRect(p[0]-6,p[1]-6,12,12));};
  const sync=()=>{const el=document.querySelector('#crop_box_json textarea,#crop_box_json input');if(el){const value=JSON.stringify(b);const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}};
  const point=e=>{const r=canvas.getBoundingClientRect(),s=toCanvas();return {x:(e.clientX-r.left)/s,y:(e.clientY-r.top)/s};};
  canvas.onpointerdown=e=>{const p=point(e), edge=Math.min(Math.abs(p.x-b.left),Math.abs(p.x-b.right),Math.abs(p.y-b.top),Math.abs(p.y-b.bottom));drag={p,b:{...b},resize:edge<35};canvas.setPointerCapture(e.pointerId)};
  canvas.onpointermove=e=>{if(!drag)return;const p=point(e),dx=p.x-drag.p.x,dy=p.y-drag.p.y,old=drag.b,w=old.right-old.left,h=old.bottom-old.top;
   if(drag.resize){const cx=(old.left+old.right)/2,cy=(old.top+old.bottom)/2;let nw=Math.max(32,w+dx*2),nh=nw/ratio;const maxw=2*Math.min(cx,W-cx,cy*ratio,(H-cy)*ratio);nw=Math.min(nw,maxw);nh=nw/ratio;b={left:cx-nw/2,top:cy-nh/2,right:cx+nw/2,bottom:cy+nh/2};}
   else {let l=Math.max(0,Math.min(W-w,old.left+dx)),t=Math.max(0,Math.min(H-h,old.top+dy));b={left:l,top:t,right:l+w,bottom:t+h}} draw();};
  canvas.onpointerup=()=>{drag=null;b={left:Math.round(b.left),top:Math.round(b.top),right:Math.round(b.right),bottom:Math.round(b.bottom)};sync();draw()};
  canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.5,Math.min(2,zoom+(e.deltaY<0?.1:-.1)));draw()}; img.onload=draw;img.src=host.dataset.source;
 };
 const scan=()=>document.querySelectorAll('.cropper-host').forEach(init);new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});window.addEventListener('load',scan);scan();
})();
</script>
"""


def build_app(initial_pdf: str | None = None) -> gr.Blocks:
    with gr.Blocks(title="PDF Image Extractor") as demo:
        gr.Markdown("# PDF embedded-image extractor\nDirect XObject extraction · centered vertical 9:16 crop · maximum frame 2160×3840 · upscaling disabled")
        state = gr.State({})
        with gr.Row():
            with gr.Column(scale=1):
                pdf = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
                detect_button = gr.Button("Auto Detect", variant="primary")
                page = gr.Dropdown(label="Detected image page", choices=[])
                with gr.Row():
                    previous = gr.Button("Previous page")
                    next_ = gr.Button("Next page")
                with gr.Row():
                    auto = gr.Button("Auto Center")
                    reset = gr.Button("Reset")
                    apply = gr.Button("Apply to live preview")
                fmt = gr.Radio(["PNG", "JPEG"], value="PNG", label="Output format")
                save = gr.Button("Save")
                save_adjusted = gr.Button("Apply & Save Final", variant="primary")
                save_all_button = gr.Button("Save All Detected Images", variant="primary")
                result = gr.Markdown()
                detection = gr.Markdown()
                crop_box = gr.Textbox(visible=False, elem_id="crop_box_json")
            with gr.Column(scale=2):
                editor = gr.HTML("Upload a PDF and select Auto Detect.")
                preview = gr.Image(label="Live final preview", type="pil", interactive=False)
                processing = gr.Markdown()
                with gr.Accordion("PDF Analysis", open=False):
                    analysis = gr.Markdown()
        detect_button.click(detect, [pdf], [state, page, detection, editor, preview, processing, analysis, crop_box])
        page.change(show_page, [state, page], [editor, preview, processing, analysis, crop_box])
        crop_box.change(apply_crop, [state, page, crop_box], [state, editor, preview, processing, crop_box])
        auto.click(auto_center, [state, page], [state, editor, preview, processing, crop_box])
        reset.click(auto_center, [state, page], [state, editor, preview, processing, crop_box])
        apply.click(apply_crop, [state, page, crop_box], [state, editor, preview, processing, crop_box])
        previous.click(lambda s, p: move_page(s, p, -1), [state, page], [page])
        next_.click(lambda s, p: move_page(s, p, 1), [state, page], [page])
        save.click(save_one, [state, page, crop_box, fmt], result)
        save_adjusted.click(
            apply_and_save, [state, page, crop_box, fmt],
            [state, editor, preview, processing, crop_box, result],
        )
        save_all_button.click(save_all, [state, fmt], result)
        if initial_pdf:
            demo.load(
                lambda: detect_initial(initial_pdf),
                outputs=[pdf, state, page, detection, editor, preview, processing, analysis, crop_box],
            )
    return demo


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local PDF embedded-image extractor")
    parser.add_argument(
        "pdf", nargs="?", metavar="INPUT_PDF",
        help="Optional local PDF, for example: input/document.pdf",
    )
    args = parser.parse_args()
    initial_pdf = None
    if args.pdf:
        candidate = Path(args.pdf).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
            parser.error(f"PDF file not found or not a .pdf: {args.pdf}")
        initial_pdf = str(candidate)
    build_app(initial_pdf).launch(
        server_name="127.0.0.1",
        head=HEAD,
        css=".cropper-host canvas{max-width:100%;border-radius:8px;cursor:move}.cropper-host p{font-size:.85em;color:#666}",
    )
