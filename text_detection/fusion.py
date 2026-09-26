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


def calculate_smaller_box_coverage(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    """Return intersection area divided by the smaller box area.

    Standard IoU understates overlap when a tight damage box is contained in a
    looser OCR box. This companion measure lets the damage localization win in
    that common case without weakening the ordinary IoU rule.
    """
    x_a = max(box_a[0], box_b[0])
    y_a = max(box_a[1], box_b[1])
    x_b = min(box_a[2], box_b[2])
    y_b = min(box_a[3], box_b[3])
    inter_area = max(0, x_b - x_a) * max(0, y_b - y_a)
    area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
    area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])
    smaller = min(area_a, area_b)
    return inter_area / smaller if smaller > 0 else 0


def fuse_localizations(
    damage_boxes: Sequence[BBox],
    ocr_boxes: Sequence[BBox],
    iou_threshold: float = 0.5,
    containment_threshold: float = 0.8,
) -> Tuple[List[BBox], List[BBox], Set[int]]:
    """Prefer damage boxes and retain only non-overlapping OCR boxes.

    An OCR box is removed when standard IoU is high. When a tight damage box
    is substantially contained in a larger OCR box, the OCR geometry is
    promoted to damaged instead: the resulting red box keeps the full
    character extent rather than the much smaller damage localization.
    """

    to_remove: Set[int] = set()
    promoted_damage_boxes: List[BBox] = []
    for damage_box in damage_boxes:
        promoted_box = damage_box
        promoted_index = None
        best_coverage = 0.0
        for index, ocr_box in enumerate(ocr_boxes):
            iou = calculate_iou(damage_box, ocr_box)
            coverage = calculate_smaller_box_coverage(damage_box, ocr_box)
            if iou >= iou_threshold:
                to_remove.add(index)
            elif coverage >= containment_threshold and coverage > best_coverage:
                # A small damaged patch inside a full OCR character box means
                # the full character is damaged. Preserve the OCR extent and
                # render that region red.
                promoted_box = ocr_box
                promoted_index = index
                best_coverage = coverage
        if promoted_index is not None:
            to_remove.add(promoted_index)
        if promoted_box not in promoted_damage_boxes:
            promoted_damage_boxes.append(list(promoted_box))

    normal_boxes = [box for index, box in enumerate(ocr_boxes) if index not in to_remove]
    fused_boxes = promoted_damage_boxes + normal_boxes
    return fused_boxes, normal_boxes, to_remove
