"""Reading-order adapter for the vendored AutoHDR layout heuristic."""

from __future__ import annotations

from typing import List, Sequence

from .types import BBox


def sort_recognized_boxes(boxes: Sequence[BBox], image_height: int, image_width: int) -> List[BBox]:
    """Order fused boxes with the repository's unchanged layout heuristic."""

    # An image can legitimately contain no detected characters. Returning
    # early also keeps this inexpensive case independent of the optional
    # OpenCV/NumPy/Shapely runtime used by the layout heuristic.
    if not boxes:
        return []

    # The heuristic is vendored in ``text_detection.runtime`` so this package
    # does not depend on repository-level helper modules.
    from .runtime.reader import get_sort

    return get_sort(list(boxes), image_height, image_width)
