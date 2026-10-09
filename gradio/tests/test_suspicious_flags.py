"""Suspicious is a persisted box flag, independent of character token order."""
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.state import new_state, set_verified_content, initialize_alignment
from annotation.bbox import add_bbox, delete_bbox
from annotation.status import update_status, replace_statuses, validate_flags
from annotation.reading_order import update_text_sequence, suspicious_box_ids
from annotation.io import atomic_write, read_json, load_annotation
from annotation.workflow import Workflow
from ui.editor import snapshot

class SuspiciousFlags(unittest.TestCase):
    def state(self,text='永永寺',n=3):
        s=new_state();s.update(image='1.png',image_size=[100,100],current_step=4,image_url='image.jpg')
        set_verified_content(s,{},text)
        for x in range(n):add_bbox(s,[x*20,10,x*20+10,30])
        if n>len(text):s['source_mismatch']={'source_text':text,'source_character_count':len(text),
            'bounding_box_count':n,'issue_type':'missing_text','note':''}
        initialize_alignment(s)
        return s

    def test_defaults_combinations_and_validation(self):
        s=self.state();uid=s['region_uid_by_box_id']['1']
        self.assertFalse(s['regions'][uid]['suspicious'])
        update_status(s,uid,'damaged',unknown=True)
        update_status(s,uid,'damaged',suspicious=True)
        self.assertFalse(s['regions'][uid]['unknown'])
        update_status(s,uid,'intact',unavailable_font=True,expert_prediction=True)
        update_status(s,uid,'intact')
        self.assertTrue(all(s['regions'][uid][f] for f in ('suspicious','unavailable_font','expert_prediction')))
        update_status(s,uid,'damaged',unknown=True)
        self.assertTrue(s['regions'][uid]['unknown'])
        self.assertFalse(any(s['regions'][uid][f] for f in ('suspicious','unavailable_font','expert_prediction')))
        invalid=dict(s['regions'][uid],suspicious=True)
        with self.assertRaises(ValueError):validate_flags(invalid)
        for value in ('true',None,1):
            with self.assertRaises(ValueError):validate_flags(dict(s['regions'][uid],suspicious=value))
        missing=dict(s['regions'][uid]);del missing['suspicious']
        with self.assertRaises(ValueError):validate_flags(missing)
        statuses={uid:box['status'] for uid,box in s['regions'].items()}
        before=deepcopy(s)
        with self.assertRaises(ValueError):replace_statuses(s,statuses,suspiciouses={uid:'true'})
        self.assertEqual(s,before)

    def test_reordering_duplicate_characters_keeps_suspicious_on_box(self):
        s=self.state();uid=s['region_uid_by_box_id']['2']
        update_status(s,uid,'intact',suspicious=True)
        update_text_sequence(s,['寺','永','永'])
        self.assertEqual(suspicious_box_ids(s),['2'])
        self.assertTrue(s['regions'][uid]['suspicious'])
        for step in (4,7):
            s['current_step']=step;markup=snapshot(s)['markup']
            self.assertIn('data-suspicious="true"',markup)
            self.assertIn('suspicious-region',markup)
            self.assertNotIn('suspiciousTokenIds',snapshot(s))
        delete_bbox(s,uid)
        self.assertEqual(suspicious_box_ids(s),[])

    def test_assigning_miss_clears_flag_on_that_box(self):
        s=self.state('永寺',3);uid=s['region_uid_by_box_id']['1']
        update_status(s,uid,'intact',suspicious=True)
        update_text_sequence(s,['MISS','永','寺'])
        self.assertFalse(s['regions'][uid]['suspicious'])
        self.assertFalse(s['bounding_boxes']['1']['suspicious'])

    def test_full_save_load_back_next_and_no_sidecar(self):
        for source_text,issue,n in [('永寺',None,2),('永寺','missing_text',3),('永寺樂','extra_text',2)]:
            with self.subTest(issue=issue),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);image=root/'1.png';Image.new('RGB',(100,100)).save(image)
                source=root/'source.json';atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
                    {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':source_text}]}]}])
                engine=Workflow(SimpleNamespace(output_dir=root/'out',source_json=source,
                    content_titles=('Nguyên văn chữ Hán Nôm',),annotation_title='Nguyên văn chữ Hán Nôm'))
                s=engine.apply(engine.open_image(image),'next')
                for x in range(n):s=engine.apply(s,'add',{'bbox':[x*20,10,x*20+10,30]})
                if issue:s=engine.apply(s,'confirm_source_mismatch',{'issue_type':issue,'note':''})
                boxes=deepcopy(s['regions'])
                for i,box in enumerate(boxes.values(),1):box['order']=i
                s=engine.apply(s,'next',{'boxes':boxes})
                s=engine.apply(s,'suspicious',{'id':'1','value':True})
                if issue is None:
                    import gradio as gr
                    from app import create_app, parser
                    options=parser().parse_args(['--image-dir',str(root),'--source-json',str(source),
                        '--output-dir',str(root/'out'),'--skip-detection'])
                    app=create_app(options)
                    callback=next(f for f in app.fns.values() if f.fn and f.fn.__name__=='on_action')
                    result=callback.fn(dict(active=s,drafts={}),gr.EventData(None,{
                        'action':'suspicious','payload':{'id':'1','value':False}}))
                    self.assertEqual(len(result),len(callback.outputs))
                    self.assertFalse(result[0]['active']['bounding_boxes']['1']['suspicious'])
                    self.assertNotIn('suspicious-preview',str(app.get_config_file()))
                    control=next(c for c in app.get_config_file()['components']
                                 if c['props'].get('elem_id')=='suspicious-toggle')
                    self.assertEqual(control['type'],'radio')
                    self.assertEqual(control['props']['choices'],[('False','False'),('True','True')])
                if issue=='missing_text':
                    with self.assertRaises(ValueError):engine.apply(s,'suspicious',{'id':'3','value':True})
                if issue=='extra_text':
                    with self.assertRaises(ValueError):engine.apply(s,'suspicious',{'id':'3','value':True})
                for _ in range(3):s=engine.apply(s,'next')
                s=engine.apply(s,'save')
                output=root/'out';path=output/('source_mismatches/1.json' if issue else '1.json')
                doc=read_json(path)
                self.assertTrue(doc['bounding_boxes']['1']['suspicious'])
                self.assertTrue(all(type(box['suspicious']) is bool for box in doc['bounding_boxes'].values()))
                self.assertEqual(doc.get('issue_type'),[issue] if issue else None)
                self.assertFalse((output/'suspicious_details.json').exists())
                s=engine.apply(engine.open_image(image),'next')
                boxes=deepcopy(s['regions'])
                for box_id,uid in s['region_uid_by_box_id'].items():boxes[uid]['order']=int(box_id)
                s=engine.apply(s,'next',{'boxes':boxes})
                self.assertTrue(s['bounding_boxes']['1']['suspicious'])
                s=engine.apply(s,'back');s=engine.apply(s,'next',{'boxes':deepcopy(s['regions'])})
                self.assertTrue(s['bounding_boxes']['1']['suspicious'])
                s=engine.apply(s,'suspicious',{'id':'1','value':False})
                for _ in range(3):s=engine.apply(s,'next')
                engine.apply(s,'save')
                self.assertFalse(engine.open_image(image)['bounding_boxes']['1']['suspicious'])
                if issue is None:
                    del doc['bounding_boxes']['1']['suspicious'];atomic_write(root/'invalid.json',doc)
                    with self.assertRaisesRegex(ValueError,'suspicious'):load_annotation(root/'invalid.json','1.png',[100,100])

if __name__=='__main__':unittest.main()
