"""Pixel-space crop and no-upscale image processing operations."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image

from .models import DCI_PORTRAIT_RATIO, MAX_DCI_HEIGHT, MAX_DCI_WIDTH, MAX_LONGEST_DIMENSION


def get_center_dci_portrait_crop(width: int, height: int) -> tuple[int, int, int, int]:
    """Return the largest centered 2160:4096 box contained in an image."""
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive")
    ratio = width / height
    if math.isclose(ratio, DCI_PORTRAIT_RATIO, rel_tol=0, abs_tol=1e-12):
        return (0, 0, width, height)
    if ratio > DCI_PORTRAIT_RATIO:
        crop_width = round(height * DCI_PORTRAIT_RATIO)
        left = (width - crop_width) // 2
        return (left, 0, left + crop_width, height)
    crop_height = round(width / DCI_PORTRAIT_RATIO)
    top = (height - crop_height) // 2
    return (0, top, width, top + crop_height)


def normalise_crop_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(round(value)) for value in box)
    left, right = sorted((max(0, left), min(width, right)))
    top, bottom = sorted((max(0, top), min(height, bottom)))
    if right <= left or bottom <= top:
        raise ValueError("Crop box must have a positive area inside the image")
    return left, top, right, bottom


def process_image(image: Image.Image, crop_mode: str = "center", crop_box: tuple[int, int, int, int] | None = None, max_width: int = MAX_DCI_WIDTH, max_height: int = MAX_DCI_HEIGHT) -> dict[str, Any]:
    """Crop in source pixels, then downscale proportionally only when needed."""
    if max_width <= 0 or max_height <= 0:
        raise ValueError("Maximum dimensions must be positive")
    box = get_center_dci_portrait_crop(*image.size) if crop_mode == "center" else normalise_crop_box(crop_box, *image.size) if crop_box else None
    if box is None:
        raise ValueError("Manual processing requires crop_box")
    cropped = image.crop(box)
    crop_width, crop_height = cropped.size
    scale = min(1.0, max_width / crop_width, max_height / crop_height)
    downscaled = scale < 1.0
    if downscaled:
        cropped = cropped.resize((max(1, round(crop_width * scale)), max(1, round(crop_height * scale))), Image.Resampling.LANCZOS)
    return {"image": cropped, "crop_box": box, "crop_size": (crop_width, crop_height), "final_size": cropped.size, "upscaled": False, "downscaled": downscaled}


def fit_longest_dimension(image: Image.Image, maximum: int = MAX_LONGEST_DIMENSION) -> Image.Image:
    """Downscale only to a maximum longest side."""
    if max(image.size) <= maximum:
        return image
    scale = maximum / max(image.size)
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
