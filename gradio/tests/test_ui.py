"""Exercise real Gradio callbacks without requiring a browser or ML assets."""
import asyncio
import base64
import json
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app, parser, resolve_app_paths
import gradio as gr
from annotation.state import (new_state, set_verified_content,
                              refresh_bbox_validation, initialize_alignment)
from annotation.bbox import add_bbox
from annotation.status import confirm_status
from annotation.io import atomic_write
from annotation.text_extraction import content_fields
from annotation.workflow import Workflow
from ui.presentation import SECTION_LABELS, header
from ui.editor import snapshot
from PIL import Image


class GradioCallbacks(unittest.TestCase):
    def test_miss_box_is_derived_unknown_and_rendered_yellow(self):
        state=new_state();state.update(image='12305.png',image_size=[100,100],
                                      image_url='image.jpg',current_step=4)
        set_verified_content(state,{},'永寺')
        for x in (0,20,40):add_bbox(state,[x,0,x+10,10])
        state['source_mismatch']={
            'source_text':state['annotation_text'],'source_character_count':2,
            'bounding_box_count':3,'issue_type':'missing_source_characters','note':''}
        refresh_bbox_validation(state);confirm_status(state);initialize_alignment(state)
        missing_id=next(key for key,value in state['annotations'].items() if value=='MISS')
        self.assertEqual(state['bounding_boxes'][missing_id]['status'],'unknown')
        reading_markup=snapshot(state)['markup']
        self.assertIn('stroke="#f4f4f5"',reading_markup)
        self.assertNotIn('stroke="#f59e0b"',reading_markup)
        state['current_step']=5
        markup=snapshot(state)['markup']
        self.assertIn(f'<title>{missing_id} MISS · unknown</title>',markup)
        self.assertIn('stroke="#f59e0b"',markup)
        self.assertIn('Unknown / MISS',markup)

    def test_canvas_script_keeps_selection_and_geometry_local_until_next(self):
        script=(Path(__file__).resolve().parents[1]/'ui/assets/editor.js').read_text()
        self.assertNotIn("send('select'",script)
        self.assertNotIn("send('commit_boxes'",script)
        self.assertIn("send('status'",script)
        self.assertIn('boxes: Object.fromEntries',script)
        self.assertIn("kind:'marquee'",script)
        self.assertIn('selectedIds = new Set()',script)
        self.assertIn('const showResizeHandles = selectedIds.size === 1',script)
        self.assertIn("group.classList.toggle('active-region', active && showResizeHandles)",script)
        self.assertIn("event.target.closest('[data-order-chip]')",script)
        self.assertIn('textSequence: [...localTextSequence]',script)
        self.assertIn('textSequenceFromDOM',script)
        self.assertNotIn('chip.dataset.boxId',script)
        self.assertIn('animateChipReflow',script)
        self.assertIn('captureChipRects',script)
        self.assertIn('getBoundingClientRect()',script)
        self.assertIn('translate3d(${dx}px, ${dy}px, 0)',script)
        self.assertIn('duration:180',script)
        self.assertIn("easing:'cubic-bezier(.22, 1, .36, 1)'",script)
        self.assertIn('chipReflowAnimations.get(chip)?.cancel()',script)
        self.assertIn("White:'#f4f4f5', Cyan:'#22d3ee', Amber:'#f59e0b'",script)
        self.assertIn("#bbox-color-palette input",script)
        self.assertIn('applyAnnotationColor',script)
        self.assertIn('updateExcludedChips',script)
        self.assertIn("event.target.closest('#bbox-x1 input, #bbox-y1 input, #bbox-x2 input, #bbox-y2 input')",script)
        self.assertIn('localBoxes[activeBoxId].bbox=[x1,y1,x2,y2]',script)
        self.assertIn('syncingCoordinateControls = true',script)
        self.assertIn('if (syncingCoordinateControls || props.value.step !== 3',script)
        self.assertIn("send('add',{",script)
        self.assertIn('boxes:Object.fromEntries(Object.entries(localBoxes)',script)
        self.assertIn('syncExternalControls();',script)
        self.assertNotIn("addEventListener('dragover'",script)
        editor_css=(Path(__file__).resolve().parents[1]/'ui/assets/editor.css').read_text()
        self.assertIn('.order-chips {',editor_css)
        self.assertIn('flex-wrap: wrap',editor_css)
        self.assertIn('.order-chip-ghost {',editor_css)
        self.assertIn('.order-chip.excluded {',editor_css)
        self.assertIn('overflow-x: auto',editor_css)
        self.assertIn('overflow-y: auto',editor_css)
        self.assertIn('const availableWidth = Math.max(1, viewport.clientWidth',script)
        self.assertIn('const fit = availableWidth / width',script)
        self.assertIn("root.querySelector('#control-panel')",script)
        self.assertIn('Math.min(fullViewportHeight, sidebarHeight)',script)
        workbench_css=(Path(__file__).resolve().parents[1]/'ui/assets/workbench.css').read_text()
        self.assertNotIn('#bbox-color-palette label::after',workbench_css)
        self.assertNotIn('--box-swatch',workbench_css)
        editor_source=(Path(__file__).resolve().parents[1]/'ui/editor.py').read_text()
        self.assertNotIn('data-zoom="fit"',editor_source)
        self.assertNotIn('Fit image to view',editor_source)

    def test_apply_and_next_snapshot_visible_text_cards(self):
        source=(Path(__file__).resolve().parents[1]/'app.py').read_text()
        self.assertIn("document.querySelector('#annotation-board')",source)
        self.assertIn("board?.querySelector('.order-chips')",source)
        self.assertIn("snapshot.textSequence = [...cards.querySelectorAll('[data-order-chip]')]",source)
        self.assertIn("snapshot.crop = bbox",source)
        self.assertIn("snapshot.boxes = boxes",source)
        self.assertIn('snapshot_board_state_js(5)',source)
        self.assertIn('snapshot_board_state_js(1)',source)
        self.assertIn('delete_selected,[session,selection_bridge,x1,y1,x2,y2]',source)
        self.assertIn("value='White',show_label=False,interactive=True",source)
        self.assertNotIn("label='Outline color'",source)

    def test_compact_header_has_all_steps_and_no_draft_status(self):
        state=new_state();state.update(image='12305.jpg',current_step=2)
        markup=header(state)
        self.assertNotIn('Draft',markup)
        self.assertNotIn('save-indicator',markup)
        self.assertIn('<span class="brand-mark" aria-hidden="true">文</span>',markup)
        self.assertEqual(markup.count('class="stepper-item'),7)
        self.assertEqual(markup.count('class="stepper-label"'),7)
        self.assertIn('aria-current="step"',markup)
        for label in ('Image','Content','Bounding Boxes','Reading Order','Status','Crop','Review'):
            self.assertIn(f'>{label}</span>',markup)

    def test_sidebar_has_bounded_scroll_and_aligned_action_controls(self):
        css=(Path(__file__).resolve().parents[1]/'ui/assets/workbench.css').read_text()
        self.assertIn('#header-stack {',css)
        self.assertIn('#topbar {',css)
        self.assertIn('#save-image { grid-column: 4; }',css)
        self.assertIn('#workflow-chrome {',css)
        self.assertIn('flex: 0 0 auto !important',css)
        self.assertIn('grid-template-rows: auto auto auto',css)
        self.assertIn('min-height: 100dvh',css)
        self.assertIn('overflow: visible',css)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))',css)
        self.assertIn('#image-start {',css)
        self.assertIn('#control-panel .sidebar-action-stack {',css)
        app_source=(Path(__file__).resolve().parents[1]/'app.py').read_text()
        self.assertNotIn('Restore original content',app_source)
        self.assertNotIn('content-image-preview',app_source)
        self.assertIn('white-space: nowrap',css)
        self.assertIn('#confirm-source-mismatch',css)
        self.assertIn('justify-content: center',css)
        self.assertNotIn('.font-picker',css)
        self.assertNotIn("Accordion('Display font'",(Path(__file__).resolve().parents[1]/'app.py').read_text())

    def test_cli_paths_override_config_and_missing_paths_use_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            config=root/'config.json'
            config.write_text(json.dumps({
                'paths': {'output_json': 'source.json'},
                'gradio': {'image_dir': 'images', 'output_dir': 'annotations'},
                'records': {'content': {
                    'start_heading': 'Nguyên văn chữ Hán Nôm',
                    'section_headings': ['Nguyên văn chữ Hán Nôm'],
                }},
            }))
            override=root/'override-images'
            options=parser().parse_args([
                '--config',str(config),'--image-dir',str(override),
            ])
            resolve_app_paths(options)
            self.assertEqual(options.image_dir,str(override))
            self.assertEqual(options.source_json,str(root/'source.json'))
            self.assertEqual(options.output_dir,str(root/'annotations'))

            missing=root/'missing.json'
            explicit=parser().parse_args([
                '--config',str(missing),'--image-dir','images',
                '--source-json','source.json','--output-dir','annotations',
            ])
            with self.assertRaisesRegex(ValueError, 'Cannot read app config'):
                resolve_app_paths(explicit)

    def test_cli_lets_gradio_choose_an_available_port_by_default(self):
        self.assertIsNone(parser().parse_args([]).port)
        self.assertEqual(parser().parse_args(['--port','7861']).port,7861)

    def test_content_editor_only_selected_face_sections(self):
        titles=['Nguyên văn chữ Hán Nôm','Phiên âm Hán Việt','Dịch nghĩa','Toát yếu','Chú thích']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            image=root/'12306.png';Image.new('RGB',(100,100),'white').save(image)
            source=root/'source.json'
            metadata_labels=['Tên bia','Địa điểm','Niên đại']
            record={'ten_bia':'Giữ tên bia','dia_diem':'Hà Nội','nien_dai':'Cảnh Hưng',
                    'extra':{'keep':42},'noi_dung':[
                {'ky_hieu':'12305','chuyen_muc':[{'tieu_de':titles[0],'van_ban':'文'}]},
                {'ky_hieu':'12306','chuyen_muc':[
                    {'tieu_de':title,'van_ban':'永寺樂' if title==titles[0] else title+' gốc','extra':'giữ nguyên'}
                    for title in reversed(titles)] + [{'tieu_de':'Mục khác','van_ban':'Giữ nguyên mục khác'}]}]}
            original=[record,{'noi_dung':[],'extra':'record khác'}]
            atomic_write(source,original)
            config=root/'config.json'
            atomic_write(config,{
                'records': {
                    'metadata': [
                        {'label':label,'field':field,'type':'string','required':True}
                        for label,field in zip(
                            metadata_labels,['ten_bia','dia_diem','nien_dai'])],
                    'content': {
                        'start_heading': titles[0], 'section_headings': titles}},
            })
            options=parser().parse_args(['--config',str(config),
                                        '--image-dir',str(root),'--source-json',str(source),
                                        '--output-dir',str(root/'out'),'--skip-detection'])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            choose=next(f for f in functions if f.__name__=='choose_field')
            edit=next(f for f in functions if f.__name__=='apply_content_field')
            save=next(f for f in functions if f.__name__=='<lambda>' and f.__defaults__==('save_content',))
            result=open_image(dict(active=new_state(),drafts={}),str(image))
            ctx=result[0];choices=result[4]['choices']
            self.assertEqual(
                [label for label,_ in choices],
                metadata_labels+[SECTION_LABELS[t] for t in titles])
            self.assertEqual(result[5],'Giữ tên bia')
            preview=json.loads(result[6])
            self.assertEqual(
                [entry['tieu_de'] for entry in preview],metadata_labels+titles)
            self.assertNotIn('ten_bia',result[6])
            choice_by_label=dict(choices)
            metadata_path=choice_by_label['Tên bia']
            self.assertEqual(choose(ctx,metadata_path),'Giữ tên bia')
            edited=edit(ctx,metadata_path,'Tên bia đã sửa')
            ctx=edited[0]
            selected=choice_by_label['Dịch nghĩa']
            self.assertEqual(choose(ctx,selected),'Dịch nghĩa gốc')
            edited=edit(ctx,selected,'Bản dịch\nđã sửa')
            self.assertIn('Bản dịch\\nđã sửa',edited[6])
            ctx=edited[0]
            ctx=save(ctx)[0]
            expected=deepcopy(original)
            expected[0]['ten_bia']='Tên bia đã sửa'
            expected[0]['noi_dung'][1]['chuyen_muc'][2]['van_ban']='Bản dịch\nđã sửa'
            self.assertEqual(json.loads(source.read_text()),expected)
            self.assertEqual(ctx['active']['annotation_text'],'永寺樂')
            content_doc=json.loads((root/'out/.state/content.json').read_text())[0]
            self.assertEqual(content_doc['image'],'12306.png')
            self.assertEqual(content_doc['inscription_code'],'12306')
            self.assertEqual(content_doc['content']['Tên bia'],'Tên bia đã sửa')
            self.assertEqual(content_doc['content']['Địa điểm'],'Hà Nội')
            self.assertEqual(content_doc['content']['Niên đại'],'Cảnh Hưng')
            self.assertEqual(content_doc['content']['Dịch nghĩa'],'Bản dịch\nđã sửa')
            export=next(f for f in functions if f.__name__=='save_folder')
            payload=json.loads(export())
            self.assertEqual(payload['name'],'annotations.zip')
            self.assertTrue((root/'out/annotations.zip').is_file())
            with zipfile.ZipFile(BytesIO(base64.b64decode(payload['content']))) as bundle:
                self.assertNotIn('text_annotations.json',bundle.namelist())
                self.assertEqual(json.loads(bundle.read('inscription_content.json')),[content_doc])
            # A submitted path cannot edit unconfigured metadata, headings,
            # other faces, or other sections.
            for path in (['extra','keep'],['noi_dung',0,'chuyen_muc',0,'van_ban'],
                         ['noi_dung',1,'chuyen_muc',0,'tieu_de'],
                         ['noi_dung',1,'chuyen_muc',5,'van_ban']):
                with self.assertLogs('app',level='ERROR'):
                    rejected=edit(ctx,json.dumps(path),'Không được ghi')
                self.assertEqual(rejected[0]['active']['draft_content'],ctx['active']['draft_content'])
            self.assertEqual([field['title'] for field in content_fields(record,'12305')],[titles[0]])

    def test_next_saves_current_editor_and_stays_on_save_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            image=root/'12305.png';Image.new('RGB',(100,100),'white').save(image)
            source=root/'source.json'
            atomic_write(source,[{'noi_dung':[{'ky_hieu':'12305','chuyen_muc':[
                {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永'}]}]}])
            options=parser().parse_args(['--image-dir',str(root),'--source-json',str(source),
                                        '--output-dir',str(root/'out'),'--skip-detection'])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            advance_stream=next(f for f in functions if f.__name__=='next_with_progress')
            def advance(*args):
                return list(advance_stream(*args))[-1]
            opened=open_image(dict(active=new_state(),drafts={}),str(image))
            ctx=opened[0];path=opened[4]['choices'][0][1]
            with patch('annotation.workflow.save_source_content',side_effect=OSError('write failed')), self.assertLogs('app',level='ERROR'):
                failed=advance(ctx,path,'永\n寺')
            self.assertEqual(failed[0]['active']['current_step'],2)
            self.assertIn('write failed',failed[2]['value'])
            self.assertEqual(content_fields(failed[0]['active']['draft_content'],'12305')[0]['value'],'永\n寺')
            result=advance(failed[0],path,'永\n寺')
            self.assertEqual(result[0]['active']['current_step'],3)
            self.assertTrue(result[0]['active']['workflow']['content_verified'])
            self.assertEqual(json.loads(source.read_text())[0]['noi_dung'][0]['chuyen_muc'][0]['van_ban'],'永\n寺')
            saved=json.loads((root/'out/.state/content.json').read_text())
            self.assertEqual(saved[0]['content']['Nguyên văn chữ Hán Nôm'],'永\n寺')

    def test_skip_detection_never_calls_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            image=root/'12305.png';Image.new('RGB',(100,100),'white').save(image)
            source=root/'source.json'
            atomic_write(source,[{'noi_dung':[{'ky_hieu':'12305','chuyen_muc':[
                {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永'}]}]}])
            options=parser().parse_args(['--image-dir',str(root),'--source-json',str(source),
                                        '--output-dir',str(root/'out'),'--skip-detection'])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            on_action=next(f for f in functions if f.__name__=='on_action')
            def action(name):
                if name == 'next':
                    stream=next(f for f in functions if f.__name__=='next_with_progress')
                    return lambda ctx: list(stream(ctx))[-1]
                return next(f for f in functions if f.__name__=='<lambda>' and f.__defaults__==(name,))
            ctx=open_image(dict(active=new_state(),drafts={}),str(image))[0]
            ctx=action('save_content')(ctx)[0]
            with patch('annotation.workflow.detect') as detector:
                result=action('next')(ctx);ctx=result[0]
                self.assertEqual(ctx['active']['current_step'],3)
                self.assertFalse(result[2]['visible'])
                # Even an explicitly submitted canvas/API action cannot invoke the model.
                with self.assertLogs('app',level='ERROR'):
                    result=on_action(ctx,gr.EventData(None,dict(action='detect',payload={})))
                ctx=result[0]
                self.assertIn('Detection is disabled',result[2]['value'])
                active=ctx['active']
                ctx=on_action(ctx,gr.EventData(None,dict(
                    action='add',payload={'bbox':[0,0,10,10],
                                          'revision':active['revision'],
                                          'image':active['image']})))[0]
                ctx=action('next')(ctx)[0]
                self.assertEqual(ctx['active']['current_step'],4)
                self.assertEqual(ctx['active']['annotations'],{'1':'永'})
                ctx=action('next')(ctx)[0]
                self.assertEqual(ctx['active']['annotations'],{'1':'永'})
                detector.assert_not_called()

    def test_ui_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();images=root/'images';images.mkdir()
            path=images/'12305.png';Image.new('RGB',(100,100),'white').save(path)
            source=root/'source.json'
            atomic_write(source,[{'noi_dung':[{'ky_hieu':'12305','chuyen_muc':[{'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永寺樂'}]}]}])
            options=parser().parse_args(['--image-dir',str(images),'--source-json',str(source),'--output-dir',str(root/'out')])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            on_action=next(f for f in functions if f.__name__=='on_action')
            update_coordinates=next(f for f in functions if f.__name__=='update_coordinates')
            delete_selected=next(f for f in functions if f.__name__=='delete_selected')
            def board_action(ctx,name,payload):
                s=ctx['active']
                event=gr.EventData(None,dict(action=name,payload=dict(payload,revision=s['revision'],image=s['image'])))
                return on_action(ctx,event)
            result=open_image(dict(active=new_state(),drafts={}),str(path))
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],2)
            self.assertTrue(result[27]['visible'])
            self.assertTrue(result[40]['visible'])
            self.assertFalse(result[39]['visible'])
            lambdas=[f for f in functions if f.__name__=='<lambda>']
            def action(name):
                if name == 'next':
                    stream=next(f for f in functions if f.__name__=='next_with_progress')
                    return lambda ctx: list(stream(ctx))[-1]
                return next(f for f in lambdas if f.__defaults__==(name,))
            ctx=action('save_content')(ctx)[0]
            self.assertTrue(ctx['active']['workflow']['content_verified'])
            with self.assertLogs('app',level='ERROR'), patch('annotation.workflow.detect',side_effect=RuntimeError('fixture model unavailable')) as detector:
                stream=next(f for f in functions if f.__name__=='next_with_progress')(ctx)
                running=next(stream)
                self.assertEqual(running[0]['active']['current_step'],3)
                self.assertEqual(running[2]['value'],'Running detection…')
                detector.assert_not_called()
                result=next(stream)
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],3)
            self.assertFalse(result[27]['visible'])
            self.assertIn('fixture model unavailable',result[2]['value'])
            advance=next(f for f in functions if f.__name__=='next_with_progress')
            # Mounted coordinate controls submit placeholder values even when
            # no box exists. Next must report the actual count validation,
            # rather than treating those placeholders as a manual edit.
            with patch('annotation.workflow.detect',side_effect=RuntimeError('fixture model unavailable')):
                no_boxes=list(advance(
                    ctx,None,None,None,'','{}','intact',0,0,1,1,None))[-1]
            self.assertNotIn('Select a box and enter all four coordinates',
                             no_boxes[2]['value'])
            ctx=board_action(ctx,'add',{'bbox':[0,0,10,10]})[0]
            first_uid=next(iter(ctx['active']['regions']))
            ctx=board_action(ctx,'add',{
                'bbox':[20,0,30,10],
                'boxes':{first_uid:[2,2,12,12]},
                'active':first_uid,'selected':[first_uid],
            })[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[2,2,12,12])
            ctx=board_action(ctx,'add',{'bbox':[40,0,50,10]})[0]
            region_uids=list(ctx['active']['regions'])
            first_uid,deleted_uid=region_uids[0],region_uids[-1]
            live_boxes={
                uid:list(region['bbox'])
                for uid,region in ctx['active']['regions'].items()
            }
            live_boxes[first_uid]=[4,4,14,14]
            deleted_bbox=live_boxes[deleted_uid]
            delete_snapshot=json.dumps({
                'active':deleted_uid,'selected':[deleted_uid],'boxes':live_boxes,
            })
            ctx=delete_selected(ctx,delete_snapshot,*deleted_bbox)[0]
            self.assertNotIn(deleted_uid,ctx['active']['regions'])
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[4,4,14,14])
            # Restore the third region so the remainder of the full workflow
            # continues with one box per source character.
            ctx=board_action(ctx,'add',{'bbox':[40,0,50,10]})[0]
            first_uid=list(ctx['active']['regions'])[0]
            ctx=board_action(ctx,'commit_boxes',{
                'boxes':{first_uid:[1,1,11,11]},
                'active':first_uid,'selected':[first_uid],
            })[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[1,1,11,11])
            local_selection=json.dumps({'active':first_uid,'selected':[first_uid]})
            ctx=update_coordinates(ctx,local_selection,2,2,12,12)[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[2,2,12,12])
            # A first-time manual coordinate edit is a direct Next input; it
            # must not require Update coordinates or a Back/Next round trip.
            result=list(advance(
                ctx,None,None,None,'',local_selection,'intact',3,3,13,13,None))[-1]
            ctx=result[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[3,3,13,13])
            self.assertEqual(ctx['active']['current_step'],4)
            self.assertTrue(result[18]['visible'])
            self.assertIn('source-preview',result[8]['value']['markup'])
            self.assertIn('永',result[8]['value']['markup'])
            self.assertIn('stroke="#f4f4f5"',result[8]['value']['markup'])
            self.assertNotIn('stroke="#22c55e"',result[8]['value']['markup'])
            self.assertNotIn('stroke="#ef4444"',result[8]['value']['markup'])
            self.assertNotIn('status-legend',result[8]['value']['markup'])
            self.assertIn('data-box-id',result[8]['value']['markup'])
            self.assertNotIn('data-region-uid',result[8]['value']['markup'])
            region_uids=list(ctx['active']['regions'])
            first_damaged_uid,damaged_uid=region_uids[:2]
            # Reading order is edited as text-only cards and explicitly
            # committed with Apply Changes (or implicitly by Next).
            self.assertIn('class="order-chip',result[8]['value']['markup'])
            self.assertIn('class="order-chips"',result[8]['value']['markup'])
            self.assertIn('draggable="false"',result[8]['value']['markup'])
            self.assertIn('data-token-id=',result[8]['value']['markup'])
            self.assertNotIn('chip-id',result[8]['value']['markup'])
            mapping=dict(ctx['active']['annotations'])
            with self.assertLogs('app',level='ERROR'):
                rejected=board_action(ctx,'reorder_text',{'sequence':['永','寺','寺']})
            self.assertEqual(rejected[0]['active']['reading_order'],[1,2,3])
            apply_reading_order=next(
                f for f in functions if f.__name__=='apply_reading_order')
            local_order=json.dumps({'textSequence':['永','樂','寺']})
            ctx=apply_reading_order(rejected[0],local_order)[0]
            self.assertNotEqual(ctx['active']['annotations'],mapping)
            mapping=dict(ctx['active']['annotations'])
            self.assertEqual(mapping,{'1':'永','2':'樂','3':'寺'})
            reordered_markup=board_action(ctx,'select',{'id':1})[8]['value']['markup']
            # The cards expose only their text; Box IDs remain on the canvas.
            self.assertLess(reordered_markup.index('data-character="永"'),
                            reordered_markup.index('data-character="樂"'))
            self.assertLess(reordered_markup.index('data-character="樂"'),
                            reordered_markup.index('data-character="寺"'))
            self.assertNotIn('<span class="chip-id">',reordered_markup)
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],5)
            self.assertTrue(result[15]['visible'])
            self.assertIn('status-legend',result[8]['value']['markup'])
            self.assertIn('stroke="#22c55e"',result[8]['value']['markup'])
            first_damaged_box_id=ctx['active']['box_id_by_region'][first_damaged_uid]
            damaged_box_id=ctx['active']['box_id_by_region'][damaged_uid]
            # Each completed radio edit is persisted before moving to another
            # box. A lagging bridge must not undo it on Next.
            ctx=board_action(ctx,'status',{
                'id':first_damaged_box_id,'status':'damaged',
            })[0]
            local_selection=json.dumps({
                'active':damaged_box_id,'selected':[damaged_box_id],
                'statuses':{uid:'intact' for uid in region_uids},
            })
            result=list(advance(ctx,None,None,None,'',local_selection,'damaged'))[-1]
            ctx=result[0]
            self.assertEqual(ctx['active']['regions'][first_damaged_uid]['status'],'damaged')
            self.assertEqual(ctx['active']['regions'][damaged_uid]['status'],'damaged')
            self.assertEqual(ctx['active']['current_step'],6)
            self.assertTrue(result[21]['visible'])
            self.assertNotIn('data-image-resize-handle',result[8]['value']['markup'])
            # Typed crop coordinates are committed by Next without Apply crop.
            result=list(advance(
                ctx,None,None,None,'','{}','intact',None,None,None,None,
                json.dumps([5,10,95,70])))[-1]
            ctx=result[0]
            self.assertEqual(ctx['active']['annotations'],mapping)
            self.assertEqual(ctx['active']['crop'],[5,10,95,70])
            self.assertEqual(ctx['active']['current_step'],7)
            self.assertIn('viewBox="5 10 90 60"',result[8]['value']['markup'])
            self.assertIn('aspect-ratio:90/60',result[8]['value']['markup'])
            self.assertIn('cropped review',result[8]['value']['markup'])
            self.assertEqual(result[8]['value']['width'],90)
            self.assertEqual(result[8]['value']['height'],60)
            self.assertEqual(ctx['active']['reading_order'],[1,2,3])
            self.assertEqual(ctx['active']['bounding_boxes'][first_damaged_box_id]['status'],'damaged')
            self.assertEqual(ctx['active']['bounding_boxes'][damaged_box_id]['status'],'damaged')
            damaged_annotation=ctx['active']['annotations'][damaged_box_id]
            self.assertIn(f'{damaged_box_id} {damaged_annotation}',
                          result[8]['value']['markup'])
            self.assertIn(
                f'<title>{damaged_box_id} {damaged_annotation} · damaged</title>',
                result[8]['value']['markup'])
            self.assertNotIn('<table',result[8]['value']['markup'])
            result=action('save')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],1)
            self.assertFalse(ctx['active'].get('image'))
            self.assertTrue(result[39]['visible'])
            self.assertFalse(result[40]['visible'])
            self.assertFalse(result[41]['visible'])
            self.assertFalse(result[42]['visible'])
            self.assertTrue((root/'out/12305.json').exists())
            saved=json.loads((root/'out/12305.json').read_text())
            self.assertEqual(set(saved),{'image','bounding_boxes','annotations','reading_order','crop','image_resize'})
            self.assertEqual(saved['reading_order'],[1,2,3])
            self.assertEqual(saved['crop']['top_left'],[5,10])
            self.assertEqual(saved['image_resize'],{
                'source_size':[100,100], 'output_size':[100,100],
                'scale_x':1.0, 'scale_y':1.0,
            })
            export=next(f for f in functions if f.__name__=='save_folder')
            payload=json.loads(export())
            self.assertEqual(payload['name'],'annotations.zip')
            self.assertTrue((root/'out/annotations.zip').is_file())
            with zipfile.ZipFile(BytesIO(base64.b64decode(payload['content']))) as bundle:
                annotations=json.loads(bundle.read('text_annotations.json'))
                contents=json.loads(bundle.read('inscription_content.json'))
            self.assertEqual(annotations,[saved])
            self.assertEqual(contents[0]['image'],'12305.png')
            self.assertEqual(contents[0]['content']['Nguyên văn chữ Hán Nôm'],'永寺樂')
            # Reopening reads the durable annotation, starts at Content, and
            # marks detection as already loaded.
            restored=open_image(ctx,str(path))[0]
            self.assertEqual(restored['active']['current_step'],2)
            self.assertTrue(restored['active']['detection_loaded'])
            self.assertEqual(restored['active']['annotations'],{'1':'永','2':'樂','3':'寺'})
            reopened=action('save_content')(restored)[0]
            reopened=action('next')(reopened)[0]
            self.assertEqual(reopened['active']['current_step'],3)
            first_loaded=next(iter(reopened['active']['regions'].values()))['bbox']
            reopened_result=list(advance(
                reopened,None,None,None,'','{}','intact',*first_loaded,None))[-1]
            self.assertEqual(reopened_result[0]['active']['current_step'],4)
            self.assertNotIn('Select a box and enter all four coordinates',
                             reopened_result[2]['value'])
            reset_image=next(f for f in functions if f.__name__=='reset_image')
            unchanged=reset_image(restored,False)[0]
            self.assertTrue((root/'out/12305.json').exists())
            self.assertEqual(unchanged['active']['annotations'],{'1':'永','2':'樂','3':'寺'})
            reset=reset_image(restored,True)[0]
            self.assertEqual(reset['active']['current_step'],2)
            self.assertFalse(reset['active']['detection_loaded'])
            self.assertEqual(reset['active']['annotations'],{})
            self.assertFalse((root/'out/12305.json').exists())

    def test_ui_source_mismatch_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();image=root/'1.png'
            Image.new('RGB',(100,100),'white').save(image)
            source=root/'source.json'
            atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
                {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永寺'}]}]}])
            options=parser().parse_args(['--image-dir',str(root),'--source-json',str(source),
                                         '--output-dir',str(root/'out'),'--skip-detection'])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            on_action=next(f for f in functions if f.__name__=='on_action')
            confirm=next(f for f in functions if f.__name__=='confirm_source_mismatch')
            lambdas=[f for f in functions if f.__name__=='<lambda>']
            def action(name):
                if name=='next':
                    stream=next(f for f in functions if f.__name__=='next_with_progress')
                    return lambda ctx:list(stream(ctx))[-1]
                return next(f for f in lambdas if f.__defaults__==(name,))

            ctx=open_image(dict(active=new_state(),drafts={}),str(image))[0]
            ctx=action('save_content')(ctx)[0];ctx=action('next')(ctx)[0]
            active=ctx['active']
            result=on_action(ctx,gr.EventData(None,dict(
                action='add',payload={'bbox':[0,0,10,10],
                                      'revision':active['revision'],
                                      'image':active['image']})))
            ctx=result[0]
            self.assertIn('Difference (boxes − characters)',result[25])
            self.assertTrue(result[31]['visible'])
            self.assertTrue(result[34]['interactive'])
            rejected=confirm(ctx,'other','   ')
            self.assertIn('require a note',rejected[2]['value'])
            result=confirm(ctx,'other','source does not match the image')
            ctx=result[0]
            self.assertTrue(result[35]['visible'])
            self.assertIn('Source mismatch confirmed',result[25])
            result=action('next')(ctx);ctx=result[0]
            self.assertIn('mismatch confirmed',result[8]['value']['markup'])
            self.assertEqual(ctx['active']['current_step'],7)
            self.assertEqual(ctx['active']['annotations'],{})
            ctx=action('save')(ctx)[0]
            export=next(f for f in functions if f.__name__=='save_folder')
            payload=json.loads(export())
            with zipfile.ZipFile(BytesIO(base64.b64decode(payload['content']))) as bundle:
                self.assertIn('source_mismatches.json',bundle.namelist())
                self.assertNotIn('text_annotations.json',bundle.namelist())
                mismatch=json.loads(bundle.read('source_mismatches.json'))[0]
            self.assertNotIn('annotations',mismatch)
            self.assertEqual(set(mismatch),{
                'image','inscription_code','issue_type','note','bounding_boxes'})
            self.assertEqual(mismatch['bounding_boxes'],{'1':{'bbox':[0,0,10,10]}})


if __name__=='__main__':unittest.main()
