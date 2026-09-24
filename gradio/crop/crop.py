from pathlib import Path
from annotation.bbox import validate_coordinates
from annotation.io import atomic_write


def crop_document(image, bbox, size):
    x1, y1, x2, y2 = validate_coordinates(bbox, size)
    return dict(image=image, crop=dict(top_left=[x1, y1], top_right=[x2, y1],
                                    bottom_right=[x2, y2], bottom_left=[x1, y2]))


def save_crop_coordinates(image, bbox, size, output_dir):
    doc = crop_document(image, bbox, size)
    path = Path(output_dir) / (Path(image).stem + '.json')
    atomic_write(path, doc)
    return path
