"""Missing configured sections remain editable and survive Review/export/reopen."""
import json
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.io import atomic_write, read_json
from annotation.state import new_state
from annotation.text_extraction import (
    complete_content_record, content_fields, content_document,
    edit_content_field, save_content_document,
)
from annotation.export import collect_content_documents, save_export_archive
from annotation.workflow import Workflow


class ContentCompletion(unittest.TestCase):
    titles = ('Nguyên văn chữ Hán Nôm', 'Phiên âm Hán Việt', 'Dịch nghĩa', 'Toát yếu')
    metadata = (('Tên bia', 'ten_bia'),)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / '00001.png'
        Image.new('RGB', (100, 100)).save(self.image)
        self.source = self.root / 'source.json'
        self.record = {'extra': {'preserve': True}, 'noi_dung': [
            {'ky_hieu': '2', 'chuyen_muc': []},
            {'ky_hieu': '1', 'chuyen_muc': [
                {'tieu_de': self.titles[0], 'van_ban': '永寺', 'extra': 'keep'},
                {'tieu_de': 'Unconfigured', 'van_ban': 'Keep this too'}]},
        ]}
        atomic_write(self.source, [self.record])
        self.original = self.source.read_bytes()
        self.options = SimpleNamespace(
            source_json=self.source, output_dir=self.root / 'out',
            content_titles=self.titles, metadata_fields=self.metadata,
            annotation_title=self.titles[0])
        self.engine = Workflow(self.options)
        self.addCleanup(self.engine._preview_cache.cleanup)

    def fields(self, state):
        return content_fields(state['draft_content'], state['code'], self.titles, self.metadata)

    def edit(self, state, title, value):
        field = next(field for field in self.fields(state) if field['title'] == title)
        return self.engine.apply(state, 'field', {'path': field['path'], 'value': value})

    def finish(self, state):
        state = self.engine.apply(state, 'next')
        for x in (10, 40):
            state = self.engine.apply(state, 'add', {'bbox': [x, 10, x + 20, 30]})
        boxes = deepcopy(state['regions'])
        for index, box in enumerate(boxes.values(), 1):
            box['order'] = index
        state = self.engine.apply(state, 'next', {'boxes': boxes})
        state = self.engine.apply(state, 'next')
        state = self.engine.apply(state, 'next')
        self.assertEqual(state['current_step'], 7)
        return self.engine.apply(state, 'save')

    def test_fields_default_to_empty_without_mutating_source_or_other_faces(self):
        before = deepcopy(self.record)
        fields = content_fields(self.record, '00001', self.titles, self.metadata)
        self.assertEqual([f['title'] for f in fields], ['Tên bia', *self.titles])
        self.assertEqual([f['value'] for f in fields], ['', '永寺', '', '', ''])
        self.assertEqual(self.record, before)
        summary = fields[-1]
        edited = edit_content_field(self.record, '00001', summary['path'], 'Bổ sung', self.titles, self.metadata)
        self.assertEqual(edited['noi_dung'][0], before['noi_dung'][0])
        self.assertEqual(edited['extra'], before['extra'])
        self.assertEqual(edited['noi_dung'][1]['chuyen_muc'][:2], before['noi_dung'][1]['chuyen_muc'])
        self.assertEqual(content_fields(edited, '00001', self.titles, self.metadata)[-1]['value'], 'Bổ sung')
        self.assertEqual(complete_content_record(edited, '00001', self.titles, self.metadata), edited)
        with self.assertRaisesRegex(ValueError, 'Only configured'):
            edit_content_field(self.record, '00001', ('noi_dung', 0, 'chuyen_muc'), 'bad', self.titles, self.metadata)

    def test_null_or_missing_values_are_editable_empty_text(self):
        self.record['ten_bia'] = None
        self.record['noi_dung'][1]['chuyen_muc'].extend([
            {'tieu_de': 'Toát yếu', 'van_ban': None}, {'tieu_de': 'Dịch nghĩa'}])
        fields = content_fields(self.record, '1', self.titles, self.metadata)
        self.assertTrue(all(isinstance(f['value'], str) for f in fields))
        self.assertEqual(fields[-1]['value'], '')
        self.assertIsNone(self.record['noi_dung'][1]['chuyen_muc'][-2]['van_ban'])

    def test_added_summary_survives_save_export_and_new_session(self):
        state = self.engine.open_image(self.image)
        state = self.edit(state, 'Toát yếu', 'Nội dung bổ sung\nDòng thứ hai')
        state = self.edit(state, 'Tên bia', 'Tên mới')
        saved = self.finish(state)
        documents = collect_content_documents([self.image], self.engine.output, titles=self.engine.verification_titles)
        values = documents[0]['content']
        self.assertEqual(values['Toát yếu'], 'Nội dung bổ sung\nDòng thứ hai')
        self.assertEqual(values['Tên bia'], 'Tên mới')
        self.assertEqual(values['Phiên âm Hán Việt'], '')
        self.assertEqual(values['Dịch nghĩa'], '')
        archive = save_export_archive([], documents, self.engine.output)
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(json.loads(bundle.read('inscription_content.json')), documents)
        reopened_engine = Workflow(self.options)
        self.addCleanup(reopened_engine._preview_cache.cleanup)
        reopened = reopened_engine.open_image(self.image)
        self.assertEqual(next(f['value'] for f in self.fields(reopened) if f['title'] == 'Toát yếu'), values['Toát yếu'])
        self.assertEqual(self.source.read_bytes(), self.original)
        # Editing supplementary text must preserve an established alignment.
        while saved['current_step'] != 2:
            saved = self.engine.apply(saved, 'back')
        alignment = deepcopy(saved['annotations'])
        saved = self.edit(saved, 'Dịch nghĩa', 'Bản dịch mới')
        saved = self.engine.apply(saved, 'save_content')
        self.assertEqual(saved['annotations'], alignment)

    def test_missing_original_text_opens_empty_and_requires_text_before_next(self):
        self.record['noi_dung'][1].pop('chuyen_muc')
        atomic_write(self.source, [self.record])
        state = self.engine.open_image(self.image)
        self.assertTrue(all(f['value'] == '' for f in self.fields(state)))
        with self.assertRaisesRegex(ValueError, 'no characters'):
            self.engine.apply(state, 'next')
        state = self.edit(state, self.titles[0], '永寺')
        self.assertEqual(self.engine.apply(state, 'next')['current_step'], 3)

    def test_legacy_registry_fills_missing_sections_and_restores_added_text(self):
        self.finish(self.engine.open_image(self.image))
        legacy = {'image': self.image.name, 'inscription_code': self.image.stem,
                  'content': {self.titles[0]: '永寺', 'Toát yếu': 'Đã bổ sung', 'Dịch nghĩa': None}}
        atomic_write(self.engine.output / '.state/content.json', [legacy])
        fields = {f['title']: f['value'] for f in self.fields(self.engine.open_image(self.image))}
        self.assertEqual(fields['Toát yếu'], 'Đã bổ sung')
        self.assertEqual(fields['Dịch nghĩa'], '')
        self.assertEqual(fields['Phiên âm Hán Việt'], '')
        projected = collect_content_documents([self.image], self.engine.output, titles=self.engine.verification_titles)
        self.assertTrue(all(isinstance(value, str) for value in projected[0]['content'].values()))
        document = content_document(self.image.name, self.image.stem, self.record, self.titles, self.metadata)
        save_content_document(document, self.engine.output, self.engine.verification_titles)
        self.assertEqual(read_json(self.engine.output / '.state/content.json')[0]['content']['Toát yếu'], '')

    def test_ui_exposes_missing_fields_and_accepts_their_browser_draft(self):
        from app import create_app, parser
        config = self.root / 'config.json'
        atomic_write(config, {'records': {'content': {
            'start_heading': self.titles[0], 'section_headings': list(self.titles)}}})
        app = create_app(parser().parse_args([
            '--config', str(config), '--image-dir', str(self.root),
            '--source-json', str(self.source), '--output-dir', str(self.engine.output), '--skip-detection']))
        functions = [f for f in app.fns.values() if f.fn]
        opening = next(f for f in functions if f.fn.__name__ == 'open_image')
        result = opening.fn(dict(active=new_state(), drafts={}), str(self.image.resolve()))
        bridge_index = next(i for i, output in enumerate(opening.outputs) if output.elem_id == 'content-draft-bridge')
        browser = json.loads(result[bridge_index])
        self.assertEqual(set(entry['title'] for entry in browser.values()), set(self.titles))
        summary = next(entry for entry in browser.values() if entry['title'] == 'Toát yếu')
        self.assertEqual(summary['value'], '')
        summary['value'] = 'Bổ sung qua giao diện'
        next_step = next(f.fn for f in functions if f.fn.__name__ == 'next_with_progress')
        updated = list(next_step(result[0], json.dumps(browser, ensure_ascii=False)))[-1][0]['active']
        self.assertEqual(updated['current_step'], 3)
        self.assertEqual(next(f['value'] for f in self.fields(updated) if f['title'] == 'Toát yếu'), summary['value'])
        self.assertEqual(self.source.read_bytes(), self.original)
