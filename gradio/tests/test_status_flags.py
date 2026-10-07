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
from ui.editor import snapshot


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
                if unknown:self.assertEqual((mark.text,mark.get('fill')),('?','#ef4444'))
                if font:self.assertEqual((rect.get('fill'),rect.get('fill-opacity')),('#ec4899','.20'))

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
