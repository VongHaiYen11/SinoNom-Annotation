"""Adapter from AutoHDR character detections to project-local JSON artifacts.

The AutoHDR-derived algorithm remains in :mod:`character_detection`; this
module only converts its public result objects and manages local output paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def default_detector_executable(project_root: Path | None = None) -> Path:
    """Return the documented local location for the external detector binary.

    The current released model is a single ``det_model`` executable.  The
    nested path remains supported for people who used the earlier documented
    directory layout.
    """
    root = project_root or Path(__file__).resolve().parents[1]
    model_path = root / "character_detection" / "models" / "det_model"
    nested_executable = model_path / "det_model"
    return nested_executable if nested_executable.is_file() else model_path


def detection_payload(image_path: str | Path, result: Any) -> dict[str, Any]:
    """Adapt ``CharacterDetector.detect`` output without changing detection logic."""
    return {
        "source_image": str(image_path),
        "image_width": result.image_size[0],
        "image_height": result.image_size[1],
        "reading_order": "autohdr_coordinate_heuristic",
        "detections": [
            {
                "bbox_xyxy": list(item.bbox_xyxy),
                "confidence": item.confidence,
                "corners": [list(corner) for corner in item.corners],
            }
            for item in result.detections
        ],
    }


def collection_payload(image_paths: list[str | Path], results: list[dict[str, Any]], output_directory: str | Path) -> dict[str, Any]:
    """Package per-image detector results into one portable PDF-level JSON file."""
    if len(image_paths) != len(results):
        raise ValueError("Each source image must have exactly one detection result.")
    root = Path(output_directory).resolve()
    images = []
    for image_path, result in zip(image_paths, results, strict=True):
        image = Path(image_path).resolve()
        try:
            relative_path = image.relative_to(root)
        except ValueError:
            relative_path = image
        images.append({
            "image_name": image.name,
            "image_path": str(relative_path),
            **result,
        })
    return {
        "schema_version": 1,
        "annotation_type": "character_detection_collection",
        "reading_order": "autohdr_coordinate_heuristic",
        "images": images,
    }


def detect_characters(
    image_path: str | Path,
    executable_path: str | Path,
    *,
    device: str | None = None,
    reading_order: bool = True,
    confidence_threshold: float = .45,
) -> dict[str, Any]:
    """Run the optional local model and return a serializable annotation payload."""
    try:
        from character_detection import CharacterDetector
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Character detection dependencies are not installed. Run "
            "`uv sync --extra character-detection` with Python 3.12, then install "
            "a compatible local detector executable."
        ) from exc
    with CharacterDetector(executable_path, device=device, confidence_threshold=confidence_threshold) as detector:
        return detection_payload(image_path, detector.detect(image_path, reading_order=reading_order))


def detect_character_collection(
    image_paths: list[str | Path],
    executable_path: str | Path,
    output_directory: str | Path,
    *,
    device: str | None = None,
    reading_order: bool = True,
    confidence_threshold: float = .45,
    progress: Callable[[int, Path], None] | None = None,
) -> dict[str, Any]:
    """Run one detector process across all final images and return one collection."""
    try:
        from character_detection import CharacterDetector
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Character detection dependencies are not installed. Install the "
            "character-detection optional dependency before running this command."
        ) from exc
    paths = [Path(path) for path in image_paths]
    results = []
    with CharacterDetector(executable_path, device=device, confidence_threshold=confidence_threshold) as detector:
        for index, image_path in enumerate(paths, start=1):
            if progress:
                progress(index, image_path)
            results.append(detection_payload(image_path, detector.detect(image_path, reading_order=reading_order)))
    return collection_payload(paths, results, output_directory)


def write_annotations(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write one UTF-8 annotation sidecar without modifying the source image."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
