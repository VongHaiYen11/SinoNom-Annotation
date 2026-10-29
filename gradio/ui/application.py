"""Gradio composition for the unified workflow; no legacy annotation controls."""
import base64
import html
import json
import logging
from collections import namedtuple
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import gradio as gr
from annotation.state import new_state, source_mismatch_confirmed, calculate_spatial_order
from annotation.workflow import Workflow
from annotation.recovery import RecoveryStore
from annotation.progress import ProgressBackup
from annotation.workspace import ensure_workspace, spatial_insert, issues_text, active_entries
from annotation.io import read_json, load_image_list, final_document, final_source_mismatch_document
from annotation.text_extraction import CONTENT_LOCK, content_fields
from annotation.export import collect_annotations, collect_content_documents, collect_source_mismatches, save_export_archive
from .editor import snapshot, SCRIPT, CSS, RECOVERY_SCRIPT, WORKSPACE_SCRIPT, WORKSPACE_CSS
from .presentation import app_identity, workflow_progress, panel_heading, footer, SECTION_LABELS
from .fonts import FONT_FILES, FONT_PRELOAD_JS
from crop.crop import suggest_crop

log = logging.getLogger(__name__)

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
    const el = document.getElementById('global-loading');
    const image = document.querySelector('#current-image-name')?.textContent?.trim() || 'picker';
    if (el) {
        const label = el.querySelector('span:not(.global-loading-spinner)');
        if (label) label.textContent = 'Loading…';
        el.classList.add('is-visible');
    }
    console.info('[verification-ui] loading shown', {image, visible: Boolean(el?.classList.contains('is-visible'))});
    return args;
}"""
HISTORY_FILTER_JS = """(...args) => {
    const root = document.querySelector('#history-modal');
    if (!root) return;
    const search = root.querySelector('#history-search input, #history-search textarea');
    const query = (search?.value || '').trim().toLocaleLowerCase();
    const selected = Array.isArray(args[1]) ? args[1] : ['Done', 'Not Done'];
    const showDone = selected.includes('Done');
    const showPending = selected.includes('Not Done');
    let shown = 0;
    root.querySelectorAll('.history-item').forEach(item => {
        const name = item.querySelector('.history-image-name')?.textContent || '';
        const matches = name.toLocaleLowerCase().includes(query)
            && (item.classList.contains('processed') ? showDone : showPending);
        item.hidden = !matches;
        if (matches) shown++;
    });
    const count = root.querySelector('#history-shown');
    if (count) count.textContent = shown;
    const empty = root.querySelector('.history-empty');
    if (empty) empty.hidden = shown > 0;
    const clear = root.querySelector('#history-search-clear');
    if (clear) clear.hidden = !query;
}"""
HISTORY_CLEAR_JS = """(selected) => {
    const root = document.querySelector('#history-modal');
    const input = root?.querySelector('#history-search input, #history-search textarea');
    if (input) {
        const prototype = input.tagName === 'TEXTAREA'
            ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (setter) setter.call(input, ''); else input.value = '';
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }
    let shown = 0;
    root?.querySelectorAll('.history-item').forEach(item => {
        const visible = item.classList.contains('processed')
            ? selected.includes('Done') : selected.includes('Not Done');
        item.hidden = !visible;
        if (visible) shown++;
    });
    const count = root?.querySelector('#history-shown');
    if (count) count.textContent = shown;
    const empty = root?.querySelector('.history-empty');
    if (empty) empty.hidden = shown > 0;
    const clear = root?.querySelector('#history-search-clear');
    if (clear) clear.hidden = true;
    return [''];
}"""
HISTORY_OPEN_JS = """() => {
    if (!window.vietnamicaHistoryKeyboard) {
        document.addEventListener('keydown', event => {
            const modal = document.getElementById('history-modal');
            if (!modal || getComputedStyle(modal).display === 'none') return;
            if (event.key === 'Escape') {
                event.preventDefault();
                (document.querySelector('#history-close button') || document.getElementById('history-close'))?.click();
            } else if (event.key === 'Tab') {
                const focusable = [...modal.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])')]
                    .filter(element => element.getClientRects().length);
                if (!focusable.length) return;
                const first = focusable[0], last = focusable[focusable.length - 1];
                if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
                    event.preventDefault(); last.focus();
                } else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
                    event.preventDefault(); first.focus();
                }
            }
        });
        window.vietnamicaHistoryKeyboard = true;
    }
    const modal = document.getElementById('history-modal');
    modal?.setAttribute('role', 'dialog');
    modal?.setAttribute('aria-modal', 'true');
    modal?.setAttribute('aria-label', 'Image History');
    (document.querySelector('#history-close button') || document.getElementById('history-close'))?.setAttribute('aria-label', 'Close image history');
    (document.querySelector('#history-search-clear button') || document.getElementById('history-search-clear'))?.setAttribute('aria-label', 'Clear image search');
    document.querySelector('#history-search input, #history-search textarea')?.setAttribute('aria-label', 'Search image name');
    setTimeout(() => document.querySelector('#history-search input, #history-search textarea')?.focus(), 0);
}"""
HISTORY_CLOSE_JS = """() => setTimeout(() => (document.querySelector('#history-open button') || document.getElementById('history-open'))?.focus(), 0)"""


HIDE_LOADING_JS = "() => document.getElementById('global-loading')?.classList.remove('is-visible')"
LIVE_EDITOR_JS = '''async (...args) => {
    const workspace=window.vietnamicaWorkspace;
    if (workspace?.active()) {
        await workspace.ready(); args[2]=JSON.stringify({workspace:workspace.snapshot()});
    } else if (window.vietnamicaViewer?.active()) {
        args[2]=JSON.stringify(window.vietnamicaViewer.snapshot());
    }
    return args;
}'''
PROGRESS_EXPORT_JS = '''async (ctx, request) => {
    if (window.vietnamicaWorkspace?.active()) await window.vietnamicaWorkspace.ready();
    const backup = window.vietnamicaDraftRecovery?.exportProgress() || {drafts:{}};
    return [ctx, JSON.stringify(backup)];
}'''
PROGRESS_DOWNLOAD_JS = '''payload => {
    if (!payload) return;
    const download=JSON.parse(payload);
    const url=URL.createObjectURL(new Blob([download.content],{type:'application/json;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=download.name;
    document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
}'''


def build_app(options):
    engine=Workflow(options)
    if hasattr(gr,'set_static_paths'):
        gr.set_static_paths(paths=[engine.preview_dir]+[p for p in FONT_FILES.values() if p.is_file()])
    skip_detection=getattr(options,'skip_detection',False)
    startup=''
    try:
        images=load_image_list(options.image_dir)
        read_json(options.source_json)
        if not images: startup='The image folder is empty.'
    except (ValueError,OSError) as exc:
        images=[];startup=str(exc)
    store=RecoveryStore()
    progress_backup=ProgressBackup(engine,images)
    initial=dict(active=dict(new_state(),unified_enabled=True),drafts={})
    def has_saved():
        output=Path(options.output_dir)
        return any((output/(p.stem+'.json')).is_file() or
                   (output/'source_mismatches'/(p.stem+'.json')).is_file() for p in images)

    with gr.Blocks(title='Sino-Nôm Annotation Tool',fill_width=True,analytics_enabled=False) as app:
        session=gr.State(initial)
        recovery_request=gr.Textbox(visible=False)
        selection_bridge=gr.Textbox(value='{}',visible=False)
        recovery_notice=gr.HTML(value=None,html_template='<span role="status">Restoring draft…</span>',
                                js_on_load=RECOVERY_SCRIPT,elem_id='draft-recovery-status')
        with gr.Column(elem_id='header-stack',scale=0):
            with gr.Row(elem_id='topbar',scale=0):
                progress=gr.HTML(app_identity(initial['active']),elem_id='app-chrome')
                with gr.Row(elem_id='header-actions',scale=0):
                    history_open=gr.Button('History',elem_id='history-open',scale=0)
                    progress_download=gr.Button('Download Progress',elem_id='progress-download',scale=0,interactive=has_saved())
                    save_all=gr.Button('Download All',variant='primary',scale=0,interactive=has_saved(),elem_id='save-all')
            workflow_chrome=gr.HTML(workflow_progress(initial['active']),elem_id='workflow-chrome')
        with gr.Group(visible=False,elem_id='history-modal') as history_modal:
            with gr.Column(elem_id='history-modal-card'):
                with gr.Row(elem_id='history-modal-heading'):
                    gr.Markdown('### Image History')
                    history_close=gr.Button('×',elem_id='history-close',scale=0)
                with gr.Group(elem_id='history-search-wrap'):
                    history_search=gr.Textbox(placeholder='Search image name…',show_label=False,elem_id='history-search')
                    history_clear=gr.Button('×',elem_id='history-search-clear')
                history_filter=gr.CheckboxGroup(['Done','Not Done'],value=['Done','Not Done'],show_label=False,elem_id='history-filter')
                history_results=gr.HTML(elem_id='history-results')
        message=gr.Markdown(startup,visible=bool(startup),elem_id='action-message')
        loading_modal=gr.HTML(LOADING_HIDDEN,elem_id='global-loading-host')
        download_payload=gr.Textbox(visible=False)
        progress_export_request=gr.Textbox(visible=False)
        progress_download_payload=gr.Textbox(visible=False)
        progress_pending=gr.State(None)
        with gr.Row(elem_id='workspace'):
            with gr.Column(elem_id='image-start',elem_classes='panel') as image_start:
                gr.Markdown('## Select an image')
                image_choice=gr.Dropdown(choices=[(p.name,str(p.resolve())) for p in images],label='Image')
                open_button=gr.Button('Start Verification',variant='primary')
                with gr.Accordion('Restore from Progress File',open=False):
                    gr.Markdown('Choose a previously downloaded progress file. The server must use the same input image set. Maximum file size: 128 MB.')
                    progress_upload=gr.File(label='Progress JSON file',file_types=['.json'],type='filepath')
                    with gr.Group(visible=False) as progress_preview_group:
                        progress_preview=gr.HTML()
                        gr.Markdown('Restoring replaces this session’s drafts and the listed matching results. Other saved results are kept.')
                        with gr.Row():
                            progress_restore=gr.Button('Restore Progress',variant='primary')
                            progress_cancel=gr.Button('Cancel')
            with gr.Column(visible=False,elem_id='control-panel',elem_classes='panel',min_width=0) as control_panel:
                heading=gr.HTML()
                current_image=gr.Markdown('—',elem_id='current-image-name')
                with gr.Group(visible=False) as crop_group:
                    gr.Markdown('### Crop')
                    gr.Markdown('Drag the crop frame or its corners. Oversized crops are scaled on export.')
                    crop_coords=gr.Textbox(label='Coordinates [x1, y1, x2, y2]',elem_id='crop-coordinates')
                    crop_suggest=gr.Button('Suggest position',elem_id='crop-suggest')
                    gr.Markdown('The suggested crop includes all bounding boxes on all four sides.')
            with gr.Column(visible=False,elem_id='main-workspace',elem_classes='panel',min_width=0) as main_workspace:
                with gr.Group(visible=False,elem_id='content-editor') as content_group:
                    gr.Markdown('## Content Verification')
                    field=gr.Dropdown(label='Section',filterable=False)
                    field_value=gr.Textbox(label='Content',lines=8,elem_id='content-value',elem_classes='han-nom-text')
                    content_bridge=gr.Textbox(value='{}',visible=False,elem_id='content-draft-bridge')
                    with gr.Row(visible=False,elem_id='content-actions') as content_actions:
                        apply_field=gr.Button('Apply to Draft',variant='primary')
                        undo=gr.Button('Undo Content')
                    with gr.Accordion('Content JSON',open=False):
                        content_preview=gr.Code(label='Content',language='json',interactive=False)
                workspace_board=gr.HTML(value=None,visible=False,html_template='<div></div>',
                    css_template=WORKSPACE_CSS,js_on_load=WORKSPACE_SCRIPT,elem_id='unified-annotation')
                board=gr.HTML(value=dict(markup='',image=None,step=1,revision=0),visible=False,html_template='${value.markup}',
                    css_template=CSS,js_on_load=SCRIPT,elem_id='annotation-board')
                with gr.Group(visible=False) as final_json_group:
                    with gr.Accordion('text_annotations.json',open=True):
                        preview=gr.JSON(label='Image JSON')
                    with gr.Accordion('source_mismatches.json',open=False) as mismatch_preview_group:
                        source_mismatches_preview=gr.JSON(label='Source Mismatches')
        with gr.Row(visible=False,elem_id='workflow-footer') as workflow_footer:
            back=gr.Button('Back',elem_id='back-button')
            footer_label=gr.HTML(elem_id='footer-step')
            next_button=gr.Button('Continue',variant='primary',elem_id='next-button')
            save=gr.Button('Save Annotation',visible=False,variant='primary',elem_id='save-image')
        components=dict(session=session,progress=progress,message=message,
            content_group=content_group,field=field,field_value=field_value,content_preview=content_preview,
            board=board,preview=preview,crop_group=crop_group,crop_coords=crop_coords,save=save,
            heading=heading,footer_label=footer_label,content_actions=content_actions,back=back,
            next_button=next_button,workflow_chrome=workflow_chrome,loading_modal=loading_modal,
            image_start=image_start,control_panel=control_panel,main_workspace=main_workspace,
            workflow_footer=workflow_footer,current_image=current_image,content_bridge=content_bridge,
            final_json_group=final_json_group,source_mismatches_preview=source_mismatches_preview,
            mismatch_preview_group=mismatch_preview_group,save_all=save_all,image_choice=image_choice,
            recovery_notice=recovery_notice,workspace_board=workspace_board,progress_download=progress_download)
        Output=namedtuple('AnnotationUI',components)
        outputs=list(components.values())

        def render(ctx,msg='',progress_seed=None):
            s=ctx['active'];step=s['current_step'];has=bool(s.get('image'))
            if msg: gr.Warning(str(msg))
            fields=content_fields(s['draft_content'],s['code'],engine.content_titles,engine.metadata_fields) if has else []
            choices=[(SECTION_LABELS.get(f['title'],f['title']),json.dumps(f['path'],ensure_ascii=False)) for f in fields]
            draft={json.dumps(f['path'],ensure_ascii=False):dict(title=f['title'],path=f['path'],value=f['value']) for f in fields}
            chosen=choices[0][1] if choices else None
            mismatch=source_mismatch_confirmed(s) if step==7 else False
            final=(final_source_mismatch_document(s) if mismatch else final_document(s)) if step==7 else None
            metadata=store.checkpoint(ctx)
            view=snapshot(s) if step in (6,7) else dict(markup='',image=None,step=step,revision=s['revision'])
            view['recovery']=metadata
            values=dict(session=ctx,progress=app_identity(s),message=gr.update(visible=bool(startup and not has)),
                content_group=gr.update(visible=step==2 and has),field=gr.update(choices=choices,value=chosen),
                field_value=fields[0]['value'] if fields else '',
                content_preview=json.dumps([dict(tieu_de=f['title'],van_ban=f['value']) for f in fields],ensure_ascii=False,indent=2),
                board=gr.update(value=view,visible=step in (6,7)),preview=gr.update(value=final),
                crop_group=gr.update(visible=step==6),crop_coords=json.dumps(s.get('crop')),
                save=gr.update(visible=step==7),heading=panel_heading(s),footer_label=footer(s),
                content_actions=gr.update(visible=step==2 and has),back=gr.update(interactive=has and step>1),
                next_button=gr.update(visible=step in (2,6),interactive=has),workflow_chrome=workflow_progress(s),
                loading_modal=LOADING_HIDDEN,image_start=gr.update(visible=step==1),
                control_panel=gr.update(visible=has and step in (6,7)),main_workspace=gr.update(visible=has and step>1),
                workflow_footer=gr.update(visible=has and step>1),current_image=f'`{s["image"]}`' if has else '—',
                content_bridge=json.dumps(draft,ensure_ascii=False),final_json_group=gr.update(visible=step==7),
                source_mismatches_preview=gr.update(value=[final] if mismatch and final else []),
                mismatch_preview_group=gr.update(visible=step==7 and mismatch),save_all=gr.update(interactive=has_saved()),
                image_choice=gr.update(value=s.get('image_path') if step==1 else None),
                recovery_notice=dict(metadata,defaultSection=chosen,
                    **({'progressImport':progress_seed} if progress_seed else {})) if metadata else None,
                progress_download=gr.update(interactive=has or bool(ctx.get('drafts')) or has_saved()),
                workspace_board=gr.update(visible=step==3,value=dict(step=step,model=s.get('workspace'),image=s.get('image'),
                    image_url=s.get('image_url'),size=s.get('image_size'),recovery=metadata,
                    issues=s.get('workspace_issues',[]),report=issues_text(s.get('image'),s.get('workspace_issues',[])),can_detect=not skip_detection)))
            return Output(**values)

        def run(ctx,action,payload=None):
            try:
                before=ctx['active'];updated=engine.apply(before,action,payload)
                ctx=dict(ctx,active=updated)
                if action in ('undo','detect','save') or before['current_step']!=updated['current_step']:
                    store.rotate(ctx,before.get('image_path'))
                if action=='detect': ensure_workspace(updated,reset_boxes=True)
                if action=='save':
                    gr.Info('Saved.')
                    path=updated.get('image_path');ctx['drafts'].pop(path,None)
                    ctx['_recovery_discard']=path
                    ctx['active']=dict(new_state(),unified_enabled=True,revision=updated['revision']+1)
                return render(ctx)
            except Exception as exc:
                log.exception('Action %s failed',action)
                return render(ctx,str(exc))

        def restore_browser_fields(result,ctx,request):
            try:
                meta=store.metadata(ctx)
                record=next((item for item in request.get('drafts',{}).values()
                    if all(item.get('metadata',{}).get(k)==v for k,v in meta.items())),None)
                if not record or not ctx['active'].get('image'): return result
                if record.get('workspace') and ctx['active'].get('workspace') and ctx['active']['current_step']==3:
                    ctx=dict(ctx,active=engine.apply(ctx['active'],'workspace_sync',{'model':record['workspace']}))
                    result=render(ctx)
                fields=json.loads(result.content_bridge)
                content=json.loads(record.get('content') or '{}')
                for key,entry in fields.items():
                    if isinstance(content.get(key),dict) and isinstance(content[key].get('value'),str): entry['value']=content[key]['value']
                    if isinstance(record.get('typing',{}).get(key),str): entry['value']=record['typing'][key]
                section=record.get('section')
                updates=dict(content_bridge=json.dumps(fields,ensure_ascii=False),
                    content_preview=json.dumps([dict(tieu_de=f['title'],van_ban=f['value']) for f in fields.values()],ensure_ascii=False,indent=2))
                if section in fields: updates.update(field=gr.update(value=section),field_value=fields[section]['value'])
                return result._replace(**updates)
            except (ValueError,TypeError,AttributeError):
                log.warning('Ignoring invalid browser recovery fields')
                return result

        def open_image(ctx,path,browser_request=None):
            try:
                if path not in {str(p.resolve()) for p in images}: raise ValueError('Select an image from the list.')
                ctx=deepcopy(ctx);ctx.pop('_recovery_discard',None);old=ctx['active']
                if old.get('image_path') and old['current_step']>1: ctx['drafts'][old['image_path']]=deepcopy(old)
                state=deepcopy(ctx['drafts'][path]) if path in ctx['drafts'] else engine.open_image(path)
                state.update(unified_enabled=True,revision=old['revision']+1)
                ctx['active']=state
                result=render(ctx)
                return restore_browser_fields(result,ctx,json.loads(browser_request)) if browser_request else result
            except (ValueError,OSError,TypeError) as exc: return render(ctx,str(exc))

        def commit_frontend_content(ctx,draft):
            parsed=json.loads(draft or '{}');s=ctx['active']
            fields=content_fields(s['draft_content'],s['code'],engine.content_titles,engine.metadata_fields)
            expected={json.dumps(f['path'],ensure_ascii=False):f for f in fields}
            if not isinstance(parsed,dict) or set(parsed)!=set(expected): raise ValueError('The local content draft is incomplete or invalid.')
            updated=s
            for key,f in expected.items():
                entry=parsed[key]
                if (not isinstance(entry,dict) or entry.get('title')!=f['title']
                    or entry.get('path')!=list(f['path']) or not isinstance(entry.get('value'),str)):
                    raise ValueError('The local content draft is invalid.')
                if entry['value']!=f['value']: updated=engine.apply(updated,'field',{'path':entry['path'],'value':entry['value']})
            return dict(ctx,active=updated)

        def next_with_progress(ctx,content_draft=None,selection='{}',crop_coordinates=None):
            previous=ctx['active']['current_step']
            try:
                if previous==2: ctx=commit_frontend_content(ctx,content_draft)
                elif previous==6:
                    raw=json.loads(selection or '{}')
                    crop=raw.get('crop') if raw.get('crop') is not None else json.loads(crop_coordinates or 'null')
                    if crop is not None: ctx=dict(ctx,active=engine.apply(ctx['active'],'crop',{'bbox':crop}))
                result=run(ctx,'next')
                if result.session['active']['current_step']==2:
                    result=result._replace(field=gr.skip(),field_value=gr.skip())
                state=result.session['active']
                if previous==2 and state['current_step']==3 and not state['detection_loaded'] and not skip_detection:
                    yield result._replace(loading_modal=loading_markup('Running detection…',True),back=gr.update(interactive=False))
                    result=run(result.session,'detect')
                yield result
            except (ValueError,TypeError,AttributeError) as exc:
                yield render(ctx,str(exc))._replace(field=gr.skip(),field_value=gr.skip(),content_bridge=gr.skip())

        def go_back(ctx,selection='{}'):
            try:
                raw=json.loads(selection or '{}')
                if ctx['active']['current_step']==3 and raw.get('workspace'):
                    ctx=dict(ctx,active=engine.apply(ctx['active'],'workspace_sync',{'model':raw['workspace']}))
                return run(ctx,'back')
            except (ValueError,TypeError) as exc: return render(ctx,str(exc))

        def save_image(ctx): return run(ctx,'save')
        def undo_content(ctx): return run(ctx,'undo')

        def suggest_crop_position(ctx):
            state=ctx['active']
            try:
                if state['current_step']!=6:
                    raise ValueError('Crop suggestions are available only in the Crop step.')
                return json.dumps(suggest_crop(state['regions'].values(),state['image_size']))
            except ValueError as exc:
                gr.Warning(str(exc))
                return gr.skip()

        def on_workspace_action(ctx,evt:gr.EventData):
            data=evt._data
            try:
                ctx=dict(ctx,active=engine.apply(ctx['active'],'workspace_sync',{'model':data['model']}))
                model=ctx['active']['workspace']
                if data['action']=='insert': spatial_insert(ctx['active'],data['box_id'])
                elif data['action']=='sort':
                    ordered=calculate_spatial_order({uid:b['bbox'] for uid,b in model['boxes'].items()},ctx['active']['image_size'])
                    for i,uid in enumerate(ordered,1): model['boxes'][uid]['order']=i
                    ctx['active']['regions']=deepcopy(model['boxes'])
                    pos=model['boxes'].get(model.get('selected_box'),{}).get('order');entries=active_entries(model)
                    model['selected_char']=(model['confirmed'].get(model.get('selected_box'))
                        or (entries[pos-1]['char_id'] if pos and pos<=len(entries) else None))
                elif data['action']=='continue': return run(ctx,'next')
                elif data['action']=='detect': return run(ctx,'detect')
                elif data['action']!='checkpoint': raise ValueError('Unknown workspace action.')
                if data['action'] in ('insert','sort'): model['version']=data['model'].get('version',0)+1
                return render(ctx)
            except (ValueError,TypeError,KeyError) as exc: return render(ctx,str(exc))

        def restore_session(request):
            try:
                request=json.loads(request or '{}')
                if not isinstance(request,dict): request={}
            except ValueError: request={}
            ctx=store.restore(request.get('tab'),initial)
            seed=ctx.get('_progress_seed')
            if seed and request.get('progressImportId')==seed['id']: seed=None
            return restore_browser_fields(render(ctx,progress_seed=seed),ctx,request)

        def save_folder():
            try:
                annotations=collect_annotations(images,options.output_dir,allow_empty=True)
                mismatches=collect_source_mismatches(images,options.output_dir,allow_empty=True)
                committed={d['image'] for d in annotations+mismatches}
                content=collect_content_documents([p for p in images if p.name in committed],options.output_dir,
                    allow_empty=True,titles=engine.verification_titles)
                archive=save_export_archive(annotations,content,options.output_dir,mismatches)
                return json.dumps(dict(name=archive.name,content=base64.b64encode(archive.read_bytes()).decode('ascii')))
            except (ValueError,OSError,KeyError,TypeError) as exc: raise gr.Error(str(exc)) from exc

        def download_progress(ctx,browser_request):
            try:
                browser=json.loads(browser_request or '{}')
                browser['application']=store.application
                with CONTENT_LOCK:
                    data=progress_backup.export(ctx,browser)
                name='vietnamica-progress-'+data['created_at'][:19].replace(':','').replace('-','')+'Z.json'
                return json.dumps(dict(name=name,content=json.dumps(data,ensure_ascii=False,allow_nan=False)))
            except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
                raise gr.Error(f'Could not download progress: {exc}') from exc

        def preview_progress(path):
            try:
                if not path: return None,'',gr.update(visible=False)
                data=progress_backup.read(path)
                summary=progress_backup.summary(progress_backup.prepare(data))
                local_time=datetime.fromisoformat(summary['created_at']).astimezone(timezone(timedelta(hours=7)))
                rows=[('Backup time',local_time.strftime('%d/%m/%Y %H:%M:%S (UTC+07)')),
                      ('Active image',summary['active_image'] or 'None'),
                      ('Step',summary['step'] or 'Image selection'),
                      ('Drafts',summary['drafts']),('Saved results',summary['saved'])]
                markup='<dl>'+''.join(f'<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>' for label,value in rows)+'</dl>'
                markup+='<p>Server results that will be replaced: '+html.escape(', '.join(summary['conflicts']) or 'None')+'</p>'
                return dict(backup=data,conflicts=summary['conflicts']),markup,gr.update(visible=True)
            except (ValueError,OSError,KeyError,TypeError,AttributeError,OverflowError) as exc:
                gr.Warning(f'Could not read progress file: {exc}')
                return None,'',gr.update(visible=False)

        def restore_progress(ctx,pending,path):
            try:
                if not pending or not path: raise ValueError('Choose and preview a progress file first.')
                data=pending['backup']
                if progress_backup.read(path)!=data:
                    raise ValueError('The file changed. Select it again to preview the latest version.')
                # Revalidate on confirmation: images/source/output may have changed since preview.
                prepared=progress_backup.prepare(data)
                if progress_backup.summary(prepared)['conflicts']!=pending['conflicts']:
                    raise ValueError('Server results changed. Select the file again to preview the current state.')
                candidate=dict(active=dict(new_state(),unified_enabled=True),drafts=deepcopy(prepared['drafts']),
                    _recovery=dict(tab=ctx.get('_recovery',{}).get('tab') or uuid4().hex,generations={}))
                if prepared['active_name']:
                    candidate['active']=deepcopy(prepared['drafts'][str(progress_backup.images[prepared['active_name']])])
                records={}
                for state in candidate['drafts'].values():
                    metadata=store.metadata(dict(candidate,active=state))
                    key=json.dumps([metadata['application'],metadata['tab'],metadata['image'],metadata['step']],separators=(',',':'))
                    records[key]=dict(prepared['ui'][state['image']],metadata=metadata)
                candidate['_progress_seed']=dict(id=uuid4().hex,records=records)
                # All validation, generation allocation and browser seed construction precede writes.
                progress_backup.commit(prepared)
                result=restore_browser_fields(render(candidate,progress_seed=candidate['_progress_seed']),candidate,dict(drafts=records))
                return tuple(result)+(None,'',gr.update(visible=False),None)
            except (ValueError,OSError,KeyError,TypeError,AttributeError,OverflowError) as exc:
                gr.Warning(f'Could not restore progress: {exc}')
                return tuple(gr.skip() for _ in outputs)+(gr.skip(),gr.skip(),gr.skip(),gr.skip())

        def history_markup():
            items=[];processed=0;out=Path(options.output_dir)
            for image in images:
                done=(out/(image.stem+'.json')).exists() or (out/'source_mismatches'/(image.stem+'.json')).exists()
                processed+=int(done)
                items.append(f'<li class="history-item {"processed" if done else "pending"}"><span class="history-image-name">{html.escape(image.name)}</span><span class="history-status">{"Processed" if done else "Not processed"}</span></li>')
            return f'<div class="history-count">Processed {processed}/{len(images)} images · Showing <span id="history-shown">{len(images)}</span></div><ul class="history-list">'+''.join(items)+'<li class="history-empty" hidden>No matching images found.</li></ul>'

        event_args=dict(outputs=outputs,concurrency_id='annotation-actions',concurrency_limit=1,show_progress='hidden')
        def clear_loading(event):
            event.success(fn=None,inputs=None,outputs=None,js=HIDE_LOADING_JS)
            event.failure(fn=None,inputs=None,outputs=None,js=HIDE_LOADING_JS)
            return event
        open_js=SHOW_LOADING_JS.replace('return args;', '''
            window.vietnamicaDraftRecovery?.captureUI();
            let drafts={};try {drafts=JSON.parse(sessionStorage.getItem('vietnamica-drafts-v1') || '{}');} catch (_) {}
            return [args[0],args[1],JSON.stringify({drafts})];''')
        clear_loading(open_button.click(open_image,[session,image_choice,recovery_request],js=open_js,**event_args))
        clear_loading(next_button.click(next_with_progress,[session,content_bridge,selection_bridge,crop_coords],js=LIVE_EDITOR_JS,**event_args))
        back_js=LIVE_EDITOR_JS.replace('args[2]','args[1]')
        clear_loading(back.click(go_back,[session,selection_bridge],js=back_js,**event_args))
        clear_loading(save.click(save_image,[session],js=SHOW_LOADING_JS,**event_args))
        clear_loading(undo.click(undo_content,[session],**event_args))
        progress_download.click(download_progress,[session,progress_export_request],[progress_download_payload],
            js=PROGRESS_EXPORT_JS,concurrency_id='annotation-actions',concurrency_limit=1,show_progress='hidden').success(
                fn=None,inputs=[progress_download_payload],outputs=None,js=PROGRESS_DOWNLOAD_JS,show_progress='hidden')
        progress_upload.change(preview_progress,[progress_upload],
            [progress_pending,progress_preview,progress_preview_group],show_progress='hidden')
        progress_cancel.click(lambda:(None,'',gr.update(visible=False),None),[],
            [progress_pending,progress_preview,progress_preview_group,progress_upload],show_progress='hidden')
        progress_restore.click(restore_progress,[session,progress_pending,progress_upload],
            outputs+[progress_pending,progress_preview,progress_preview_group,progress_upload],
            concurrency_id='annotation-actions',concurrency_limit=1,show_progress='hidden')
        crop_suggest.click(suggest_crop_position,[session],[crop_coords],
            concurrency_id='annotation-actions',concurrency_limit=1,show_progress='hidden').success(
                fn=None,inputs=[crop_coords],outputs=None,show_progress='hidden',js='''coordinates => {
                    try { window.vietnamicaViewer?.setCrop(JSON.parse(coordinates)); } catch (_) {}
                }''')
        workspace_board.action(on_workspace_action,[session],**event_args)
        field.change(fn=None,inputs=[field,content_bridge],outputs=[field_value],queue=False,show_progress='hidden',js='''(path,draft) => {
            const typed=window.vietnamicaRecovery?.section(path,draft);
            try {return typed ?? JSON.parse(draft || '{}')?.[path]?.value ?? '';} catch (_) {return '';}
        }''')
        apply_field.click(fn=None,inputs=[field,field_value,content_bridge],outputs=[content_bridge,content_preview],queue=False,show_progress='hidden',js='''(path,value,draft) => {
            let fields={};try {fields=JSON.parse(draft || '{}');} catch (_) {}
            if(fields[path]) fields[path].value=String(value ?? '');
            window.vietnamicaRecovery?.content(fields);
            return [JSON.stringify(fields),JSON.stringify(Object.values(fields).map(f=>({tieu_de:f.title,van_ban:f.value})),null,2)];
        }''')
        history_open.click(lambda:(gr.update(visible=True),history_markup()),[],[history_modal,history_results],show_progress='hidden').success(
            fn=None,inputs=[history_search,history_filter],outputs=None,js=HISTORY_FILTER_JS,show_progress='hidden').success(
            fn=None,inputs=None,outputs=None,js=HISTORY_OPEN_JS,show_progress='hidden')
        history_close.click(lambda:gr.update(visible=False),[],[history_modal],show_progress='hidden').success(
            fn=None,inputs=None,outputs=None,js=HISTORY_CLOSE_JS,show_progress='hidden')
        history_search.input(fn=None,inputs=[history_search,history_filter],outputs=None,js=HISTORY_FILTER_JS,show_progress='hidden')
        history_filter.change(fn=None,inputs=[history_search,history_filter],outputs=None,js=HISTORY_FILTER_JS,show_progress='hidden')
        history_clear.click(fn=None,inputs=[history_filter],outputs=[history_search],js=HISTORY_CLEAR_JS,show_progress='hidden')
        clear_loading(save_all.click(save_folder,[],[download_payload],concurrency_id='annotation-actions',concurrency_limit=1,
            show_progress='hidden',js=SHOW_LOADING_JS)).success(fn=None,inputs=[download_payload],outputs=None,js='''payload => {
            if(!payload) return;const archive=JSON.parse(payload),binary=atob(archive.content);
            const bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));
            const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
            const a=document.createElement('a');a.href=url;a.download=archive.name;document.body.appendChild(a);a.click();a.remove();
            setTimeout(()=>URL.revokeObjectURL(url),10000);
        }''')
        bootstrap_js='''async () => {
            const container=document.querySelector('.gradio-container');
            if (container) container.inert=true;
            const workspace=document.querySelector('#workspace');
            if (workspace) workspace.inert=true;
            const footer=document.querySelector('#workflow-footer');
            if (footer) footer.inert=true;
            let tab;
            try {
                tab=sessionStorage.getItem('vietnamica-tab');
                if (!tab) {
                    tab=crypto.randomUUID();
                    sessionStorage.setItem('vietnamica-tab',tab);
                }
            } catch (_) {
                tab=crypto.randomUUID();
                window.vietnamicaStorageError=true;
            }
            // Duplicating a tab can copy sessionStorage. Claim a separate ID
            // if the original tab is still alive; a reload has no live owner.
            try { if (typeof BroadcastChannel !== 'undefined') {
                const channel=new BroadcastChannel('vietnamica-tab-ownership');
                const nonce=crypto.randomUUID();
                const owned=await new Promise(resolve => {
                    const timer=setTimeout(() => resolve(false),150);
                    channel.onmessage=event => {
                        if (event.data?.type==='owned' && event.data.nonce===nonce) {
                            clearTimeout(timer); resolve(true);
                        }
                    };
                    channel.postMessage({type:'probe',tab,nonce});
                });
                channel.close();
                if (owned) {
                    tab=crypto.randomUUID();
                    try {
                        sessionStorage.setItem('vietnamica-tab',tab);
                        sessionStorage.removeItem('vietnamica-drafts-v1');
                    } catch (_) { window.vietnamicaStorageError=true; }
                }
            } } catch (_) { /* Restricted frames may disable tab discovery. */ }
            let drafts={};
            try { drafts=JSON.parse(sessionStorage.getItem('vietnamica-drafts-v1') || '{}'); }
            catch (_) { window.vietnamicaStorageError=true; }
            let progressImportId;try {progressImportId=sessionStorage.getItem('vietnamica-progress-import-id');} catch (_) {}
            return [JSON.stringify({tab,drafts,progressImportId})];
        }'''
        restored=app.load(restore_session,inputs=[recovery_request],js=bootstrap_js,**event_args)
        restored.then(fn=None,inputs=None,outputs=None,js=FONT_PRELOAD_JS,show_progress='hidden')
    return app
