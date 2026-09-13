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
    serialize_jsonl,
)

__all__ = [
    "ExtractConfig", "ExtractionError", "GlyphDecoder", "MetadataSpec",
    "TextLine", "atomic_write", "clean_extracted_text", "extract_document",
    "load_config", "load_glyph_profile", "normalize_line", "parse_records",
    "serialize_jsonl",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Vietnamese inscriptions from one configured PDF"
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        records, warnings = extract_document(config)
        payload = serialize_jsonl(records)
        atomic_write(config.output_jsonl, payload)
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(records)} records to {config.output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
