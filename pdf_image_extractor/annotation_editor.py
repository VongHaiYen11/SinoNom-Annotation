"""UI-independent persistence for editable character-box annotations."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image


def _resolve_image(annotation_path: Path, record: dict[str, Any], override: str | None = None) -> Path:
    """Resolve a collection-relative image path or a legacy sidecar source path."""
    candidates = [Path(override)] if override else []
    for key in ("image_path", "source_image"):
        value = record.get(key)
        if isinstance(value, str):
            candidate = Path(value)
            if candidate.is_absolute():
                candidates.append(candidate)
            else:
                candidates.extend((candidate, annotation_path.parent / candidate))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Could not find this image. Set 'Image path override' for a legacy one-image JSON.")


def _valid_box(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("Each bbox_xyxy must contain exactly four coordinates.")
    left, top, right, bottom = (round(float(coordinate)) for coordinate in value)
    left = min(max(0, left), width - 1)
    top = min(max(0, top), height - 1)
    right = min(max(left + 1, right), width)
    bottom = min(max(top + 1, bottom), height)
    return left, top, right, bottom


def _rotation_degrees(value: Any) -> float:
    """Return a finite clockwise canvas angle in the compact [-180, 180) range."""
    try:
        angle = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(angle):
        return 0.0
    return round((angle + 180) % 360 - 180, 3)


def corners_from_box(
    box: tuple[int, int, int, int], rotation_degrees: float = 0.0,
) -> list[list[float]]:
    """Return the four oriented rectangle corners for an editable character box."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    radians = math.radians(_rotation_degrees(rotation_degrees))
    cosine, sine = math.cos(radians), math.sin(radians)

    def rotate(x: float, y: float) -> list[float]:
        return [round(cx + x * cosine - y * sine, 3), round(cy + x * sine + y * cosine, 3)]

    return [
        rotate(left - cx, top - cy),
        rotate(right - cx, top - cy),
        rotate(right - cx, bottom - cy),
        rotate(left - cx, bottom - cy),
    ]


def _normalise_record(annotation_path: Path, record: dict[str, Any], image_override: str | None = None) -> None:
    image_path = _resolve_image(annotation_path, record, image_override)
    with Image.open(image_path) as image:
        width, height = image.size
    detections = record.get("detections", [])
    if not isinstance(detections, list):
        raise ValueError("Every image record field 'detections' must be a list.")
    normalised = []
    for detection in detections:
        if not isinstance(detection, dict):
            raise ValueError("Every detection must be a JSON object.")
        box = _valid_box(detection.get("bbox_xyxy"), width, height)
        item = deepcopy(detection)
        rotation = _rotation_degrees(item.get("rotation_degrees", item.get("angle_degrees", 0)))
        item["bbox_xyxy"] = list(box)
        item["rotation_degrees"] = rotation
        item["corners"] = corners_from_box(box, rotation)
        normalised.append(item)
    record["image_width"] = width
    record["image_height"] = height
    record["detections"] = normalised
    record["_resolved_image_path"] = str(image_path)


def load_annotation(annotation_file: str | Path, image_override: str | None = None) -> dict[str, Any]:
    """Load a PDF-level collection or the original one-image sidecar schema."""
    annotation_path = Path(annotation_file).expanduser().resolve()
    if not annotation_path.is_file():
        raise FileNotFoundError(f"Annotation JSON not found: {annotation_path}")
    try:
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid annotation JSON: {annotation_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Annotation JSON must be an object.")
    collection = isinstance(payload.get("images"), list)
    records = payload["images"] if collection else [payload]
    if not records:
        raise ValueError("Annotation collection has no images.")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Image record {index + 1} must be an object.")
        _normalise_record(annotation_path, record, image_override if not collection else None)
    return {"annotation_path": str(annotation_path), "payload": payload, "collection": collection, "current_index": 0}


def current_record(session: dict[str, Any]) -> dict[str, Any]:
    records = session["payload"]["images"] if session["collection"] else [session["payload"]]
    return records[session["current_index"]]


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    clean = deepcopy(record)
    clean.pop("_resolved_image_path", None)
    return clean


def apply_pending(session: dict[str, Any], edited_detections: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep current-image edits in memory so they survive Next/Previous."""
    updated = deepcopy(session)
    record = current_record(updated)
    width, height = int(record["image_width"]), int(record["image_height"])
    detections: list[dict[str, Any]] = []
    for index, incoming in enumerate(edited_detections):
        if not isinstance(incoming, dict):
            raise ValueError(f"Edited detection {index + 1} is not an object.")
        box = _valid_box(incoming.get("bbox_xyxy"), width, height)
        item = deepcopy(incoming)
        item.pop("editor_id", None)
        rotation = _rotation_degrees(item.get("rotation_degrees", item.get("angle_degrees", 0)))
        item["bbox_xyxy"] = list(box)
        item["rotation_degrees"] = rotation
        item["corners"] = corners_from_box(box, rotation)
        item.setdefault("confidence", None)
        detections.append(item)
    record["detections"] = detections
    return updated


def move_to_image(session: dict[str, Any], index: int) -> dict[str, Any]:
    records = session["payload"]["images"] if session["collection"] else [session["payload"]]
    updated = deepcopy(session)
    updated["current_index"] = max(0, min(index, len(records) - 1))
    return updated


def save_annotation(session: dict[str, Any]) -> dict[str, Any]:
    """Overwrite the loaded JSON with all in-memory image edits."""
    payload_to_write = deepcopy(session["payload"])
    if session["collection"]:
        payload_to_write["images"] = [_clean_record(record) for record in payload_to_write["images"]]
    else:
        payload_to_write = _clean_record(payload_to_write)
    Path(session["annotation_path"]).write_text(json.dumps(payload_to_write, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Retain the resolved local image paths in the in-memory session so the UI
    # can redraw immediately after saving; they are omitted only on disk.
    return session


def save_current_annotation(session: dict[str, Any]) -> dict[str, Any]:
    """Persist only the image currently selected in a collection.

    Other in-memory edits stay pending and do not overwrite their corresponding
    records on disk. This makes incremental review safe without losing the
    option to save every pending edit later.
    """
    if not session["collection"]:
        return save_annotation(session)
    annotation_path = Path(session["annotation_path"])
    try:
        disk_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid annotation JSON on disk: {annotation_path}") from exc
    disk_records = disk_payload.get("images") if isinstance(disk_payload, dict) else None
    if not isinstance(disk_records, list):
        raise ValueError("Annotation collection on disk no longer contains an 'images' list.")
    current = _clean_record(current_record(session))
    current_path = current.get("image_path")
    current_name = current.get("image_name")
    target = next(
        (
            index for index, record in enumerate(disk_records)
            if isinstance(record, dict)
            and ((current_path and record.get("image_path") == current_path) or (current_name and record.get("image_name") == current_name))
        ),
        None,
    )
    if target is None:
        raise ValueError("Current image is not present in the collection on disk.")
    disk_records[target] = current
    annotation_path.write_text(json.dumps(disk_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return session
