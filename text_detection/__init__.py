"""OCR-assisted intact and damaged Sino-Nôm character detection."""

from .fusion import calculate_iou, fuse_localizations
from .pipeline import detect_ocr, iter_detection_pipeline, run_detection_pipeline
from .reading_order import sort_recognized_boxes
from .types import BBox, DetectionEvent, DetectionResult

__all__ = [
    'BBox',
    'DetectionEvent',
    'DetectionResult',
    'calculate_iou',
    'detect_ocr',
    'fuse_localizations',
    'iter_detection_pipeline',
    'run_detection_pipeline',
    'sort_recognized_boxes',
]
