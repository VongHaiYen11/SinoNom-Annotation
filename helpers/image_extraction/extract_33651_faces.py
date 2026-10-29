"""Re-extract inscription 146 from volume 4 with distinct 33651a/b markers."""
from pathlib import Path
import sys

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from helpers.text_extraction.config import load_config, load_glyph_profile
from helpers.text_extraction.decoder import GlyphDecoder
from helpers.text_extraction.parser import parse_records_with_issues
from helpers.text_extraction.output import atomic_write, prepare_records_for_output, serialize_pretty_json


def main():
    config = load_config(ROOT / 'helpers/configs/tap_4.json')
    # PDF pages 543–549 contain this inscription; page 550 starts the next.
    with pymupdf.open(config.input_pdf_path) as document:
        document.select(list(range(542, 549)))
        decoder = GlyphDecoder(document, load_glyph_profile(config.glyph_profile),
                               tuple(font.pdf_name for font in config.encoded_fonts))
        lines = decoder.extract_lines(config.top_margin, config.bottom_margin,
                                      config.footnote_start_pattern,
                                      config.footnote_max_font_size)
    records, warnings, issues = parse_records_with_issues(lines, config)
    if len(records) != 1 or records[0]['so_van_bia'] != 146:
        raise ValueError('Expected exactly inscription 146')
    record = records[0]
    expected = ['33651a', '33651b']
    if record['ky_hieu_vnchn'] != expected or [f['ky_hieu'] for f in record['noi_dung']] != expected:
        raise ValueError('Face markers are missing, unknown or merged')
    if any(issue.get('loi') for issue in issues):
        raise ValueError(str(issues))
    destination = ROOT / 'outputs/extraction/33651_faces.json'
    atomic_write(destination, serialize_pretty_json(prepare_records_for_output(records)))
    for warning in warnings:
        print(f'Warning: {warning}')
    print(destination)
    for face in record['noi_dung']:
        print(face['ky_hieu'], [(s['tieu_de'], len(s['van_ban'])) for s in face['chuyen_muc']])


if __name__ == '__main__':
    main()
