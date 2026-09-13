"""High-level PDF extraction workflow."""

from __future__ import annotations

import pymupdf

from extract_support import ExtractConfig, ExtractionError, load_glyph_profile
from extraction.decoder import GlyphDecoder
from extraction.records import parse_records


def extract_document(config: ExtractConfig) -> tuple[list[dict], list[str]]:
    """Extract one configured PDF without writing its output."""
    if not config.input_pdf.is_file():
        raise ExtractionError(f"Input PDF does not exist: {config.input_pdf}")
    profile = load_glyph_profile(config.glyph_profile)
    try:
        document = pymupdf.open(config.input_pdf)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {config.input_pdf}: {exc}") from exc
    try:
        decoder = GlyphDecoder(document, profile, config.encoded_fonts)
        lines = decoder.extract_lines(config.top_margin, config.bottom_margin)
    finally:
        document.close()
    return parse_records(lines, config)
