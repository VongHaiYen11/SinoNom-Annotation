"""AutoHDR Stage 1: OCR-Assisted Damage Localization (OADL)."""

from .fusion import calculate_iou, fuse_localizations
from .pipeline import detect_ocr, iter_stage1, run_stage1
from .reading_order import sort_recognized_boxes
from .types import BBox, Stage1Event, Stage1Result

__all__ = [
    'BBox',
    'Stage1Event',
    'Stage1Result',
    'calculate_iou',
    'detect_ocr',
    'fuse_localizations',
    'iter_stage1',
    'run_stage1',
    'sort_recognized_boxes',
]
