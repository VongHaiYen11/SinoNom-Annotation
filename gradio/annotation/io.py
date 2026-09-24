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
            raise ValueError('JSON trùng key: ' + k)
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
        raise ValueError('Thư mục ảnh không tồn tại: ' + str(root))
    images = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp'))
    stems = [p.stem for p in images]
    if len(stems) != len(set(stems)):
        raise ValueError('Tên mã ảnh bị trùng giữa các extension.')
    return images


def validate_document(doc, image, size):
    if doc['image'] != image or not isinstance(doc['bounding_boxes'], dict):
        raise ValueError('Annotation không thuộc ảnh này.')
    for key, box in doc['bounding_boxes'].items():
        if not key.isdecimal() or int(key) < 1 or str(int(key)) != key:
            raise ValueError('Box ID phải là số nguyên dương dạng canonical.')
        validate_coordinates(box['bbox'], size)
        if box['status'] not in ('intact', 'damaged'):
            raise ValueError('Status không hợp lệ.')
    if not validate_reading_order(doc):
        raise ValueError('Reading order không hợp lệ.')
    if 'annotations' in doc:
        if set(doc['annotations']) != set(doc['bounding_boxes']):
            raise ValueError('Annotation thiếu hoặc thừa box ID.')
        if any(not isinstance(c, str) or characters(c) != [c] for c in doc['annotations'].values()):
            raise ValueError('Mỗi annotation phải là một ký tự hợp lệ.')


def load_annotation(path, image, size):
    doc = read_json(path)
    validate_document(doc, image, size)
    return doc


def final_document(state):
    if not all(state['workflow'].values()) or not validate_bbox_text_count(state):
        raise ValueError('Chưa hoàn tất xác nhận hoặc số box không khớp ký tự.')
    doc = {k: state[k] for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')}
    validate_document(doc, state['image'], state['image_size'])
    return doc


def save_annotation(state, output_dir):
    doc = final_document(state)
    path = Path(output_dir) / (Path(state['image']).stem + '.json')
    atomic_write(path, doc)
    return path
