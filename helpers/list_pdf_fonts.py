#!/usr/bin/env python3
"""List unique embedded CID font names that need Unicode references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from text_extraction.font_discovery import embedded_type0_font_names  # noqa: E402
from text_extraction.types import ExtractionError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "List unique embedded Type0/Identity font names that require "
            "matching Unicode reference fonts for glyph-profile generation."
        )
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON array instead of one font name per line",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        names = embedded_type0_font_names(args.pdf.expanduser().resolve())
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(names, ensure_ascii=False, indent=2))
    else:
        for name in names:
            print(name)
    if not names:
        print("No embedded Type0/Identity fonts found.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
