#!/usr/bin/env python3
"""Extract one face from a TTC collection as a standalone TTF."""

from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.ttLib import TTFont


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--font-number", required=True, type=int)
    args = parser.parse_args()

    try:
        font = TTFont(args.input, fontNumber=args.font_number)
    except Exception as exc:
        raise SystemExit(f"error: cannot read TTC face: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
