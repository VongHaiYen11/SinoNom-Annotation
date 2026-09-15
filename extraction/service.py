"""High-level PDF extraction workflow."""

from __future__ import annotations

import pymupdf

from extraction.config import load_glyph_profile
from extraction.models import ExtractConfig, ExtractionError
from extraction.decoder import GlyphDecoder
from extraction.records import parse_records, parse_records_with_issues


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
        lines = decoder.extract_lines(
            config.top_margin,
            config.bottom_margin,
            config.footnote_start_pattern,
            config.footnote_min_y,
            config.footnote_max_font_size,
        )
    finally:
        document.close()
    return parse_records(lines, config)


def extract_document_with_issues(
    config: ExtractConfig,
) -> tuple[list[dict], list[str], list[dict]]:
    """Extract recoverable records and separately retain structural problems."""
    if not config.input_pdf.is_file():
        raise ExtractionError(f"Input PDF does not exist: {config.input_pdf}")
    profile = load_glyph_profile(config.glyph_profile)
    try:
        document = pymupdf.open(config.input_pdf)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {config.input_pdf}: {exc}") from exc
    try:
        decoder = GlyphDecoder(document, profile, config.encoded_fonts)
        lines = decoder.extract_lines(
            config.top_margin,
            config.bottom_margin,
            config.footnote_start_pattern,
            config.footnote_min_y,
            config.footnote_max_font_size,
        )
    finally:
        document.close()
    return parse_records_with_issues(lines, config)
