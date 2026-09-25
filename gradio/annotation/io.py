import json
import os
import tempfile
from pathlib import Path
from .bbox import validate_coordinates
from .reading_order import validate_reading_order
from .text_alignment import validate_bbox_text_count, characters


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError('Duplicate JSON key: ' + k)
        out[k] = v
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique)


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_image_list(folder):
    root = Path(folder)
    if not root.is_dir():
        raise ValueError('Image folder does not exist: ' + str(root))
    images = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp'))
    stems = [p.stem for p in images]
    if len(stems) != len(set(stems)):
        raise ValueError('Image filenames must have unique stems.')
    return images


def validate_document(doc, image, size):
    if doc['image'] != image or not isinstance(doc['bounding_boxes'], dict):
        raise ValueError('Annotation does not belong to this image.')
    for key, box in doc['bounding_boxes'].items():
        if not key.isdecimal() or int(key) < 1 or str(int(key)) != key:
            raise ValueError('Box IDs must be canonical positive integers.')
        validate_coordinates(box['bbox'], size)
        if box['status'] not in ('intact', 'damaged'):
            raise ValueError('Invalid status.')
    expected_ids = {str(index) for index in range(1, len(doc['bounding_boxes']) + 1)}
    if set(doc['bounding_boxes']) != expected_ids:
        raise ValueError('Box IDs must be contiguous from 1 to n.')
    if not validate_reading_order(doc):
        raise ValueError('Invalid reading order.')
    if 'annotations' in doc:
        if set(doc['annotations']) != set(doc['bounding_boxes']):
            raise ValueError('Annotations contain missing or unknown box IDs.')
        if any(not isinstance(c, str) or characters(c) != [c] for c in doc['annotations'].values()):
            raise ValueError('Each annotation must contain one valid character.')
    if 'crop' in doc:
        from crop.crop import crop_bbox
        crop_bbox(doc['crop'], size)


def load_annotation(path, image, size):
    doc = read_json(path)
    if isinstance(doc, dict) and isinstance(doc.get('bounding_boxes'), dict):
        keys = set(doc['bounding_boxes'])
        expected = {str(index) for index in range(1, len(keys) + 1)}
        if keys != expected:
            order = doc.get('reading_order', [])
            if (len(order) != len(keys) or len(set(order)) != len(order)
                    or {str(box_id) for box_id in order} != keys):
                raise ValueError('Legacy annotation has an invalid reading order.')
            old_ids = [str(box_id) for box_id in order]
            doc['bounding_boxes'] = {
                str(index): doc['bounding_boxes'][old_id]
                for index, old_id in enumerate(old_ids, 1)
            }
            if 'annotations' in doc:
                doc['annotations'] = {
                    str(index): doc['annotations'][old_id]
                    for index, old_id in enumerate(old_ids, 1)
                }
            doc['reading_order'] = list(range(1, len(old_ids) + 1))
    validate_document(doc, image, size)
    return doc


def final_document(state):
    if not all(state['workflow'].values()) or not validate_bbox_text_count(state):
        raise ValueError('Complete all verification steps and match the box and character counts.')
    doc = {k: state[k] for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')}
    from crop.crop import crop_document, default_crop
    doc['crop'] = crop_document(
        state['image'], state.get('crop') or default_crop(state['image_size']),
        state['image_size']
    )['crop']
    validate_document(doc, state['image'], state['image_size'])
    return doc


def save_annotation(state, output_dir):
    doc = final_document(state)
    path = Path(output_dir) / (Path(state['image']).stem + '.json')
    atomic_write(path, doc)
    return path
