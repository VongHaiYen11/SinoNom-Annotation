from pathlib import Path
from annotation.bbox import validate_coordinates
from annotation.io import atomic_write


def crop_document(image, bbox, size):
    x1, y1, x2, y2 = validate_coordinates(bbox, size)
    return dict(image=image, crop=dict(top_left=[x1, y1], top_right=[x2, y1],
                                    bottom_right=[x2, y2], bottom_left=[x1, y2]))


def crop_bbox(crop, size):
    """Validate all four corners rather than silently ignoring malformed corners."""
    names = ('top_left', 'top_right', 'bottom_right', 'bottom_left')
    if not isinstance(crop, dict) or set(crop) != set(names):
        raise ValueError('Crop must contain all four corners.')
    if any(not isinstance(crop[name], list) or len(crop[name]) != 2 for name in names):
        raise ValueError('Each crop corner must contain two coordinates.')
    bbox = validate_coordinates(crop['top_left'] + crop['bottom_right'], size)
    if crop_document('', bbox, size)['crop'] != crop:
        raise ValueError('Crop corners must form an axis-aligned rectangle.')
    return bbox


def save_crop_coordinates(image, bbox, size, output_dir):
    doc = crop_document(image, bbox, size)
    path = Path(output_dir) / (Path(image).stem + '.json')
    atomic_write(path, doc)
    return path
