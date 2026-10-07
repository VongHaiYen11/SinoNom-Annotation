"""New annotation schema, flag transitions, overlays and committed exports."""
import json
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.bbox import add_bbox, sync_draft_boxes
from annotation.state import new_state, set_verified_content, initialize_alignment
from annotation.status import FLAGS, update_status, replace_statuses, confirm_status
from annotation.io import atomic_write, load_annotation, read_json
from annotation.export import collect_annotations, collect_source_mismatches, save_export_archive
from annotation.workflow import Workflow
from ui.editor import snapshot, review_result_text


class StatusFlags(unittest.TestCase):
    def state(self):
        s = new_state()
        s.update(image='1.png', image_size=[100,100], current_step=4, image_url='image.jpg')
        set_verified_content(s, {}, '永寺')
        for x in (10,40):
            add_bbox(s, [x,10,x+20,30])
        initialize_alignment(s)
        return s

    def test_defaults_exclusion_and_intact(self):
        s = self.state(); uid = s['region_uid_by_box_id']['1']
        self.assertTrue(all(s['regions'][uid][flag] is False for flag in FLAGS))
        update_status(s,uid,'intact',unavailable_font=True)
        update_status(s,uid,'intact',expert_prediction=True)
        self.assertEqual(s['regions'][uid]['status'],'damaged')
        update_status(s,uid,'intact')
        self.assertTrue(s['regions'][uid]['expert_prediction'])
        self.assertTrue(s['regions'][uid]['unavailable_font'])
        update_status(s,uid,'damaged',unknown=True)
        self.assertTrue(s['regions'][uid]['unknown'])
        self.assertFalse(s['regions'][uid]['expert_prediction'])
        self.assertFalse(s['regions'][uid]['unavailable_font'])
        update_status(s,uid,'damaged',unavailable_font=True)
        self.assertFalse(s['regions'][uid]['unknown'])
        update_status(s,uid,'damaged',unknown=True)
        update_status(s,uid,'intact')
        self.assertFalse(s['regions'][uid]['unknown'])

    def test_complete_snapshot_preserves_intact_after_expert_toggle(self):
        s=self.state();uid=s['region_uid_by_box_id']['1']
        statuses={u:'intact' for u in s['regions']}
        experts={u:u==uid for u in s['regions']}
        replace_statuses(s,statuses,expert_predictions=experts)
        confirm_status(s)
        self.assertEqual(s['bounding_boxes']['1']['status'],'intact')
        self.assertTrue(s['bounding_boxes']['1']['expert_prediction'])
        before=deepcopy(s)
        with self.assertRaises(ValueError):
            replace_statuses(s,statuses,unavailable_fonts={uid:'true'})
        self.assertEqual(s,before)

    def overlay(self,s,step):
        s['current_step']=step
        markup=snapshot(s)['markup']
        start=markup.index('<svg class="annotation-canvas"');end=markup.index('</svg>',start)+6
        svg=ET.fromstring(markup[start:end]);ns={'svg':''}
        return svg.find(".//svg:g[@data-box-id='1']",ns), ns

    def test_python_overlay_colors_and_marks(self):
        for step in (4,7):
            for font,expert,unknown,expected in (
                (False,False,False,('#22c55e','#ffffff')),
                (True,False,False,('#22c55e','#ec4899')),
                (False,True,False,('#facc15','#facc15')),
                (True,True,False,('#facc15','#ec4899')),
                (False,False,True,('#ef4444','#ffffff'))):
                s=self.state();uid=s['region_uid_by_box_id']['1']
                s['regions'][uid].update(status='damaged' if unknown else 'intact',
                    unknown=unknown,unavailable_font=font,expert_prediction=expert)
                confirm_status(s)
                group,ns=self.overlay(s,step)
                rect=group.find('svg:rect',ns)
                label=group.find("svg:text[@data-box-order-label='1']",ns)
                self.assertEqual((rect.get('stroke'),label.get('fill')),expected)
                mark=group.find("svg:text[@data-unknown-mark='1']",ns)
                self.assertEqual(mark is not None,unknown)
                if unknown:
                    self.assertEqual((mark.text,mark.get('fill')),('?','#ef4444'))
                    self.assertEqual(mark.get('font-weight'),'700')
                    self.assertEqual(float(mark.get('font-size')),float(rect.get('width'))*0.80)
                if font:self.assertEqual((rect.get('fill'),rect.get('fill-opacity')),('#ec4899','.20'))

    def test_review_crop_resize_preserves_visuals_and_scales_question_mark(self):
        s=self.state();uid=s['region_uid_by_box_id']['1']
        # A reopened crop may have non-uniform image scale factors.
        s.update(crop=[5,5,95,95], loaded_crop_source=[5,5,95,95],
                 loaded_crop_scaled=[2,1,48,24], resized_image_size=[50,25])
        for font,expert,unknown in ((True,False,False),(True,True,False),(False,False,True)):
            s['regions'][uid].update(status='damaged',unknown=unknown,
                unavailable_font=font,expert_prediction=expert)
            confirm_status(s)
            group,ns=self.overlay(s,7)
            rect=group.find('svg:rect',ns)
            self.assertEqual(float(rect.get('width')),10)
            self.assertEqual(float(rect.get('height')),5)
            if font:
                self.assertEqual((rect.get('fill'),rect.get('fill-opacity')),('#ec4899','.20'))
            if expert:self.assertEqual(rect.get('stroke'),'#facc15')
            mark=group.find("svg:text[@data-unknown-mark='1']",ns)
            if unknown:
                self.assertEqual(float(mark.get('font-size')),4)
                self.assertEqual(float(mark.get('x')),float(rect.get('x'))+5)
                self.assertEqual(float(mark.get('y')),float(rect.get('y'))+2.5)
                self.assertEqual(mark.get('font-weight'),'700')

    def test_review_miss_display_is_escaped_and_preserves_annotations(self):
        s=self.state()
        cases = [(['MISS','MISS'],'<miss> <miss>'),
                 (['永','MISS'],'永<miss>'),
                 (['MISS','寺'],'<miss>寺'),
                 (['永','寺'],'永寺')]
        for tokens,expected in cases:
            s['annotations']=dict(zip(('1','2'),tokens))
            original=deepcopy(s['annotations'])
            self.assertEqual(review_result_text(s),expected)
            s['current_step']=7
            markup=snapshot(s)['markup']
            import html
            self.assertIn('<p>'+html.escape(expected)+'</p>',markup)
            self.assertEqual(s['annotations'],original)
        s['annotations']={'1':'MISS','2':'MISS','3':'永','4':'MISS','5':'MISS'}
        s['bounding_boxes']['3']=deepcopy(s['bounding_boxes']['1'])
        s['bounding_boxes']['4']=deepcopy(s['bounding_boxes']['1'])
        s['bounding_boxes']['5']=deepcopy(s['bounding_boxes']['1'])
        s['reading_order']=[1,2,3,4,5]
        self.assertEqual(review_result_text(s),'<miss> <miss>永<miss> <miss>')

    def test_miss_clears_all_character_flags(self):
        s=self.state();uid=s['region_uid_by_box_id']['1']
        s['annotations']['1']='MISS'
        update_status(s,uid,'damaged',unavailable_font=True,expert_prediction=True)
        self.assertTrue(all(not s['regions'][uid][flag] for flag in FLAGS))
        group,ns=self.overlay(s,4)
        self.assertIsNotNone(group.find("svg:g[@data-miss-mark='1']",ns))
        self.assertIsNone(group.find("svg:text[@data-unknown-mark='1']",ns))

    def test_draft_geometry_and_alignment_preserve_flags(self):
        s=self.state();uid=s['region_uid_by_box_id']['1']
        update_status(s,uid,'intact',unavailable_font=True,expert_prediction=True)
        boxes=deepcopy(s['regions'])
        boxes[uid]['bbox']=[11,11,31,31]
        for index,u in enumerate(reversed(list(boxes)),1):boxes[u]['order']=index
        sync_draft_boxes(s,{'boxes':boxes})
        box_id=s['box_id_by_region'][uid]
        self.assertTrue(s['bounding_boxes'][box_id]['unavailable_font'])
        self.assertTrue(s['bounding_boxes'][box_id]['expert_prediction'])
        self.assertEqual(s['bounding_boxes'][box_id]['bbox'],[11,11,31,31])

    def test_workflow_save_reopen_export_normal_and_missing_extra(self):
        for text,issue in [('永寺',None),('永','missing_text'),('永寺樂','extra_text')]:
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);image=root/'1.png';Image.new('RGB',(100,100)).save(image)
                source=root/'source.json';atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
                    {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':text}]}]}])
                engine=Workflow(SimpleNamespace(output_dir=root/'out',source_json=source,
                    content_titles=('Nguyên văn chữ Hán Nôm',),annotation_title='Nguyên văn chữ Hán Nôm'))
                s=engine.apply(engine.open_image(image),'save_content');s=engine.apply(s,'next')
                for x in (10,40):s=engine.apply(s,'add',{'bbox':[x,10,x+20,30]})
                if issue:s=engine.apply(s,'confirm_source_mismatch',{'issue_type':issue,'note':''})
                boxes=deepcopy(s['regions'])
                for index,box in enumerate(boxes.values(),1):box['order']=index
                s=engine.apply(s,'next',{'boxes':boxes})
                s=engine.apply(s,'status',{'id':'1','status':'intact','unavailable_font':True,'expert_prediction':True})
                s=engine.apply(s,'status',{'id':'1','status':'intact'})
                for _ in range(3):s=engine.apply(s,'next')
                s=engine.apply(s,'save')
                reopened=engine.open_image(image)
                box=reopened['bounding_boxes']['1']
                self.assertEqual((box['status'],box['unavailable_font'],box['expert_prediction']),('intact',True,True))
                docs=(collect_source_mismatches([image],root/'out') if issue else collect_annotations([image],root/'out'))
                self.assertEqual(docs[0]['bounding_boxes']['1'],box)
                if not issue:
                    doc=read_json(root/'out/1.json');del doc['bounding_boxes']['1']['unavailable_font']
                    atomic_write(root/'invalid.json',doc)
                    with self.assertRaisesRegex(ValueError,'unavailable_font'):
                        load_annotation(root/'invalid.json','1.png',[100,100])

    def test_reopened_missing_alignment_survives_frontend_box_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'1.png';Image.new('RGB',(100,100)).save(image)
            source=root/'source.json';atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
                {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永寺'}]}]}])
            engine=Workflow(SimpleNamespace(output_dir=root/'out',source_json=source,
                content_titles=('Nguyên văn chữ Hán Nôm',),annotation_title='Nguyên văn chữ Hán Nôm'))
            s=engine.apply(engine.open_image(image),'next')
            for x in (0,15,30,45,60):s=engine.apply(s,'add',{'bbox':[x,10,x+10,30]})
            s=engine.apply(s,'confirm_source_mismatch',{'issue_type':'missing_text','note':''})
            boxes=deepcopy(s['regions'])
            for index,box in enumerate(boxes.values(),1):box['order']=index
            s=engine.apply(s,'next',{'boxes':boxes})
            expected=['MISS','寺','MISS','永','MISS']
            s=engine.apply(s,'reorder_text',{'sequence':expected})
            for _ in range(3):s=engine.apply(s,'next')
            s=engine.apply(s,'save')
            reopened=engine.open_image(image)
            self.assertEqual(reopened['text_sequence'],expected)
            reopened=engine.apply(reopened,'next')
            self.assertEqual(reopened['text_sequence'],expected)
            boxes=deepcopy(reopened['regions'])
            for box_id,uid in reopened['region_uid_by_box_id'].items():boxes[uid]['order']=int(box_id)
            reopened=engine.apply(reopened,'next',{'boxes':boxes})
            self.assertEqual(reopened['text_sequence'],expected)
            self.assertEqual([reopened['annotations'][str(i)] for i in range(1,6)],expected)
            markup=snapshot(reopened)['markup']
            import re,html
            chips=re.findall(r'data-character="([^"]*)"',markup)
            self.assertEqual([html.unescape(value) for value in chips],expected)
            # Back/Next with a geometry edit must also keep the slot assignment.
            reopened=engine.apply(reopened,'back')
            boxes=deepcopy(reopened['regions'])
            for uid,box in boxes.items():box['bbox'][1]+=1;box['bbox'][3]+=1
            reopened=engine.apply(reopened,'next',{'boxes':boxes})
            self.assertEqual(reopened['text_sequence'],expected)
            for _ in range(3):reopened=engine.apply(reopened,'next')
            reopened=engine.apply(reopened,'save')
            self.assertEqual(engine.open_image(image)['text_sequence'],expected)
            # Reversing spatial slot order renumbers boxes but retains MISS by region.
            reopened=engine.apply(engine.open_image(image),'next')
            boxes=deepcopy(reopened['regions'])
            for box_id,uid in reopened['region_uid_by_box_id'].items():boxes[uid]['order']=6-int(box_id)
            reopened=engine.apply(reopened,'next',{'boxes':boxes})
            self.assertEqual(reopened['text_sequence'],list(reversed(expected)))

    def test_reopened_normal_extra_alignment_keeps_assignment_and_metadata(self):
        for source_text,expected,issue,n in (
                ('永寺',['寺','永'],None,2),
                ('永寺永',['寺','永','永'],None,3),
                ('永寺樂',['樂','永','寺'],'extra_text',2)):
            with self.subTest(issue=issue,source=source_text), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);image=root/'1.png';Image.new('RGB',(100,100)).save(image)
                source=root/'source.json';atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
                    {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':source_text}]}]}])
                engine=Workflow(SimpleNamespace(output_dir=root/'out',source_json=source,
                    content_titles=('Nguyên văn chữ Hán Nôm',),annotation_title='Nguyên văn chữ Hán Nôm'))
                s=engine.apply(engine.open_image(image),'next')
                for x in range(n):s=engine.apply(s,'add',{'bbox':[x*20,10,x*20+10,30]})
                if issue:s=engine.apply(s,'confirm_source_mismatch',{'issue_type':issue,'note':''})
                boxes=deepcopy(s['regions'])
                for index,box in enumerate(boxes.values(),1):box['order']=index
                s=engine.apply(s,'next',{'boxes':boxes})
                s=engine.apply(s,'reorder_text',{'sequence':expected})
                s=engine.apply(s,'status',{'id':'1','status':'intact','unavailable_font':True})
                s=engine.apply(s,'suspicious',{'token_id':s['text_token_ids'][0],'value':True})
                for _ in range(3):s=engine.apply(s,'next')
                s=engine.apply(s,'save')
                s=engine.apply(engine.open_image(image),'next')
                for reverse in (False,True):
                    boxes=deepcopy(s['regions'])
                    for box_id,uid in s['region_uid_by_box_id'].items():
                        boxes[uid]['order']=n+1-int(box_id) if reverse else int(box_id)
                        boxes[uid]['bbox'][1]+=1;boxes[uid]['bbox'][3]+=1
                    s=engine.apply(s,'next',{'boxes':boxes})
                    wanted=list(reversed(expected[:n]))+expected[n:] if reverse else expected
                    self.assertEqual(s['text_sequence'],wanted)
                    self.assertEqual([s['annotations'][str(i)] for i in range(1,n+1)],wanted[:n])
                    if issue:self.assertEqual(s['source_mismatch']['excluded_characters'],expected[n:])
                    marked_box=str(n if reverse else 1)
                    self.assertTrue(s['bounding_boxes'][marked_box]['unavailable_font'])
                    from annotation.reading_order import suspicious_box_ids
                    self.assertEqual(list(map(str,suspicious_box_ids(s))),[marked_box])
                    if not reverse:s=engine.apply(s,'back')
                for _ in range(3):s=engine.apply(s,'next')
                s=engine.apply(s,'save')
                self.assertEqual(engine.open_image(image)['text_sequence'],wanted)

    def test_archive_all_categories_and_empty_arrays(self):
        with tempfile.TemporaryDirectory() as directory:
            for annotations,details in [([],None),([{'image':'1.png'}],{'1':{'note':'test'}})]:
                archive=save_export_archive(annotations,[],directory,[],details)
                with zipfile.ZipFile(archive) as bundle:
                    self.assertEqual(set(bundle.namelist()),{'text_annotations.json','inscription_content.json',
                        'source_mismatches.json','suspicious_details.json'})
                    self.assertEqual(json.loads(bundle.read('suspicious_details.json')),details or [])
                    self.assertEqual(json.loads(bundle.read('text_annotations.json')),annotations)
                    self.assertEqual(json.loads(bundle.read('source_mismatches.json')),[])

if __name__=='__main__':unittest.main()
