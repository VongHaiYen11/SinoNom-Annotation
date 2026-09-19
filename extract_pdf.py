#!/usr/bin/env python3
"""Config-driven CLI for deterministic Vietnamica PDF extraction.

The workflow is intentionally data-driven:
1. Read the PDF, glyph profile, parsing rules, and output paths from one config.
2. Decode encoded font runs and normalize the PDF text.
3. Parse inscription records, separating recoverable structural issues.
4. Validate and atomically write JSONL plus optional review artifacts.

PDF-specific behavior belongs in the config file rather than this CLI, so the
same command supports new documents without source-code changes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from extraction.decoder import GlyphDecoder
from extraction.records import parse_records
from extraction.service import extract_document, extract_document_with_issues
from extraction.config import load_config, load_glyph_profile
from extraction.jsonl import (
    atomic_write,
    prepare_records_for_output,
    serialize_jsonl,
    serialize_pretty_json,
)
from extraction.models import ExtractConfig, ExtractionError, MetadataSpec, TextLine
from extraction.text import clean_extracted_text, normalize_line

__all__ = [
    "ExtractConfig", "ExtractionError", "GlyphDecoder", "MetadataSpec",
    "TextLine", "atomic_write", "clean_extracted_text", "extract_document",
    "extract_document_with_issues",
    "load_config", "load_glyph_profile", "normalize_line", "parse_records",
    "prepare_records_for_output", "serialize_jsonl", "serialize_pretty_json",
]


def build_parser() -> argparse.ArgumentParser:
    """Build the config-driven CLI parser without hard-coded PDF settings."""
    parser = argparse.ArgumentParser(
        description="Extract inscriptions from a PDF described by a JSON config.",
        epilog=(
            "The config defines input_pdf, glyph_profile, output_jsonl, font "
            "decoding rules, and record parsing rules."
        ),
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--pretty-output",
        type=Path,
        help="Optional indented JSON file for manual review; JSONL remains unchanged.",
    )
    parser.add_argument(
        "--content-layout",
        choices=("preserve", "space", "no-space"),
        default="preserve",
        help="Keep PDF line breaks, replace them with spaces, or remove them in van_ban.",
    )
    parser.add_argument(
        "--strip-literal-backslashes",
        action="store_true",
        help="Remove actual U+005C backslashes from van_ban; does not target JSON escapes.",
    )
    parser.add_argument(
        "--issues-output",
        type=Path,
        help="Optional JSON for structural review; defaults beside output_jsonl.",
    )
    parser.add_argument(
        "--keep-flagged-records",
        action="store_true",
        help="Keep records with structural issues in the primary JSONL output.",
    )
    return parser


def default_issues_path(output_jsonl: Path) -> Path:
    """Return the review-file path derived dynamically from the configured output."""
    return output_jsonl.with_name(f"{output_jsonl.stem}_invalid.json")


def main(argv: list[str] | None = None) -> int:
    """Run the configured extraction workflow and write its requested artifacts."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        records, warnings, issues = extract_document_with_issues(config)
        issue_path = args.issues_output or default_issues_path(config.output_jsonl)
        # Issue records are retained separately so the primary corpus remains
        # strict by default while manual review still has complete context.
        flagged_numbers = {
            item["so_van_bia"] for item in issues if item["so_van_bia"] is not None
        }
        output_records = [
            record for record in records
            if args.keep_flagged_records or record["so_van_bia"] not in flagged_numbers
        ]
        output_records = prepare_records_for_output(
            output_records, args.content_layout, args.strip_literal_backslashes
        )
        payload = serialize_jsonl(output_records)
        atomic_write(config.output_jsonl, payload)
        atomic_write(issue_path, json.dumps(issues, ensure_ascii=False, indent=2) + "\n")
        if args.pretty_output is not None:
            atomic_write(args.pretty_output, serialize_pretty_json(output_records))
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(output_records)} valid records to {config.output_jsonl}")
    print(f"Wrote {len(issues)} format-review items to {issue_path}")
    if args.pretty_output is not None:
        print(f"Wrote formatted review JSON to {args.pretty_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
