"""Localization-only implementation of AutoHDR Stage 1 (OADL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator, List, Mapping, Sequence
from uuid import uuid4

from .fusion import fuse_localizations
from .reading_order import sort_recognized_boxes
from .runtime.ocr_detector import detect_ocr
from .types import BBox, Stage1Event, Stage1Result


PACKAGE_DIR = Path(__file__).resolve().parent
MODEL_DIR = PACKAGE_DIR / 'models'
WORK_DIR = PACKAGE_DIR / 'work'


def _option(opt: Any, name: str, default: Path | str) -> str:
    return str(getattr(opt, name, default))


def _required_model_path(opt: Any, name: str, default: Path) -> str:
    """Resolve and validate one externally supplied model asset."""

    path = Path(_option(opt, name, default))
    if not path.is_file():
        raise FileNotFoundError(
            f"{name.replace('_', '-')} does not exist: {path}. "
            "See text_detection/README.md for the required model layout."
        )
    return str(path)


def _damage_boxes_from_prediction(prediction: Any, score_threshold: float = 0.3) -> List[BBox]:
    """Extract rounded DINO damage boxes using the repository threshold."""

    boxes = prediction.pred_instances.bboxes.cpu().numpy()
    scores = prediction.pred_instances.scores.cpu().numpy()
    damage_boxes: List[BBox] = []
    for box, score in zip(boxes, scores):
        x1, y1, x2, y2 = map(lambda value: int(round(value)), box)
        if score > score_threshold:
            damage_boxes.append([x1, y1, x2, y2])
    return damage_boxes


def _ocr_boxes_from_detection(detection_result: Mapping[str, Sequence[Sequence[float]]]) -> List[BBox]:
    """Keep only xyxy geometry from the OCR detector output."""

    ocr_boxes: List[BBox] = []
    for detections in detection_result.values():
        for coordinates in detections:
            ocr_boxes.append([round(coordinates[0]), round(coordinates[1]), round(coordinates[2]), round(coordinates[3])])
    return ocr_boxes


def iter_stage1(image_path: str, opt: Any) -> Generator[Stage1Event, None, Stage1Result]:
    """Run only localization, fusion, and reading order.

    No character crop is sent to the OCR recognizer. The OCR model in this
    module is used solely as a character *box detector*.
    """

    yield Stage1Event('loading_models')
    damage_config = _required_model_path(
        opt, 'vague_det_config', MODEL_DIR / 'ckpts' / 'damage_detect.py'
    )
    damage_weights = _required_model_path(
        opt, 'vague_det_weights', MODEL_DIR / 'ckpts' / 'damage_detect.pth'
    )
    _required_model_path(
        opt,
        'ocr_det_executable',
        MODEL_DIR / 'dists' / 'det_model' / 'det_model',
    )
    try:
        from mmdet.apis import inference_detector, init_detector
    except ModuleNotFoundError as exc:
        if exc.name == 'mmdet':
            raise RuntimeError(
                'AutoHDR damage localization requires MMDetection. Install the '
                'MMDetection/MMCV/MMEngine versions required by your '
                'damage_detect.py configuration.'
            ) from exc
        raise

    import cv2
    import numpy as np
    import torch
    from PIL import Image

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    damage_model = init_detector(
        damage_config,
        damage_weights,
        device=str(device),
    )

    yield Stage1Event('preprocessing')
    original_image = Image.open(image_path).convert('RGB')
    inverted_image = Image.fromarray(255 - np.array(original_image))
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    # Do not overwrite another invocation's OCR input. The retained path is
    # part of Stage1Result so callers can inspect the exact preprocessed image.
    inverted_image_path = str(WORK_DIR / f'inverted-{uuid4().hex}.jpg')
    inverted_image.save(inverted_image_path)
    inverted_image_gray = Image.open(inverted_image_path).convert('L').convert('RGB')

    yield Stage1Event('detecting')
    print('Đang phát hiện vị trí ký tự và vùng hư hỏng...')
    damage_prediction = inference_detector(damage_model, np.array(inverted_image_gray))
    damage_boxes = _damage_boxes_from_prediction(damage_prediction)
    ocr_detection = detect_ocr(
        opt,
        inverted_image_path,
        opt.det_batch_size,
        opt.img_size,
        opt.conf_thres,
        opt.iou_thres,
    )
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    ocr_boxes = _ocr_boxes_from_detection(ocr_detection)
    grayscale_image = cv2.imread(inverted_image_path, 0)
    if grayscale_image is None:
        raise RuntimeError(f'Cannot read generated OCR input: {inverted_image_path}')

    yield Stage1Event('fusing')
    fused_boxes, normal_boxes, _ = fuse_localizations(damage_boxes, ocr_boxes)

    yield Stage1Event('reading_order')
    print('Đang sắp xếp thứ tự đọc...')
    image_height, image_width = grayscale_image.shape[:2]
    ordered_boxes = sort_recognized_boxes(fused_boxes, image_height, image_width)

    result = Stage1Result(
        original_image=original_image,
        inverted_image=inverted_image,
        grayscale_image=grayscale_image,
        inverted_image_path=inverted_image_path,
        image_height=image_height,
        image_width=image_width,
        damage_boxes=damage_boxes,
        ocr_boxes=ocr_boxes,
        normal_boxes=normal_boxes,
        fused_boxes=fused_boxes,
        ordered_boxes=ordered_boxes,
        num_normal=len(normal_boxes),
        num_damaged=len(damage_boxes),
    )
    del damage_model
    return result


def run_stage1(image_path: str, opt: Any) -> Stage1Result:
    """Synchronously return the ordered normal/damaged bounding boxes."""

    stage1 = iter_stage1(image_path, opt)
    while True:
        try:
            next(stage1)
        except StopIteration as completed:
            return completed.value
