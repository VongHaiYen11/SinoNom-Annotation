from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from text_extraction.config import load_config
from text_extraction.font_discovery import synchronize_encoded_fonts


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "tap_1.json"
PDF_PATH = ROOT / "input" / "tap1-short-21-page.pdf"


class FontDiscoveryTests(unittest.TestCase):
    def test_refreshes_only_embedded_fonts_with_local_references(self) -> None:
        source = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        source["input_pdf_path"] = str(PDF_PATH)
        source["paths"]["output_json"] = "output.json"
        source["paths"]["glyph_profile"] = "profile.json"
        source["encoded_fonts"] = {}

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "document.json"
            config_path.write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )
            result = synchronize_encoded_fonts(config_path)
            config = load_config(config_path)

        self.assertTrue(result.changed)
        self.assertEqual(
            (
                "Calibri",
                "Cambria-Bold",
                "NomNaTong",
                "PalatinoLinotype",
                "PalatinoLinotype,Bold",
                "PalatinoLinotype,BoldItalic",
            ),
            result.configured,
        )
        self.assertEqual(result.configured, tuple(font.pdf_name for font in config.encoded_fonts))
        self.assertTrue(all(font.reference_path.is_file() for font in config.encoded_fonts))


if __name__ == "__main__":
    unittest.main()
