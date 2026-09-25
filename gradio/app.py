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
from annotation.text_extraction import content_fields, annotation_text
from annotation.export import collect_annotations, collect_content_documents
from ui.editor import snapshot, SCRIPT, CSS
from ui.presentation import APP_CSS, header, panel_heading, panel_summary, footer, status_rows, SECTION_LABELS
from ui.fonts import FONT_FILES, FONT_PICKER, FONT_PICKER_SCRIPT

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _config_relative(config_path, value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Config field {field} must be a non-empty path string.')
    path = Path(value).expanduser()
    return str(path.resolve() if path.is_absolute() else (config_path.parent / path).resolve())


def resolve_app_paths(options):
    """Fill omitted CLI paths from config while preserving CLI precedence."""
    if all(getattr(options, name, None) for name in ('image_dir', 'source_json', 'output_dir')):
        return options
    config_path = Path(options.config).expanduser().resolve()
    try:
        config = read_json(config_path)
    except OSError as exc:
        raise ValueError(f'Cannot read app config {config_path}: {exc}') from exc
    if not isinstance(config, dict):
        raise ValueError('App config must be a JSON object.')
    paths = config.get('paths')
    gradio_paths = config.get('gradio')
    if not isinstance(paths, dict) or not isinstance(gradio_paths, dict):
        raise ValueError("Config must contain 'paths' and 'gradio' objects.")
    if not options.image_dir:
        options.image_dir = _config_relative(config_path, gradio_paths.get('image_dir'), 'gradio.image_dir')
    if not options.source_json:
        options.source_json = _config_relative(config_path, paths.get('output_json'), 'paths.output_json')
    if not options.output_dir:
        options.output_dir = _config_relative(config_path, gradio_paths.get('output_dir'), 'gradio.output_dir')
    return options


def parser():
    p=argparse.ArgumentParser(description='Vietnamica character annotation workflow')
    p.add_argument('--config', default=str(REPO_ROOT / 'configs/tap_1.json'),
                   help='Config used for omitted image/source/output paths.')
    p.add_argument('--image-dir', default=None,
                   help='Override config gradio.image_dir.')
    p.add_argument('--source-json', default=None,
                   help='Override config paths.output_json.')
    p.add_argument('--output-dir', default=None,
                   help='Override config gradio.output_dir.')
    p.add_argument('--skip-detection', action='store_true',
                   help='Disable detection; load existing annotations or draw boxes manually.')
    p.add_argument('--vague-det-config', default=str(REPO_ROOT / 'text_detection/models/ckpts/damage_detect.py'))
    p.add_argument('--vague-det-weights', default=str(REPO_ROOT / 'text_detection/models/ckpts/damage_detect.pth'))
    p.add_argument('--ocr-det-executable', default=str(REPO_ROOT / 'text_detection/models/dists/det_model/det_model'))
    p.add_argument('--det-batch-size', type=int, default=1)
    p.add_argument('--img-size', type=int, default=2048)
    p.add_argument('--conf-thres', type=float, default=.45)
    p.add_argument('--iou-thres', type=float, default=.2)
    p.add_argument('--show-detection-logs', action='store_true',
                   help='Show stdout/stderr from the packaged OCR detector process.')
    p.add_argument('--port', type=int, default=7860)
    p.add_argument('--server-name', default='127.0.0.1')
    p.add_argument('--share', action='store_true', help='Create a public Gradio link.')
    return p


def create_app(options):
    options=resolve_app_paths(options)
    # Expose only the requested font assets, regardless of the working directory.
    gr.set_static_paths(paths=[path for path in FONT_FILES.values() if path.is_file()])
    engine=Workflow(options)
    skip_detection=getattr(options,'skip_detection',False)
    startup=''
    try:
        images=load_image_list(options.image_dir)
        read_json(options.source_json)
        if not images: startup='The image folder is empty.'
    except (ValueError,OSError) as exc:
        images=[]; startup=str(exc)
    initial=dict(active=new_state(), drafts={})
    with gr.Blocks(title='Sino-Nôm Annotation Tool', fill_width=True, analytics_enabled=False) as app:
        session=gr.State(initial)
        with gr.Row(elem_id='header-row'):
            progress=gr.HTML(header(initial['active']), elem_id='app-chrome')
            save_all=gr.Button('Save all', variant='primary', scale=0, elem_id='save-all')
        download_payload=gr.Textbox(visible=False)
        with gr.Row(elem_id='workspace'):
            with gr.Column(elem_id='control-panel', min_width=0, elem_classes='panel'):
                heading=gr.HTML(panel_heading(initial['active']))
                with gr.Group(elem_classes='section'):
                    image_choice=gr.Dropdown(choices=[(p.name,str(p.resolve())) for p in images],label='Image')
                    with gr.Row(elem_classes='button-group'):
                        open_button=gr.Button('Open image', size='sm', min_width=0)
                        reset_button=gr.Button('Reset draft', size='sm', min_width=0)
                with gr.Group(visible=False, elem_classes='section') as content_actions:
                    gr.Markdown('### Content')
                    save_content=gr.Button('Save content',variant='primary')
                    with gr.Column(elem_classes='button-group'):
                        undo=gr.Button('Undo changes')
                        restore=gr.Button('Restore original content')
                with gr.Group(visible=False, elem_classes='section') as box_group:
                    with gr.Group(elem_classes='section'):
                        gr.Markdown('### Selected Region')
                        box_id=gr.Dropdown(label='Box ID')
                    with gr.Group(elem_classes='section'):
                        gr.Markdown('### Coordinates')
                        with gr.Row(elem_classes=['coordinate-row','field-group']):
                            x1=gr.Number(label='x1', min_width=0);y1=gr.Number(label='y1', min_width=0)
                        with gr.Row(elem_classes=['coordinate-row','field-group']):
                            x2=gr.Number(label='x2', min_width=0);y2=gr.Number(label='y2', min_width=0)
                        update=gr.Button('Update coordinates')
                    with gr.Group(elem_classes='section'):
                        gr.Markdown('### Box Actions')
                        with gr.Row(elem_classes='button-group'):
                            add=gr.Button('Add box', min_width=0);delete=gr.Button('Delete box', elem_id='delete-box', min_width=0)
                    with gr.Accordion('Detection', open=False, elem_classes='section'):
                        rerun_confirm=gr.Checkbox(label='Replace all existing boxes')
                        detect=gr.Button('Run detection', interactive=not skip_detection)
                with gr.Group(visible=False, elem_classes='section') as status_group:
                    gr.Markdown('### Region Status')
                    status_table=gr.Dataframe(headers=['Box ID','Status'],datatype=['str','str'],value=[],interactive=False, label='Regions',elem_id='status-table')
                    status_id=gr.Dropdown(label='Box ID')
                    status=gr.Radio(['intact','damaged'],value='intact',label='Status',elem_id='status-radio')
                    set_status=gr.Button('Update status', variant='primary')
                with gr.Group(visible=False, elem_classes='section') as order_group:
                    gr.Markdown('### Reading Order')
                    order_text=gr.Textbox(label='Box IDs', placeholder='[1, 3, 2]')
                    set_order=gr.Button('Apply order')
                with gr.Group(visible=False, elem_classes='section') as crop_group:
                    gr.Markdown('### Crop')
                    crop_coords=gr.Textbox(label='Coordinates [x1, y1, x2, y2]')
                    apply_crop=gr.Button('Apply crop')
                summary=gr.HTML(panel_summary(initial['active']))
                gr.HTML(FONT_PICKER, js_on_load=FONT_PICKER_SCRIPT, elem_id='font-control')
            with gr.Column(elem_id='main-workspace', min_width=0, scale=1, elem_classes='panel'):
                with gr.Column(elem_id='workspace-body'):
                    with gr.Group(visible=False, elem_id='content-editor',elem_classes='section') as content_group:
                        gr.Markdown('## Content Verification')
                        field=gr.Dropdown(label='Section')
                        field_value=gr.Textbox(label='Content',lines=8, elem_classes='han-nom-text')
                        with gr.Row(elem_classes='button-group'):
                            apply_field=gr.Button('Apply content', variant='primary')
                        with gr.Accordion('Content JSON', open=False, elem_classes='section'):
                            content_preview=gr.JSON(label='Content', elem_classes='han-nom-json')
                    board=gr.HTML(value=snapshot(initial['active']),html_template='${value.markup}',css_template=CSS,js_on_load=SCRIPT, elem_id='annotation-board')
                    preview=gr.JSON(label='Image JSON',visible=False, elem_id='final-preview', elem_classes='han-nom-json')
                message=gr.Markdown(startup,visible=bool(startup),elem_id='action-message')
                with gr.Row(elem_id='workflow-footer',elem_classes='button-group'):
                    back=gr.Button('← Back', interactive=False, scale=0)
                    footer_label=gr.HTML(footer(initial['active']))
                    save=gr.Button('Save image',visible=False,variant='primary', scale=0)
                    next_button=gr.Button('Next →',variant='primary',interactive=False, scale=0)
        # Preserve callback output slots while removing the normalized-text component.
        normalized=gr.State(None)
        outputs=[session,progress,message,content_group,field,field_value,content_preview,normalized,board,box_group,box_id,x1,y1,x2,y2,status_group,status_id,status,order_group,order_text,preview,crop_group,crop_coords,save,heading,summary,footer_label,content_actions,back,next_button,status_table]

        def render(ctx, msg=''):
            s=ctx['active']; step=s['current_step']; has=bool(s.get('image'))
            fields=content_fields(s['draft_content'],s['code']) if has else []
            choices=[(SECTION_LABELS[field['title']],json.dumps(field['path'],ensure_ascii=False)) for field in fields]
            chosen=choices[0][1] if choices else None
            val=fields[0]['value'] if fields else ''
            draft_preview=[dict(tieu_de=field['title'],van_ban=field['value']) for field in fields]
            ids=list(s['bounding_boxes']);selected=s['selected_box_id'] if s['selected_box_id'] in ids else (ids[0] if ids else None)
            box=s['bounding_boxes'].get(selected,dict(bbox=[0,0,1,1],status='intact'))
            final=final_document(s) if step==7 else None
            return [ctx,header(s),gr.update(value=msg,visible=bool(msg)),
                    gr.update(visible=step==2 and has),gr.update(choices=choices,value=chosen),val,draft_preview,None,gr.update(value=snapshot(s),visible=step!=2),
                    gr.update(visible=step==3 and has),gr.update(choices=ids,value=selected),*box['bbox'],
                    gr.update(visible=step==4),gr.update(choices=ids,value=selected),box['status'],
                    gr.update(visible=step==5),json.dumps(s['reading_order']),gr.update(value=final,visible=step==7),
                    gr.update(visible=step==6),json.dumps(s.get('crop')),gr.update(visible=step==7),
                    panel_heading(s),panel_summary(s),footer(s),gr.update(visible=step==2 and has),
                    gr.update(interactive=has and step>1),gr.update(interactive=has and step<7,visible=step<7),
                    status_rows(s)]

        def run(ctx, action, payload=None):
            try:
                updated=engine.apply(ctx['active'],action,payload)
                ctx=dict(ctx,active=updated)
                msg=''
                if action in ('save','save_content'):gr.Info('Saved.')
                if action=='next' and updated['current_step']==3 and not updated['detection_loaded'] and not skip_detection:
                    try:
                        ctx=dict(ctx,active=engine.apply(updated,'detect'))
                    except Exception as exc:
                        log.exception('Detection failed')
                        msg='Detection failed: '+str(exc)
                result = render(ctx,msg)
                # Preserve unaffected editors and avoid replacing unrelated component values.
                affected = {
                    'select': {0,2,8,10,11,12,13,14,16,17},
                    'status': {0,2,8,17,30},
                    'reorder': {0,2,8,19},
                    'crop': {0,2,8,22},
                    'field': {0,2,6,7},
                }.get(action)
                if affected is not None:
                    result = [value if i in affected | {1,25} else gr.skip() for i,value in enumerate(result)]
                return result
            except Exception as exc:
                log.exception('Action %s rejected',action)
                # Return a new revision even on errors, so the browser releases pending state.
                ctx=deepcopy(ctx);ctx['active']['revision']+=1
                return render(ctx,'⚠ '+str(exc))

        def open_image(ctx,path,reset=False):
            try:
                if path not in {str(p.resolve()) for p in images}:raise ValueError('Select an image from the list.')
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
        def save_folder():
            try:
                annotations=collect_annotations(images,options.output_dir,allow_empty=True)
                content=collect_content_documents(images,options.output_dir,allow_empty=True)
                files={}
                if annotations:files['annotations.json']=annotations
                if content:files['content.json']=content
                if not files:raise ValueError('No image or content records have been saved yet.')
                return json.dumps(files,ensure_ascii=False)
            except (ValueError,OSError,KeyError,TypeError) as exc:
                raise gr.Error(str(exc)) from exc
        save_all.click(save_folder,[],[download_payload],concurrency_id='annotation-actions',concurrency_limit=1).success(
            fn=None,inputs=[download_payload],outputs=None,js="""(payload) => {
                if (!payload) return;
                const files=JSON.parse(payload);
                for (const [name,data] of Object.entries(files)) {
                    const text=JSON.stringify(data,null,2);
                    const url=URL.createObjectURL(new Blob([text],{type:'application/json;charset=utf-8'}));
                    const link=document.createElement('a');link.href=url;link.download=name;
                    document.body.appendChild(link);link.click();link.remove();
                    setTimeout(()=>URL.revokeObjectURL(url),10000);
                }
            }""")
        open_button.click(open_image,[session,image_choice],**event_args)
        reset_button.click(lambda c,p:open_image(c,p,True),[session,image_choice],**event_args)
        for button,action in [(back,'back'),(next_button,'next'),(save,'save'),(save_content,'save_content'),(undo,'undo'),(restore,'original')]:
            button.click(lambda c,a=action:run(c,a),[session],**event_args)
        def choose_field(ctx,path):
            if not path:return ''
            s=ctx['active']
            try:
                selected=tuple(json.loads(path))
                for entry in content_fields(s['draft_content'],s['code']):
                    if entry['path']==selected:return entry['value']
            except (ValueError,TypeError):
                pass
            raise gr.Error('This section does not belong to the selected image.')
        field.input(choose_field,[session,field],[field_value],concurrency_id='annotation-actions')
        def apply_content_field(ctx,path,value):
            try:
                parsed=json.loads(path)
            except (ValueError,TypeError):
                return render(ctx,'Select a content section.')
            return run(ctx,'field',dict(path=parsed,value=value))
        apply_field.click(apply_content_field,[session,field,field_value],**event_args)
        for button,action in [(add,'add'),(update,'update')]:
            button.click(lambda c,i,a,b,d,e,op=action:run(c,op,dict(id=i,bbox=[a,b,d,e])),[session,box_id,x1,y1,x2,y2],**event_args)
        delete.click(lambda c,i:run(c,'delete',dict(id=i)),[session,box_id],**event_args)
        detect.click(lambda c,ok:run(c,'detect') if ok or not c['active']['detection_loaded'] else render(c,'Confirm replacement of existing boxes.'),[session,rerun_confirm],**event_args)
        for selector in (box_id,status_id):
            selector.input(lambda c,i:run(c,'select',dict(id=i)),[session,selector],**event_args)
        set_status.click(lambda c,i,v:run(c,'status',dict(id=i,status=v)),[session,status_id,status],**event_args)
        def parse_action(c,a,key,value):
            try:return run(c,a,{key:json.loads(value)})
            except ValueError as exc:return render(c,'Invalid JSON: '+str(exc))
        set_order.click(lambda c,v:parse_action(c,'reorder','order',v),[session,order_text],**event_args)
        apply_crop.click(lambda c,v:parse_action(c,'crop','bbox',v),[session,crop_coords],**event_args)
        def select_status_row(ctx,evt:gr.SelectData):
            key=str(evt.row_value[0])
            return run(ctx,'select',dict(id=key))
        status_table.select(select_status_row,[session],**event_args)
        def on_action(ctx,evt:gr.EventData):
            return run(ctx,evt._data['action'],evt._data['payload'])
        board.action(on_action,[session],**event_args)
    return app


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    args=parser().parse_args()
    create_app(args).queue().launch(server_name=args.server_name,server_port=args.port,share=args.share,css=APP_CSS,
        theme=gr.themes.Base(font=['Arial', 'sans-serif'], font_mono=['monospace']), footer_links=[])
