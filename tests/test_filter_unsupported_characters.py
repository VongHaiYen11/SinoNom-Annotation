"""Tests for the JSON/JSONL unsupported-glyph review utility."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "filter_unsupported_characters.py"
SPEC = importlib.util.spec_from_file_location("filter_unsupported_characters", MODULE_PATH)
assert SPEC and SPEC.loader
FILTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTER)


class FilterUnsupportedCharactersTests(unittest.TestCase):
    def test_filters_records_and_reports_character_paths(self) -> None:
        records = [
            {"so_van_bia": 1, "ten_bia": "Bia A", "noi_dung": []},
            {"so_van_bia": 2, "ten_bia": "Bia 𠀀", "noi_dung": [{"van_ban": "Hán 𠀀"}]},
        ]

        filtered = FILTER.filter_records(records, {ord(char) for char in "Bia AHán"})

        self.assertEqual([record["so_van_bia"] for record in filtered], [2])
        self.assertEqual(filtered[0]["ky_tu_khong_ho_tro"], [{
            "ky_tu": "𠀀", "ma_unicode": "U+20000", "so_lan": 2,
            "vi_tri": ["$.ten_bia", "$.noi_dung[0].van_ban"],
        }])
        self.assertNotIn("ky_tu_khong_ho_tro", records[1])

    def test_loads_jsonl_and_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "input.jsonl"
            output = folder / "output.jsonl"
            source.write_text('{"so_van_bia":1,"ten_bia":"A"}\n{"so_van_bia":2,"ten_bia":"B"}\n', encoding="utf-8")
            records = FILTER.load_records(source)
            FILTER.write_records(output, FILTER.filter_records(records, {ord("A")}))

            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                "so_van_bia": 2,
                "ten_bia": "B",
                "ky_tu_khong_ho_tro": [{
                    "ky_tu": "B", "ma_unicode": "U+0042", "so_lan": 1,
                    "vi_tri": ["$.ten_bia"],
                }],
            })
