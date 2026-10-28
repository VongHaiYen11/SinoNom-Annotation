"""Legacy annotation-domain and document compatibility regressions."""
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.io import atomic_write, final_source_mismatch_document, validate_source_mismatch_document
from annotation.state import set_verified_content
from annotation.workflow import Workflow

TITLE = 'Nguyên văn chữ Hán Nôm'


class CurrentWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.image = self.root / '1.png'
        Image.new('RGB', (100, 100)).save(self.image)
        self.source = self.root / 'source.json'
        atomic_write(self.source, [{'noi_dung': [{'ky_hieu': '1', 'chuyen_muc': [
            {'tieu_de': TITLE, 'van_ban': '永寺'}]}]}])
        self.output = self.root / 'out'
        self.engine = Workflow(SimpleNamespace(
            source_json=self.source, output_dir=self.output,
            content_titles=(TITLE,), annotation_title=TITLE, skip_detection=True))
        self.addCleanup(self.engine._preview_cache.cleanup)

    def aligned(self, text='永寺', count=2):
        state = self.engine.apply(self.engine.open_image(self.image), 'next')
        set_verified_content(state, state['draft_content'], text)
        for x in range(count):
            state = self.engine.apply(state, 'add', {'bbox': [x * 20, 0, x * 20 + 10, 10]})
        if count > len(text):
            state = self.engine.apply(state, 'confirm_source_mismatch', {'issue_type': 'missing_text'})
        return self.engine.apply(state, 'sort_boxes')

    def test_placeholder_flags_follow_submitted_assignment(self):
        for placeholder in ('□', '@'):
            with self.subTest(placeholder=placeholder):
                state = self.aligned(placeholder + '永')
                state = self.engine.apply(state, 'next')
                flags = ('unknown', 'unavailable_font', 'expert_prediction', 'suspicious')
                payload = {
                    'statuses': {'1': 'intact', '2': 'damaged' if placeholder == '□' else 'intact'},
                    'damage_levels': {'1': None, '2': 2 if placeholder == '□' else None},
                    'unknowns': {'1': False, '2': placeholder == '□'},
                    'unavailable_fonts': {'1': False, '2': placeholder == '@'},
                    'expert_predictions': {'1': False, '2': False},
                    'suspiciouses': {'1': False, '2': False},
                    'textSequence': ['永', placeholder], 'tokenOrder': ['2', '1'],
                }
                accepted = self.engine.apply(state,'reorder_text',{
                    'sequence':payload['textSequence'],'token_order':payload['tokenOrder']})
                from annotation.status import replace_statuses, require_damage_levels
                mapping=accepted['region_uid_by_box_id']
                remap=lambda values:{mapping[key]:value for key,value in values.items()}
                replace_statuses(accepted,remap(payload['statuses']),remap(payload['unknowns']),
                    remap(payload['unavailable_fonts']),remap(payload['expert_predictions']),
                    remap(payload['suspiciouses']),remap(payload['damage_levels']))
                require_damage_levels(accepted)
                self.assertEqual(accepted['annotations'], {'1': '永', '2': placeholder})
                self.assertEqual(accepted['bounding_boxes']['1']['status'], 'intact')
                self.assertTrue(all(not accepted['bounding_boxes']['1'][flag] for flag in flags))

    def test_geometry_edit_does_not_mutate_previous_snapshot(self):
        state = self.aligned()
        before = deepcopy(state)
        uid = next(iter(state['regions']))
        updated = self.engine.apply(state, 'update', {'uid': uid, 'bbox': [1, 1, 9, 9]})
        self.assertEqual(state, before)
        box_id = updated['box_id_by_region'][uid]
        self.assertEqual(updated['bounding_boxes'][box_id]['bbox'], [1, 1, 9, 9])
        self.assertEqual(updated['annotations'], before['annotations'])

    def test_cleared_or_duplicate_orders_block_next_even_with_old_mapping(self):
        state = self.aligned()
        for orders in ((None, None), (1, 1)):
            with self.subTest(orders=orders):
                boxes = deepcopy(state['regions'])
                for box, order in zip(boxes.values(), orders):
                    box['order'] = order
                with self.assertRaisesRegex(ValueError, 'reading order'):
                    self.engine.apply(state, 'next', {'boxes': boxes})

    def test_failed_commit_does_not_invalidate_previous_mismatch(self):
        state = self.aligned(count=3)
        before = deepcopy(state)
        boxes = deepcopy(state['regions'])
        boxes.pop(next(iter(boxes)))
        with self.assertRaises(ValueError):
            self.engine.apply(state, 'commit_boxes', {
                'boxes': boxes, 'unavailable_fonts': {next(iter(boxes)): 'invalid'}})
        self.assertEqual(state, before)

    def test_edit_source_after_reopen_invalidates_saved_alignment(self):
        state = self.engine.apply(self.aligned(), 'next')
        while state['current_step'] < 7:
            state = self.engine.apply(state, 'next')
        self.engine.apply(state, 'save')
        reopened = self.engine.open_image(self.image)
        reopened = self.engine.apply(reopened, 'field', {
            'path': ['noi_dung', 0, 'chuyen_muc', 0, 'van_ban'], 'value': '寺永'})
        reopened = self.engine.apply(reopened, 'save_content')
        self.assertFalse(reopened['workflow']['alignment_valid'])
        self.assertEqual(reopened['annotations'], {})

    def test_missing_source_document_cannot_replace_source_characters(self):
        state = self.engine.apply(self.aligned(count=3), 'next')
        while state['current_step'] < 7:
            state = self.engine.apply(state, 'next')
        document = final_source_mismatch_document(state)
        document = deepcopy(document)
        document['annotations']['1'] = '假'
        with self.assertRaises(ValueError):
            validate_source_mismatch_document(document, self.image.name, [100, 100])

    def test_failed_save_preserves_annotation_content_and_sidecar(self):
        state = self.engine.apply(self.aligned(), 'next')
        while state['current_step'] < 7:
            state = self.engine.apply(state, 'next')
        state = self.engine.apply(state, 'save')
        while state['current_step'] > 2:
            state = self.engine.apply(state, 'back')
        state = self.engine.apply(state, 'field', {
            'path': ['noi_dung', 0, 'chuyen_muc', 0, 'van_ban'], 'value': '永文'})
        while state['current_step'] < 7:
            state = self.engine.apply(state, 'next')
        before = {path: path.read_bytes() for path in self.output.rglob('*.json')}
        for failing_write in ('annotation.workflow.save_annotation', 'annotation.workflow.atomic_write'):
            with self.subTest(failing_write=failing_write):
                with patch(failing_write, side_effect=OSError('save failed')):
                    with self.assertRaisesRegex(OSError, 'save failed'):
                        self.engine.apply(state, 'save')
                self.assertEqual({path: path.read_bytes() for path in self.output.rglob('*.json')}, before)


if __name__ == '__main__':
    unittest.main()
