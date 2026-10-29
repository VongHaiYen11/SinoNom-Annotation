import json
from pathlib import Path
import tempfile
import unittest

from helpers.analysis.count_han_viet_frequency import analyze_volume, segments


class HanVietFrequencyTests(unittest.TestCase):
    def test_normalization_and_boundaries(self):
        parts, trimmed = segments("ÐIỀN\nđiền, hậu [] thần □ xã… dân 123 thôn 漢 phật")
        self.assertEqual(parts, [["điền", "điền"], ["hậu"], ["thần"],
                                 ["xã"], ["dân"], ["thôn"], ["phật"]])
        self.assertFalse(trimmed)

    def test_counts_documents_faces_and_summary_trimming(self):
        def face(text):
            return {"ky_hieu": "1", "chuyen_muc": [
                {"tieu_de": "Phiên âm Hán Việt", "van_ban": text},
                {"tieu_de": "Toát yếu", "van_ban": "không đếm"}]}

        records = [
            {"so_van_bia": 1, "noi_dung": [face("Bản xã bản xã"), face("Hậu thần")]},
            {"so_van_bia": 2, "noi_dung": [face("Bản xã\nToát yếu: <1>\nkhông đếm")]},
            {"so_van_bia": 3, "noi_dung": [face("[]")]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "volume.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            summary, tables = analyze_volume(path)
        self.assertEqual(summary["valid_inscriptions"], 2)
        self.assertEqual(summary["missing_transcriptions"], 1)
        self.assertEqual(summary["contaminated_sections"], 1)
        singles = {row["term"]: row for row in tables["single"]}
        pairs = {row["term"]: row for row in tables["pairs"]}
        self.assertEqual(singles["bản"]["count"], 3)
        self.assertEqual(singles["bản"]["inscription_count"], 2)
        self.assertEqual(singles["bản"]["inscription_pct"], 100)
        self.assertEqual(singles["bản"]["frequency_pct"], 37.5)
        self.assertEqual(pairs["bản xã"]["count"], 3)
        self.assertNotIn("xã hậu", pairs)
        self.assertNotIn("không", singles)
        self.assertEqual(tables["single"][0]["term"], "bản")

    def test_no_valid_transcriptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text('[{"noi_dung": []}]', encoding="utf-8")
            summary, tables = analyze_volume(path)
        self.assertEqual(summary["valid_inscriptions"], 0)
        self.assertEqual(tables, {"single": [], "pairs": []})
        self.assertEqual(summary["single_types_below_20"], 0)
        self.assertEqual(summary["pair_types_below_20"], 0)

    def test_below_20_excludes_exactly_20(self):
        text = ". ".join(["bản xã"] * 20 + ["hậu thần"] * 19)
        records = [{"noi_dung": [{"chuyen_muc": [
            {"tieu_de": "Phiên âm Hán Việt", "van_ban": text}]}]}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "volume.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            summary, _ = analyze_volume(path)
        self.assertEqual(summary["single_types_below_20"], 2)
        self.assertEqual(summary["pair_types_below_20"], 1)


if __name__ == "__main__":
    unittest.main()
