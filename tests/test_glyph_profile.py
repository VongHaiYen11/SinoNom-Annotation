from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from text_extraction.font_discovery import (
    normalize_font_name,
    parse_pdf_font_name,
)
from text_extraction.glyph_profile import (
    _closest_reference_codepoint,
    unique_cmap_candidates,
)


class GlyphProfileHelperTests(unittest.TestCase):
    def test_normalizes_subset_font_names_and_style(self) -> None:
        self.assertEqual("palatinolinotypebold", normalize_font_name("ABCDEF+Palatino Linotype,Bold"))
        self.assertEqual(
            ("palatinolinotype", "bold"),
            parse_pdf_font_name("ABCDEF+Palatino Linotype,Bold"),
        )

    def test_keeps_lowest_codepoint_for_duplicate_glyph(self) -> None:
        candidates = unique_cmap_candidates({66: "B", 65: "A", 97: "A"})
        self.assertEqual([(65, "A"), (66, "B")], sorted(candidates))

    def test_vectorized_pixel_match_preserves_score_then_codepoint_order(self) -> None:
        index = {
            "entries": [(65, "A", ""), (66, "B", ""), (67, "C", "")],
            "exact": {},
            "pixels": np.array([[0, 10, 20], [0, 10, 20], [5, 10, 20]], dtype=np.uint8),
        }
        result = _closest_reference_codepoint(
            bytes([0, 10, 20]), index, Path("reference.ttf"), batch_size=2
        )
        self.assertEqual(65, result)


if __name__ == "__main__":
    unittest.main()
