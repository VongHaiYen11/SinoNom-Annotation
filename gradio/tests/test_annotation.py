import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from annotation.state import new_state, set_verified_content, refresh_bbox_validation, initialize_alignment
from annotation.bbox import add_bbox, update_bbox, delete_bbox
from annotation.text_alignment import count_annotation_characters, normalize_annotation_text
from annotation.reading_order import update_reading_order, build_text_sequence, validate_reading_order
from annotation.status import update_status, confirm_status
from annotation.io import read_json, atomic_write, load_annotation, save_annotation, final_document
from annotation.text_extraction import extract_source_content, save_source_content
from annotation.workflow import Workflow
from crop.crop import (save_crop_coordinates, crop_document, default_crop,
                       MAX_CROP_SIDE)
from PIL import Image


def state(text='永寺樂',n=3):
    s=new_state();s.update(image='12305.png',image_size=[100,100],current_step=3)
    set_verified_content(s,{},text)
    for i in range(n):add_bbox(s,[i*10,0,i*10+9,9])
    refresh_bbox_validation(s)
    return s


def aligned_state(text='永寺樂', n=3):
    s = state(text, n)
    confirm_status(s)
    initialize_alignment(s)
    return s


class Invariants(unittest.TestCase):
    def test_count_cases(self):
        self.assertTrue(state()['workflow']['bbox_valid'])
        self.assertFalse(state()['workflow']['alignment_valid'])
        self.assertFalse(state('永寺樂文')['workflow']['bbox_valid'])
        self.assertFalse(state(n=4)['workflow']['bbox_valid'])

    def test_same_length_edit(self):
        s=state();set_verified_content(s,{},'永樂寺')
        self.assertFalse(s['workflow']['alignment_valid']);self.assertEqual(s['annotations'],{})
        refresh_bbox_validation(s);self.assertEqual(s['annotations'],{})
        confirm_status(s);initialize_alignment(s)
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺'})

    def test_changed_count_and_add(self):
        s=state();s['workflow']['reading_order_valid']=True
        set_verified_content(s,{},'永樂寺文');refresh_bbox_validation(s)
        self.assertFalse(s['workflow']['bbox_valid']);self.assertFalse(s['workflow']['reading_order_valid'])
        add_bbox(s,[40,0,49,9]);refresh_bbox_validation(s)
        self.assertEqual(s['annotations'],{})
        confirm_status(s);initialize_alignment(s)
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺','4':'文'})
        self.assertFalse(s['workflow']['reading_order_valid'])

    def test_region_identity_is_internal_and_public_ids_are_rebuilt(self):
        s=aligned_state();uids=list(s['regions'])
        update_status(s,uids[0],'damaged')
        delete_bbox(s,uids[1])
        self.assertEqual(len(s['regions']),2)
        self.assertEqual(s['bounding_boxes'],{});self.assertEqual(s['reading_order'],[])
        self.assertEqual(s['regions'][uids[0]]['status'],'damaged')
        new_uid=add_bbox(s,[40,0,49,9]);self.assertNotIn(new_uid,uids)
        self.assertEqual(s['regions'][new_uid]['status'],'intact')
        refresh_bbox_validation(s);confirm_status(s);initialize_alignment(s)
        self.assertEqual(set(s['bounding_boxes']),{'1','2','3'})
        self.assertEqual(s['reading_order'],[1,2,3])
        self.assertEqual(sum(box['status']=='damaged' for box in s['bounding_boxes'].values()),1)

    def test_geometry_edit_invalidates_and_rebuilds_public_ids(self):
        s=aligned_state();uid=next(iter(s['regions']))
        update_bbox(s,uid,[1,1,8,8])
        self.assertEqual(s['bounding_boxes'],{})
        self.assertEqual(s['annotations'],{})
        self.assertEqual(s['reading_order'],[])
        refresh_bbox_validation(s);confirm_status(s);initialize_alignment(s)
        self.assertEqual(set(s['bounding_boxes']),{'1','2','3'})

    def test_reorder_preserves_mapping(self):
        s=aligned_state();before=deepcopy(s['annotations'])
        update_reading_order(s,[1,3,2])
        self.assertEqual(s['annotations'],before);self.assertEqual(build_text_sequence(s),'永樂寺')
        for order in ([1,3],[1,3,3],[1,3,5],['1',2,3],[True,2,3]):
            with self.assertRaises(ValueError):update_reading_order(s,order)

    def test_status_only(self):
        s=state();uid=list(s['regions'])[1];old=deepcopy(s);update_status(s,uid,'damaged')
        old['regions'][uid]['status']='damaged'
        self.assertEqual(s,old)

    def test_coordinates(self):
        for coords in ([1,1,0,0],[-1,0,2,2],[0,0,101,2],[0,0,float('nan'),2],[False,0,2,2]):
            candidate=state();uid=next(iter(candidate['regions']))
            with self.assertRaises(ValueError):update_bbox(candidate,uid,coords)

    def test_crop_dimensions_are_limited_to_4096(self):
        self.assertEqual(default_crop([5000, 3000]), [0, 0, MAX_CROP_SIDE, 3000])
        self.assertEqual(default_crop([3000, 5000]), [0, 0, 3000, MAX_CROP_SIDE])
        valid = crop_document('scan.png', [500, 600, 4596, 4696], [6000, 6000])
        self.assertEqual(valid['crop']['bottom_right'], [4596, 4696])
        with self.assertRaisesRegex(ValueError, 'cannot exceed 4096'):
            crop_document('scan.png', [0, 0, 4097, 100], [6000, 6000])
        with self.assertRaisesRegex(ValueError, 'cannot exceed 4096'):
            crop_document('scan.png', [0, 0, 100, 4097], [6000, 6000])

        s = aligned_state()
        s['image_size'] = [5000, 6000]
        s['workflow']['reading_order_valid'] = True
        self.assertEqual(final_document(s)['crop']['bottom_right'],
                         [MAX_CROP_SIDE, MAX_CROP_SIDE])

    def test_unicode(self):
        self.assertEqual(count_annotation_characters(' 永、樂。寺\n(𨴦) '),4)
        self.assertEqual(count_annotation_characters('a\u0301 𨴦\U000E0100'),2)
        self.assertEqual(normalize_annotation_text('(永樂寺)'), '永樂寺')
        self.assertFalse(state('，。',0)['workflow']['alignment_valid'])

    def test_save_guards(self):
        s=state()
        with self.assertRaises(ValueError):final_document(s)
        confirm_status(s);initialize_alignment(s);update_reading_order(s,[1,3,2]);s['workflow']['reading_order_valid']=True
        self.assertEqual(final_document(s)['annotations']['2'],'寺')
        del s['annotations']['2']
        with self.assertRaises(ValueError):final_document(s)


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.image=self.root/'12305.png';Image.new('RGB',(100,100),'white').save(self.image)
        self.source=self.root/'source.json'
        self.record={'so_van_bia':1,'extra':{'keep':42},'noi_dung':[
            {'ky_hieu':'12305','chuyen_muc':[{'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永寺樂'}]},
            {'ky_hieu':'12306','chuyen_muc':[{'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'文'}]}]}
        atomic_write(self.source,[self.record,{'so_van_bia':2,'noi_dung':[]}])
        self.engine=Workflow(SimpleNamespace(output_dir=self.root/'out',source_json=self.source))

    def tearDown(self):self.tmp.cleanup()

    def test_extraction_and_source_conflict(self):
        located=extract_source_content('12305.jpg',self.source)
        self.assertEqual(located['record'],self.record)
        with self.assertRaises(ValueError):extract_source_content('001.jpg',self.source)
        updated=deepcopy(self.record);updated['extra']['keep']=43
        save_source_content(self.source,self.image.name,self.record,updated)
        records=read_json(self.source);self.assertEqual(records[0]['extra']['keep'],43)
        self.assertEqual(records[1],{'so_van_bia':2,'noi_dung':[]})
        with self.assertRaises(ValueError):save_source_content(self.source,self.image.name,self.record,updated)

    def test_full_workflow_roundtrip_and_edit(self):
        e=self.engine;s=e.open_image(self.image);s=e.apply(s,'save_content');s=e.apply(s,'next')
        self.assertTrue(s['image_url'].startswith('gradio_api/file='))
        self.assertNotIn('base64',s['image_url'])
        from urllib.parse import unquote
        preview_path = unquote(s['image_url'].split('file=',1)[1])
        with Image.open(preview_path) as preview_image:
            self.assertEqual(preview_image.size,tuple(s['image_size']))
            self.assertEqual(preview_image.format,'JPEG')
            self.assertEqual(preview_image.getpixel((0,0)),(255,255,255))
        detected={'image':self.image.name,
                  'bounding_boxes':{str(i+1):dict(bbox=[i*10,0,i*10+9,9],status='intact') for i in range(3)},
                  'reading_order':[1,2,3]}
        with patch('annotation.workflow.detect',return_value=detected):
            s=e.apply(s,'detect')
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        self.assertFalse(s['workflow']['alignment_valid'])
        damaged_uid=list(s['regions'])[1]
        s=e.apply(s,'status',{'uid':damaged_uid,'status':'damaged'})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],5)
        self.assertTrue(s['workflow']['alignment_valid'])
        mapping=deepcopy(s['annotations'])
        s=e.apply(s,'reorder',{'order':[1,3,2]});s=e.apply(s,'next')
        self.assertEqual(s['current_step'],6)
        self.assertEqual(s['annotations'],mapping)
        before_crop=deepcopy(final_document(s))
        s=e.apply(s,'crop',{'bbox':[1,2,90,95]});s=e.apply(s,'save_crop')
        self.assertEqual({k:v for k,v in final_document(s).items() if k!='crop'},
                         {k:v for k,v in before_crop.items() if k!='crop'})
        self.assertEqual(final_document(s)['crop']['top_left'],[1,2])
        self.assertEqual(read_json(self.root/'out/crops/12305.json')['crop']['bottom_left'],[1,95])
        self.assertFalse((self.root/'out/12305.json').exists())
        s=e.apply(s,'next');self.assertEqual(s['current_step'],7)
        s=e.apply(s,'save')
        self.assertEqual(build_text_sequence(s),'永樂寺')
        doc=read_json(self.root/'out/12305.json')
        self.assertNotIn('region_uid',json.dumps(doc))
        loaded=e.open_image(self.image);self.assertEqual(loaded['annotations'],doc['annotations'])
        loaded=e.apply(loaded,'save_content');self.assertEqual(loaded['reading_order'],[1,3,2])
        self.assertTrue(loaded['crop_saved'])
        self.assertEqual(loaded['crop'],[1,2,90,95])
        s=e.apply(s,'back');self.assertEqual(s['current_step'],6)
        s=e.apply(s,'crop',{'bbox':[2,3,80,90]});self.assertFalse(s['crop_saved'])
        self.assertEqual(read_json(self.root/'out/12305.json'),doc)
        while s['current_step']>2:s=e.apply(s,'back')
        s=e.apply(s,'field',{'path':['noi_dung',0,'chuyen_muc',0,'van_ban'],'value':'永樂寺文'})
        s=e.apply(s,'save_content');self.assertFalse(s['workflow']['alignment_valid'])
        s=e.apply(s,'next')
        with self.assertRaises(ValueError):e.apply(s,'next')
        s=e.apply(s,'add',{'bbox':[40,0,49,9]})
        self.assertEqual(s['annotations'],{})
        self.assertFalse(s['workflow']['reading_order_valid'])
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        s=e.apply(s,'next');self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺','4':'文'})

    def test_seven_step_gates_and_crop_independence(self):
        e=self.engine;s=e.open_image(self.image)
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20):s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        with self.assertRaises(ValueError):e.apply(s,'next')
        s=e.apply(s,'add',{'bbox':[40,0,50,10]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        with self.assertRaises(ValueError):e.apply(s,'reorder',{'order':[1,3,2]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],5)
        with self.assertRaises(ValueError):e.apply(s,'reorder',{'order':[1,1,2]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],6)
        with self.assertRaises(ValueError):e.apply(s,'save')
        with self.assertRaises(ValueError):e.apply(s,'crop',{'bbox':[0,0,101,100]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],7)
        # Crop remains optional and independent of the annotation schema.
        self.assertFalse(s['crop_saved'])
        s=e.apply(s,'save');self.assertTrue(s['saved'])
        self.assertEqual(e.apply(s,'next')['current_step'],7)

    def test_multiselect_then_delete_regions(self):
        e=self.engine
        s=e.apply(e.open_image(self.image),'save_content')
        s=e.apply(s,'next')
        for x in (0,20,40):
            s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        uids=list(s['regions'])
        s=e.apply(s,'select',{'uid':uids[0]})
        s=e.apply(s,'select',{'uid':uids[2],'toggle':True})
        self.assertEqual(s['selected_region_uids'],[uids[0],uids[2]])
        self.assertEqual(s['selected_region_uid'],uids[2])
        s=e.apply(s,'delete',{'ids':s['selected_region_uids']})
        self.assertEqual(set(s['regions']),{uids[1]})
        self.assertEqual(s['selected_region_uids'],[])
        self.assertEqual(s['selected_region_uid'],uids[1])

    def test_stale_and_transaction(self):
        s=self.engine.open_image(self.image);before=deepcopy(s)
        with self.assertRaises(ValueError):self.engine.apply(s,'select',{'id':'1','image':s['image'],'revision':99})
        self.assertEqual(s,before)
        advanced=self.engine.apply(s,'next')
        self.assertEqual(advanced['current_step'],3)
        self.assertTrue(advanced['workflow']['content_verified'])
        self.assertEqual(s,before)

    def test_duplicate_json(self):
        self.source.write_text('{"1":{},"1":{}}')
        with self.assertRaises(ValueError):read_json(self.source)

    def test_legacy_gapped_box_ids_are_migrated_on_load(self):
        path=self.root/'legacy.json'
        atomic_write(path,dict(image=self.image.name,
            bounding_boxes={'1':{'bbox':[0,0,9,9],'status':'intact'},
                            '3':{'bbox':[20,0,29,9],'status':'damaged'}},
            reading_order=[3,1],annotations={'1':'寺','3':'永'}))
        loaded=load_annotation(path,self.image.name,[100,100])
        self.assertEqual(set(loaded['bounding_boxes']),{'1','2'})
        self.assertEqual(loaded['reading_order'],[1,2])
        self.assertEqual(loaded['annotations'],{'1':'永','2':'寺'})

    def test_existing_annotation_without_matching_sidecar_realigns_later(self):
        s=aligned_state();s['workflow']['reading_order_valid']=True
        save_annotation(s,self.root/'out')
        opened=self.engine.open_image(self.image)
        self.assertEqual(opened['annotations'],s['annotations'])
        opened=self.engine.apply(opened,'save_content')
        self.assertTrue(opened['workflow']['bbox_valid'])
        self.assertFalse(opened['workflow']['alignment_valid'])
        self.assertEqual(opened['annotations'],{})
        self.assertFalse(opened['workflow']['reading_order_valid'])


if __name__=='__main__':unittest.main()
