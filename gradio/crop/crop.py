from pathlib import Path
from annotation.bbox import validate_coordinates
from annotation.io import atomic_write

MAX_CROP_SIDE = 4096


def default_crop(size):
    """Return a top-left anchored crop that fits the image and size limit."""
    width, height = size
    return [0, 0, min(width, MAX_CROP_SIDE), min(height, MAX_CROP_SIDE)]


def validate_crop_coordinates(bbox, size):
    x1, y1, x2, y2 = validate_coordinates(bbox, size)
    if x2 - x1 > MAX_CROP_SIDE or y2 - y1 > MAX_CROP_SIDE:
        raise ValueError(f'Crop width and height cannot exceed {MAX_CROP_SIDE} pixels.')
    return [x1, y1, x2, y2]


def crop_document(image, bbox, size):
    x1, y1, x2, y2 = validate_crop_coordinates(bbox, size)
    return dict(image=image, crop=dict(top_left=[x1, y1], top_right=[x2, y1],
                                    bottom_right=[x2, y2], bottom_left=[x1, y2]))


def crop_bbox(crop, size):
    """Validate all four corners rather than silently ignoring malformed corners."""
    names = ('top_left', 'top_right', 'bottom_right', 'bottom_left')
    if not isinstance(crop, dict) or set(crop) != set(names):
        raise ValueError('Crop must contain all four corners.')
    if any(not isinstance(crop[name], list) or len(crop[name]) != 2 for name in names):
        raise ValueError('Each crop corner must contain two coordinates.')
    bbox = validate_crop_coordinates(crop['top_left'] + crop['bottom_right'], size)
    if crop_document('', bbox, size)['crop'] != crop:
        raise ValueError('Crop corners must form an axis-aligned rectangle.')
    return bbox


def save_crop_coordinates(image, bbox, size, output_dir):
    doc = crop_document(image, bbox, size)
    path = Path(output_dir) / (Path(image).stem + '.json')
    atomic_write(path, doc)
    return path
