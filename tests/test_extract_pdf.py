from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extract_pdf import (
    ExtractConfig,
    ExtractionError,
    MetadataSpec,
    TextLine,
    atomic_write,
    parse_records,
    serialize_jsonl,
)


def line(text: str, page: int = 1) -> TextLine:
    return TextLine(text=text, page_number=page)


def config(**overrides) -> ExtractConfig:
    values = {
        "input_pdf": Path("input.pdf"),
        "output_jsonl": Path("output.jsonl"),
        "glyph_profile": Path("profile.json"),
        "metadata": (
            MetadataSpec("Tên bia", "ten_bia"),
            MetadataSpec("Địa điểm", "dia_diem"),
            MetadataSpec("Niên đại", "nien_dai"),
            MetadataSpec("Kí hiệu VNCHN", "ky_hieu_vnchn", "identifiers"),
        ),
        "expected_record_count": 1,
    }
    values.update(overrides)
    return ExtractConfig(**values)


class ParserTests(unittest.TestCase):
    def test_metadata_faces_sections_and_missing_closing_bracket(self) -> None:
        source = [
            line("VĂN BIA SỐ 1"),
            line("Tên bia: Phúc Giao tự Hậu Phật bí"),
            line("Địa điểm: Bia gồm 03 mặt khắc chữ, dựng tại xã An Tiêm,"),
            line("huyện Tây Quan, phủ Thái Bình."),
            line("Niên đại: Vĩnh Tộ 10 (1628)"),
            line("Kí hiệu VNCHN: <4349><4350><4351>"),
            line("Nguyên văn chữ Hán Nôm:"),
            line("<4349>"),
            line("原文一"),
            line("<4350"),
            line("原文二"),
            line("Phiên âm Hán Việt:"),
            line("<4349>"),
            line("Phiên âm một"),
            line("<4350> Phiên âm hai"),
            line("Toát yếu:"),
            line("<4349>"),
            line("Tóm tắt"),
        ]

        records, warnings = parse_records(source, config())

        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual(
            "Bia gồm 03 mặt khắc chữ, dựng tại xã An Tiêm, huyện Tây Quan, phủ Thái Bình.",
            record["dia_diem"],
        )
        self.assertEqual(["4349", "4350", "4351"], record["ky_hieu_vnchn"])
        self.assertEqual(["4349", "4350", "4351"], [x["ky_hieu"] for x in record["noi_dung"]])
        first_sections = record["noi_dung"][0]["chuyen_muc"]
        self.assertEqual(
            ["Nguyên văn chữ Hán Nôm", "Phiên âm Hán Việt", "Toát yếu"],
            [item["tieu_de"] for item in first_sections],
        )
        self.assertEqual("Phiên âm hai", record["noi_dung"][1]["chuyen_muc"][1]["van_ban"])
        self.assertIn("không tìm thấy nội dung cho <4351>", "\n".join(warnings))

    def test_unmarked_content_is_preserved_and_warned(self) -> None:
        source = [
            line("VĂN BIA SỐ 1"),
            line("Tên bia: A"),
            line("Địa điểm: B"),
            line("Niên đại: C"),
            line("Kí hiệu VNCHN: <10>"),
            line("Nguyên văn chữ Hán Nôm:"),
            line("Đoạn chưa có marker"),
            line("<10>"),
            line("Nội dung mặt bia"),
        ]

        records, warnings = parse_records(source, config())

        self.assertEqual(None, records[0]["noi_dung"][-1]["ky_hieu"])
        self.assertEqual(
            "Đoạn chưa có marker",
            records[0]["noi_dung"][-1]["chuyen_muc"][0]["van_ban"],
        )
        self.assertTrue(any("không thuộc marker" in item for item in warnings))

    def test_abbreviated_and_accent_variant_labels(self) -> None:
        source = [
            line("VĂN BIA SỐ 1"),
            line("Tên bia: A"),
            line("Địa điểm: B"),
            line("Niên đại: C"),
            line("Ký hiệu: <10>"),
            line("Nguyên văn chữ Hán:"),
            line("<10>"),
            line("原文"),
            line("Phiên âm:"),
            line("<10>"),
            line("Phiên âm thử"),
        ]

        records, _ = parse_records(source, config())

        self.assertEqual(["10"], records[0]["ky_hieu_vnchn"])
        self.assertEqual(
            ["Nguyên văn chữ Hán Nôm", "Phiên âm Hán Việt"],
            [
                section["tieu_de"]
                for section in records[0]["noi_dung"][0]["chuyen_muc"]
            ],
        )

    def test_non_consecutive_titles_fail(self) -> None:
        source = [line("VĂN BIA SỐ 1"), line("VĂN BIA SỐ 3")]
        with self.assertRaisesRegex(ExtractionError, "not consecutive"):
            parse_records(source, config(expected_record_count=None))

    def test_jsonl_is_deterministic_and_content_is_last(self) -> None:
        record = {
            "so_van_bia": 1,
            "ten_bia": "Bia thử",
            "noi_dung": [{"ky_hieu": "1", "chuyen_muc": []}],
        }
        first = serialize_jsonl([record])
        second = serialize_jsonl([record])
        self.assertEqual(first, second)
        self.assertEqual(
            ["so_van_bia", "ten_bia", "noi_dung"],
            list(json.loads(first).keys()),
        )
        with self.assertRaisesRegex(ExtractionError, "U\+FFFD"):
            serialize_jsonl([{"noi_dung": "bad\ufffdtext"}])

    def test_atomic_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "result.jsonl"
            atomic_write(target, "first\n")
            atomic_write(target, "second\n")
            self.assertEqual("second\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(target.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
