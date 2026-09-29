"""Run from any directory: python gradio/app.py --image-dir ... --source-json ..."""
import argparse
import base64
import html
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# This directory deliberately is NOT a Python package named gradio.
import gradio as gr
from annotation.state import new_state, source_mismatch_confirmed
from annotation.reading_order import suspicious_box_ids
from annotation.workflow import Workflow
from annotation.io import (final_document, final_source_mismatch_document,
                           load_image_list, read_json)
from annotation.text_extraction import content_fields, normalize_content_titles
from annotation.text_alignment import count_annotation_characters
from annotation.export import (collect_annotations, collect_content_documents,
                               collect_source_mismatches, collect_suspicious_details,
                               save_export_archive)
from ui.editor import snapshot, source_text, SCRIPT, CSS
from ui.presentation import (APP_CSS, app_identity, workflow_progress,
                             panel_heading, panel_summary, footer,
                             status_rows, SECTION_LABELS)
from ui.fonts import FONT_FILES
from ui.icons import WARNING

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]


def loading_markup(label='Loading…', visible=False):
    """The single, application-wide progress surface used for queued actions."""
    state = ' is-visible' if visible else ''
    return (
        f'<div id="global-loading" class="global-loading{state}" '
        'role="status" aria-live="polite" aria-busy="true">'
        '<div class="global-loading-card">'
        '<span class="global-loading-spinner" aria-hidden="true"></span>'
        f'<span>{html.escape(label)}</span>'
        '</div></div>'
    )


LOADING_HIDDEN = loading_markup()
SHOW_LOADING_JS = """(...args) => {
    document.getElementById('global-loading')?.classList.add('is-visible');
    return args;
}"""


def snapshot_board_state_js(selection_index):
    """Submit the live board state instead of a potentially stale bridge."""
    return f"""(...args) => {{
        document.getElementById('global-loading')?.classList.add('is-visible');
        // The editor owns the canvas; there is no #annotation-board wrapper.
        // Read the live SVG so drag/resize changes are committed before the
        // Gradio event sends the selection bridge to Python.
        const board = document.querySelector('.annotation-canvas')?.closest('.workbench-board')
            || document.querySelector('.annotation-canvas')?.parentElement;
        const cards = board?.querySelector('.order-chips');
        let snapshot = {{}};
        try {{ snapshot = JSON.parse(args[{selection_index}] || '{{}}'); }} catch (_) {{}}
        if (cards) {{
            snapshot.textSequence = [...cards.querySelectorAll('[data-order-chip]')]
                .map(card => card.dataset.character);
            snapshot.tokenOrder = [...cards.querySelectorAll('[data-order-chip]')]
                .map(card => card.dataset.tokenId);
            snapshot.suspiciousTokenIds = [...cards.querySelectorAll('[data-order-chip].suspicious')]
                .map(card => card.dataset.tokenId);
        }}
        const groups = [...(board?.querySelectorAll('.annotation-canvas [data-box-id]') || [])];
        const boxes = {{}};
        const statuses = {{}};
        for (const group of groups) {{
            const id = group.dataset.boxId;
            const rect = group.querySelector('rect:not([data-image-resize-handle])');
            if (!rect) continue;
            const x = Number(rect.getAttribute('x')), y = Number(rect.getAttribute('y'));
            const bbox = [x, y, x + Number(rect.getAttribute('width')),
                          y + Number(rect.getAttribute('height'))];
            if (id === 'crop') snapshot.crop = bbox; else {{
                boxes[id] = bbox;
                if (group.dataset.status === 'intact' || group.dataset.status === 'damaged')
                    statuses[id] = group.dataset.status;
            }}
        }}
        if (Object.keys(boxes).length) snapshot.boxes = boxes;
        if (Object.keys(statuses).length) snapshot.statuses = statuses;
        args[{selection_index}] = JSON.stringify(snapshot);
        return args;
    }}"""


HIDE_LOADING_JS = """() => {
    document.getElementById('global-loading')?.classList.remove('is-visible');
}"""


def _config_relative(config_path, value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Config field {field} must be a non-empty path string.')
    path = Path(value).expanduser()
    return str(path.resolve() if path.is_absolute() else (config_path.parent / path).resolve())


def resolve_app_paths(options):
    """Fill omitted CLI paths from config while preserving CLI precedence."""
    paths_complete = all(
        getattr(options, name, None) for name in ('image_dir', 'source_json', 'output_dir'))
    config_path = Path(options.config).expanduser().resolve()
    try:
        config = read_json(config_path)
    except OSError as exc:
        raise ValueError(f'Cannot read app config {config_path}: {exc}') from exc
    if not isinstance(config, dict):
        raise ValueError('App config must be a JSON object.')
    paths = config.get('paths', {})
    gradio_paths = config.get('gradio', {})
    if (not paths_complete and
            (not isinstance(paths, dict) or not isinstance(gradio_paths, dict))):
        raise ValueError("Config must contain 'paths' and 'gradio' objects.")
    records_config = config.get('records', {})
    if not isinstance(records_config, dict):
        raise ValueError("Config field 'records' must be an object.")
    content_config = records_config.get('content', {})
    if not isinstance(content_config, dict):
        raise ValueError("Config field 'records.content' must be an object.")
    options.content_titles = normalize_content_titles(
        content_config.get('section_headings'))
    metadata_config = records_config.get('metadata', [])
    if not isinstance(metadata_config, list):
        raise ValueError("Config field 'records.metadata' must be an array.")
    show_metadata_fields = gradio_paths.get('show_metadata_fields', True)
    if not isinstance(show_metadata_fields, bool):
        raise ValueError("Config field 'gradio.show_metadata_fields' must be boolean.")
    options.metadata_fields = tuple(
        (item.get('label'), item.get('field'))
        for item in metadata_config
        if (show_metadata_fields and isinstance(item, dict)
            and item.get('type') == 'string')
    )
    options.annotation_title = content_config.get('start_heading')
    if (not isinstance(options.annotation_title, str) or
            not options.annotation_title.strip()):
        raise ValueError('Config field records.content.start_heading must be a non-empty string.')
    if options.annotation_title not in options.content_titles:
        raise ValueError('Config start_heading must also appear in section_headings.')
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
    p.add_argument('--port', type=int, default=None,
                   help='Server port. When omitted, Gradio selects the first available port.')
    p.add_argument('--server-name', default='127.0.0.1')
    p.add_argument('--share', action='store_true', help='Create a public Gradio link.')
    return p


def create_app(options):
    options=resolve_app_paths(options)
    # Expose only the requested font assets, regardless of the working directory.
    gr.set_static_paths(paths=[path for path in FONT_FILES.values() if path.is_file()])
    engine=Workflow(options)
    gr.set_static_paths(paths=[engine.preview_dir])
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
        with gr.Column(elem_id='header-stack', scale=0):
            with gr.Row(elem_id='topbar', scale=0):
                progress=gr.HTML(app_identity(initial['active']), elem_id='app-chrome')
                save_all=gr.Button('Download All', variant='primary', scale=0, elem_id='save-all')
            workflow_chrome=gr.HTML(workflow_progress(initial['active']),
                                    elem_id='workflow-chrome')
        message=gr.Markdown(startup,visible=bool(startup),elem_id='action-message')
        download_payload=gr.Textbox(visible=False)
        # This remains mounted across every callback, so only one loading modal is shown.
        loading_modal=gr.HTML(value=LOADING_HIDDEN, elem_id='global-loading-host')
        with gr.Row(elem_id='workspace', scale=1):
            with gr.Column(elem_id='image-start', min_width=0, elem_classes='panel') as image_start:
                gr.Markdown('## Select an image')
                gr.Markdown('Choose an inscription image to begin or reopen saved annotation data.')
                image_choice=gr.Dropdown(choices=[(p.name,str(p.resolve())) for p in images],label='Image')
                open_button=gr.Button('Start Verification', variant='primary')
            with gr.Column(visible=False, elem_id='control-panel', min_width=0,
                           elem_classes='panel') as control_panel:
                heading=gr.HTML(panel_heading(initial['active']))
                with gr.Group(elem_classes=['section','sidebar-section','sidebar-component','current-image-section']):
                    gr.Markdown('### Current image')
                    current_image=gr.Markdown('—', elem_id='current-image-name')
                    reset_confirm=gr.Checkbox(value=False, visible=False)
                    reset_button=gr.Button('Reset All', size='sm', min_width=0,
                                           elem_id='reset-all')
                with gr.Group(visible=False,
                              elem_classes=['section','sidebar-section','sidebar-component','content-tools']) as content_actions:
                    gr.Markdown('### Content actions')
                    with gr.Column(elem_classes=['button-group','sidebar-action-stack']):
                        save_content=gr.Button('Save Content',variant='primary',min_width=0)
                        undo=gr.Button('Undo changes',min_width=0)
                with gr.Group(visible=False, elem_classes=['section','sidebar-step-stack']) as box_group:
                    box_id=gr.Dropdown(visible=False)
                    selection_bridge=gr.Textbox(value='{}',show_label=False,
                                                elem_id='selection-bridge',
                                                elem_classes='frontend-bridge')
                    with gr.Group(visible=False, elem_classes=['section','sidebar-section','sidebar-component','selection-section']) as bbox_selection_group:
                        gr.Markdown('### Selected region')
                        with gr.Row(elem_classes=['coordinate-row','field-group']):
                            x1=gr.Number(label='x1', min_width=0,elem_id='bbox-x1');y1=gr.Number(label='y1', min_width=0,elem_id='bbox-y1')
                        with gr.Row(elem_classes=['coordinate-row','field-group']):
                            x2=gr.Number(label='x2', min_width=0,elem_id='bbox-x2');y2=gr.Number(label='y2', min_width=0,elem_id='bbox-y2')
                        update=gr.Button('Update coordinates',variant='primary')
                    gr.HTML('''<section class="selection-guide" aria-label="Selection Guide">
                        <h3>Selection Guide</h3>
                        <ul>
                          <li><kbd>Click</kbd><span>Select a single box.</span></li>
                          <li><kbd>Drag</kbd><span>Draw a selection area to select multiple boxes.</span></li>
                          <li><kbd>Ctrl/Cmd + Click</kbd><span>Add or remove individual boxes from the current selection.</span></li>
                          <li><kbd>Alt/Option + Drag</kbd><span>Create a new bounding box.</span></li>
                        </ul>
                    </section>''', elem_id='selection-guide-host')
                    delete=gr.Button('Delete Selected', size='sm', min_width=0,
                                     elem_id='delete-box')
                    detect_confirm=gr.Checkbox(value=False,visible=False)
                    with gr.Row(elem_classes=['button-group','sidebar-action-row','bbox-action-row']):
                        sort_boxes=gr.Button('Sort Boxes', variant='primary', size='sm',
                                             min_width=0, elem_id='sort-boxes')
                        detect=gr.Button('Run Detection', variant='primary', size='sm',
                                         interactive=not skip_detection,elem_id='run-detection',
                                         min_width=0)
                    with gr.Group(visible=False,
                                  elem_classes=['section','sidebar-section','sidebar-component','mismatch-panel']) as mismatch_group:
                        gr.Markdown('### Box-Content Mismatch')
                        summary=gr.HTML(panel_summary(initial['active']),
                                        elem_id='validation-summary-host')
                        mismatch_type=gr.Dropdown([
                            ('Missing Content','missing_text'),
                            ('Extra Content','extra_text'),
                            ('Other','other'),
                        ],label='Issue type',filterable=False)
                        mismatch_note=gr.Textbox(
                            label='Note (required only for Other)',lines=2,max_lines=3)
                        with gr.Row(elem_classes=['button-group','sidebar-action-row','mismatch-action-row']):
                            confirm_mismatch=gr.Button(
                                'Confirm Mismatch', variant='primary', min_width=0,
                                elem_id='confirm-source-mismatch')
                            clear_mismatch=gr.Button(
                                'Clear', visible=False, variant='secondary', min_width=0,
                                elem_id='clear-source-mismatch')
                with gr.Group(visible=False,
                              elem_classes=['section','sidebar-section','sidebar-component','selection-section']) as status_group:
                    gr.Markdown('### Selected region')
                    status_id=gr.Dropdown(visible=False)
                    status=gr.Radio(['intact','damaged'],value='intact',label='Selected box status',elem_id='status-radio')
                with gr.Group(visible=False,
                              elem_classes=['section','sidebar-section','sidebar-component','box-color-control']) as box_color_group:
                    gr.Markdown('### Box color')
                    box_color=gr.Dropdown(
                        ['White','Cyan','Amber','Violet','Pink'],
                        value='White',show_label=False,interactive=True,
                        filterable=False,container=False,
                        elem_id='bbox-color-palette')
                # Preserve the status-table callback slot without rendering the
                # redundant region table.
                status_table=gr.State([])
                with gr.Group(visible=False,
                              elem_classes=['section','sidebar-section','sidebar-component']) as order_group:
                    gr.Markdown('### Reading order')
                    gr.Markdown('Drag the text cards into sequence. Apply assigns them to boxes in detector-sorted spatial order.',
                                elem_classes='sidebar-help')
                    apply_order=gr.Button('Apply Changes',variant='primary',
                                          elem_id='apply-reading-order')
                    with gr.Row(elem_classes='suspicious-control'):
                        suspicious_toggle=gr.Checkbox(
                            value=False,label='Suspicious annotation',show_label=False,
                            interactive=False,container=False,elem_id='suspicious-toggle')
                source_text_group=gr.HTML(
                    value='', visible=False, elem_id='sidebar-source-text',
                    elem_classes=['section','sidebar-section','sidebar-component'])
                order_text=gr.State('[]')
                with gr.Group(visible=False, elem_classes=['section','sidebar-section','sidebar-component']) as crop_group:
                    gr.Markdown('### Crop')
                    gr.Markdown('Adjust the orange crop frame. Oversized crops are scaled automatically on export.',
                                elem_classes='sidebar-help')
                    crop_coords=gr.Textbox(label='Coordinates [x1, y1, x2, y2]',
                                           elem_id='crop-coordinates')
                    apply_crop=gr.Button('Apply crop',variant='primary')
            with gr.Column(visible=False, elem_id='main-workspace', min_width=0, scale=1,
                           elem_classes='panel') as main_workspace:
                with gr.Column(elem_id='workspace-body'):
                    with gr.Group(visible=False, elem_id='content-editor',elem_classes='section') as content_group:
                        gr.Markdown('## Content Verification')
                        # These are fixed record sections, so an editable/searchable
                        # combobox only delays committing a click selection.
                        field=gr.Dropdown(label='Section', filterable=False)
                        field_value=gr.Textbox(label='Content',lines=8, elem_classes='han-nom-text')
                        content_bridge=gr.Textbox(
                            value='{}',visible=False,elem_id='content-draft-bridge')
                        with gr.Row(elem_classes='button-group'):
                            apply_field=gr.Button('Save change', variant='primary')
                        with gr.Accordion('Content JSON', open=False, elem_classes='section'):
                            content_preview=gr.Code(
                                label='Content', language='json', interactive=False,
                                lines=12, max_lines=30, elem_classes='han-nom-json',
                            )
                    board=gr.HTML(value=snapshot(initial['active']),html_template='${value.markup}',css_template=CSS,js_on_load=SCRIPT, elem_id='annotation-board')
                    preview=gr.JSON(label='Image JSON',visible=False, elem_id='final-preview', elem_classes='han-nom-json')
        with gr.Row(visible=False, elem_id='workflow-footer',elem_classes='button-group') as workflow_footer:
            back=gr.Button('Back', interactive=False, scale=0, elem_id='back-button')
            footer_label=gr.HTML(footer(initial['active']), elem_id='footer-step')
            save=gr.Button('Save Annotation',visible=False,variant='primary', scale=0, elem_id='save-image')
            next_button=gr.Button('Next',variant='primary',interactive=False, scale=0, elem_id='next-button')
        # Preserve callback output slots while removing the normalized-text component.
        normalized=gr.State(None)
        outputs=[session,progress,message,content_group,field,field_value,content_preview,normalized,board,box_group,box_id,x1,y1,x2,y2,status_group,status_id,status,order_group,order_text,preview,crop_group,crop_coords,save,heading,summary,footer_label,content_actions,back,next_button,status_table,
                 mismatch_group,mismatch_type,mismatch_note,confirm_mismatch,clear_mismatch]
        outputs.append(box_color_group)
        outputs.append(workflow_chrome)
        outputs.append(loading_modal)
        outputs.extend([image_start,control_panel,main_workspace,workflow_footer,current_image])
        outputs.append(content_bridge)
        outputs.append(suspicious_toggle)
        outputs.append(source_text_group)

        def render(ctx, msg=''):
            s=ctx['active']; step=s['current_step']; has=bool(s.get('image'))
            fields=(content_fields(
                s['draft_content'],s['code'],engine.content_titles,engine.metadata_fields)
                if has else [])
            choices=[(SECTION_LABELS.get(field['title'],field['title']),json.dumps(field['path'],ensure_ascii=False)) for field in fields]
            chosen=choices[0][1] if choices else None
            val=fields[0]['value'] if fields else ''
            draft_preview=json.dumps(
                [dict(tieu_de=field['title'],van_ban=field['value']) for field in fields],
                ensure_ascii=False, indent=2,
            )
            browser_draft=json.dumps({
                json.dumps(field['path'],ensure_ascii=False): {
                    'title':field['title'],'path':field['path'],'value':field['value']}
                for field in fields
            },ensure_ascii=False)
            region_ids=list(s['regions'])
            selected_region=(s['selected_region_uid'] if s['selected_region_uid'] in region_ids
                             else (region_ids[0] if region_ids else None))
            region_box=s['regions'].get(selected_region,dict(bbox=[0,0,1,1],status='intact'))
            box_ids=list(s['bounding_boxes'])
            selected_box=(s['selected_box_id'] if s['selected_box_id'] in box_ids
                          else (box_ids[0] if box_ids else None))
            status_box=s['bounding_boxes'].get(selected_box,dict(status='intact'))
            status_choices=['intact','damaged']
            suspicious_ids=set(suspicious_box_ids(s))
            mismatch=source_mismatch_confirmed(s)
            final=(final_source_mismatch_document(s) if mismatch else final_document(s)) if step==7 else None
            issue=s.get('source_mismatch') or {}
            counts_differ=bool(has and len(s['regions']) != count_annotation_characters(s['annotation_text']))
            return [ctx,app_identity(s),gr.update(value=msg,visible=bool(msg)),
                    gr.update(visible=step==2 and has),gr.update(choices=choices,value=chosen),val,draft_preview,None,gr.update(value=snapshot(s),visible=step!=2),
                    gr.update(visible=step==3 and has),gr.update(choices=region_ids,value=selected_region),*region_box['bbox'],
                    gr.update(visible=step==4),gr.update(choices=box_ids,value=selected_box),
                    gr.update(choices=status_choices,value=('intact' if status_box['status']=='unknown' else status_box['status']),interactive=True),
                    gr.update(visible=step==4),json.dumps(s['reading_order']),gr.update(value=final,visible=step==7),
                    gr.update(visible=step==6),json.dumps(s.get('crop')),gr.update(visible=step==7),
                    panel_heading(s),panel_summary(s),footer(s),gr.update(visible=step==2 and has),
                    gr.update(interactive=has and step>1),gr.update(interactive=has and step<7,visible=step<7),
                    status_rows(s),gr.update(visible=step==3 and has),
                    gr.update(value=issue.get('issue_type')),
                    gr.update(value=issue.get('note','')),
                    gr.update(interactive=has and step==3),gr.update(visible=mismatch),
                    gr.update(visible=has and step==3),
                    workflow_progress(s),LOADING_HIDDEN,
                    gr.update(visible=step==1),gr.update(visible=has and step>1),
                    gr.update(visible=has and step>1),gr.update(visible=has and step>1),
                    (f'`{s["image"]}`' if has else '—'),
                    browser_draft,
                    gr.update(value=selected_box in suspicious_ids,
                              interactive=step==4 and selected_box is not None),
                    gr.update(value=source_text(s), visible=step==4 and has)]

        def run(ctx, action, payload=None, auto_detect=True):
            try:
                updated=engine.apply(ctx['active'],action,payload)
                ctx=dict(ctx,active=updated)
                msg=''
                if action in ('save','save_content'):gr.Info('Saved.')
                if action == 'save':
                    saved_path=updated.get('image_path')
                    if saved_path:
                        ctx['drafts'].pop(saved_path,None)
                    fresh=new_state()
                    fresh['revision']=updated['revision']+1
                    ctx=dict(ctx,active=fresh)
                if auto_detect and action=='next' and updated['current_step']==3 and not updated['detection_loaded'] and not skip_detection:
                    try:
                        ctx=dict(ctx,active=engine.apply(updated,'detect'))
                    except Exception as exc:
                        log.exception('Detection failed')
                        msg='Detection failed: '+str(exc)
                result = render(ctx,msg)
                # Preserve unaffected editors and avoid replacing unrelated component values.
                suspicious_outputs={len(outputs)-2}
                affected = {
                    'select': {0,2,8,10,11,12,13,14,16,17} | suspicious_outputs,
                    'suspicious': {0,2,8} | suspicious_outputs,
                    'status': {0,2,8,17,30},
                    'statuses': {0,2,8,17,30},
                    'reorder_text': {0,2,8,19} | suspicious_outputs,
                    'crop': {0,2,8,22},
                    'field': {0,2,6,7},
                }.get(action)
                if affected is not None:
                    always={1,25,37,38}
                    result = [value if i in affected | always else gr.skip() for i,value in enumerate(result)]
                return result
            except Exception as exc:
                log.exception('Action %s rejected',action)
                # Return a new revision even on errors, so the browser releases pending state.
                ctx=deepcopy(ctx);ctx['active']['revision']+=1
                return render(ctx,WARNING+' '+html.escape(str(exc)))

        def open_image(ctx,path):
            try:
                if path not in {str(p.resolve()) for p in images}:raise ValueError('Select an image from the list.')
                ctx=deepcopy(ctx)
                old=ctx['active']
                if old.get('image_path'):ctx['drafts'][old['image_path']]=old
                # Starting from the Image screen always reflects durable data.
                # Drafts are only for Back/Next within the currently open image.
                state=engine.open_image(path)
                state['revision']=old['revision']+1
                ctx['active']=state
                return render(ctx)
            except Exception as exc:
                log.exception('Cannot open image')
                return render(ctx,WARNING+' '+html.escape(str(exc)))

        # Hide Gradio's per-component timers/spinners and show one centered modal instead.
        event_args=dict(outputs=outputs,concurrency_id='annotation-actions',concurrency_limit=1,
                        show_progress='hidden',js=SHOW_LOADING_JS)
        box_color.change(
            fn=None, inputs=[box_color], outputs=None, show_progress='hidden',
            js="""(color) => {
                document.querySelector('#annotation-board')?.dispatchEvent(
                    new CustomEvent('bbox-color-change', {detail: color, bubbles: true})
                );
            }""")
        def clear_loading_when_done(event):
            # The returned loading HTML is normally identical to its initial value,
            # so Gradio may skip patching the DOM after a completed action. Clear
            # the class explicitly on both completion paths instead.
            event.success(fn=None,inputs=None,outputs=None,js=HIDE_LOADING_JS)
            event.failure(fn=None,inputs=None,outputs=None,js=HIDE_LOADING_JS)
            return event

        def save_folder():
            try:
                annotations=collect_annotations(images,options.output_dir,allow_empty=True)
                content=collect_content_documents(
                    images,options.output_dir,allow_empty=True,
                    titles=engine.verification_titles)
                mismatches=collect_source_mismatches(images,options.output_dir,allow_empty=True)
                suspicious=collect_suspicious_details(images,options.output_dir)
                archive=save_export_archive(
                    annotations,content,options.output_dir,mismatches,suspicious)
                return json.dumps({'name':archive.name,
                                   'content':base64.b64encode(archive.read_bytes()).decode('ascii')})
            except (ValueError,OSError,KeyError,TypeError) as exc:
                raise gr.Error(str(exc)) from exc
        save_all.click(save_folder,[],[download_payload],concurrency_id='annotation-actions',concurrency_limit=1,
                       show_progress='hidden',js=SHOW_LOADING_JS).success(
            fn=None,inputs=[download_payload],outputs=None,js="""(payload) => {
                document.getElementById('global-loading')?.classList.remove('is-visible');
                if (!payload) return;
                const archive=JSON.parse(payload);
                const binary=atob(archive.content);
                const bytes=new Uint8Array(binary.length);
                for (let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
                const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
                const link=document.createElement('a');link.href=url;link.download=archive.name;
                document.body.appendChild(link);link.click();link.remove();
                setTimeout(()=>URL.revokeObjectURL(url),10000);
            }""")
        clear_loading_when_done(open_button.click(open_image,[session,image_choice],**event_args))
        def reset_image(ctx,confirmed):
            if not confirmed:
                return render(ctx)
            try:
                ctx=deepcopy(ctx)
                path=ctx['active'].get('image_path')
                if not path:
                    raise ValueError('No image is currently open.')
                restored=engine.reset_image(path)
                restored['revision']=ctx['active']['revision']+1
                ctx['drafts'].pop(path,None)
                ctx['active']=restored
                gr.Info('All changes for this image were reset.')
                return render(ctx)
            except Exception as exc:
                log.exception('Cannot reset image')
                return render(ctx,WARNING+' '+html.escape(str(exc)))
        clear_loading_when_done(reset_button.click(
            reset_image,[session,reset_confirm],
            **dict(event_args,js="""(ctx, confirmed) => [ctx, window.confirm(
                'Reset all changes for this image to the state from server startup?\\n\\nShared record metadata may also affect related image faces.'
            )]""")))
        for button,action in [(back,'back'),(save,'save'),(undo,'undo')]:
            clear_loading_when_done(button.click(lambda c,a=action:run(c,a),[session],**event_args))
        def commit_frontend_content(ctx,draft):
            try:
                parsed=json.loads(draft or '{}')
                s=ctx['active']
                fields=content_fields(
                    s['draft_content'],s['code'],engine.content_titles,
                    engine.metadata_fields)
                expected={json.dumps(field['path'],ensure_ascii=False):field
                          for field in fields}
                if not isinstance(parsed,dict) or set(parsed) != set(expected):
                    raise ValueError('The local content draft is incomplete or invalid.')
                updated=s
                for key,field in expected.items():
                    entry=parsed[key]
                    if (not isinstance(entry,dict)
                            or entry.get('title') != field['title']
                            or entry.get('path') != list(field['path'])
                            or not isinstance(entry.get('value'),str)):
                        raise ValueError('The local content draft is invalid.')
                    if entry['value'] != field['value']:
                        updated=engine.apply(updated,'field',{
                            'path':entry['path'],'value':entry['value']})
                return dict(ctx,active=updated)
            except (ValueError,TypeError,AttributeError) as exc:
                raise ValueError(str(exc)) from exc

        def save_content_draft(ctx,draft):
            try:
                return run(commit_frontend_content(ctx,draft),'save_content')
            except Exception as exc:
                return render(ctx,WARNING+' '+html.escape(str(exc)))
        clear_loading_when_done(save_content.click(
            save_content_draft,[session,content_bridge],**event_args))

        def next_step(ctx, content_draft=None, auto_detect=True,
                      issue_type=None, mismatch_note_value='', selection='{}',
                      status_value='intact', x1_value=None, y1_value=None,
                      x2_value=None, y2_value=None, crop_coordinates=None):
            if ctx['active']['current_step'] == 2:
                try:
                    ctx=commit_frontend_content(ctx,content_draft)
                except Exception as exc:
                    result = render(ctx, WARNING+' '+html.escape(str(exc)))
                    result[4] = gr.skip()
                    result[5] = gr.skip()
                    return result
            if ctx['active']['current_step'] == 3:
                try:
                    ctx,_,_=commit_frontend_boxes(
                        ctx, selection, (x1_value, y1_value, x2_value, y2_value))
                except Exception as exc:
                    return render(ctx, WARNING+' '+html.escape(str(exc)))
            if (ctx['active']['current_step'] == 3
                    and not ctx['active']['workflow']['bbox_valid']
                    and not source_mismatch_confirmed(ctx['active'])
                    and issue_type):
                try:
                    updated = engine.apply(ctx['active'], 'confirm_source_mismatch', {
                        'issue_type': issue_type,
                        'note': mismatch_note_value or '',
                    })
                    ctx = dict(ctx, active=updated)
                except Exception as exc:
                    return render(ctx, WARNING+' '+html.escape(str(exc)))
            if ctx['active']['current_step'] == 4:
                try:
                    ctx = commit_statuses(ctx, selection, status_value)
                    text_sequence,token_order,suspicious_token_ids = frontend_text_sequence(selection)
                    if text_sequence is not None and (text_sequence or ctx['active']['annotations']):
                        updated = engine.apply(ctx['active'], 'reorder_text', {
                            'sequence': text_sequence,
                            'token_order': token_order,
                            'suspicious_token_ids': suspicious_token_ids,
                        })
                        ctx = dict(ctx, active=updated)
                    elif suspicious_token_ids is not None:
                        updated = engine.apply(ctx['active'], 'reorder_text', {
                            'sequence': list(ctx['active'].get('text_sequence', [])),
                            'token_order': list(map(str, ctx['active'].get('text_token_ids', []))),
                            'suspicious_token_ids': suspicious_token_ids,
                        })
                        ctx = dict(ctx, active=updated)
                    ctx = commit_statuses(ctx, selection, status_value)
                except Exception as exc:
                    return render(ctx, WARNING+' '+html.escape(str(exc)))
            if ctx['active']['current_step'] == 6:
                try:
                    crop_value = (sidebar_crop(crop_coordinates)
                                  if crop_coordinates not in (None,'')
                                  else frontend_crop(selection))
                    if crop_value is not None:
                        updated = engine.apply(ctx['active'], 'crop', {
                            'bbox': crop_value,
                        })
                        ctx = dict(ctx, active=updated)
                except Exception as exc:
                    return render(ctx, WARNING+' '+html.escape(str(exc)))
            result = run(ctx, 'next', auto_detect=auto_detect)
            if result[0]['active']['current_step'] == 2:
                # Keep the current section and unsaved input visible on failure.
                result[4] = gr.skip()
                result[5] = gr.skip()
            return result
        def next_with_progress(ctx, content_draft=None, issue_type=None,
                               mismatch_note_value='', selection='{}',
                               status_value='intact', x1_value=None, y1_value=None,
                               x2_value=None, y2_value=None, crop_coordinates=None):
            result = next_step(
                ctx, content_draft, auto_detect=False, issue_type=issue_type,
                mismatch_note_value=mismatch_note_value, selection=selection,
                status_value=status_value, x1_value=x1_value,
                y1_value=y1_value, x2_value=x2_value, y2_value=y2_value,
                crop_coordinates=crop_coordinates)
            state = result[0]['active']
            needs_detection = (state['current_step'] == 3 and
                               not state['detection_loaded'] and not skip_detection)
            if needs_detection:
                result[2] = gr.update(value='Running detection…', visible=True)
                result[29] = gr.update(interactive=False)
                result[28] = gr.update(interactive=False)
                result[38] = loading_markup('Running detection…', visible=True)
            yield result
            if needs_detection:
                yield run(result[0], 'detect')
        clear_loading_when_done(next_button.click(
            next_with_progress,
            [session,content_bridge,mismatch_type,mismatch_note,
             selection_bridge,status,x1,y1,x2,y2,crop_coords],
            **dict(event_args,js=snapshot_board_state_js(4))))
        field.change(
            fn=None,inputs=[field,content_bridge],outputs=[field_value],queue=False,
            js="""(path, draft) => {
                try { return JSON.parse(draft || '{}')?.[path]?.value ?? ''; }
                catch (_) { return ''; }
            }""",show_progress='hidden')
        apply_field.click(
            fn=None,inputs=[field,field_value,content_bridge],
            outputs=[content_bridge,content_preview],queue=False,
            js="""(path, value, draft) => {
                let fields={};
                try { fields=JSON.parse(draft || '{}'); } catch (_) {}
                if (fields[path]) fields[path].value=String(value ?? '');
                const preview=Object.values(fields).map(
                    field => ({tieu_de:field.title, van_ban:field.value}));
                return [JSON.stringify(fields), JSON.stringify(preview,null,2)];
            }""",show_progress='hidden')
        def frontend_selection(value):
            try:
                parsed=json.loads(value or '{}')
                active=parsed.get('active')
                selected=parsed.get('selected',[])
                if not isinstance(selected,list):raise ValueError
                return active,selected
            except (ValueError,TypeError,AttributeError):
                raise gr.Error('The local box selection is invalid.')
        def frontend_boxes(value):
            try:
                parsed=json.loads(value or '{}')
                boxes=parsed.get('boxes',{})
                if (not isinstance(boxes,dict)
                        or any(not isinstance(uid,str) or not isinstance(bbox,list)
                               or len(bbox) != 4 for uid,bbox in boxes.items())):
                    raise ValueError
                return boxes
            except (ValueError,TypeError,AttributeError):
                raise gr.Error('The local bounding boxes are invalid.')
        def commit_frontend_boxes(ctx,selection,coordinates=(None,None,None,None)):
            """Commit live canvas geometry plus the active sidebar coordinates."""
            boxes=frontend_boxes(selection)
            active,selected=frontend_selection(selection)
            if not boxes:
                boxes={
                    uid:list(region['bbox'])
                    for uid,region in ctx['active']['regions'].items()
                }
            active=(active or ctx['active'].get('selected_region_uid')
                    or next(iter(ctx['active']['regions']),None))
            if any(coordinate is not None for coordinate in coordinates):
                # Gradio keeps the coordinate inputs mounted and may submit
                # their placeholder values even when there is no selected (or
                # even no existing) box.  That is not a manual coordinate edit
                # and must not block Next.
                if not active and not ctx['active']['regions']:
                    pass
                elif not active or any(coordinate is None for coordinate in coordinates):
                    raise ValueError('Select a box and enter all four coordinates.')
                else:
                    boxes[active]=list(coordinates)
                    if active not in selected:selected=[*selected,active]
            if boxes:
                updated=engine.apply(ctx['active'],'commit_boxes',{
                    'boxes':boxes,'active':active,'selected':selected,
                })
                ctx=dict(ctx,active=updated)
            return ctx,active,selected
        def frontend_crop(value):
            try:
                parsed=json.loads(value or '{}')
                crop_value=parsed.get('crop')
                if crop_value is not None and (
                        not isinstance(crop_value,list) or len(crop_value) != 4):
                    raise ValueError
                return crop_value
            except (ValueError,TypeError,AttributeError):
                raise gr.Error('The local crop frame is invalid.')
        def sidebar_crop(value):
            try:
                parsed=json.loads(value) if isinstance(value,str) else value
                if (not isinstance(parsed,list) or len(parsed) != 4
                        or any(isinstance(item,bool) or not isinstance(item,(int,float))
                               for item in parsed)):
                    raise ValueError
                return parsed
            except (ValueError,TypeError):
                raise gr.Error('Crop coordinates must be [x1, y1, x2, y2].')
        def frontend_text_sequence(value):
            try:
                parsed=json.loads(value or '{}')
                sequence=parsed.get('textSequence')
                token_order=parsed.get('tokenOrder')
                suspicious_token_ids=parsed.get('suspiciousTokenIds')
                if sequence is not None and (
                        not isinstance(sequence,list)
                        or any(not isinstance(item,str) or not item for item in sequence)):
                    raise ValueError
                if token_order is not None and (
                        not isinstance(token_order,list)
                        or any(not isinstance(item,str) or not item for item in token_order)):
                    raise ValueError
                if suspicious_token_ids is not None and (
                        not isinstance(suspicious_token_ids,list)
                        or any(not isinstance(item,str) or not item
                               for item in suspicious_token_ids)):
                    raise ValueError
                return sequence,token_order,suspicious_token_ids
            except (ValueError,TypeError,AttributeError):
                raise gr.Error('The local text sequence is invalid.')
        def frontend_statuses(value):
            try:
                parsed=json.loads(value or '{}')
                statuses=parsed.get('statuses',{})
                if (not isinstance(statuses,dict)
                        or any(not isinstance(box_id,str)
                               or status not in ('intact','damaged')
                               for box_id,status in statuses.items())):
                    raise ValueError
                return statuses
            except (ValueError,TypeError,AttributeError):
                raise gr.Error('The local status selection is invalid.')
        def commit_statuses(ctx,selection,status_value='intact'):
            statuses={
                uid: box['status']
                for uid,box in ctx['active']['regions'].items()
            }
            frontend=frontend_statuses(selection)
            for box_id,status_name in frontend.items():
                region_uid=ctx['active']['region_uid_by_box_id'].get(str(box_id))
                if region_uid:
                    statuses[region_uid]=status_name
            active,_=frontend_selection(selection)
            # The bridge contains the complete live working set. The mounted
            # radio value is only a compatibility fallback for an older or
            # incomplete browser snapshot; it must not overwrite that map.
            if active and str(active) not in frontend:
                region_uid=ctx['active']['region_uid_by_box_id'].get(str(active))
                if region_uid:
                    statuses[region_uid]=status_value
            updated=engine.apply(ctx['active'],'statuses',{'statuses':statuses})
            return dict(ctx,active=updated)
        def update_coordinates(ctx,selection,a,b,d,e):
            active,_=frontend_selection(selection)
            if not active:raise gr.Error('Select a bounding box first.')
            return run(ctx,'update',dict(id=active,bbox=[a,b,d,e]))
        clear_loading_when_done(update.click(update_coordinates,
            [session,selection_bridge,x1,y1,x2,y2],**event_args))
        def delete_selected(ctx,selection,a,b,d,e):
            try:
                ctx,_,selected=commit_frontend_boxes(ctx,selection)
                if not selected:raise ValueError('Select at least one box to delete.')
                return run(ctx,'delete',dict(ids=selected))
            except Exception as exc:
                return render(ctx,WARNING+' '+html.escape(str(exc)))
        clear_loading_when_done(delete.click(
            delete_selected,[session,selection_bridge,x1,y1,x2,y2],
            **dict(event_args,js=snapshot_board_state_js(1))))
        def run_detection(ctx,confirmed):
            if ctx['active']['regions'] and not confirmed:
                return render(ctx)
            return run(ctx,'detect')
        clear_loading_when_done(detect.click(
            run_detection,[session,detect_confirm],
            **dict(event_args,js="""(ctx, confirmed) => {
                const hasBoxes=Object.keys(ctx?.active?.regions || {}).length > 0;
                return [ctx, !hasBoxes || window.confirm('Run detection again and replace all existing boxes?')];
            }""")))
        def sort_current_boxes(ctx,selection,a,b,d,e):
            try:
                ctx,_,_=commit_frontend_boxes(ctx,selection)
                return run(ctx,'sort_boxes')
            except Exception as exc:
                return render(ctx,WARNING+' '+html.escape(str(exc)))
        clear_loading_when_done(sort_boxes.click(
            sort_current_boxes,[session,selection_bridge,x1,y1,x2,y2],
            **dict(event_args,js=snapshot_board_state_js(1))))
        def confirm_source_mismatch(ctx,issue_type,note):
            return run(ctx,'confirm_source_mismatch',dict(issue_type=issue_type,note=note))
        def clear_source_mismatch(ctx):
            return run(ctx,'clear_source_mismatch')
        clear_loading_when_done(confirm_mismatch.click(
            confirm_source_mismatch,[session,mismatch_type,mismatch_note],**event_args))
        clear_loading_when_done(clear_mismatch.click(
            clear_source_mismatch,[session],**event_args))
        for selector in (box_id,status_id):
            clear_loading_when_done(selector.input(lambda c,i:run(c,'select',dict(id=i)),[session,selector],**event_args))
        def parse_action(c,a,key,value):
            try:return run(c,a,{key:json.loads(value)})
            except ValueError as exc:return render(c,'Invalid JSON: '+str(exc))
        clear_loading_when_done(apply_crop.click(lambda c,v:parse_action(c,'crop','bbox',v),[session,crop_coords],**event_args))
        def apply_reading_order(ctx,selection,status_value='intact'):
            sequence,token_order,suspicious_token_ids=frontend_text_sequence(selection)
            try:
                if sequence is not None and (sequence or ctx['active']['annotations']):
                    updated=engine.apply(ctx['active'],'reorder_text',{
                        'sequence':sequence,'token_order':token_order,
                        'suspicious_token_ids':suspicious_token_ids})
                    ctx=dict(ctx,active=updated)
                elif suspicious_token_ids is not None:
                    updated=engine.apply(ctx['active'],'reorder_text',{
                        'sequence':list(ctx['active'].get('text_sequence',[])),
                        'token_order':list(map(str,ctx['active'].get('text_token_ids',[]))),
                        'suspicious_token_ids':suspicious_token_ids})
                    ctx=dict(ctx,active=updated)
                ctx=commit_statuses(ctx,selection,status_value)
                return render(ctx)
            except Exception as exc:
                return render(ctx,WARNING+' '+html.escape(str(exc)))
        clear_loading_when_done(apply_order.click(
            apply_reading_order,[session,selection_bridge,status],
            **dict(event_args,js=snapshot_board_state_js(1))))
        def on_action(ctx,evt:gr.EventData):
            return run(ctx,evt._data['action'],evt._data['payload'])
        board.action(on_action,[session],outputs=outputs,concurrency_id='annotation-actions',
                     concurrency_limit=1,show_progress='hidden')
    return app


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    args=parser().parse_args()
    create_app(args).queue().launch(server_name=args.server_name,server_port=args.port,share=args.share,css=APP_CSS,
        theme=gr.themes.Base(font=['Arial', 'sans-serif'], font_mono=['monospace']), footer_links=[],
        allowed_paths=[str(Path(args.image_dir).resolve())])
