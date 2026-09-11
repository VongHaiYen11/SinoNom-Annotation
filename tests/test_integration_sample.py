from __future__ import annotations

import unittest
from pathlib import Path

from extract_pdf import extract_document, load_config, serialize_jsonl


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "tap_1.json"


class SamplePdfIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(CONFIG_PATH.is_file(), "sample config is unavailable")
    def test_sample_pdf_contains_100_reproducible_records(self) -> None:
        config = load_config(CONFIG_PATH)
        if not config.input_pdf.is_file() or not config.glyph_profile.is_file():
            self.skipTest("sample PDF or generated glyph profile is unavailable")

        records, _ = extract_document(config)

        self.assertEqual(list(range(1, 101)), [x["so_van_bia"] for x in records])
        self.assertEqual(["12305", "12306"], records[0]["ky_hieu_vnchn"])
        self.assertTrue(records[0]["noi_dung"])
        self.assertEqual(serialize_jsonl(records), serialize_jsonl(records))


if __name__ == "__main__":
    unittest.main()
