#!/usr/bin/env python3
"""Export a PDF with a searchable/copyable Unicode text layer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extraction.searchable_pdf import export_searchable_pdf
from extract_support import ExtractionError, load_config


def _parse_pages(value: str | None) -> set[int] | None:
    if value is None:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        start, separator, end = part.strip().partition("-")
        if not start.isdigit() or (separator and not end.isdigit()):
            raise argparse.ArgumentTypeError("pages must look like 1,3-5")
        first = int(start)
        last = int(end) if separator else first
        if first < 1 or last < first:
            raise argparse.ArgumentTypeError("page numbers must be positive and ordered")
        pages.update(range(first, last + 1))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--font", required=True, action="append", type=Path,
        help="Unicode font; repeat this option for fallback fonts.",
    )
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument(
        "--pages",
        type=_parse_pages,
        help="Optional pages for QA, for example 1,3-5. Omit for the full PDF.",
    )
    args = parser.parse_args(argv)
    try:
        export_searchable_pdf(
            load_config(args.config), args.output, args.font, args.dpi, args.pages
        )
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote searchable PDF to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
