from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers.text_extraction.config import load_config
from helpers.text_extraction.types import ExtractionError


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "helpers" / "configs" / "tap_1.json"


class ConfigSchemaTests(unittest.TestCase):
    def test_document_rules_are_loaded_only_from_the_json_file(self) -> None:
        config = load_config(CONFIG_PATH)
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        self.assertEqual((CONFIG_PATH.parent / raw["input_pdf_path"]).resolve(), config.input_pdf_path)
        self.assertEqual("^VĂN BIA SỐ\\s+(?P<number>\\d+)\\s*$", config.title_pattern)
        self.assertEqual("Nguyên văn chữ Hán Nôm", config.content_start)
        self.assertEqual(
            tuple(raw["encoded_fonts"]),
            tuple(font.pdf_name for font in config.encoded_fonts),
        )
        self.assertTrue(all(font.reference_path.is_file() for font in config.encoded_fonts))
        self.assertEqual((40.0, 45.0), (config.top_margin, config.bottom_margin))
        self.assertFalse(hasattr(config, "expected_record_count"))

    def test_legacy_flat_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "legacy.json"
            legacy.write_text('{"output_json": "output.json"}', encoding="utf-8")
            with self.assertRaisesRegex(ExtractionError, "missing: encoded_fonts"):
                load_config(legacy)


if __name__ == "__main__":
    unittest.main()
