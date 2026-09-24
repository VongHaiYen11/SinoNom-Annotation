"""Run from any directory: python gradio/app.py --image-dir ... --source-json ..."""
import argparse
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# This directory deliberately is NOT a Python package named gradio.
import gradio as gr
from annotation.state import new_state
from annotation.workflow import Workflow
from annotation.io import load_image_list, final_document, read_json
from annotation.text_extraction import leaf_fields, annotation_text
from annotation.text_alignment import normalize_annotation_text, count_annotation_characters
from ui.editor import snapshot, SCRIPT, CSS

log = logging.getLogger(__name__)


def parser():
    p=argparse.ArgumentParser(description='Vietnamica character annotation workflow')
    p.add_argument('--image-dir', default='data/images')
    p.add_argument('--source-json', default='data/source_json/source.json')
    p.add_argument('--output-dir', default='data/annotations')
    p.add_argument('--vague-det-config', default='text_detection/models/ckpts/damage_detect.py')
    p.add_argument('--vague-det-weights', default='text_detection/models/ckpts/damage_detect.pth')
    p.add_argument('--ocr-det-executable', default='text_detection/models/dists/det_model/det_model')
    p.add_argument('--det-batch-size', type=int, default=1)
    p.add_argument('--img-size', type=int, default=2048)
    p.add_argument('--conf-thres', type=float, default=.45)
    p.add_argument('--iou-thres', type=float, default=.2)
    p.add_argument('--port', type=int, default=7860)
    return p


def create_app(options):
    engine=Workflow(options)
    startup=''
    try:
        images=load_image_list(options.image_dir)
        read_json(options.source_json)
        if not images: startup='Không có ảnh trong input folder.'
    except (ValueError,OSError) as exc:
        images=[]; startup=str(exc)
    initial=dict(active=new_state(), drafts={})
    labels=['Image','Content','BBox','Alignment','Status','Reading Order','Review','Crop']
    with gr.Blocks(title='Vietnamica Annotation') as app:
        session=gr.State(initial)
        gr.Markdown('# Vietnamica · Character annotation')
        progress=gr.Markdown('**1 Image** → 2 Content → 3 BBox → 4 Alignment → 5 Status → 6 Reading Order → 7 Review → 8 Crop')
        with gr.Row():
            image_choice=gr.Dropdown(choices=[(p.name,str(p.resolve())) for p in images],label='Ảnh từ input folder')
            open_button=gr.Button('Mở ảnh')
            reset_button=gr.Button('Reset draft / nạp lại file')
        message=gr.Markdown(startup)
        with gr.Group(visible=False) as content_group:
            gr.Markdown('Chọn từng field để sửa. **Áp dụng field** cập nhật draft; **Save content** ghi source JSON và xác nhận. Không sửa ky_hieu của ảnh đang chọn.')
            field=gr.Dropdown(label='Field (đường dẫn trong record)')
            field_value=gr.Textbox(label='Giá trị',lines=5)
            with gr.Row():
                apply_field=gr.Button('Áp dụng field')
                save_content=gr.Button('Save content',variant='primary')
                undo=gr.Button('Undo về lần Save gần nhất')
                restore=gr.Button('Khôi phục content ban đầu vào draft')
            content_preview=gr.JSON(label='Toàn bộ draft content')
            normalized=gr.Textbox(label='Chuỗi annotation sau bỏ dấu câu / whitespace',interactive=False)
        board=gr.HTML(value=snapshot(initial['active']),html_template='${value.markup}',css_template=CSS,js_on_load=SCRIPT)
        with gr.Group(visible=False) as box_group:
            gr.Markdown('Kéo trên vùng trống để thêm box; kéo box để di chuyển; kéo bốn góc để resize. Tọa độ theo pixel ảnh.')
            box_id=gr.Dropdown(label='Box ID')
            with gr.Row():
                x1=gr.Number(label='x1');y1=gr.Number(label='y1');x2=gr.Number(label='x2');y2=gr.Number(label='y2')
            with gr.Row():
                add=gr.Button('Thêm box'); update=gr.Button('Cập nhật tọa độ');delete=gr.Button('Xóa box')
            rerun_confirm=gr.Checkbox(label='Tôi muốn thay toàn bộ boxes bằng kết quả detection mới')
            detect=gr.Button('Chạy / chạy lại detection')
        with gr.Group(visible=False) as status_group:
            status_id=gr.Dropdown(label='Box cần sửa status')
            status=gr.Radio(['intact','damaged'],value='intact',label='Status')
            set_status=gr.Button('Cập nhật status')
        with gr.Group(visible=False) as order_group:
            gr.Markdown('Kéo thẻ để thay thứ tự. Next xác nhận thứ tự hiện tại. Mapping ký tự theo ID được giữ nguyên.')
            order_text=gr.Textbox(label='Phương án nhập thứ tự bằng JSON, ví dụ [1,3,2]')
            set_order=gr.Button('Áp dụng reading order')
        preview=gr.JSON(label='Final JSON preview',visible=False)
        with gr.Group(visible=False) as crop_group:
            gr.Markdown('Crop độc lập: kéo frame/bốn góc, hoặc sửa tọa độ. Không thay ảnh/bbox annotation.')
            crop_coords=gr.Textbox(label='Crop [x1,y1,x2,y2]')
            apply_crop=gr.Button('Áp dụng crop coordinates')
            save_crop=gr.Button('Save crop')
        with gr.Row():
            back=gr.Button('← Back');next_button=gr.Button('Next →',variant='primary')
            save=gr.Button('Save annotation',visible=False)
        outputs=[session,progress,message,content_group,field,field_value,content_preview,normalized,board,box_group,box_id,x1,y1,x2,y2,status_group,status_id,status,order_group,order_text,preview,crop_group,crop_coords,save]

        def render(ctx, msg=''):
            s=ctx['active']; step=s['current_step']; has=bool(s.get('image'))
            fields=list(leaf_fields(s['draft_content'])) if has else []
            choices=[('/'.join(map(str,path)),json.dumps(path,ensure_ascii=False)) for path,_ in fields]
            chosen=choices[0][1] if choices else None
            val=fields[0][1] if fields else ''
            try:
                text=annotation_text(s['draft_content'],s['code']) if has else ''
            except ValueError:
                text='' 
            ids=list(s['bounding_boxes']);selected=s['selected_box_id'] if s['selected_box_id'] in ids else (ids[0] if ids else None)
            box=s['bounding_boxes'].get(selected,dict(bbox=[0,0,1,1],status='intact'))
            count=count_annotation_characters(s['annotation_text'])
            count_msg=f'Boxes: {len(ids)} · Source characters: {count}' if has else ''
            if has and s['workflow']['content_verified'] and len(ids)!=count:
                count_msg+=' · ⚠ Không khớp. Quay lại Step 3 để thêm/xóa box.'
            if selected:
                count_msg += f' · Selected ID {selected}: {s["annotations"].get(selected, "?")} · {box["bbox"]}'
            final=final_document(s) if step==7 else None
            return [ctx,' → '.join(f'**{i} {name}**' if step==i else f'{i} {name}' for i,name in enumerate(labels,1)),msg+'\n\n'+count_msg,
                    gr.update(visible=step==2 and has),gr.update(choices=choices,value=chosen),str(val) if isinstance(val,str) else json.dumps(val,ensure_ascii=False),s.get('draft_content'),normalize_annotation_text(text),snapshot(s),
                    gr.update(visible=step==3 and has),gr.update(choices=ids,value=selected),*box['bbox'],
                    gr.update(visible=step==5),gr.update(choices=ids,value=selected),box['status'],
                    gr.update(visible=step==6),json.dumps(s['reading_order']),gr.update(value=final,visible=step==7),
                    gr.update(visible=step==8),json.dumps(s.get('crop')),gr.update(visible=step==7)]

        def run(ctx, action, payload=None):
            try:
                updated=engine.apply(ctx['active'],action,payload)
                ctx=dict(ctx,active=updated)
                msg='Đã lưu.' if action in ('save','save_content','save_crop') else ''
                if action=='next' and updated['current_step']==3 and not updated['detection_loaded']:
                    try:
                        ctx=dict(ctx,active=engine.apply(updated,'detect'))
                    except Exception as exc:
                        log.exception('Detection failed')
                        msg='Detection chưa chạy được: '+str(exc)+'. Có thể sửa model parameters và chạy lại hoặc thêm box thủ công.'
                result = render(ctx,msg)
                # Preserve unaffected editors and avoid replacing unrelated component values.
                affected = {
                    'select': {0,2,8,10,11,12,13,14,16,17},
                    'status': {0,2,8,17},
                    'reorder': {0,2,8,19},
                    'crop': {0,2,8,22},
                    'field': {0,2,6,7},
                }.get(action)
                if affected is not None:
                    result = [value if i in affected else gr.skip() for i,value in enumerate(result)]
                return result
            except Exception as exc:
                log.exception('Action %s rejected',action)
                # Return a new revision even on errors, so the browser releases pending state.
                ctx=deepcopy(ctx);ctx['active']['revision']+=1
                return render(ctx,'⚠ '+str(exc))

        def open_image(ctx,path,reset=False):
            try:
                if path not in {str(p.resolve()) for p in images}:raise ValueError('Hãy chọn ảnh trong danh sách.')
                ctx=deepcopy(ctx)
                old=ctx['active']
                if old.get('image_path'):ctx['drafts'][old['image_path']]=old
                state=engine.open_image(path) if reset or path not in ctx['drafts'] else deepcopy(ctx['drafts'][path])
                state['revision']=old['revision']+1
                ctx['active']=state
                return render(ctx)
            except Exception as exc:
                log.exception('Cannot open image')
                return render(ctx,'⚠ '+str(exc))

        event_args=dict(outputs=outputs,concurrency_id='annotation-actions',concurrency_limit=1)
        open_button.click(open_image,[session,image_choice],**event_args)
        reset_button.click(lambda c,p:open_image(c,p,True),[session,image_choice],**event_args)
        for button,action in [(back,'back'),(next_button,'next'),(save,'save'),(save_content,'save_content'),(undo,'undo'),(restore,'original'),(save_crop,'save_crop')]:
            button.click(lambda c,a=action:run(c,a),[session],**event_args)
        def choose_field(ctx,path):
            if not path:return ''
            value=ctx['active']['draft_content']
            for part in json.loads(path):value=value[part]
            return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        field.input(choose_field,[session,field],[field_value],concurrency_id='annotation-actions')
        apply_field.click(lambda c,p,v:run(c,'field',dict(path=json.loads(p),value=v)),[session,field,field_value],**event_args)
        for button,action in [(add,'add'),(update,'update')]:
            button.click(lambda c,i,a,b,d,e,op=action:run(c,op,dict(id=i,bbox=[a,b,d,e])),[session,box_id,x1,y1,x2,y2],**event_args)
        delete.click(lambda c,i:run(c,'delete',dict(id=i)),[session,box_id],**event_args)
        detect.click(lambda c,ok:run(c,'detect') if ok or not c['active']['detection_loaded'] else render(c,'⚠ Chọn checkbox xác nhận thay boxes.'),[session,rerun_confirm],**event_args)
        for selector in (box_id,status_id):
            selector.input(lambda c,i:run(c,'select',dict(id=i)),[session,selector],**event_args)
        set_status.click(lambda c,i,v:run(c,'status',dict(id=i,status=v)),[session,status_id,status],**event_args)
        def parse_action(c,a,key,value):
            try:return run(c,a,{key:json.loads(value)})
            except ValueError as exc:return render(c,'⚠ JSON không hợp lệ: '+str(exc))
        set_order.click(lambda c,v:parse_action(c,'reorder','order',v),[session,order_text],**event_args)
        apply_crop.click(lambda c,v:parse_action(c,'crop','bbox',v),[session,crop_coords],**event_args)
        def on_action(ctx,evt:gr.EventData):
            return run(ctx,evt._data['action'],evt._data['payload'])
        board.action(on_action,[session],**event_args)
    return app


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    args=parser().parse_args()
    create_app(args).queue().launch(server_name='127.0.0.1',server_port=args.port)
