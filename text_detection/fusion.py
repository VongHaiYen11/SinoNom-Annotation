"""Localization fusion used by the original AutoHDR inference pipeline."""

from __future__ import annotations

from typing import List, Sequence, Set, Tuple

from .types import BBox


def calculate_iou(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    """Return the xyxy IoU using the repository's original calculation."""

    x_a = max(box_a[0], box_b[0])
    y_a = max(box_a[1], box_b[1])
    x_b = min(box_a[2], box_b[2])
    y_b = min(box_a[3], box_b[3])

    inter_area = max(0, x_b - x_a) * max(0, y_b - y_a)
    box_a_area = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    box_b_area = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union_area = box_a_area + box_b_area - inter_area
    return inter_area / union_area if union_area > 0 else 0


def fuse_localizations(
    damage_boxes: Sequence[BBox],
    ocr_boxes: Sequence[BBox],
    iou_threshold: float = 0.5,
) -> Tuple[List[BBox], List[BBox], Set[int]]:
    """Prefer damage boxes and retain only non-overlapping OCR boxes.

    This is a direct extraction of the fusion block from ``infer_pipeline.py``:
    an OCR box is removed if its IoU with *any* damage box is at least 0.5.
    Damage boxes remain first in the fused list, followed by retained OCR boxes.
    """

    to_remove: Set[int] = set()
    for damage_box in damage_boxes:
        for index, ocr_box in enumerate(ocr_boxes):
            if calculate_iou(damage_box, ocr_box) >= iou_threshold:
                to_remove.add(index)

    normal_boxes = [box for index, box in enumerate(ocr_boxes) if index not in to_remove]
    fused_boxes = list(damage_boxes) + normal_boxes
    return fused_boxes, normal_boxes, to_remove
