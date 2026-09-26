"""Folder export includes only images committed from the Review step."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.export import collect_annotations, collect_content_documents
from annotation.io import atomic_write, read_json
from annotation.text_extraction import CONTENT_TITLES, content_fields
from annotation.workflow import Workflow


class FolderExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.images = [self.root / f'{code}.png' for code in ('1', '2')]
        for image in self.images:
            Image.new('RGB', (100, 100)).save(image)
        self.source = self.root / 'source.json'
        atomic_write(self.source, [{'noi_dung': [
            {'ky_hieu': str(code), 'chuyen_muc': [
                {'tieu_de': 'Nguyên văn chữ Hán Nôm', 'van_ban': '永寺'}]}
            for code in (1, 2)]}])
        self.output = self.root / 'out'
        self.engine = Workflow(SimpleNamespace(output_dir=self.output, source_json=self.source))

    def complete(self, image):
        e = self.engine
        s = e.apply(e.open_image(image), 'save_content')
        s = e.apply(s, 'next')
        for x in (0, 20):
            s = e.apply(s, 'add', {'bbox': [x, 0, x + 10, 10]})
        for _ in range(4):
            s = e.apply(s, 'next')
        return e.apply(s, 'save')

    def export(self):
        return collect_annotations(self.images, self.output)

    def test_save_content_creates_separate_committed_object(self):
        state = self.engine.open_image(self.images[0])
        state = self.engine.apply(state, 'save_content')
        registry = self.output / '.state/content.json'
        saved = read_json(registry)[0]
        self.assertEqual(saved['image'], '1.png')
        self.assertEqual(saved['inscription_code'], '1')
        self.assertEqual(list(saved['content']), list(CONTENT_TITLES))
        self.assertEqual(saved['content']['Nguyên văn chữ Hán Nôm'], '永寺')
        self.assertIsNone(saved['content']['Dịch nghĩa'])
        self.assertEqual(collect_content_documents(self.images, self.output), [saved])
        with self.assertRaisesRegex(ValueError, 'No images have been saved'):
            self.export()

        # Applying an edit changes only the draft until Save content is pressed again.
        field = content_fields(state['draft_content'], state['code'])[0]
        state = self.engine.apply(state, 'field', {'path': field['path'], 'value': '寺永'})
        self.assertEqual(read_json(registry), [saved])
        self.engine.apply(state, 'save_content')
        updated = read_json(registry)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['content']['Nguyên văn chữ Hán Nôm'], '寺永')

    def test_unsaved_draft_changes_are_excluded(self):
        first = self.complete(self.images[0])
        self.complete(self.images[1])
        first = self.engine.apply(first, 'back')
        first = self.engine.apply(first, 'crop', {'bbox': [1, 2, 90, 95]})
        docs = self.export()
        self.assertEqual([d['image'] for d in docs], ['1.png', '2.png'])
        self.assertEqual(docs[0]['crop']['top_left'], [0, 0])
        self.assertEqual(docs[1]['crop']['bottom_right'], [100, 100])
        self.assertEqual(docs[0]['annotations'], {'1': '永', '2': '寺'})
        self.assertEqual(read_json(self.output / '1.json')['crop']['top_left'], [0, 0])

    def test_content_editor_newlines_round_trip_to_json(self):
        state = self.engine.open_image(self.images[0])
        field = content_fields(state['draft_content'], state['code'])[0]

        state = self.engine.apply(
            state, 'field', {'path': field['path'], 'value': '永\n寺'}
        )
        state = self.engine.apply(state, 'save_content')
        self.assertEqual(
            read_json(self.source)[0]['noi_dung'][0]['chuyen_muc'][0]['van_ban'],
            '永\n寺',
        )
        self.assertIn('永\\n寺', self.source.read_text(encoding='utf-8'))

        field = content_fields(state['draft_content'], state['code'])[0]
        state = self.engine.apply(
            state, 'field', {'path': field['path'], 'value': '永寺'}
        )
        self.engine.apply(state, 'save_content')
        self.assertEqual(
            read_json(self.source)[0]['noi_dung'][0]['chuyen_muc'][0]['van_ban'],
            '永寺',
        )
        self.assertNotIn('永\\n寺', self.source.read_text(encoding='utf-8'))

    def test_only_review_saved_images_are_included(self):
        self.complete(self.images[0])
        self.assertEqual([doc['image'] for doc in self.export()], ['1.png'])
        # Opening or completing a draft without Review save does not add it.
        self.engine.open_image(self.images[1])
        self.assertEqual([doc['image'] for doc in self.export()], ['1.png'])

    def test_source_edit_does_not_replace_last_review_save(self):
        for image in self.images:
            self.complete(image)
        source = read_json(self.source)
        source[0]['noi_dung'][0]['chuyen_muc'][0]['van_ban'] = '寺永'
        atomic_write(self.source, source)
        self.assertEqual([doc['image'] for doc in self.export()], ['1.png', '2.png'])

    def test_no_review_saves_rejects_empty_download(self):
        with self.assertRaisesRegex(ValueError, 'No images have been saved'):
            self.export()
        with self.assertRaisesRegex(ValueError, 'No content has been saved'):
            collect_content_documents(self.images, self.output)

    def test_invalid_crop_rejected(self):
        for image in self.images:
            self.complete(image)
        doc = read_json(self.output / '1.json')
        doc['crop']['top_left'] = [-1, 0]
        atomic_write(self.output / '1.json', doc)
        with self.assertRaises(ValueError):
            self.export()
