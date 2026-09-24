"""Single-image OCR detector runtime, extracted from the repository helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

def check_img_size(img_size: int, stride: int = 32) -> int:
    import numpy as np

    return int(np.ceil(img_size / int(stride)) * int(stride))


def letterbox(img, new_shape=640, color=(114, 114, 114), auto=True, scale_fill=False, scaleup=True, stride=32):
    import cv2
    import numpy as np

    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    ratio = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:
        ratio = min(ratio, 1.0)
    ratio_pair = ratio, ratio
    new_unpad = int(round(shape[1] * ratio)), int(round(shape[0] * ratio))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    if auto:
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)
    elif scale_fill:
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio_pair = new_shape[1] / shape[1], new_shape[0] / shape[0]
    dw /= 2
    dh /= 2
    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    return cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color), ratio_pair, (dw, dh)


def _xywh_to_xyxy(boxes: torch.Tensor) -> torch.Tensor:
    output = boxes.clone()
    output[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    output[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    output[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    output[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return output


def _scale_coords(model_shape, coords, original_shape, ratio_pad):
    gain = ratio_pad[0][0]
    pad = ratio_pad[1]
    coords[:, [0, 2]] -= pad[0]
    coords[:, [1, 3]] -= pad[1]
    coords[:, :4] /= gain
    coords[:, 0].clamp_(0, original_shape[1])
    coords[:, 1].clamp_(0, original_shape[0])
    coords[:, 2].clamp_(0, original_shape[1])
    coords[:, 3].clamp_(0, original_shape[0])
    return coords


def non_max_suppression(prediction, conf_thres=0.25, iou_thres=0.45, multi_label=False):
    """The repository's YOLO NMS behavior for the one-image OADL path."""

    import torch
    import torchvision

    nc = prediction.shape[2] - 5
    candidates = prediction[..., 4] > conf_thres
    multi_label &= nc > 1
    output = [torch.zeros((0, 6), device=prediction.device)] * prediction.shape[0]
    started = time.time()
    for image_index, prediction_per_image in enumerate(prediction):
        prediction_per_image = prediction_per_image[candidates[image_index]]
        if not prediction_per_image.shape[0]:
            continue
        if nc == 1:
            prediction_per_image[:, 5:] = prediction_per_image[:, 4:5]
        else:
            prediction_per_image[:, 5:] *= prediction_per_image[:, 4:5]
        boxes = _xywh_to_xyxy(prediction_per_image[:, :4])
        if multi_label:
            indices, classes = (prediction_per_image[:, 5:] > conf_thres).nonzero(as_tuple=False).T
            detections = torch.cat((boxes[indices], prediction_per_image[indices, classes + 5, None], classes[:, None].float()), 1)
        else:
            confidence, classes = prediction_per_image[:, 5:].max(1, keepdim=True)
            detections = torch.cat((boxes, confidence, classes.float()), 1)[confidence.view(-1) > conf_thres]
        if not detections.shape[0]:
            continue
        if detections.shape[0] > 30000:
            detections = detections[detections[:, 4].argsort(descending=True)[:30000]]
        class_offsets = detections[:, 5:6] * 4096
        keep = torchvision.ops.nms(detections[:, :4] + class_offsets, detections[:, 4], iou_thres)[:5000]
        output[image_index] = detections[keep]
        if time.time() - started > 10:
            break
    return output


def detect_ocr(opt: Any, image_path: str, batch_size=32, imgsz=640, conf_thres=0.001, iou_thres=0.6, dataloader=None, half_precision=True) -> Dict[str, List[List[float]]]:
    """Run the original OCR detector flow without root-level helper imports."""

    import cv2
    import numpy as np
    import torch
    from .det_wrapper import det_model

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    default_executable = Path(__file__).resolve().parents[1] / 'models' / 'dists' / 'det_model' / 'det_model'
    model = det_model(getattr(opt, 'ocr_det_executable', str(default_executable)))
    stride = model(device, mode=1)
    imgsz = check_img_size(imgsz, stride)
    half = device.type != 'cpu' and half_precision
    image_original = cv2.imread(image_path)
    if image_original is None:
        model.cleanup()
        raise FileNotFoundError(f'Image not found: {image_path}')
    image_model, ratio, pad = letterbox(image_original, imgsz, stride=2048)
    image_model = np.ascontiguousarray(image_model[:, :, ::-1].transpose(2, 0, 1))
    image_tensor = torch.from_numpy(image_model).to(device)
    image_tensor = image_tensor.half() if half else image_tensor.float()
    image_tensor = (image_tensor / 255.0).unsqueeze(0)
    with torch.no_grad():
        prediction = model(image_tensor, mode=2)
        prediction = non_max_suppression(prediction, conf_thres=conf_thres, iou_thres=iou_thres, multi_label=True)
    result: Dict[str, List[List[float]]] = {}
    for detected in prediction:
        _scale_coords(image_tensor.shape[2:], detected[:, :4], image_original.shape[:2], (ratio, pad))
        result[str(Path(image_path).absolute())] = detected[:, :5].cpu().numpy().astype(float).tolist()
    model.cleanup()
    return result
