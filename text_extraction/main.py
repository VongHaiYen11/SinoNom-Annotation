"""Command-line entry point for deterministic config-driven PDF extraction."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pymupdf

from text_extraction.config import load_config, load_glyph_profile
from text_extraction.decoder import GlyphDecoder
from text_extraction.font_discovery import synchronize_encoded_fonts
from text_extraction.output import (
    atomic_write,
    prepare_records_for_output,
    serialize_json,
    serialize_pretty_json,
)
from text_extraction.parser import parse_records, parse_records_with_issues
from text_extraction.text import clean_extracted_text, normalize_line
from text_extraction.types import EncodedFont, ExtractConfig, ExtractionError, MetadataSpec, TextLine

__all__ = [
    "EncodedFont", "ExtractConfig", "ExtractionError", "GlyphDecoder", "MetadataSpec",
    "TextLine", "atomic_write", "clean_extracted_text", "extract_document",
    "extract_document_with_issues", "load_config", "load_glyph_profile",
    "normalize_line", "parse_records", "prepare_records_for_output",
    "serialize_json", "serialize_pretty_json",
]


def _path_with_suffix(suffix: str):
    """Return an argparse converter that accepts one expected file extension."""
    def convert(value: str) -> Path:
        path = Path(value).expanduser()
        if path.suffix.casefold() != suffix:
            raise argparse.ArgumentTypeError(
                f"Expected a {suffix} file, got: {value}"
            )
        return path

    return convert


def build_parser() -> argparse.ArgumentParser:
    """Build the config-only CLI parser."""
    parser = argparse.ArgumentParser(
        description="Discover fonts and extract one configured PDF.",
    )
    parser.add_argument(
        "--config", required=True, type=_path_with_suffix(".json"),
        help="Document PDF, font, parser, profile, and output configuration.",
    )
    return parser


def default_issues_path(output_json: Path) -> Path:
    """Return the review-file path derived dynamically from the configured output."""
    return output_json.with_name(f"{output_json.stem}_invalid.json")


def _log_decode_statistics(decoder: GlyphDecoder) -> None:
    """Log the decoding evidence collected for one PDF."""
    stats = decoder.statistics
    logging.info(
        "Glyph extraction statistics: Total characters: %d; Profile matched: %d; "
        "Fallback: %d; Unresolved: %d",
        stats.total_characters,
        stats.profile_matched,
        stats.fallback,
        stats.unresolved,
    )
    decoder.log_profile_misses()
    decoder.log_fallbacks()


def _decode_lines(config: ExtractConfig) -> list[TextLine]:
    """Open the configured PDF and turn it into normalized text lines."""
    if not config.input_pdf_path.is_file():
        raise ExtractionError(f"Input PDF does not exist: {config.input_pdf_path}")
    profile = load_glyph_profile(config.glyph_profile)
    try:
        document = pymupdf.open(config.input_pdf_path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {config.input_pdf_path}: {exc}") from exc
    try:
        decoder = GlyphDecoder(
            document,
            profile,
            tuple(encoded_font.pdf_name for encoded_font in config.encoded_fonts),
        )
        lines = decoder.extract_lines(
            config.top_margin,
            config.bottom_margin,
            config.footnote_start_pattern,
            config.footnote_max_font_size,
        )
        _log_decode_statistics(decoder)
        return lines
    finally:
        document.close()


def extract_document(config: ExtractConfig) -> tuple[list[dict], list[str]]:
    """Extract one configured PDF without writing output files."""
    return parse_records(_decode_lines(config), config)


def extract_document_with_issues(
    config: ExtractConfig,
) -> tuple[list[dict], list[str], list[dict]]:
    """Extract valid records and retain structural issues for review."""
    return parse_records_with_issues(_decode_lines(config), config)


def main(argv: list[str] | None = None) -> int:
    """Run the configured extraction workflow and write JSON plus issue JSON."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        discovery = synchronize_encoded_fonts(args.config.resolve())
        for font_name in discovery.missing_reference:
            logging.warning("No local reference font for embedded font: %s", font_name)
        config = load_config(args.config.resolve())
        records, warnings, issues = extract_document_with_issues(config)
        issue_path = default_issues_path(config.output_json)
        # Issue records are retained separately so the primary corpus remains
        # strict by default while manual review still has complete context.
        flagged_numbers = {
            item["so_van_bia"] for item in issues if item["so_van_bia"] is not None
        }
        output_records = [
            record for record in records
            if record["so_van_bia"] not in flagged_numbers
        ]
        output_records = prepare_records_for_output(output_records)
        atomic_write(config.output_json, serialize_json(output_records))
        atomic_write(issue_path, json.dumps(issues, ensure_ascii=False, indent=2) + "\n")
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(output_records)} valid records to {config.output_json}")
    print(f"Wrote {len(issues)} format-review items to {issue_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
