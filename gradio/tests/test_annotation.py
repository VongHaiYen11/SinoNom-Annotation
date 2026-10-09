import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from annotation.state import (new_state, set_verified_content, refresh_bbox_validation,
                              initialize_alignment, source_mismatch_confirmed)
from annotation.bbox import (add_bbox, update_bbox, update_bboxes, delete_bbox,
                             sync_draft_boxes)
from annotation.text_alignment import count_annotation_characters, normalize_annotation_text
from annotation.reading_order import (update_text_sequence, update_text_tokens,
                                      build_text_sequence, suspicious_box_ids,
                                      validate_reading_order)
from annotation.status import update_status, replace_statuses, confirm_status
from annotation.io import (atomic_write, final_document,
                           final_source_mismatch_document, load_annotation,
                           load_source_mismatch, read_json, save_annotation)
from annotation.text_extraction import extract_source_content, save_source_content
from annotation.workflow import Workflow, annotations_to_text
from ui.editor import snapshot
from crop.crop import (auto_scale_crop, save_crop_coordinates, crop_document,
                       default_crop, MAX_CROP_SIDE)
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
    def test_saved_annotations_are_concatenated_in_numeric_box_order(self):
        self.assertEqual(annotations_to_text({'10':'庚','2':'乙','1':'甲'}),'甲乙庚')

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

    def test_frontend_batch_box_commit_is_atomic(self):
        s=aligned_state();uids=list(s['regions']);before=deepcopy(s)
        update_bboxes(s,{uids[0]:[1,1,8,8],uids[1]:[11,1,18,8]},
                      active=uids[1],selected=[uids[0],uids[1]])
        self.assertEqual(s['regions'][uids[0]]['bbox'],[1,1,8,8])
        self.assertEqual(s['regions'][uids[1]]['bbox'],[11,1,18,8])
        self.assertEqual(s['selected_region_uids'],[uids[0],uids[1]])
        self.assertEqual(s['selected_region_uid'],uids[1])
        self.assertEqual(s['annotations'],{})
        invalid=deepcopy(before)
        with self.assertRaises(ValueError):
            update_bboxes(invalid,{uids[0]:[2,2,7,7],uids[1]:[0,0,101,10]})
        self.assertEqual(invalid,before)

    def test_frontend_snapshot_replaces_regions_and_preserves_metadata(self):
        s=state();uids=list(s['regions'])
        snapshot={
            uids[0]:dict(s['regions'][uids[0]],bbox=[1,1,8,8],order=4,
                         character='永',custom_flag='kept'),
            'box_new_1':dict(bbox=[40,0,49,9],status='damaged',unknown=True,
                             order=None,character=None),
        }
        sync_draft_boxes(s,{'boxes':snapshot,'active':'box_new_1',
                            'selected':['box_new_1']})
        self.assertEqual(set(s['regions']),{uids[0],'box_new_1'})
        self.assertEqual(s['regions'][uids[0]]['custom_flag'],'kept')
        self.assertEqual(s['regions']['box_new_1']['status'],'damaged')
        self.assertEqual(s['regions']['box_new_1']['order'],None)
        self.assertEqual(s['selected_region_uid'],'box_new_1')

    def test_empty_frontend_snapshot_does_not_restore_backend_regions(self):
        s=state()
        sync_draft_boxes(s,{'boxes':{},'active':None,'selected':[]})
        self.assertEqual(s['regions'],{})
        self.assertEqual(s['bounding_boxes'],{})

    def test_box_snapshot_keeps_stale_mismatch_removable_but_unconfirmed(self):
        s=state('永寺樂文',n=3)
        s['source_mismatch']={
            'source_text':s['annotation_text'],
            'source_character_count':4,
            'bounding_box_count':3,
            'issue_type':'missing_text',
            'note':'draft',
        }
        self.assertTrue(source_mismatch_confirmed(s))
        original=deepcopy(s['regions'])
        remaining=dict(list(s['regions'].items())[:2])
        sync_draft_boxes(s,{'boxes':remaining,'active':None,'selected':[]})
        self.assertIsNotNone(s['source_mismatch'])
        self.assertFalse(source_mismatch_confirmed(s))
        sync_draft_boxes(s,{'boxes':original,'active':None,'selected':[]},
                         materialize_alignment=False)
        self.assertFalse(source_mismatch_confirmed(s))

    def test_clearing_order_preserves_confirmed_mismatch(self):
        s=state('永寺樂文',n=3)
        s['source_mismatch']={
            'source_text':s['annotation_text'],
            'source_character_count':4,
            'bounding_box_count':3,
            'issue_type':'extra_text',
            'note':'',
        }
        boxes={uid:dict(box,order=index) for index,(uid,box)
               in enumerate(s['regions'].items(),1)}
        sync_draft_boxes(s,{'boxes':boxes,'active':None,'selected':[]},
                         materialize_alignment=False)
        self.assertTrue(source_mismatch_confirmed(s))
        confirmed=deepcopy(s['source_mismatch'])
        cleared={uid:dict(box,order=None) for uid,box in boxes.items()}
        sync_draft_boxes(s,{'boxes':cleared,'active':None,'selected':[]},
                         materialize_alignment=False)
        self.assertEqual(s['source_mismatch'],confirmed)
        self.assertTrue(source_mismatch_confirmed(s))
        self.assertFalse(s['workflow']['bbox_valid'])

    def test_replacing_box_at_same_count_preserves_mismatch(self):
        s=state('永寺樂文',n=3)
        s['source_mismatch']={
            'source_text':s['annotation_text'],
            'source_character_count':4,
            'bounding_box_count':3,
            'issue_type':'extra_text',
            'note':'',
        }
        boxes=dict(list(s['regions'].items())[1:])
        boxes['replacement']=dict(bbox=[40,0,49,9],status='intact',unknown=False)
        sync_draft_boxes(s,{'boxes':boxes,'active':None,'selected':[]},
                         materialize_alignment=False)
        self.assertTrue(source_mismatch_confirmed(s))

    def test_sort_without_mismatch_confirmation_keeps_alignment_blocked(self):
        engine=Workflow.__new__(Workflow)
        s=state('永寺樂文',n=3)
        s['current_step']=3
        s['source_mismatch']={
            'source_text':s['annotation_text'],
            'source_character_count':4,
            'bounding_box_count':3,
            'issue_type':'missing_text',
            'note':'',
        }
        self.assertTrue(source_mismatch_confirmed(s))
        cleared=engine.apply(s,'clear_source_mismatch')
        self.assertFalse(source_mismatch_confirmed(cleared))
        self.assertFalse(cleared['workflow']['bbox_valid'])
        sorted_state=engine.apply(cleared,'sort_boxes')
        self.assertEqual(sorted(box['order'] for box in sorted_state['regions'].values()),[1,2,3])
        self.assertFalse(sorted_state['workflow']['alignment_valid'])
        with self.assertRaisesRegex(ValueError,'confirm a source mismatch'):
            engine.apply(sorted_state,'next')

    def test_complete_mismatch_order_materializes_character_tokens(self):
        s=state('永寺',n=3)
        s['source_mismatch']={
            'source_text':s['annotation_text'],
            'source_character_count':2,
            'bounding_box_count':3,
            'issue_type':'missing_text',
            'note':'',
        }
        boxes={}
        for order,(uid,box) in enumerate(s['regions'].items(),1):
            boxes[uid]=dict(box,order=order)
        sync_draft_boxes(s,{'boxes':boxes,'active':next(iter(boxes)),
                            'selected':[next(iter(boxes))]})
        self.assertTrue(s['workflow']['alignment_valid'])
        self.assertEqual(list(s['annotations'].values()),['永','寺','MISS'])
        self.assertEqual(s['text_sequence'],['永','寺','MISS'])
        self.assertEqual(s['text_token_ids'],['1','2','3'])

    def test_reorder_assigns_character_tokens_to_coordinate_slots(self):
        s=aligned_state()
        statuses={key:box['status'] for key,box in s['bounding_boxes'].items()}
        geometry=deepcopy(s['bounding_boxes'])
        update_text_tokens(s,['永','樂','寺'],['1','3','2'])
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺'})
        self.assertEqual(s['reading_order'],[1,2,3])
        self.assertEqual(s['bounding_boxes'],geometry)
        self.assertEqual(
            {key:box['status'] for key,box in s['bounding_boxes'].items()},
            statuses)
        self.assertEqual(build_text_sequence(s),'永樂寺')
        for token_order in (['1','3'],['1','3','3'],['1','3','5']):
            with self.assertRaises(ValueError):
                update_text_tokens(s,['永','樂','寺'],token_order)

    def test_text_sequence_is_assigned_to_spatially_sorted_boxes(self):
        s=aligned_state()
        statuses={key:box['status'] for key,box in s['bounding_boxes'].items()}
        update_text_sequence(s,['永','樂','寺'])
        self.assertEqual(s['reading_order'],[1,2,3])
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺'})
        self.assertEqual(build_text_sequence(s),'永樂寺')
        self.assertEqual(
            {key:box['status'] for key,box in s['bounding_boxes'].items()},
            statuses)
        for sequence in (['永','樂'],['永','樂','樂'],['永','樂',3],None):
            with self.assertRaises(ValueError):update_text_sequence(s,sequence)

    def test_suspicious_identity_stays_on_box_with_duplicate_tokens(self):
        s=aligned_state('永永寺')
        geometry=deepcopy(s['bounding_boxes'])
        update_status(s,s['region_uid_by_box_id']['2'],'intact',suspicious=True)
        geometry=deepcopy(s['bounding_boxes'])
        s['selected_token_id']='2';s['selected_box_id']='2'
        self.assertEqual(suspicious_box_ids(s),['2'])
        update_text_tokens(s,['永','永','寺'],['2','1','3'])
        self.assertTrue(s['bounding_boxes']['2']['suspicious'])
        self.assertEqual(suspicious_box_ids(s),['2'])
        self.assertEqual(s['selected_box_id'],'1')
        self.assertEqual(s['bounding_boxes'],geometry)

    def test_larger_token_shift_reassigns_every_intervening_slot(self):
        s=aligned_state('甲乙丙丁',4)
        geometry=deepcopy(s['bounding_boxes'])
        update_text_tokens(s,['丁','甲','乙','丙'],['4','1','2','3'])
        self.assertEqual(s['annotations'],{
            '1':'丁','2':'甲','3':'乙','4':'丙',
        })
        self.assertEqual(s['bounding_boxes'],geometry)

    def test_missing_source_alignment_adds_reorderable_miss_tags(self):
        s=state(n=5)
        s['source_mismatch']={
            'source_text':s['annotation_text'], 'source_character_count':3,
            'bounding_box_count':5, 'issue_type':'missing_text', 'note':''}
        confirm_status(s);initialize_alignment(s)
        self.assertEqual(list(s['annotations'].values()),['永','寺','樂','MISS','MISS'])
        update_text_sequence(s,['永','MISS','寺','樂','MISS'])
        self.assertEqual(s['annotations'],{
            '1':'永','2':'MISS','3':'寺','4':'樂','5':'MISS'})
        self.assertEqual(build_text_sequence(s),'永MISS寺樂MISS')
        self.assertEqual(s['bounding_boxes']['2']['status'],'unknown')
        self.assertEqual(s['bounding_boxes']['5']['status'],'unknown')
        self.assertTrue(all(s['bounding_boxes'][key]['status'] != 'unknown'
                            for key in ('1','3','4')))
        with self.assertRaises(ValueError):
            update_status(s,s['region_uid_by_box_id']['2'],'damaged')
        self.assertEqual(s['reading_order'],[1,2,3,4,5])
        self.assertEqual(s['annotations']['2'],'MISS')
        self.assertEqual(s['annotations']['5'],'MISS')
        self.assertEqual(s['bounding_boxes']['2']['status'],'unknown')
        self.assertEqual(s['bounding_boxes']['5']['status'],'unknown')
        self.assertEqual(s['bounding_boxes']['3']['status'],'intact')
        s['workflow']['reading_order_valid']=True
        confirm_status(s)
        s['code']='12305'
        document=final_source_mismatch_document(s)
        self.assertEqual(document['annotations']['2'],'MISS')
        self.assertNotIn('reading_order',document)
        invalid=deepcopy(document);invalid['bounding_boxes']['2']['status']='intact'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'invalid.json';atomic_write(path,invalid)
            with self.assertRaises(ValueError):
                load_source_mismatch(path,'12305.png',[100,100])

    def test_source_mismatch_keeps_suspicious_on_box_without_issue_type(self):
        s=state(n=2)
        s['source_mismatch']={
            'source_text':s['annotation_text'],'source_character_count':3,
            'bounding_box_count':2,'issue_type':'extra_text','note':''}
        confirm_status(s);initialize_alignment(s)
        geometry=deepcopy(s['bounding_boxes'])
        update_status(s,s['region_uid_by_box_id']['1'],'intact',suspicious=True)
        geometry=deepcopy(s['bounding_boxes'])
        s['workflow']['reading_order_valid']=True
        confirm_status(s);s['code']='12305'
        document=final_source_mismatch_document(s)
        self.assertEqual(document['issue_type'],['extra_text'])
        self.assertEqual(document['bounding_boxes'],geometry)
        s['current_step']=7;s['image_url']='image.jpg'
        review=snapshot(s)['markup']
        self.assertIn('fill="#facc15"',review)
        self.assertIn('· suspicious</title>',review)
        self.assertIn('Suspicious content',review)
        self.assertIn('MISS content',review)

        invalid=deepcopy(document)
        invalid['issue_type']='extra_source_characters'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'invalid.json';atomic_write(path,invalid)
            with self.assertRaises(ValueError):
                load_source_mismatch(path,'12305.png',[100,100])

    def test_status_only(self):
        s=state();uid=list(s['regions'])[1];old=deepcopy(s);update_status(s,uid,'damaged')
        old['regions'][uid]['status']='damaged'
        self.assertEqual(s,old)

    def test_replace_statuses_updates_every_region_atomically(self):
        s=aligned_state();uids=list(s['regions']);before=deepcopy(s)
        statuses={uids[0]:'damaged',uids[1]:'intact',uids[2]:'damaged'}
        replace_statuses(s,statuses)
        self.assertEqual(
            {uid:box['status'] for uid,box in s['regions'].items()}, statuses)
        self.assertEqual(
            {box_id:box['status'] for box_id,box in s['bounding_boxes'].items()},
            {s['box_id_by_region'][uid]:status for uid,status in statuses.items()})
        invalid=deepcopy(before)
        with self.assertRaises(ValueError):
            replace_statuses(invalid,{uids[0]:'damaged'})
        self.assertEqual(invalid,before)

    def test_confirm_status_resynchronizes_public_box_status(self):
        s=aligned_state()
        uid=list(s['regions'])[1]
        box_id=s['box_id_by_region'][uid]
        s['regions'][uid]['status']='damaged'
        s['bounding_boxes'][box_id]['status']='intact'
        confirm_status(s)
        self.assertEqual(s['bounding_boxes'][box_id]['status'],'damaged')

    def test_coordinates(self):
        for coords in ([1,1,0,0],[-1,0,2,2],[0,0,101,2],[0,0,float('nan'),2],[False,0,2,2]):
            candidate=state();uid=next(iter(candidate['regions']))
            with self.assertRaises(ValueError):update_bbox(candidate,uid,coords)

    def test_crop_dimensions_are_limited_to_4096(self):
        self.assertEqual(default_crop([5000, 3000]), [0, 0, 5000, 3000])
        valid = crop_document('scan.png', [500, 600, 4596, 4696], [6000, 6000])
        self.assertEqual(valid['crop']['bottom_right'], [4596, 4696])
        scaled, size = auto_scale_crop([0,0,5000,3000],[5000,3000])
        self.assertEqual(max(scaled[2]-scaled[0],scaled[3]-scaled[1]),MAX_CROP_SIDE)
        self.assertEqual(size,[4096,2458])

        s = aligned_state()
        s['image_size'] = [5000, 6000]
        s['crop'] = default_crop(s['image_size'])
        s['workflow']['reading_order_valid'] = True
        document=final_document(s)
        self.assertEqual(max(document['crop']['bottom_right']),MAX_CROP_SIDE)
        self.assertEqual(document['image_resize']['output_size'],[3413,4096])

    def test_unicode(self):
        self.assertEqual(count_annotation_characters(' 永、樂。寺\n(𨴦) '),6)
        self.assertEqual(count_annotation_characters('a\u0301 𨴦\U000E0100'),2)
        self.assertEqual(normalize_annotation_text('(永樂寺)'), '(永樂寺)')
        brackets='()[]{}（）【】《》〈〉「」『』〔〕〖〗“”‘’'
        self.assertEqual(normalize_annotation_text(brackets+' @□，。！？'),brackets+'@□')
        self.assertFalse(state('，。',0)['workflow']['alignment_valid'])

    def test_save_guards(self):
        s=state()
        with self.assertRaises(ValueError):final_document(s)
        confirm_status(s);initialize_alignment(s);update_text_sequence(s,['永','樂','寺']);s['workflow']['reading_order_valid']=True;confirm_status(s)
        self.assertEqual(final_document(s)['annotations']['2'],'樂')
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
        self.engine=Workflow(SimpleNamespace(
            output_dir=self.root/'out',source_json=self.source,
            content_titles=('Nguyên văn chữ Hán Nôm',),
            annotation_title='Nguyên văn chữ Hán Nôm'))

    def tearDown(self):self.tmp.cleanup()

    def test_reopened_saved_annotations_become_character_alignment_text(self):
        from crop.crop import crop_document, image_resize
        out=self.root/'out';out.mkdir(parents=True)
        boxes={str(index):{
            'bbox':[index*10,0,index*10+9,9],'status':'intact','unknown':False,'unavailable_font':False,'expert_prediction':False,'suspicious':False}
            for index in range(1,4)}
        atomic_write(out/'12305.json',{
            'image':'12305.png','bounding_boxes':boxes,
            # Deliberately serialize keys out of order; Box ID defines sequence.
            'annotations':{'2':'樂','1':'永','3':'寺'},
            'image_resize':image_resize([100,100],[100,100]),
            'crop':crop_document('12305.png',[0,0,100,100],[100,100])['crop'],
        })
        reopened=self.engine.open_image(self.image)
        self.assertEqual(reopened['saved_annotation_text'],'永樂寺')
        self.assertEqual(reopened['text_sequence'],list('永樂寺'))

    def test_extraction_and_source_conflict(self):
        located=extract_source_content('12305.jpg',self.source,'Nguyên văn chữ Hán Nôm')
        self.assertEqual(located['record'],self.record)
        with self.assertRaises(ValueError):
            extract_source_content('001.jpg',self.source,'Nguyên văn chữ Hán Nôm')
        updated=deepcopy(self.record);updated['extra']['keep']=43
        save_source_content(
            self.source,self.image.name,self.record,updated,'Nguyên văn chữ Hán Nôm')
        records=read_json(self.source);self.assertEqual(records[0]['extra']['keep'],43)
        self.assertEqual(records[1],{'so_van_bia':2,'noi_dung':[]})
        with self.assertRaises(ValueError):
            save_source_content(
                self.source,self.image.name,self.record,updated,'Nguyên văn chữ Hán Nôm')

    def test_leading_zero_code_matching(self):
        source_lz = self.root / 'source_lz.json'
        rec = {'so_van_bia': 10, 'noi_dung': [{'ky_hieu': '400', 'chuyen_muc': [{'tieu_de': 'Nguyên văn chữ Hán Nôm', 'van_ban': '測試'}]}]}
        atomic_write(source_lz, [rec])
        located = extract_source_content('0400.jpg', source_lz, 'Nguyên văn chữ Hán Nôm')
        self.assertEqual(located['code'], '0400')
        self.assertEqual(located['record'], rec)
        lz_image = self.root / '0400.png'
        Image.new('RGB', (100, 100), 'white').save(lz_image)
        engine = Workflow(SimpleNamespace(
            output_dir=self.root / 'out_lz', source_json=source_lz,
            content_titles=('Nguyên văn chữ Hán Nôm',),
            annotation_title='Nguyên văn chữ Hán Nôm'))
        state = engine.open_image(lz_image)
        state = engine.apply(state, 'save_content')
        self.assertEqual(state['code'], '0400')
        self.assertEqual(state['annotation_text'], '測試')

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
        content_preview_path = unquote(s['content_preview_url'].split('file=',1)[1])
        with Image.open(content_preview_path) as content_preview:
            self.assertLessEqual(max(content_preview.size),1600)
            self.assertEqual(content_preview.format,'JPEG')

        detected={'image':self.image.name,
                  'bounding_boxes':{str(i+1):dict(bbox=[i*10,0,i*10+9,9],status='intact') for i in range(3)},
                  'reading_order':[1,2,3]}
        with patch('annotation.workflow.detect',return_value=detected):
            s=e.apply(s,'detect')
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        self.assertTrue(s['workflow']['alignment_valid'])
        damaged_uid=list(s['regions'])[1]
        mapping=deepcopy(s['annotations'])
        s=e.apply(s,'reorder_text',{'sequence':['永','樂','寺'],'token_order':['1','3','2']});s=e.apply(s,'next')
        self.assertEqual(s['current_step'],5)
        damaged_box_id=s['box_id_by_region'][damaged_uid]
        s=e.apply(s,'status',{'id':damaged_box_id,'status':'damaged'})
        s=e.apply(s,'next')
        self.assertEqual(s['current_step'],6)
        self.assertNotEqual(s['annotations'],mapping)
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺'})
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
        self.assertEqual(loaded['saved_annotation_text'],'永樂寺')
        self.assertEqual(loaded['text_sequence'],list('永樂寺'))
        loaded=e.apply(loaded,'save_content');self.assertEqual(loaded['reading_order'],[1,2,3])
        self.assertEqual(loaded['annotations'],{'1':'永','2':'樂','3':'寺'})
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
        self.assertEqual(s['annotations'],{'1':'永','2':'樂','3':'寺','4':'文'})

    def test_suspicious_roundtrip_reorder_and_removal(self):
        e=self.engine;s=e.apply(e.open_image(self.image),'next')
        for x in (0,20,40):s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        boxes=deepcopy(s['regions'])
        for i,box in enumerate(boxes.values(),1):box['order']=i
        s=e.apply(s,'next',{'boxes':boxes})
        s=e.apply(s,'suspicious',{'id':'2','value':True})
        geometry=deepcopy(s['bounding_boxes'])
        s=e.apply(s,'reorder_text',{'sequence':['樂','永','寺']})
        self.assertEqual(suspicious_box_ids(s),['2'])
        self.assertEqual(s['bounding_boxes'],geometry)
        for _ in range(3):s=e.apply(s,'next')
        e.apply(s,'save')
        document=read_json(self.root/'out/12305.json')
        self.assertNotIn('issue_type',document)
        self.assertTrue(document['bounding_boxes']['2']['suspicious'])
        self.assertFalse((self.root/'out/suspicious_details.json').exists())
        reopened=e.apply(e.open_image(self.image),'next')
        reopened=e.apply(reopened,'next')
        self.assertEqual(suspicious_box_ids(reopened),['2'])
        reopened=e.apply(reopened,'suspicious',{'id':'2','value':False})
        for _ in range(3):reopened=e.apply(reopened,'next')
        e.apply(reopened,'save')
        self.assertFalse(e.open_image(self.image)['bounding_boxes']['2']['suspicious'])

    def test_seven_step_gates_and_crop_independence(self):
        e=self.engine;s=e.open_image(self.image)
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20):s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        with self.assertRaises(ValueError):e.apply(s,'next')
        s=e.apply(s,'add',{'bbox':[40,0,50,10]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],4)
        s=e.apply(s,'reorder_text',{'sequence':['永','樂','寺'],'token_order':['1','3','2']})
        with self.assertRaises(ValueError):
            e.apply(s,'reorder_text',{'sequence':['永','樂','寺'],'token_order':['1','1','2']})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],5)
        with self.assertRaises(ValueError):
            e.apply(s,'reorder_text',{'sequence':['永','寺','樂'],'token_order':['1','2','3']})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],6)
        with self.assertRaises(ValueError):e.apply(s,'save')
        with self.assertRaises(ValueError):e.apply(s,'crop',{'bbox':[0,0,101,100]})
        s=e.apply(s,'next');self.assertEqual(s['current_step'],7)
        # Crop remains optional and independent of the annotation schema.
        self.assertFalse(s['crop_saved'])
        s=e.apply(s,'save');self.assertTrue(s['saved'])
        self.assertEqual(e.apply(s,'next')['current_step'],7)

    def test_crop_frame_preserves_annotations_and_scales_automatically(self):
        e=self.engine;s=e.open_image(self.image)
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20,40):s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        s=e.apply(s,'next');s=e.apply(s,'next');s=e.apply(s,'next')
        self.assertEqual(s['current_step'],6)
        regions=deepcopy(s['regions']);annotations=deepcopy(s['annotations'])

        s=e.apply(s,'crop',{'bbox':[5,10,95,70]})
        self.assertEqual(s['crop'],[5,10,95,70])
        self.assertEqual(s['regions'],regions)
        self.assertEqual(s['annotations'],annotations)

        document=final_document(s)
        self.assertEqual(document['image_resize'],{
            'source_size':[100,100], 'output_size':[100,100],
            'scale_x':1.0, 'scale_y':1.0,
        })
        self.assertEqual(document['crop']['top_left'],[5,10])
        self.assertEqual(document['crop']['bottom_right'],[95,70])
        with self.assertRaises(ValueError):
            e.apply(s,'crop',{'bbox':[0,0,101,40]})

    def test_source_mismatch_roundtrip_and_return_to_normal(self):
        e=self.engine;s=e.open_image(self.image)
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20):
            s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        with self.assertRaisesRegex(ValueError,'confirm a source mismatch'):
            e.apply(s,'next')
        with self.assertRaisesRegex(ValueError,'matches the count difference'):
            e.apply(s,'confirm_source_mismatch',{
                'issue_type':'missing_text','note':''})
        s=e.apply(s,'confirm_source_mismatch',{
            'issue_type':'extra_text','note':'PDF contains an extra character'})
        s=e.apply(s,'next')
        self.assertEqual(s['current_step'],4)
        self.assertEqual(s['annotations'],{'1':'永','2':'寺'})
        s=e.apply(s,'reorder_text',{'sequence':['寺','永','樂'],'token_order':['2','1','3']})
        s=e.apply(s,'next');s=e.apply(s,'next')
        document=final_source_mismatch_document(s)
        self.assertIn('annotations',document)
        self.assertEqual(document['source_character_count'],3)
        self.assertEqual(document['bounding_box_count'],2)
        self.assertNotIn('reading_order',document)
        self.assertEqual(document['annotations'],{'1':'寺','2':'永'})
        s=e.apply(s,'next')
        s=e.apply(s,'save')
        mismatch_path=self.root/'out/source_mismatches/12305.json'
        self.assertTrue(mismatch_path.exists())
        self.assertFalse((self.root/'out/12305.json').exists())

        reopened=e.open_image(self.image)
        reopened=e.apply(reopened,'save_content');reopened=e.apply(reopened,'next')
        self.assertEqual(reopened['source_mismatch']['issue_type'],'extra_text')
        reopened=e.apply(reopened,'add',{'bbox':[40,0,50,10]})
        self.assertIsNone(reopened['source_mismatch'])
        self.assertTrue(reopened['workflow']['bbox_valid'])
        reopened=e.apply(reopened,'next');reopened=e.apply(reopened,'next')
        reopened=e.apply(reopened,'next');reopened=e.apply(reopened,'next')
        reopened=e.apply(reopened,'save')
        self.assertFalse(mismatch_path.exists())
        self.assertTrue((self.root/'out/12305.json').exists())

    def test_extra_source_characters_are_reordered_then_excluded(self):
        e=self.engine;s=e.open_image(self.image)
        original=deepcopy(s['draft_content'])
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20):
            s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        s=e.apply(s,'confirm_source_mismatch',{
            'issue_type':'extra_text','note':''})
        s=e.apply(s,'next')
        self.assertEqual(s['current_step'],4)
        self.assertEqual(s['text_sequence'],['永','寺','樂'])
        s=e.apply(s,'reorder_text',{'sequence':['永','樂','寺']})
        self.assertEqual(s['annotations'],{'1':'永','2':'樂'})
        self.assertEqual(s['source_mismatch']['excluded_characters'],['寺'])
        s=e.apply(s,'next');s=e.apply(s,'next');s=e.apply(s,'next')
        doc=final_source_mismatch_document(s)
        self.assertEqual(doc['text_sequence'],['永','樂','寺'])
        self.assertEqual(doc['excluded_characters'],['寺'])
        self.assertEqual(doc['annotations'],{'1':'永','2':'樂'})
        review=snapshot(s)['markup']
        self.assertIn('<span class="eyebrow">FINAL RESULT</span>',review)
        self.assertIn('cropped review',review)
        self.assertIn('-review.jpg',review)
        self.assertIn('<p>永樂</p>',review)
        self.assertNotIn('<p>永樂寺</p>',review)
        self.assertNotIn('<span class="eyebrow">SOURCE MISMATCH</span>',review)
        self.assertEqual(s['draft_content'],original)
        s=e.apply(s,'save')
        reopened=e.open_image(self.image)
        reopened=e.apply(reopened,'save_content')
        self.assertEqual(reopened['text_sequence'],['永','樂','寺'])
        self.assertEqual(reopened['source_mismatch']['excluded_characters'],['寺'])

    def test_other_requires_note_skips_to_review_and_saves_minimal_json(self):
        e=self.engine;s=e.open_image(self.image)
        s=e.apply(s,'save_content');s=e.apply(s,'next')
        for x in (0,20,40):
            s=e.apply(s,'add',{'bbox':[x,0,x+10,10]})
        with self.assertRaisesRegex(ValueError,'require a note'):
            e.apply(s,'confirm_source_mismatch',{'issue_type':'other','note':'  '})
        s=e.apply(s,'confirm_source_mismatch',{
            'issue_type':'other','note':'Unreadable source'})
        s=e.apply(s,'next')
        self.assertEqual(s['current_step'],7)
        doc=final_source_mismatch_document(s)
        self.assertEqual(set(doc),{
            'image','inscription_code','issue_type','note','bounding_boxes'})
        self.assertEqual(doc['bounding_boxes'],{
            '1':{'bbox':[40,0,50,10]},'2':{'bbox':[20,0,30,10]},
            '3':{'bbox':[0,0,10,10]}})
        review=snapshot(s)['markup']
        self.assertNotIn('source-preview',review)
        self.assertNotIn('review-detail',review)
        self.assertNotIn('SOURCE MISMATCH',review)
        s=e.apply(s,'back');self.assertEqual(s['current_step'],3)
        s=e.apply(s,'next');s=e.apply(s,'save')
        reopened=e.open_image(self.image)
        self.assertTrue(reopened['detection_loaded'])
        self.assertEqual(reopened['source_mismatch']['issue_type'],'other')
        self.assertEqual(len(reopened['regions']),3)
        reopened=e.apply(reopened,'save_content')
        self.assertEqual(reopened['source_mismatch']['issue_type'],'other')

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

    def test_old_annotation_schema_is_rejected(self):
        path=self.root/'old.json'
        atomic_write(path,dict(image=self.image.name,
            bounding_boxes={'1':{'bbox':[0,0,9,9],'status':'intact'},
                            '3':{'bbox':[20,0,29,9],'status':'damaged'}},
            reading_order=[3,1],annotations={'1':'寺','3':'永'}))
        with self.assertRaises(ValueError):
            load_annotation(path,self.image.name,[100,100])

    def test_existing_annotation_without_matching_sidecar_keeps_saved_alignment(self):
        s=aligned_state();s['workflow']['reading_order_valid']=True
        save_annotation(s,self.root/'out')
        opened=self.engine.open_image(self.image)
        self.assertEqual(opened['annotations'],s['annotations'])
        opened=self.engine.apply(opened,'save_content')
        self.assertTrue(opened['workflow']['bbox_valid'])
        self.assertTrue(opened['workflow']['alignment_valid'])
        self.assertEqual(opened['annotations'],s['annotations'])
        self.assertEqual(opened['text_sequence'],s['text_sequence'])
        self.assertFalse(opened['workflow']['reading_order_valid'])


if __name__=='__main__':unittest.main()
