"""Damage classification and real Apply Changes callback regression tests."""
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.state import new_state, set_verified_content, initialize_alignment
from annotation.bbox import add_bbox
from annotation.status import update_status, confirm_status, replace_statuses
from annotation.io import atomic_write, load_annotation


class DamageLevels(unittest.TestCase):
    def state(self):
        state = new_state()
        state.update(image='1.png', image_size=[100, 100], current_step=4, code='1', draft_content={'noi_dung': [{'ky_hieu': '1', 'chuyen_muc': [{'tieu_de': 'Nguyên văn chữ Hán Nôm', 'van_ban': '永寺'}]}]})
        set_verified_content(state, {}, '永寺')
        for x in (10, 40):
            add_bbox(state, [x, 10, x + 20, 30])
        initialize_alignment(state)
        return state

    def test_levels_validation_and_transitions(self):
        s = self.state()
        uid = s['region_uid_by_box_id']['1']
        update_status(s, uid, 'damaged')
        with self.assertRaisesRegex(ValueError, 'boxes: 1'):
            confirm_status(s)
        for level in (1, 2, 3):
            update_status(s, uid, 'damaged', damage_level=level)
            confirm_status(s)
            self.assertEqual(s['bounding_boxes']['1']['damage_level'], level)
        for level in (True, False, 0, 4, '2', 2.0):
            before = deepcopy(s)
            with self.assertRaises(ValueError):
                replace_statuses(s, {u: b['status'] for u, b in s['regions'].items()},
                                 damage_levels={u: level for u in s['regions']})
            self.assertEqual(s, before)
        update_status(s, uid, 'intact')
        update_status(s, uid, 'damaged', expert_prediction=True)
        self.assertIsNone(s['regions'][uid]['damage_level'])
        initialize_alignment(s, list(reversed(s['regions'])))
        self.assertIsNone(s['regions'][uid]['damage_level'])

    def test_workspace_status_validation_does_not_write_files(self):
        from annotation.workspace import ensure_workspace,sync_workspace,workspace_issues,materialize_workspace
        original=self.state();original['current_step']=3
        model=deepcopy(ensure_workspace(original))
        ordered=sorted(model['boxes'],key=lambda uid:model['boxes'][uid]['order'])
        model['confirmed']={uid:e['char_id'] for uid,e in zip(ordered,model['entries'])}
        uid=ordered[0];model['boxes'][uid].update(status='damaged',damage_level=None)
        candidate=deepcopy(original);sync_workspace(candidate,model)
        self.assertTrue(any('damage level' in issue['reason'] for issue in workspace_issues(candidate)))
        self.assertEqual(original['regions'][uid]['status'],'intact')
        with self.assertRaises(ValueError):materialize_workspace(candidate)
        model['boxes'][uid]['damage_level']=2
        sync_workspace(candidate,model);materialize_workspace(candidate)
        self.assertEqual(candidate['bounding_boxes']['1']['damage_level'],2)
        self.assertEqual(candidate['annotations'],{'1':'永','2':'寺'})


    def test_legacy_json_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            from crop.crop import image_resize, crop_document
            s = self.state()
            boxes = deepcopy(s['bounding_boxes'])
            boxes['1']['status'] = 'damaged'
            for box in boxes.values():
                box.pop('damage_level', None)
            doc = dict(image='1.png', bounding_boxes=boxes, annotations=s['annotations'],
                       image_resize=image_resize([100, 100], [100, 100]), crop=crop_document('1.png', [0, 0, 100, 100], [100, 100])['crop'])
            path = Path(folder) / '1.json'
            atomic_write(path, doc)
            original = path.read_bytes()
            self.assertEqual(load_annotation(path, '1.png', [100, 100]), doc)
            self.assertEqual(path.read_bytes(), original)

    def test_workspace_missing_entry_moves_review_mark_and_preserves_invalid_draft(self):
        from annotation.workspace import ensure_workspace,sync_workspace,materialize_workspace,workspace_issues
        from ui.editor import snapshot
        import xml.etree.ElementTree as ET
        state=self.state();state.update(current_step=3,image_url='image.jpg')
        add_bbox(state,[70,10,90,30])
        model=deepcopy(ensure_workspace(state))
        miss=dict(char_id='miss',value='MISS',source_index=None,type='missing',excluded=False)
        for position in (2,0,1):
            model['entries']=[e for e in model['entries'] if e['char_id']!='miss']
            model['entries'].insert(position,miss)
            ordered=sorted(model['boxes'],key=lambda uid:model['boxes'][uid]['order'])
            model['confirmed']={uid:e['char_id'] for uid,e in zip(ordered,model['entries'])}
            sync_workspace(state,model);materialize_workspace(state)
            review=deepcopy(state);review['current_step']=7
            markup=snapshot(review)['markup'];start=markup.index('<svg class="annotation-canvas"')
            svg=ET.fromstring(markup[start:markup.index('</svg>',start)+6])
            marked=[g.attrib['data-box-id'] for g in svg.iter('g') if 'data-box-id' in g.attrib and g.find("g[@data-miss-mark='1']") is not None]
            self.assertEqual(marked,[str(position+1)])
        before=deepcopy(state)
        model['boxes'][ordered[0]].update(status='damaged',damage_level=None)
        candidate=deepcopy(state);sync_workspace(candidate,model)
        self.assertTrue(workspace_issues(candidate))
        self.assertEqual(state,before)
