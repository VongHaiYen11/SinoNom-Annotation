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
from annotation.state import new_state
from annotation.io import atomic_write
from annotation.text_extraction import content_fields
from annotation.workflow import Workflow
from ui.presentation import SECTION_LABELS, header
from PIL import Image


class GradioCallbacks(unittest.TestCase):
    def test_canvas_script_keeps_selection_and_geometry_local_until_next(self):
        script=(Path(__file__).resolve().parents[1]/'ui/assets/editor.js').read_text()
        self.assertNotIn("send('select'",script)
        self.assertNotIn("send('commit_boxes'",script)
        self.assertIn("send('status'",script)
        self.assertIn('boxes: Object.fromEntries',script)
        self.assertIn("kind:'marquee'",script)
        self.assertIn('selectedIds = new Set()',script)

    def test_compact_header_has_all_steps_and_no_draft_status(self):
        state=new_state();state.update(image='12305.jpg',current_step=2)
        markup=header(state)
        self.assertNotIn('Draft',markup)
        self.assertNotIn('save-indicator',markup)
        self.assertIn('<span class="brand-mark" aria-hidden="true">文</span>',markup)
        self.assertEqual(markup.count('class="stepper-item'),7)
        self.assertEqual(markup.count('class="stepper-label"'),7)
        self.assertIn('aria-current="step"',markup)
        for label in ('Image','Content','Bounding Boxes','Status','Reading Order','Crop','Review'):
            self.assertIn(f'>{label}</span>',markup)

    def test_sidebar_has_bounded_scroll_and_aligned_action_controls(self):
        css=(Path(__file__).resolve().parents[1]/'ui/assets/workbench.css').read_text()
        self.assertIn('#header-stack {',css)
        self.assertIn('#topbar {',css)
        self.assertIn('#workflow-chrome {',css)
        self.assertIn('flex: 0 0 auto !important',css)
        self.assertIn('grid-template-rows: auto auto auto',css)
        self.assertIn('min-height: 100dvh',css)
        self.assertIn('overflow: visible',css)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))',css)
        self.assertIn('#content-image-preview .preview-open {',css)
        self.assertIn('white-space: nowrap',css)
        self.assertIn('#confirm-source-mismatch',css)
        self.assertIn('justify-content: center',css)

    def test_cli_paths_override_config_and_missing_paths_use_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            config=root/'config.json'
            config.write_text(json.dumps({
                'paths': {'output_json': 'source.json'},
                'gradio': {'image_dir': 'images', 'output_dir': 'annotations'},
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
            resolve_app_paths(explicit)
            self.assertEqual(explicit.source_json,'source.json')

    def test_cli_lets_gradio_choose_an_available_port_by_default(self):
        self.assertIsNone(parser().parse_args([]).port)
        self.assertEqual(parser().parse_args(['--port','7861']).port,7861)

    def test_content_editor_only_selected_face_sections(self):
        titles=['Nguyên văn chữ Hán Nôm','Phiên âm Hán Việt','Dịch nghĩa','Toát yếu','Chú thích']
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            image=root/'12306.png';Image.new('RGB',(100,100),'white').save(image)
            source=root/'source.json'
            record={'ten_bia':'Giữ tên bia','extra':{'keep':42},'noi_dung':[
                {'ky_hieu':'12305','chuyen_muc':[{'tieu_de':titles[0],'van_ban':'文'}]},
                {'ky_hieu':'12306','chuyen_muc':[
                    {'tieu_de':title,'van_ban':'永寺樂' if title==titles[0] else title+' gốc','extra':'giữ nguyên'}
                    for title in reversed(titles)] + [{'tieu_de':'Mục khác','van_ban':'Giữ nguyên mục khác'}]}]}
            original=[record,{'noi_dung':[],'extra':'record khác'}]
            atomic_write(source,original)
            options=parser().parse_args(['--image-dir',str(root),'--source-json',str(source),
                                        '--output-dir',str(root/'out'),'--skip-detection'])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            choose=next(f for f in functions if f.__name__=='choose_field')
            edit=next(f for f in functions if f.__name__=='apply_content_field')
            save=next(f for f in functions if f.__name__=='<lambda>' and f.__defaults__==('save_content',))
            result=open_image(dict(active=new_state(),drafts={}),str(image))
            ctx=result[0];choices=result[4]['choices']
            self.assertEqual([label for label,_ in choices],[SECTION_LABELS[t] for t in titles])
            self.assertEqual(result[5],'永寺樂')
            preview=json.loads(result[6])
            self.assertEqual([entry['tieu_de'] for entry in preview],titles)
            self.assertNotIn('ten_bia',result[6])
            selected=choices[2][1]
            self.assertEqual(choose(ctx,selected),'Dịch nghĩa gốc')
            edited=edit(ctx,selected,'Bản dịch\nđã sửa')
            self.assertIn('Bản dịch\\nđã sửa',edited[6])
            ctx=edited[0]
            ctx=save(ctx)[0]
            expected=deepcopy(original)
            expected[0]['noi_dung'][1]['chuyen_muc'][2]['van_ban']='Bản dịch\nđã sửa'
            self.assertEqual(json.loads(source.read_text()),expected)
            self.assertEqual(ctx['active']['annotation_text'],'永寺樂')
            content_doc=json.loads((root/'out/.state/content.json').read_text())[0]
            self.assertEqual(content_doc['image'],'12306.png')
            self.assertEqual(content_doc['inscription_code'],'12306')
            self.assertEqual(content_doc['content']['Dịch nghĩa'],'Bản dịch\nđã sửa')
            export=next(f for f in functions if f.__name__=='save_folder')
            payload=json.loads(export())
            self.assertEqual(payload['name'],'annotations.zip')
            self.assertTrue((root/'out/annotations.zip').is_file())
            with zipfile.ZipFile(BytesIO(base64.b64decode(payload['content']))) as bundle:
                self.assertNotIn('text_annotations.json',bundle.namelist())
                self.assertEqual(json.loads(bundle.read('inscription_content.json')),[content_doc])
            # A submitted path cannot edit metadata, headings, other faces, or other sections.
            for path in (['ten_bia'],['noi_dung',0,'chuyen_muc',0,'van_ban'],
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
                self.assertEqual(ctx['active']['annotations'],{})
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
            def board_action(ctx,name,payload):
                s=ctx['active']
                event=gr.EventData(None,dict(action=name,payload=dict(payload,revision=s['revision'],image=s['image'])))
                return on_action(ctx,event)
            result=open_image(dict(active=new_state(),drafts={}),str(path))
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],2)
            self.assertTrue(result[27]['visible'])
            self.assertEqual(result[-2],ctx['active']['image_url'])
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
            for x in (0,20,40):
                ctx=board_action(ctx,'add',{'bbox':[x,0,x+10,10]})[0]
            first_uid=list(ctx['active']['regions'])[0]
            ctx=board_action(ctx,'commit_boxes',{
                'boxes':{first_uid:[1,1,11,11]},
                'active':first_uid,'selected':[first_uid],
            })[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[1,1,11,11])
            local_selection=json.dumps({'active':first_uid,'selected':[first_uid]})
            ctx=update_coordinates(ctx,local_selection,2,2,12,12)[0]
            self.assertEqual(ctx['active']['regions'][first_uid]['bbox'],[2,2,12,12])
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],4)
            self.assertTrue(result[15]['visible'])
            self.assertNotIn('source-preview',result[8]['value']['markup'])
            self.assertNotIn('data-card',result[8]['value']['markup'])
            self.assertNotIn('永',result[8]['value']['markup'])
            self.assertIn('data-box-id',result[8]['value']['markup'])
            self.assertIn('data-region-uid',result[8]['value']['markup'])
            region_uids=list(ctx['active']['regions'])
            first_damaged_uid,damaged_uid=region_uids[:2]
            # Each completed radio edit is persisted before moving to another
            # region. A lagging bridge must not be allowed to undo it on Next.
            ctx=board_action(ctx,'status',{
                'id':first_damaged_uid,'status':'damaged',
            })[0]
            local_selection=json.dumps({
                'active':damaged_uid,'selected':[damaged_uid],
                # Simulate a bridge update arriving one tick behind the radio.
                'statuses':{uid:'intact' for uid in region_uids},
            })
            advance=next(f for f in functions if f.__name__=='next_with_progress')
            result=list(advance(ctx,None,None,None,'',local_selection,'damaged'))[-1]
            ctx=result[0]
            self.assertEqual(ctx['active']['regions'][first_damaged_uid]['status'],'damaged')
            self.assertEqual(ctx['active']['regions'][damaged_uid]['status'],'damaged')
            self.assertEqual(ctx['active']['current_step'],5)
            # Reading order is edited on fixed Box ID slots and explicitly
            # committed with Apply Changes (or implicitly by Next).
            self.assertTrue(result[18]['visible'])
            self.assertIn('draggable="true"',result[8]['value']['markup'])
            mapping=dict(ctx['active']['annotations'])
            with self.assertLogs('app',level='ERROR'):
                rejected=board_action(ctx,'reorder',{'order':[1,3,3]})
            self.assertEqual(rejected[0]['active']['reading_order'],[1,2,3])
            apply_reading_order=next(
                f for f in functions if f.__name__=='apply_reading_order')
            local_order=json.dumps({'readingOrder':[1,3,2]})
            ctx=apply_reading_order(rejected[0],local_order)[0]
            self.assertNotEqual(ctx['active']['annotations'],mapping)
            mapping=dict(ctx['active']['annotations'])
            self.assertEqual(mapping,{'1':'永','3':'寺','2':'樂'})
            reordered_markup=board_action(ctx,'select',{'id':1})[8]['value']['markup']
            # Box slots remain in physical ID order even though their assigned
            # annotations now follow reading order [1, 3, 2].
            card_marker=lambda box_id:f'data-card="1" data-box-id="{box_id}"'
            self.assertLess(reordered_markup.index(card_marker(1)),
                            reordered_markup.index(card_marker(2)))
            self.assertLess(reordered_markup.index(card_marker(2)),
                            reordered_markup.index(card_marker(3)))
            self.assertIn('Box 2: 樂',reordered_markup)
            self.assertIn('Box 3: 寺',reordered_markup)
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],6)
            self.assertTrue(result[21]['visible'])
            self.assertNotIn('data-image-resize-handle',result[8]['value']['markup'])
            ctx=board_action(ctx,'crop',{'bbox':[5,10,95,70]})[0]
            self.assertEqual(ctx['active']['annotations'],mapping)
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],7)
            self.assertEqual(ctx['active']['reading_order'],[1,3,2])
            damaged_box_id=ctx['active']['box_id_by_region'][damaged_uid]
            first_damaged_box_id=ctx['active']['box_id_by_region'][first_damaged_uid]
            self.assertEqual(ctx['active']['bounding_boxes'][first_damaged_box_id]['status'],'damaged')
            self.assertEqual(ctx['active']['bounding_boxes'][damaged_box_id]['status'],'damaged')
            damaged_annotation=ctx['active']['annotations'][damaged_box_id]
            self.assertIn(f'{damaged_box_id} {damaged_annotation}',
                          result[8]['value']['markup'])
            self.assertIn(
                f'<title>{damaged_box_id} {damaged_annotation} · damaged</title>',
                result[8]['value']['markup'])
            self.assertNotIn('<table',result[8]['value']['markup'])
            ctx=action('save')(ctx)[0]
            self.assertTrue(ctx['active']['saved'])
            self.assertTrue((root/'out/12305.json').exists())
            saved=json.loads((root/'out/12305.json').read_text())
            self.assertEqual(set(saved),{'image','bounding_boxes','annotations','reading_order','crop','image_resize'})
            self.assertEqual(saved['reading_order'],[1,3,2])
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
            # Session switching must preserve drafts, while reset reloads saved data.
            restored=open_image(ctx,str(path))[0]
            self.assertEqual(restored['active']['current_step'],7)
            reset=open_image(ctx,str(path),True)[0]
            self.assertEqual(reset['active']['current_step'],2)
            self.assertEqual(reset['active']['annotations'],{'1':'永','3':'寺','2':'樂'})

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
            result=confirm(ctx,'wrong_source_content','source does not match the image')
            ctx=result[0]
            self.assertTrue(result[35]['visible'])
            self.assertIn('Source mismatch confirmed',result[25])
            ctx=action('next')(ctx)[0]
            result=action('next')(ctx);ctx=result[0]
            self.assertIn('mismatch confirmed',result[8]['value']['markup'])
            ctx=action('next')(ctx)[0];ctx=action('next')(ctx)[0]
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
            self.assertEqual(mismatch['bounding_box_count'],1)


if __name__=='__main__':unittest.main()
