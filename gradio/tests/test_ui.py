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
from ui.presentation import SECTION_LABELS
from PIL import Image


class GradioCallbacks(unittest.TestCase):
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
            self.assertEqual([entry['tieu_de'] for entry in result[6]],titles)
            self.assertNotIn('ten_bia',json.dumps(result[6]))
            selected=choices[2][1]
            self.assertEqual(choose(ctx,selected),'Dịch nghĩa gốc')
            ctx=edit(ctx,selected,'Bản dịch đã sửa')[0]
            ctx=save(ctx)[0]
            expected=deepcopy(original)
            expected[0]['noi_dung'][1]['chuyen_muc'][2]['van_ban']='Bản dịch đã sửa'
            self.assertEqual(json.loads(source.read_text()),expected)
            self.assertEqual(ctx['active']['annotation_text'],'永寺樂')
            content_doc=json.loads((root/'out/.state/content.json').read_text())[0]
            self.assertEqual(content_doc['image'],'12306.png')
            self.assertEqual(content_doc['inscription_code'],'12306')
            self.assertEqual(content_doc['content']['Dịch nghĩa'],'Bản dịch đã sửa')
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
                ctx=action('add')(ctx,None,0,0,10,10)[0]
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
            def board_action(ctx,name,payload):
                s=ctx['active']
                event=gr.EventData(None,dict(action=name,payload=dict(payload,revision=s['revision'],image=s['image'])))
                return on_action(ctx,event)
            result=open_image(dict(active=new_state(),drafts={}),str(path))
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],2)
            lambdas=[f for f in functions if f.__name__=='<lambda>']
            def action(name):
                return next(f for f in lambdas if f.__defaults__==(name,))
            ctx=action('save_content')(ctx)[0]
            self.assertTrue(ctx['active']['workflow']['content_verified'])
            with self.assertLogs('app',level='ERROR'), patch('annotation.workflow.detect',side_effect=RuntimeError('fixture model unavailable')):
                result=action('next')(ctx)
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],3)
            self.assertIn('fixture model unavailable',result[2]['value'])
            add=action('add')
            for x in (0,20,40):ctx=add(ctx,None,x,0,x+10,10)[0]
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],4)
            self.assertTrue(result[15]['visible'])
            self.assertNotIn('source-preview',result[8]['value']['markup'])
            self.assertNotIn('data-card',result[8]['value']['markup'])
            self.assertNotIn('永',result[8]['value']['markup'])
            self.assertNotIn('data-box-id',result[8]['value']['markup'])
            damaged_uid=list(ctx['active']['regions'])[1]
            ctx=board_action(ctx,'select',{'uid':damaged_uid})[0]
            ctx=board_action(ctx,'status',{'uid':damaged_uid,'status':'damaged'})[0]
            self.assertEqual(ctx['active']['regions'][damaged_uid]['status'],'damaged')
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],5)
            self.assertTrue(result[18]['visible'])
            self.assertIn('draggable="true"',result[8]['value']['markup'])
            mapping=dict(ctx['active']['annotations'])
            with self.assertLogs('app',level='ERROR'):
                rejected=board_action(ctx,'reorder',{'order':[1,3,3]})
            self.assertEqual(rejected[0]['active']['reading_order'],[1,2,3])
            ctx=board_action(rejected[0],'reorder',{'order':[1,3,2]})[0]
            self.assertEqual(ctx['active']['annotations'],mapping)
            result=action('next')(ctx);ctx=result[0]
            self.assertEqual(ctx['active']['current_step'],6)
            self.assertTrue(result[21]['visible'])
            ctx=board_action(ctx,'crop',{'bbox':[5,10,95,90]})[0]
            self.assertEqual(ctx['active']['annotations'],mapping)
            ctx=action('next')(ctx)[0]
            self.assertEqual(ctx['active']['current_step'],7)
            self.assertEqual(ctx['active']['reading_order'],[1,3,2])
            ctx=action('save')(ctx)[0]
            self.assertTrue(ctx['active']['saved'])
            self.assertTrue((root/'out/12305.json').exists())
            saved=json.loads((root/'out/12305.json').read_text())
            self.assertEqual(set(saved),{'image','bounding_boxes','annotations','reading_order','crop'})
            self.assertEqual(saved['reading_order'],[1,3,2])
            self.assertEqual(saved['crop']['top_left'],[5,10])
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
            self.assertEqual(reset['active']['annotations'],{'1':'永','2':'寺','3':'樂'})


if __name__=='__main__':unittest.main()
