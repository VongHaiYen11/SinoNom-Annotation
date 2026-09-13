#!/usr/bin/env python3
"""CLI compatibility facade for deterministic Vietnamica PDF extraction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extraction.decoder import GlyphDecoder
from extraction.records import parse_records
from extraction.service import extract_document
from extract_support import (
    ExtractConfig,
    ExtractionError,
    MetadataSpec,
    TextLine,
    atomic_write,
    clean_extracted_text,
    load_config,
    load_glyph_profile,
    normalize_line,
    prepare_records_for_output,
    serialize_jsonl,
    serialize_pretty_json,
)

__all__ = [
    "ExtractConfig", "ExtractionError", "GlyphDecoder", "MetadataSpec",
    "TextLine", "atomic_write", "clean_extracted_text", "extract_document",
    "load_config", "load_glyph_profile", "normalize_line", "parse_records",
    "prepare_records_for_output", "serialize_jsonl", "serialize_pretty_json",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Vietnamese inscriptions from one configured PDF"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--pretty-output",
        type=Path,
        help="Optional indented JSON file for manual review; JSONL remains unchanged.",
    )
    parser.add_argument(
        "--content-layout",
        choices=("preserve", "space"),
        default="preserve",
        help="Keep PDF line breaks or replace them with spaces in van_ban.",
    )
    parser.add_argument(
        "--strip-literal-backslashes",
        action="store_true",
        help="Remove actual U+005C backslashes from van_ban; does not target JSON escapes.",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        records, warnings = extract_document(config)
        output_records = prepare_records_for_output(
            records, args.content_layout, args.strip_literal_backslashes
        )
        payload = serialize_jsonl(output_records)
        atomic_write(config.output_jsonl, payload)
        if args.pretty_output is not None:
            atomic_write(args.pretty_output, serialize_pretty_json(output_records))
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(records)} records to {config.output_jsonl}")
    if args.pretty_output is not None:
        print(f"Wrote formatted review JSON to {args.pretty_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
