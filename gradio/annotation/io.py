import json
import os
import tempfile
from pathlib import Path
from .bbox import validate_coordinates
from .text_alignment import MISSING_ANNOTATION, validate_bbox_text_count, characters


SOURCE_MISMATCH_TYPES = {'missing_text', 'extra_text', 'other'}


def canonical_issue_type(value):
    return value


def issue_types(value):
    values = value if isinstance(value, list) else [value]
    if (not values or any(not isinstance(item, str) for item in values)):
        raise ValueError('Issue types must be a non-empty string array.')
    normalized = [canonical_issue_type(item) for item in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError('Issue types must not contain duplicates.')
    return normalized


def source_mismatch_type(document):
    values = issue_types(document.get('issue_type'))
    mismatch = values
    if len(mismatch) != 1 or mismatch[0] not in SOURCE_MISMATCH_TYPES:
        raise ValueError('A source mismatch must contain exactly one mismatch issue type.')
    if any(value not in SOURCE_MISMATCH_TYPES for value in values):
        raise ValueError('Invalid issue type.')
    return mismatch[0]


def validate_source_mismatch_type(issue_type, character_count, box_count):
    issue_type = canonical_issue_type(issue_type)
    if issue_type not in SOURCE_MISMATCH_TYPES:
        raise ValueError('Invalid source mismatch issue type.')
    if issue_type == 'missing_text' and character_count >= box_count:
        raise ValueError('Missing source characters requires more boxes than source characters.')
    if issue_type == 'extra_text' and character_count <= box_count:
        raise ValueError('Extra source characters requires more characters than boxes.')


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
    if 'issue_type' in doc and 'inscription_code' not in doc:
        raise ValueError('Normal annotations cannot contain issue_type.')
    for key, box in doc['bounding_boxes'].items():
        if not key.isdecimal() or int(key) < 1 or str(int(key)) != key:
            raise ValueError('Box IDs must be canonical positive integers.')
        validate_coordinates(box['bbox'], size)
        if box['status'] not in ('intact', 'damaged'):
            raise ValueError('Invalid status.')
        from .status import validate_flags
        validate_flags(box)
        if doc.get('annotations', {}).get(key) == MISSING_ANNOTATION and any(box[flag] for flag in ('unknown', 'unavailable_font', 'expert_prediction', 'suspicious')):
            raise ValueError('MISS boxes cannot have character flags.')
    expected_ids = {str(index) for index in range(1, len(doc['bounding_boxes']) + 1)}
    if set(doc['bounding_boxes']) != expected_ids:
        raise ValueError('Box IDs must be contiguous from 1 to n.')
    if 'annotations' in doc:
        if set(doc['annotations']) != set(doc['bounding_boxes']):
            raise ValueError('Annotations contain missing or unknown box IDs.')
        if any(not isinstance(c, str) or (c != MISSING_ANNOTATION and characters(c) != [c])
               for c in doc['annotations'].values()):
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
    required = {'image', 'bounding_boxes', 'annotations', 'image_resize', 'crop'}
    allowed = required
    if not isinstance(doc, dict) or not required.issubset(doc) or not set(doc).issubset(allowed):
        raise ValueError('Invalid annotation document schema.')
    if isinstance(doc, dict) and 'issue_type' in doc:
        doc['issue_type'] = issue_types(doc['issue_type'])
    validate_document(doc, image, size)
    return doc


def validate_source_mismatch_document(doc, image, size):
    mismatch_type = source_mismatch_type(doc) if isinstance(doc, dict) else None
    minimal_other_keys = {'image','inscription_code','issue_type','note','bounding_boxes'}
    if (isinstance(doc, dict) and mismatch_type == 'other'
            and set(doc) == minimal_other_keys):
        if doc.get('image') != image:
            raise ValueError('Invalid Other source mismatch document.')
        if doc.get('inscription_code') != Path(image).stem:
            raise ValueError('Source mismatch does not belong to this inscription.')
        if not isinstance(doc.get('note'),str) or not doc['note'].strip():
            raise ValueError('Other source mismatches require a note.')
        boxes=doc.get('bounding_boxes')
        if not isinstance(boxes,dict):
            raise ValueError('Invalid Other bounding boxes.')
        for key,box in boxes.items():
            if (not key.isdecimal() or set(box) != {'bbox'}):
                raise ValueError('Other mismatch boxes may contain only bbox coordinates.')
            validate_coordinates(box['bbox'],size)
        return doc
    required_keys = {
        'image', 'inscription_code', 'source_text', 'source_character_count',
        'bounding_box_count', 'issue_type', 'note', 'bounding_boxes',
        'image_resize', 'crop',
    }
    allowed_keys = required_keys | {'annotations','text_sequence','excluded_characters'}
    if (not isinstance(doc, dict) or not required_keys.issubset(doc)
            or not set(doc).issubset(allowed_keys)):
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
        mismatch_type, doc['source_character_count'], doc['bounding_box_count'])
    if not isinstance(doc['note'], str):
        raise ValueError('Source mismatch note must be a string.')
    annotations = doc.get('annotations')
    if mismatch_type == 'missing_text':
        if not isinstance(annotations, dict):
            raise ValueError('Missing-source documents require annotations.')
        missing_count = doc['bounding_box_count'] - doc['source_character_count']
        if list(annotations.values()).count(MISSING_ANNOTATION) != missing_count:
            raise ValueError('Missing-source annotations contain an invalid MISS count.')
    elif mismatch_type == 'extra_text':
        sequence=doc.get('text_sequence');excluded=doc.get('excluded_characters')
        excess=doc['source_character_count']-doc['bounding_box_count']
        if (not isinstance(annotations,dict) or not isinstance(sequence,list)
                or not isinstance(excluded,list) or len(sequence) != doc['source_character_count']
                or excluded != sequence[-excess:]
                or list(annotations.values()) != sequence[:-excess]):
            raise ValueError('Extra-source character mapping is invalid.')
        if sorted(sequence) != sorted(characters(doc['source_text'])):
            raise ValueError('Extra-source text sequence does not match source content.')
    elif annotations is not None:
        raise ValueError('This mismatch type cannot contain annotations.')
    validate_document(doc, image, size)
    return doc


def load_source_mismatch(path, image, size):
    doc = read_json(path)
    doc['issue_type'] = issue_types(doc.get('issue_type'))
    return validate_source_mismatch_document(doc, image, size)


def crop_export_geometry(state):
    from crop.crop import auto_scale_crop, default_crop
    source_crop = state.get('crop') or default_crop(state['image_size'])
    if (state.get('loaded_crop_source') == source_crop
            and state.get('loaded_crop_scaled') is not None):
        return list(state['loaded_crop_scaled']), list(state['resized_image_size'])
    return auto_scale_crop(source_crop, state['image_size'])


def final_document(state):
    if not all(state['workflow'].values()) or not validate_bbox_text_count(state):
        raise ValueError('Complete all verification steps and match the box and character counts.')
    doc = {k: state[k] for k in ('image', 'bounding_boxes', 'annotations')}
    from crop.crop import crop_document, image_resize
    scaled_crop, resized_size = crop_export_geometry(state)
    doc['crop'] = crop_document(
        state['image'], scaled_crop, resized_size
    )['crop']
    doc['image_resize'] = image_resize(state['image_size'], resized_size)
    validate_document(doc, state['image'], state['image_size'])
    return doc


def final_source_mismatch_document(state):
    from .state import source_mismatch_confirmed
    issue = state['source_mismatch'] or {}
    mismatch_type = canonical_issue_type(issue.get('issue_type'))
    if mismatch_type == 'other':
        if not source_mismatch_confirmed(state) or not issue.get('note','').strip():
            raise ValueError('Confirm Other with a note before saving.')
        return validate_source_mismatch_document({
            'image':state['image'],'inscription_code':str(state['code']),
            'issue_type':['other'],
            'note':issue['note'],
            'bounding_boxes':{
                str(index):{'bbox':list(state['regions'][uid]['bbox'])}
                for index,uid in enumerate(state_order(state),1)
            },
        },state['image'],state['image_size'])
    required = ('content_verified', 'alignment_valid', 'status_valid', 'reading_order_valid')
    if not all(state['workflow'][key] for key in required) or not source_mismatch_confirmed(state):
        raise ValueError('Complete all verification steps and confirm the source mismatch.')
    doc = {
        'image': state['image'],
        'inscription_code': str(state['code']),
        'source_text': state['annotation_text'],
        'source_character_count': issue['source_character_count'],
        'bounding_box_count': issue['bounding_box_count'],
        'issue_type': [mismatch_type],
        'note': issue['note'],
        'bounding_boxes': state['bounding_boxes'],
    }
    if mismatch_type in ('missing_text','extra_text'):
        doc['annotations'] = state['annotations']
    if mismatch_type == 'extra_text':
        doc['text_sequence']=list(state['text_sequence'])
        doc['excluded_characters']=list(issue['excluded_characters'])
    from crop.crop import crop_document, image_resize
    scaled_crop, resized_size = crop_export_geometry(state)
    doc['image_resize'] = image_resize(state['image_size'], resized_size)
    doc['crop'] = crop_document(
        state['image'], scaled_crop, resized_size
    )['crop']
    return validate_source_mismatch_document(doc, state['image'], state['image_size'])


def state_order(state):
    """Stable spatial order for minimal coordinate-only mismatch exports."""
    from .state import _spatial_region_order
    return _spatial_region_order(state)


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
