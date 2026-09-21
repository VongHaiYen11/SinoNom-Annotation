"""Gradio presentation layer for the local PDF embedded-image extractor."""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
from typing import Any

import gradio as gr
from PIL import Image

from .detection import load_embedded_image
from .processing import get_center_dci_portrait_crop
from .service import create_session, preview as build_preview, save_entry


def _label(entry: dict[str, Any]) -> str:
    return f"Page {entry['page']}"


def _entry(state: dict[str, Any], selection: str) -> dict[str, Any]:
    return next(item for item in state["pages"] if _label(item) == selection)


def _navigation_updates(state: dict[str, Any], page: str | None):
    choices = [_label(item) for item in state.get("pages", [])]
    index = choices.index(page) if page in choices else 0
    return gr.update(interactive=index > 0), gr.update(interactive=index < len(choices) - 1)


def _box(value: str | None, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    try:
        data = json.loads(value or "")
        return tuple(int(data[key]) for key in ("left", "top", "right", "bottom"))  # type: ignore[return-value]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return fallback


def _box_json(box: tuple[int, int, int, int]) -> str:
    return json.dumps(dict(zip(("left", "top", "right", "bottom"), box)))


def _free_crop_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Give free crop a visible, immediately draggable inset frame."""
    inset_x = max(1, round(image.width * 0.06))
    inset_y = max(1, round(image.height * 0.06))
    return (inset_x, inset_y, image.width - inset_x, image.height - inset_y)


def _thumbnail_data(image: Image.Image) -> str:
    view = image.copy()
    view.thumbnail((1200, 850), Image.Resampling.LANCZOS)
    if view.mode not in ("RGB", "RGBA"):
        view = view.convert("RGBA" if "A" in view.getbands() else "RGB")
    stream = io.BytesIO()
    view.save(stream, "PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _editor(image: Image.Image, box: tuple[int, int, int, int], mode: str) -> str:
    return (
        '<div class="cropper-host" data-source="%s" data-width="%d" data-height="%d" '
        'data-box="%s" data-mode="%s"><canvas aria-label="Interactive crop editor"></canvas>'
        '<p>Drag inside the frame to move it. Drag a corner to resize. %s</p></div>'
        % (_thumbnail_data(image), image.width, image.height, _box_json(box).replace('"', '&quot;'), mode,
           "DCI 4K portrait ratio is locked." if mode == "dci_4k" else "Free crop; saved image never exceeds 4096 px on its longest side.")
    )


def _summary(image: Image.Image, box: tuple[int, int, int, int], mode: str) -> tuple[Image.Image, str]:
    dci = mode == "dci_4k"
    result = build_preview(image, box, mode)
    cw, ch = result["crop_size"]
    fw, fh = result["final_size"]
    info = (
        f"### Processing\n\nOriginal image: **{image.width}×{image.height}**  \n"
        f"Crop: **{cw}×{ch}** ({'DCI 4K portrait ratio' if dci else 'free crop'})  \nFinal: **{fw}×{fh}**  \n"
        f"Final portrait frame max: **2160×4096**  \n"
        f"Saved-image longest-side limit: **4096 px**  \nUpscaling: **Disabled (0%)**  \n"
        f"Processing: **Center/manual DCI 4K portrait crop + {'downscale' if result['downscaled'] else 'native resolution'}**"
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
    state = create_session(pdf_path)
    pages = state["pages"]
    choices = [_label(item) for item in pages]
    if not pages:
        return state, gr.update(choices=[], value=None), "No dominant standalone image pages were detected.", None, "", "", "", "{}", gr.update(interactive=False), gr.update(interactive=False)
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
    saved = state.get("crops", {}).get(str(entry["page"]))
    mode = state.get("crop_modes", {}).get(str(entry["page"]), "free")
    box = tuple(saved) if saved else (0, 0, image.width, image.height)
    preview, summary = _summary(image, box, mode)
    editor = _editor(image, box, mode)
    previous_update, next_update = _navigation_updates(state, page)
    return editor, preview, summary, _analysis(entry), _box_json(box), previous_update, next_update


def apply_crop(state: dict[str, Any], page: str, crop_value: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    mode = state.get("crop_modes", {}).get(str(entry["page"]), "free")
    box = _box(crop_value, (0, 0, image.width, image.height))
    print("APPLY CROP RAW:", crop_value)
    print("APPLY CROP PARSED:", box)
    # The editor has already kept the box in DCI 4K portrait ratio and bounds.
    state = {**state, "crops": {**state.get("crops", {}), str(entry["page"]): list(box)}}
    preview, summary = _summary(image, box, mode)
    return state, _editor(image, box, mode), preview, summary, _box_json(box)


def use_dci_frame(state: dict[str, Any], page: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    box = get_center_dci_portrait_crop(*image.size)
    state = {**state, "crops": {**state.get("crops", {}), str(entry["page"]): list(box)}, "crop_modes": {**state.get("crop_modes", {}), str(entry["page"]): "dci_4k"}}
    preview, summary = _summary(image, box, "dci_4k")
    return state, _editor(image, box, "dci_4k"), preview, summary, _box_json(box)


def use_free_crop(state: dict[str, Any], page: str):
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    prior_mode = state.get("crop_modes", {}).get(str(entry["page"]))
    saved = state.get("crops", {}).get(str(entry["page"]))
    # Entering Free Crop always gives a usable inset frame unless the user is
    # already editing an applied free crop on this page.
    box = tuple(saved) if saved and prior_mode == "free" else _free_crop_box(image)
    state = {**state, "crops": {**state.get("crops", {}), str(entry["page"]): list(box)}, "crop_modes": {**state.get("crop_modes", {}), str(entry["page"]): "free"}}
    preview, summary = _summary(image, box, "free")
    return state, _editor(image, box, "free"), preview, summary, _box_json(box)


def move_page(state: dict[str, Any], page: str, direction: int):
    choices = [_label(item) for item in state.get("pages", [])]
    if not choices:
        return None
    index = min(len(choices) - 1, max(0, choices.index(page) + direction))
    return choices[index]


def save_one(state: dict[str, Any], page: str):
    """Save only the already-applied server-side crop for this page."""
    entry = _entry(state, page)
    image, _ = load_embedded_image(state["pdf"], entry)
    saved = state.get("crops", {}).get(str(entry["page"]))
    crop = tuple(saved) if saved else None
    mode = state.get("crop_modes", {}).get(str(entry["page"]), "free")
    path = save_entry(state, entry)
    return f"Saved page {entry['page']} to `{path}`."


def apply_and_save(state: dict[str, Any], page: str, crop_value: str):
    """Persist the current original-pixel crop and write its final file now."""
    updated, editor, preview, summary, box_json = apply_crop(state, page, crop_value)
    # save_one reads the exact crop that apply_crop just persisted in ``updated``.
    message = save_one(updated, page)
    return updated, editor, preview, summary, box_json, message


def save_all(state: dict[str, Any]):
    if not state or not state.get("pages"):
        raise gr.Error("Detect image pages first.")
    locations = []
    for entry in state["pages"]:
        custom = state.get("crops", {}).get(str(entry["page"]))
        mode = state.get("crop_modes", {}).get(str(entry["page"]), "free")
        locations.append(save_entry(state, entry))
    return f"Saved {len(locations)} pages under `{Path(locations[0]).parents[1]}`."


HEAD = """
<script>
(() => {
 const init = host => {
  if (host.dataset.ready) return; host.dataset.ready = 'yes';
  const canvas=host.querySelector('canvas'), ctx=canvas.getContext('2d'), img=new Image();
  const W=+host.dataset.width,H=+host.dataset.height, mode=host.dataset.mode; let b=JSON.parse(host.dataset.box), zoom=1, drag=null;
  host._cropBox={...b};
  const ratio=2160/4096; const toCanvas=()=>Math.min(900/(W*zoom),560/(H*zoom));
  const draw=()=>{const s=toCanvas(), dw=W*s,dh=H*s; canvas.width=dw;canvas.height=dh;ctx.drawImage(img,0,0,dw,dh);ctx.fillStyle='rgba(0,0,0,.42)';
   const x=b.left*s,y=b.top*s,w=(b.right-b.left)*s,h=(b.bottom-b.top)*s;ctx.fillRect(0,0,dw,y);ctx.fillRect(0,y,x,h);ctx.fillRect(x+w,y,dw-x-w,h);ctx.fillRect(0,y+h,dw,dh-y-h);ctx.strokeStyle='#ffb000';ctx.lineWidth=3;ctx.strokeRect(x,y,w,h);ctx.fillStyle='#ffb000';[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].forEach(p=>ctx.fillRect(p[0]-6,p[1]-6,12,12));};
  const sync=()=>{const el=document.querySelector('#crop_box_json textarea,#crop_box_json input');if(el){const value=JSON.stringify(b);const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));}};
  const point=e=>{const r=canvas.getBoundingClientRect(),s=toCanvas();return {x:(e.clientX-r.left)/s,y:(e.clientY-r.top)/s};};
  canvas.onpointerdown=e=>{const p=point(e), inside=p.x>=b.left&&p.x<=b.right&&p.y>=b.top&&p.y<=b.bottom, handle=24;const corner=[[b.left,b.top],[b.right,b.top],[b.left,b.bottom],[b.right,b.bottom]].some(c=>Math.hypot(p.x-c[0],p.y-c[1])<=handle);if(!inside&&!corner)return;drag={p,b:{...b},resize:corner};canvas.setPointerCapture(e.pointerId)};
  canvas.onpointermove=e=>{if(!drag)return;const p=point(e),dx=p.x-drag.p.x,dy=p.y-drag.p.y,old=drag.b,w=old.right-old.left,h=old.bottom-old.top;
   if(drag.resize){const cx=(old.left+old.right)/2,cy=(old.top+old.bottom)/2;if(mode==='dci_4k'){let nw=Math.max(32,w+dx*2),nh=nw/ratio;const maxw=2*Math.min(cx,W-cx,cy*ratio,(H-cy)*ratio);nw=Math.min(nw,maxw);nh=nw/ratio;b={left:cx-nw/2,top:cy-nh/2,right:cx+nw/2,bottom:cy+nh/2};}else{const nw=Math.max(32,Math.min(2*Math.min(cx,W-cx),w+dx*2)),nh=Math.max(32,Math.min(2*Math.min(cy,H-cy),h+dy*2));b={left:cx-nw/2,top:cy-nh/2,right:cx+nw/2,bottom:cy+nh/2};}}
   else {let l=Math.max(0,Math.min(W-w,old.left+dx)),t=Math.max(0,Math.min(H-h,old.top+dy));b={left:l,top:t,right:l+w,bottom:t+h}} host._cropBox={...b};draw();};
  canvas.onpointerup=()=>{drag=null;b={left:Math.round(b.left),top:Math.round(b.top),right:Math.round(b.right),bottom:Math.round(b.bottom)};host._cropBox={...b};console.log('CROP POINTER UP',host._cropBox);sync();draw()};
  canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.5,Math.min(2,zoom+(e.deltaY<0?.1:-.1)));draw()}; img.onload=draw;img.src=host.dataset.source;
 };
 const scan=()=>document.querySelectorAll('.cropper-host').forEach(init);new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});window.addEventListener('load',scan);scan();
})();
</script>
"""

# Apply callbacks read the cropper's own state directly. Normal Save
# intentionally does not read browser state at all.
READ_CROP_BOX_JS = """
(state, page, crop) => {
  const host = document.querySelector('.cropper-host');
  const box = host && host._cropBox ? JSON.stringify(host._cropBox) : crop;
  console.log('CROP SENT TO PYTHON', host ? host._cropBox : null);
  return [state, page, box];
}
"""


HELP_TEXT = """
### Hướng dẫn nhanh

- **Use DCI 4K Frame (2160×4096):** bật khung dọc DCI 4K và khóa tỷ lệ khi chỉnh kích thước.
- **Free Crop:** crop tự do; file lưu vẫn không có cạnh nào vượt quá 4096 px.
- **Apply to live preview:** xác nhận crop đang thấy trên canvas. Chỉ sau bước này crop mới được lưu cho trang đó.
- **Save Applied Final:** lưu crop đã Apply gần nhất. Nếu bạn kéo frame nhưng chưa Apply, thay trang sẽ bỏ thay đổi đó.
- **Apply & Save Final:** Apply và lưu ngay trong một lần bấm.
- **Previous / Next:** chuyển trang; nút xám nghĩa là không còn trang theo hướng đó.
"""

def build_app(initial_pdf: str | None = None) -> gr.Blocks:
    with gr.Blocks(title="PDF Image Extractor") as demo:
        gr.Markdown("# PDF embedded-image extractor\nDirect XObject extraction · centered DCI 4K portrait crop · maximum frame 2160×4096 · upscaling disabled")
        state = gr.State({})
        with gr.Row():
            with gr.Column(scale=1):
                pdf = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
                detect_button = gr.Button("Auto Detect", variant="primary")
                page = gr.Dropdown(label="Detected image page", choices=[])
                with gr.Row(equal_height=True):
                    previous = gr.Button("← Previous page", interactive=False, elem_id="previous-page")
                    next_ = gr.Button("Next page →", interactive=False, elem_id="next-page")
                with gr.Row():
                    dci_frame = gr.Button("Use DCI 4K Frame (2160×4096)", elem_classes="crop-mode-button")
                    free_crop = gr.Button("Free Crop", elem_classes="crop-mode-button")
                    apply = gr.Button("Apply", elem_id="apply-button")
                help_button = gr.Button("? Hướng dẫn", elem_id="help-button")
                gr.Markdown("Output: **JPEG only** · name: `<book_name>.001.jpg`, `<book_name>.002.jpg`, …")
                save = gr.Button("Save Applied Final")
                save_adjusted = gr.Button("Apply & Save Final", variant="primary")
                save_all_button = gr.Button("Save All Detected Images", variant="primary")
                result = gr.Markdown()
                detection = gr.Markdown()
                with gr.Accordion("Current crop coordinates (original pixels)", open=False):
                    crop_box = gr.Textbox(
                        label="Crop box JSON",
                        info="The editor updates this field. You may also edit it, then choose Apply to live preview.",
                        lines=2,
                        elem_id="crop_box_json",
                    )
                help_popup = gr.Markdown(HELP_TEXT, visible=False, elem_id="help-popup")
                close_help = gr.Button("×", visible=False, elem_id="close-help")
            with gr.Column(scale=2):
                editor = gr.HTML("Upload a PDF and select Auto Detect.")
                preview = gr.Image(label="Live final preview", type="pil", interactive=False)
                processing = gr.Markdown()
                with gr.Accordion("PDF Analysis", open=False):
                    analysis = gr.Markdown()
        detect_button.click(detect, [pdf], [state, page, detection, editor, preview, processing, analysis, crop_box, previous, next_])
        page.change(show_page, [state, page], [editor, preview, processing, analysis, crop_box, previous, next_])
        dci_frame.click(use_dci_frame, [state, page], [state, editor, preview, processing, crop_box])
        free_crop.click(use_free_crop, [state, page], [state, editor, preview, processing, crop_box])
        apply.click(
            apply_crop, [state, page, crop_box], [state, editor, preview, processing, crop_box],
            js=READ_CROP_BOX_JS,
        )
        previous.click(lambda s, p: move_page(s, p, -1), [state, page], [page])
        next_.click(lambda s, p: move_page(s, p, 1), [state, page], [page])
        save.click(save_one, [state, page], result)
        save_adjusted.click(
            apply_and_save, [state, page, crop_box],
            [state, editor, preview, processing, crop_box, result], js=READ_CROP_BOX_JS,
        )
        save_all_button.click(save_all, [state], result)
        help_button.click(lambda: (gr.update(visible=True), gr.update(visible=True)), outputs=[help_popup, close_help])
        close_help.click(lambda: (gr.update(visible=False), gr.update(visible=False)), outputs=[help_popup, close_help])
        if initial_pdf:
            demo.load(
                lambda: detect_initial(initial_pdf),
                outputs=[pdf, state, page, detection, editor, preview, processing, analysis, crop_box],
            )
    return demo


def main(argv: list[str] | None = None) -> int:
    """Launch the local UI; kept separate from UI construction for testing."""
    parser = argparse.ArgumentParser(description="Local PDF embedded-image extractor")
    parser.add_argument(
        "pdf", nargs="?", metavar="INPUT_PDF",
        help="Optional local PDF, for example: input/document.pdf",
    )
    args = parser.parse_args(argv)
    initial_pdf = None
    if args.pdf:
        candidate = Path(args.pdf).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
            parser.error(f"PDF file not found or not a .pdf: {args.pdf}")
        initial_pdf = str(candidate)
    build_app(initial_pdf).launch(
        server_name="127.0.0.1",
        head=HEAD,
        css="""
        .cropper-host canvas{max-width:100%;border-radius:10px;cursor:move;box-shadow:0 2px 12px #0002}
        .cropper-host p{font-size:.85em;color:#667085}
        .crop-mode-button button,#previous-page button,#next-page button,#apply-button button,#help-button button{height:42px;min-height:42px}
        .crop-mode-button button{background:#f1f5f9;color:#1e293b;border:1px solid #cbd5e1}
        .crop-mode-button button:hover{background:#e2e8f0}
        #help-button button{color:#475569}
        #help-popup{position:fixed;z-index:1000;top:14%;left:50%;transform:translateX(-50%);width:min(560px,88vw);max-height:65vh;overflow:auto;padding:24px;background:#ffffff!important;color:#172033!important;border:1px solid #cbd5e1;border-radius:14px;box-shadow:0 20px 55px #0005}
        #help-popup *,#help-popup p,#help-popup li,#help-popup h3{color:#172033!important}
        #close-help{position:fixed;z-index:1001;top:calc(14% + 8px);left:calc(50% + min(280px,44vw) - 40px)}
        #close-help button{width:32px;height:32px;min-height:32px;padding:0;background:#ffffff;color:#172033;border:1px solid #94a3b8;border-radius:50%;font-size:24px;line-height:24px;box-shadow:0 2px 8px #0003}
        """,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
