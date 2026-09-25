"""Command-line entry point and JSON output for AutoHDR Stage 1."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence
from uuid import uuid4

from .pipeline import MODEL_DIR, run_stage1
from .types import BBox, Stage1Result


def _json_path(value: str) -> Path:
    path = Path(value)
    if path.suffix.casefold() != ".json":
        raise argparse.ArgumentTypeError(f"Expected a .json output path: {value}")
    return path


def build_parser() -> argparse.ArgumentParser:
    """Build the one-image text-detection CLI parser."""

    parser = argparse.ArgumentParser(
        description="Detect and order intact/damaged character boxes in one image."
    )
    parser.add_argument("image", type=Path, help="Input image path.")
    parser.add_argument(
        "--output",
        type=_json_path,
        help="Output JSON path (default: the input path with a .json suffix).",
    )
    parser.add_argument(
        "--vague-det-config",
        default=MODEL_DIR / "ckpts" / "damage_detect.py",
    )
    parser.add_argument(
        "--vague-det-weights",
        default=MODEL_DIR / "ckpts" / "damage_detect.pth",
    )
    parser.add_argument(
        "--ocr-det-executable",
        default=MODEL_DIR / "dists" / "det_model" / "det_model",
    )
    parser.add_argument("--det-batch-size", type=int, default=1)
    parser.add_argument("--img-size", type=int, default=2048)
    parser.add_argument("--conf-thres", type=float, default=0.45)
    parser.add_argument("--iou-thres", type=float, default=0.2)
    parser.add_argument(
        "--show-detection-logs",
        action="store_true",
        help="Show stdout/stderr from the packaged OCR detector process.",
    )
    return parser


def _ordered_box_ids(fused_boxes: Sequence[BBox], ordered_boxes: Sequence[BBox]) -> list[int]:
    """Map ordered boxes back to stable one-based IDs, including duplicates."""

    remaining = [(box_id, list(box)) for box_id, box in enumerate(fused_boxes, 1)]
    ordered_ids: list[int] = []
    for ordered_box in ordered_boxes:
        for position, (box_id, fused_box) in enumerate(remaining):
            if fused_box == list(ordered_box):
                ordered_ids.append(box_id)
                remaining.pop(position)
                break
        else:
            raise ValueError(f"Ordered box is absent from fused_boxes: {ordered_box}")
    if remaining:
        raise ValueError("reading order does not contain every fused box")
    return ordered_ids


def build_detection_document(image_path: Path, result: Stage1Result) -> dict[str, Any]:
    """Convert a Stage 1 result to the public JSON document schema."""

    expected_fused = list(result.damage_boxes) + list(result.normal_boxes)
    if list(result.fused_boxes) != expected_fused:
        raise ValueError("fused_boxes must contain damage_boxes followed by normal_boxes")
    if any(len(box) != 4 for box in result.fused_boxes):
        raise ValueError("every bounding box must contain exactly four xyxy values")

    damage_count = len(result.damage_boxes)
    bounding_boxes = {
        str(box_id): {
            "bbox": [int(value) for value in box],
            "status": "damaged" if box_id <= damage_count else "intact",
        }
        for box_id, box in enumerate(result.fused_boxes, 1)
    }
    return {
        "image": image_path.name,
        "bounding_boxes": bounding_boxes,
        "reading_order": _ordered_box_ids(result.fused_boxes, result.ordered_boxes),
    }


def write_detection_json(output_path: Path, document: dict[str, Any]) -> None:
    """Atomically write one UTF-8 detection JSON file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run detection for one image and write its JSON document."""

    options = build_parser().parse_args(argv)
    if not options.image.is_file():
        raise FileNotFoundError(options.image)

    output_path = options.output or options.image.with_suffix(".json")
    runtime_values = vars(options).copy()
    runtime_values.pop("image")
    runtime_values.pop("output")
    result = run_stage1(str(options.image), SimpleNamespace(**runtime_values))
    document = build_detection_document(options.image, result)
    write_detection_json(output_path, document)
    print(
        f"Wrote {len(result.fused_boxes)} bounding boxes to {output_path} "
        f"({result.num_normal} intact, {result.num_damaged} damaged)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
