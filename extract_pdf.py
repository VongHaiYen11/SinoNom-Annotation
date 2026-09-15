#!/usr/bin/env python3
"""CLI compatibility facade for deterministic Vietnamica PDF extraction."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument(
        "--issues-output",
        type=Path,
        help="JSON riêng cho văn bia/cảnh báo sai format; mặc định cạnh output_jsonl.",
    )
    parser.add_argument(
        "--keep-flagged-records",
        action="store_true",
        help="Giữ cả văn bia có warning cấu trúc trong JSONL chính.",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        records, warnings, issues = extract_document_with_issues(config)
        issue_path = args.issues_output or config.output_jsonl.with_name(
            f"{config.output_jsonl.stem}_invalid.json"
        )
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
