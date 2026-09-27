import json
import os
import tempfile
from pathlib import Path
from .bbox import validate_coordinates
from .reading_order import validate_reading_order
from .text_alignment import validate_bbox_text_count, characters


SOURCE_MISMATCH_TYPES = {
    'missing_source_characters',
    'extra_source_characters',
    'wrong_source_content',
    'other',
}


def validate_source_mismatch_type(issue_type, character_count, box_count):
    if issue_type not in SOURCE_MISMATCH_TYPES:
        raise ValueError('Invalid source mismatch issue type.')
    if issue_type == 'missing_source_characters' and character_count >= box_count:
        raise ValueError('Missing source characters requires more boxes than source characters.')
    if issue_type == 'extra_source_characters' and character_count <= box_count:
        raise ValueError('Extra source characters requires more source characters than boxes.')


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
    resized_size = size
    if 'image_resize' in doc:
        from crop.crop import image_resize
        resize = doc['image_resize']
        if not isinstance(resize, dict) or set(resize) != {
                'source_size', 'output_size', 'scale_x', 'scale_y'}:
            raise ValueError('Invalid image resize metadata.')
        expected = image_resize(size, resize.get('output_size'))
        if resize != expected:
            raise ValueError('Image resize metadata does not match the image dimensions.')
        resized_size = expected['output_size']
    if 'crop' in doc:
        from crop.crop import crop_bbox
        crop_bbox(doc['crop'], resized_size)


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


def validate_source_mismatch_document(doc, image, size):
    expected_keys = {
        'image', 'inscription_code', 'source_text', 'source_character_count',
        'bounding_box_count', 'issue_type', 'note', 'bounding_boxes',
        'reading_order', 'image_resize', 'crop',
    }
    if not isinstance(doc, dict) or set(doc) != expected_keys:
        raise ValueError('Invalid source mismatch document.')
    if doc['inscription_code'] != Path(image).stem:
        raise ValueError('Source mismatch does not belong to this inscription.')
    if not isinstance(doc['source_text'], str):
        raise ValueError('Source mismatch text must be a string.')
    if (type(doc['source_character_count']) is not int
            or type(doc['bounding_box_count']) is not int
            or doc['source_character_count'] < 0 or doc['bounding_box_count'] < 0):
        raise ValueError('Source mismatch counts must be non-negative integers.')
    if doc['source_character_count'] != len(characters(doc['source_text'])):
        raise ValueError('Source mismatch character count is invalid.')
    if doc['bounding_box_count'] != len(doc.get('bounding_boxes', {})):
        raise ValueError('Source mismatch bounding-box count is invalid.')
    if doc['source_character_count'] == doc['bounding_box_count']:
        raise ValueError('Source mismatch counts must differ.')
    validate_source_mismatch_type(
        doc['issue_type'], doc['source_character_count'], doc['bounding_box_count'])
    if not isinstance(doc['note'], str):
        raise ValueError('Source mismatch note must be a string.')
    if 'annotations' in doc:
        raise ValueError('Source mismatch documents cannot contain annotations.')
    validate_document(doc, image, size)
    return doc


def load_source_mismatch(path, image, size):
    return validate_source_mismatch_document(read_json(path), image, size)


def final_document(state):
    if not all(state['workflow'].values()) or not validate_bbox_text_count(state):
        raise ValueError('Complete all verification steps and match the box and character counts.')
    doc = {k: state[k] for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')}
    from crop.crop import crop_document, default_crop, image_resize
    resized_size = state.get('resized_image_size') or state['image_size']
    doc['crop'] = crop_document(
        state['image'], state.get('crop') or default_crop(resized_size),
        resized_size
    )['crop']
    doc['image_resize'] = image_resize(state['image_size'], resized_size)
    validate_document(doc, state['image'], state['image_size'])
    return doc


def final_source_mismatch_document(state):
    from .state import source_mismatch_confirmed
    required = ('content_verified', 'alignment_valid', 'status_valid', 'reading_order_valid')
    if not all(state['workflow'][key] for key in required) or not source_mismatch_confirmed(state):
        raise ValueError('Complete all verification steps and confirm the source mismatch.')
    issue = state['source_mismatch']
    doc = {
        'image': state['image'],
        'inscription_code': str(state['code']),
        'source_text': state['annotation_text'],
        'source_character_count': issue['source_character_count'],
        'bounding_box_count': issue['bounding_box_count'],
        'issue_type': issue['issue_type'],
        'note': issue['note'],
        'bounding_boxes': state['bounding_boxes'],
        'reading_order': state['reading_order'],
    }
    from crop.crop import crop_document, default_crop, image_resize
    resized_size = state.get('resized_image_size') or state['image_size']
    doc['image_resize'] = image_resize(state['image_size'], resized_size)
    doc['crop'] = crop_document(
        state['image'], state.get('crop') or default_crop(resized_size), resized_size
    )['crop']
    return validate_source_mismatch_document(doc, state['image'], state['image_size'])


def save_annotation(state, output_dir):
    doc = final_document(state)
    path = Path(output_dir) / (Path(state['image']).stem + '.json')
    atomic_write(path, doc)
    mismatch_path = Path(output_dir) / 'source_mismatches' / path.name
    mismatch_path.unlink(missing_ok=True)
    return path


def save_source_mismatch(state, output_dir):
    doc = final_source_mismatch_document(state)
    path = Path(output_dir) / 'source_mismatches' / (Path(state['image']).stem + '.json')
    atomic_write(path, doc)
    (Path(output_dir) / (Path(state['image']).stem + '.json')).unlink(missing_ok=True)
    return path
