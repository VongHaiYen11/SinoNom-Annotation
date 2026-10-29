from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import pymupdf

from helpers.text_extraction.config import load_config
from helpers.text_extraction.font_discovery import synchronize_encoded_fonts


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "helpers" / "configs" / "tap_1.json"


class FontDiscoveryTests(unittest.TestCase):
    def test_refreshes_only_embedded_fonts_with_local_references(self) -> None:
        source = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        source["paths"]["output_json"] = "output.json"
        source["paths"]["glyph_profile"] = "profile.json"
        source["encoded_fonts"] = {}

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / 'fonts.pdf'
            with pymupdf.open() as document:
                page = document.new_page()
                for y, name, filename in ((40, 'Calibri', 'calibri.ttf'),
                                          (80, 'NomNaTong', 'NomNaTong.ttf')):
                    page.insert_font(fontname=name, fontfile=str(ROOT / 'fonts' / filename))
                    page.insert_text((40, y), 'Sample', fontname=name)
                document.save(pdf_path)
            source['input_pdf_path'] = str(pdf_path)
            config_path = Path(directory) / "document.json"
            config_path.write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )
            result = synchronize_encoded_fonts(config_path)
            config = load_config(config_path)

        self.assertTrue(result.changed)
        self.assertEqual(
            (
                "Calibri Regular",
                "Nom Na Tong Regular",
            ),
            result.configured,
        )
        self.assertEqual(result.configured, tuple(font.pdf_name for font in config.encoded_fonts))
        self.assertTrue(all(font.reference_path.is_file() for font in config.encoded_fonts))


if __name__ == "__main__":
    unittest.main()
