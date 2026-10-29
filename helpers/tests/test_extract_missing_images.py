import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from helpers.image_extraction.extract_missing_images import (export_face, group_strips, inscription_ranges,
                                           missing_ids, run, verified_matches, VERIFIED_FACES)
from helpers.text_extraction.types import TextLine


class MissingImageTests(unittest.TestCase):
    def test_report_normalizes_and_unions_groups(self):
        self.assertEqual(missing_ids({'missing_ids': ['00012'], 'groups': [
            {'missing_ids': ['12', '131335']}]}), {'12', '131335'})

    def test_decoded_metadata_order_and_continuation(self):
        lines = [TextLine('VĂN BIA SỐ 1', 1, y0=50),
                 TextLine('Ký hiệu: 55432/', 1), TextLine('55431.', 1),
                 TextLine('Nguyên văn chữ Hán Nôm', 1),
                 TextLine('VĂN BIA SỐ 2', 4, y0=80)]
        records = list(inscription_ranges(lines, r'VĂN BIA SỐ (?P<number>\d+)', 6))
        self.assertEqual(records[0]['ids'], ['55432', '55431'])
        self.assertEqual(records[0]['end'], (4, 80))
        self.assertEqual(records[1]['end'], (7, 0))

    def test_verified_assignments_keep_suffixes_and_exclude_noise(self):
        from unittest.mock import MagicMock
        document = MagicMock()
        face = {'bbox': [0, 0, 100, 200], 'scale': 2, 'strips': 1}
        with patch('helpers.image_extraction.extract_missing_images.group_strips', return_value=[face]):
            for (volume, number), assignments in VERIFIED_FACES.items():
                requested = {name.rstrip('ab') for name, _ in assignments}
                result = verified_matches(document, {'so_van_bia': number}, volume, requested)
                actual = [(o['name'], o['face']['page']) for outputs in result.values() for o in outputs]
                self.assertEqual(actual, assignments)
            result = verified_matches(document, {'so_van_bia': 146}, 'tap_4', {'33651'})
            self.assertEqual([o['name'] for o in result['33651']], ['33651a', '33651b'])

    def test_face_marker_is_not_metadata_continuation(self):
        lines = [TextLine('VĂN BIA SỐ 1', 1),
                 TextLine('Kí hiệu: 22695/22696/22697.', 1),
                 TextLine('<22695>', 1)]
        record = list(inscription_ranges(lines, r'VĂN BIA SỐ (?P<number>\d+)', 2))[0]
        self.assertEqual(record['ids'], ['22695', '22696', '22697'])

    def test_strips_and_small_glyphs(self):
        for count in (2, 4):
            strips = [{'bbox': (50, 50 + i * 100, 250, 150 + i * 100),
                       'width': 600, 'height': 300} for i in range(count)]
            strips.append({'bbox': (10, 10, 20, 20), 'width': 40, 'height': 40})
            result = group_strips(list(reversed(strips)))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['strips'], count)
            self.assertEqual(result[0]['bbox'], [50, 50, 250, 50 + 100 * count])

    def test_export_preserves_strip_positions(self):
        with tempfile.TemporaryDirectory() as tmp, pymupdf.open() as doc:
            page = doc.new_page(width=300, height=300)
            for i, color in enumerate((0xFF0000, 0x0000FF)):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 300), False)
                pix.clear_with(0)
                pix.set_rect(pix.irect, ((color >> 16) & 255, (color >> 8) & 255, color & 255))
                page.insert_image(pymupdf.Rect(50, 50 + i * 100, 250, 150 + i * 100), pixmap=pix)
            face = {'page': 1, **group_strips(page.get_image_info())[0]}
            target = Path(tmp) / '00123.png'
            export_face(doc, face, target)
            image = pymupdf.Pixmap(target)
            self.assertEqual((image.width, image.height), (600, 600))
            self.assertEqual(image.pixel(300, 100), (255, 0, 0))
            self.assertEqual(image.pixel(300, 500), (0, 0, 255))

    def test_missing_second_face_and_duplicate_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tap_1.json').write_text('{}')
            source = root / 'report.json'
            source.write_text(json.dumps({'missing_ids': ['11']}))
            args = argparse.Namespace(report=source, config_dir=root, output_dir=root / 'images', dry_run=True, overwrite=False)
            config = argparse.Namespace(input_pdf_path=root / 'source.pdf', glyph_profile=root / 'profile', encoded_fonts=[],
                                        top_margin=0, bottom_margin=0, footnote_start_pattern=None,
                                        footnote_max_font_size=None, title_pattern='unused')
            with pymupdf.open() as doc:
                doc.new_page(); doc.save(config.input_pdf_path)
            record = {'ids': ['10', '11'], 'so_van_bia': 1, 'start': (1, 0), 'end': (2, 0)}
            faces = [{'page': 1, 'bbox': [0, 0, 100, 100]}, {'page': 1, 'bbox': [0, 100, 100, 200]}]
            with patch('helpers.image_extraction.extract_missing_images.load_config', return_value=config), \
                 patch('helpers.image_extraction.extract_missing_images.load_glyph_profile', return_value={}), \
                 patch('helpers.image_extraction.extract_missing_images.GlyphDecoder'), \
                 patch('helpers.image_extraction.extract_missing_images.inscription_ranges', return_value=[record]) as ranges, \
                 patch('helpers.image_extraction.extract_missing_images.face_candidates', return_value=faces) as candidates:
                report = run(args)
                self.assertEqual(report['results'][0]['face'], faces[1])
                self.assertFalse(args.output_dir.exists())
                candidates.return_value = faces[:1]
                self.assertEqual(run(args)['results'][0]['status'], 'needs_review')
                candidates.return_value = faces
                ranges.return_value = [record, {**record, 'so_van_bia': 2}]
                self.assertEqual(run(args)['results'][0]['status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
