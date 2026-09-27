from pathlib import Path
import math
from annotation.bbox import validate_coordinates
from annotation.io import atomic_write

MAX_CROP_SIDE = 4096


def default_crop(size):
    """Return the full image; export scaling is applied after cropping."""
    width, height = size
    return [0, 0, width, height]


def validate_crop_coordinates(bbox, size):
    x1, y1, x2, y2 = validate_coordinates(bbox, size)
    return [x1, y1, x2, y2]


def auto_scale_crop(bbox, source_size):
    """Uniformly scale image/crop metadata so the crop's longest side is <= 4096."""
    bbox = validate_crop_coordinates(bbox, source_size)
    longest = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    scale = min(1.0, MAX_CROP_SIDE / longest)
    output_size = [max(1, round(value * scale)) for value in source_size]
    scale_x = output_size[0] / source_size[0]
    scale_y = output_size[1] / source_size[1]
    scaled = [round(bbox[0] * scale_x), round(bbox[1] * scale_y),
              round(bbox[2] * scale_x), round(bbox[3] * scale_y)]
    return validate_crop_coordinates(scaled, output_size), output_size


def validate_resized_image_size(size):
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in size)):
        raise ValueError('Resized image size must contain two finite numbers.')
    width, height = (round(value) for value in size)
    if width < 1 or height < 1:
        raise ValueError('Resized image width and height must be positive.')
    return [width, height]


def image_resize(source_size, output_size):
    """Describe the independent, potentially non-uniform source resize."""
    source_width, source_height = validate_resized_image_size(source_size)
    output_width, output_height = validate_resized_image_size(output_size)
    return dict(source_size=[source_width, source_height],
                output_size=[output_width, output_height],
                scale_x=round(output_width / source_width, 8),
                scale_y=round(output_height / source_height, 8))


def constrain_crop(bbox, size):
    """Move or shrink a crop just enough to fit resized image bounds."""
    width, height = validate_resized_image_size(size)
    x1, y1, x2, y2 = bbox
    crop_width = min(max(1, x2 - x1), width, MAX_CROP_SIDE)
    crop_height = min(max(1, y2 - y1), height, MAX_CROP_SIDE)
    x1 = min(max(0, x1), width - crop_width)
    y1 = min(max(0, y1), height - crop_height)
    return [x1, y1, x1 + crop_width, y1 + crop_height]


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


def save_crop_coordinates(image, bbox, size, output_dir, source_size=None):
    doc = crop_document(image, bbox, size)
    doc['image_resize'] = image_resize(source_size or size, size)
    path = Path(output_dir) / (Path(image).stem + '.json')
    atomic_write(path, doc)
    return path
