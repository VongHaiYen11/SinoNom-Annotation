from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extract_pdf import (
    ExtractConfig,
    ExtractionError,
    GlyphDecoder,
    MetadataSpec,
    TextLine,
    atomic_write,
    clean_extracted_text,
    normalize_line,
    parse_records,
    prepare_records_for_output,
    serialize_json,
    serialize_pretty_json,
)
from extraction.records import parse_records_with_issues


def line(text: str, page: int = 1) -> TextLine:
    return TextLine(text=text, page_number=page)


def config(**overrides) -> ExtractConfig:
    values = {
        "input_pdf": Path("input.pdf"),
        "output_json": Path("output.json"),
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
    def test_pdf_control_characters_are_removed_before_serialization(self) -> None:
        # TimesNewRoman is intentionally not in encoded_fonts, so it takes
        # the PyMuPDF fallback path that previously returned U+0001 unchanged.
        decoder = GlyphDecoder.__new__(GlyphDecoder)
        decoder.encoded_fonts = ("NomNaTong",)
        fallback = decoder.decode_span(
            "Times\x01New\ufffdRoman", "TimesNewRoman", {}, 1
        )

        self.assertEqual("TimesNewRoman", fallback)
        self.assertEqual("AB", clean_extracted_text("A\x01B\ufffd"))
        self.assertEqual("AB", normalize_line("A\x01B\ufffd"))
        self.assertEqual(
            '[{"noi_dung":"TimesNewRoman"}]\n',
            serialize_json([{"noi_dung": fallback}]),
        )

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
        self.assertIn(
            "metadata khai báo marker <4351> nhưng không có dòng nội dung nào",
            "\n".join(warnings),
        )

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
        warning = next(item for item in warnings if "không thuộc marker" in item)
        self.assertIn("trang 1", warning)
        self.assertIn("Nội dung chưa gán: 'Đoạn chưa có marker'", warning)

    def test_unknown_marker_warning_includes_source_and_metadata(self) -> None:
        source = [
            line("VĂN BIA SỐ 1"),
            line("Tên bia: A"),
            line("Địa điểm: B"),
            line("Niên đại: C"),
            line("Kí hiệu VNCHN: <10>"),
            line("Nguyên văn chữ Hán Nôm:"),
            line("<11> Nội dung ngoài metadata", page=7),
        ]

        _, warnings = parse_records(source, config())

        warning = next(item for item in warnings if "<11> không có" in item)
        self.assertIn("danh sách marker metadata: <10>", warning)
        self.assertIn("trang 7", warning)
        self.assertIn("dòng: '<11> Nội dung ngoài metadata'", warning)

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

    def test_eth_variant_of_vietnamese_d_matches_metadata_label(self) -> None:
        source = [
            line("VĂN BIA SỐ 1"),
            line("Tên bia: A"),
            line("Ðịa điểm: B"),
            line("Niên đại: C"),
            line("Kí hiệu VNCHN: <10>"),
            line("Nguyên văn chữ Hán Nôm:"),
            line("<10> Nội dung"),
        ]

        records, _ = parse_records(source, config())

        self.assertEqual("B", records[0]["dia_diem"])

    def test_non_consecutive_titles_fail(self) -> None:
        source = [line("VĂN BIA SỐ 1"), line("VĂN BIA SỐ 3")]
        with self.assertRaisesRegex(ExtractionError, "not consecutive"):
            parse_records(source, config(expected_record_count=None))

    def test_malformed_record_is_collected_while_later_record_is_kept(self) -> None:
        source = [
            line("VĂN BIA SỐ 1", 3),
            line("Tên bia: Thiếu phần nội dung", 3),
            line("VĂN BIA SỐ 2", 4),
            line("Tên bia: Hợp lệ", 4),
            line("Địa điểm: A", 4),
            line("Niên đại: B", 4),
            line("Kí hiệu VNCHN: <20>", 4),
            line("Nguyên văn chữ Hán Nôm:", 4),
            line("<20> Nội dung", 4),
        ]

        records, warnings, issues = parse_records_with_issues(
            source, config(expected_record_count=None)
        )

        self.assertEqual([2], [record["so_van_bia"] for record in records])
        self.assertEqual([], warnings)
        self.assertEqual(1, issues[0]["so_van_bia"])
        self.assertEqual([3], issues[0]["trang"])
        self.assertIn("thiếu mốc", issues[0]["loi"][0])
        self.assertIn("Tên bia: Thiếu phần nội dung", issues[0]["du_lieu_nguon"])

    def test_json_is_deterministic_and_content_is_last(self) -> None:
        record = {
            "so_van_bia": 1,
            "ten_bia": "Bia thử",
            "noi_dung": [{"ky_hieu": "1", "chuyen_muc": []}],
        }
        first = serialize_json([record])
        second = serialize_json([record])
        self.assertEqual(first, second)
        self.assertEqual(
            ["so_van_bia", "ten_bia", "noi_dung"],
            list(json.loads(first)[0].keys()),
        )
        pretty = serialize_pretty_json([record])
        self.assertEqual([record], json.loads(pretty))
        self.assertIn('\n    "so_van_bia": 1,', pretty)
        with self.assertRaisesRegex(ExtractionError, "U\+FFFD"):
            serialize_json([{"noi_dung": "bad\ufffdtext"}])

    def test_output_cleanup_is_explicit_and_only_changes_content(self) -> None:
        records = [{
            "so_van_bia": 1,
            "ten_bia": "Tên\\bia",
            "noi_dung": [{"ky_hieu": "1", "chuyen_muc": [{
                "tieu_de": "Nguyên văn chữ Hán Nôm",
                "van_ban": "Dòng một\\\nDòng hai\\thừa",
            }]}],
        }]

        cleaned = prepare_records_for_output(records, "space", True)
        self.assertEqual("Dòng một Dòng haithừa", cleaned[0]["noi_dung"][0]["chuyen_muc"][0]["van_ban"])
        compact = prepare_records_for_output(records, "no-space", True)
        self.assertEqual("Dòng mộtDòng haithừa", compact[0]["noi_dung"][0]["chuyen_muc"][0]["van_ban"])
        self.assertEqual("Tên\\bia", cleaned[0]["ten_bia"])
        self.assertEqual("Dòng một\\\nDòng hai\\thừa", records[0]["noi_dung"][0]["chuyen_muc"][0]["van_ban"])

    def test_atomic_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "result.json"
            atomic_write(target, "first\n")
            atomic_write(target, "second\n")
            self.assertEqual("second\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(target.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
