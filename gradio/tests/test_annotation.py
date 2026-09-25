import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from annotation.state import new_state, set_verified_content, refresh_alignment
from annotation.bbox import add_bbox, update_bbox, delete_bbox
from annotation.text_alignment import count_annotation_characters, normalize_annotation_text
from annotation.reading_order import update_reading_order, build_text_sequence, validate_reading_order
from annotation.status import update_status, confirm_status
from annotation.io import read_json, atomic_write, load_annotation, save_annotation, final_document
from annotation.text_extraction import extract_source_content, save_source_content
from annotation.workflow import Workflow
from crop.crop import save_crop_coordinates
from PIL import Image


def state(text='永寺樂',n=3):
    s=new_state();s.update(image='12305.png',image_size=[100,100],current_step=3)
    set_verified_content(s,{},text)
    for i in range(n):add_bbox(s,[i*10,0,i*10+9,9])
    refresh_alignment(s)
    return s


class Invariants(unittest.TestCase):
    def test_count_cases(self):
        self.assertTrue(state()['workflow']['alignment_valid'])
        self.assertFalse(state('永寺樂文')['workflow']['alignment_valid'])
        self.assertFalse(state(n=4)['workflow']['alignment_valid'])

    def test_same_length_edit(self):
        s=state();set_verified_content(s,{},'永樂寺')
        self.assertFalse(s['workflow']['alignment_valid']);self.assertEqual(s['annotations'],{})
        refresh_alignment(s);self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺'})

    def test_changed_count_and_add(self):
        s=state();s['workflow']['reading_order_valid']=True
        set_verified_content(s,{},'永樂寺文');refresh_alignment(s)
        self.assertFalse(s['workflow']['bbox_valid']);self.assertFalse(s['workflow']['reading_order_valid'])
        add_bbox(s,[40,0,49,9]);refresh_alignment(s)
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺','4':'文'})
        self.assertFalse(s['workflow']['reading_order_valid'])

    def test_delete_sync_and_no_reuse(self):
        s=state();delete_bbox(s,2)
        self.assertEqual(set(s['bounding_boxes']),{'1','3'})
        self.assertEqual(s['reading_order'],[1,3]);self.assertEqual(set(s['annotations']),{'1','3'})
        delete_bbox(s,3);self.assertEqual(add_bbox(s,[40,0,49,9]),'4')

    def test_reorder_preserves_mapping(self):
        s=state();confirm_status(s);before=deepcopy(s['annotations'])
        update_reading_order(s,[1,3,2])
        self.assertEqual(s['annotations'],before);self.assertEqual(build_text_sequence(s),'永樂寺')
        for order in ([1,3],[1,3,3],[1,3,5],['1',2,3],[True,2,3]):
            with self.assertRaises(ValueError):update_reading_order(s,order)

    def test_status_only(self):
        s=state();old=deepcopy(s);update_status(s,2,'damaged')
        old['bounding_boxes']['2']['status']='damaged'
        self.assertEqual(s,old)

    def test_coordinates(self):
        for coords in ([1,1,0,0],[-1,0,2,2],[0,0,101,2],[0,0,float('nan'),2],[False,0,2,2]):
            with self.assertRaises(ValueError):update_bbox(state(),1,coords)

    def test_unicode(self):
        self.assertEqual(count_annotation_characters(' 永、樂。寺\n(𨴦) '),4)
        self.assertEqual(count_annotation_characters('a\u0301 𨴦\U000E0100'),2)
        self.assertEqual(normalize_annotation_text('(永樂寺)'), '永樂寺')
        self.assertFalse(state('，。',0)['workflow']['alignment_valid'])

    def test_save_guards(self):
        s=state()
        with self.assertRaises(ValueError):final_document(s)
        confirm_status(s);update_reading_order(s,[1,3,2]);s['workflow']['reading_order_valid']=True
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
        with patch('annotation.workflow.detect',return_value={k:state()[k] for k in ('image','bounding_boxes','reading_order')}):
            s=e.apply(s,'detect')
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        self.assertTrue(s['workflow']['alignment_valid'])
        s=e.apply(s,'status',{'id':2,'status':'damaged'})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],5)
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
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺','4':'文'})
        self.assertFalse(s['workflow']['reading_order_valid'])
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)

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

    def test_stale_and_transaction(self):
        s=self.engine.open_image(self.image);before=deepcopy(s)
        with self.assertRaises(ValueError):self.engine.apply(s,'select',{'id':'1','image':s['image'],'revision':99})
        self.assertEqual(s,before)
        with self.assertRaises(ValueError):self.engine.apply(s,'next')

    def test_duplicate_json(self):
        self.source.write_text('{"1":{},"1":{}}')
        with self.assertRaises(ValueError):read_json(self.source)

    def test_existing_wrong_source_realigns(self):
        s=state();confirm_status(s);s['workflow']['reading_order_valid']=True
        save_annotation(s,self.root/'out')
        opened=self.engine.open_image(self.image)
        self.assertEqual(opened['annotations'],s['annotations'])
        opened=self.engine.apply(opened,'save_content')
        self.assertTrue(opened['workflow']['alignment_valid'])
        self.assertFalse(opened['workflow']['reading_order_valid'])


if __name__=='__main__':unittest.main()
