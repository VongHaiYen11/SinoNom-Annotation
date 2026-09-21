#!/usr/bin/env python3
"""Run optional AutoHDR character detection on one saved image."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pdf_image_extractor.character_annotations import (
    default_detector_executable,
    detect_characters,
    write_annotations,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create local character-box annotations for one image.")
    parser.add_argument("image", type=Path, help="Source JPEG/PNG image")
    parser.add_argument("--model", type=Path, default=default_detector_executable(), help="AutoHDR detector executable")
    parser.add_argument("--output", type=Path, help="JSON output (defaults beside image)")
    parser.add_argument("--device", help="Torch device, e.g. cpu, cuda, or mps")
    parser.add_argument("--detector-order", action="store_true", help="Keep detector/NMS order instead of AutoHDR reading order")
    args = parser.parse_args(argv)
    if not args.image.is_file():
        parser.error(f"Image not found: {args.image}")
    if not args.model.is_file():
        parser.error(f"Detector executable not found: {args.model}")
    payload = detect_characters(args.image, args.model, device=args.device, reading_order=not args.detector_order)
    output = args.output or args.image.with_suffix(".characters.json")
    write_annotations(output, payload)
    print(f"Wrote {len(payload['detections'])} character detections to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
