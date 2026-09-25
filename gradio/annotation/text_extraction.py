"""Adapter for the inspected text_extraction JSON schema; UI is schema agnostic."""
from copy import deepcopy
from pathlib import Path
from threading import RLock
from .io import read_json, atomic_write

SOURCE_LOCK = RLock()
CONTENT_LOCK = RLock()
TITLE = 'Nguyên văn chữ Hán Nôm'
CONTENT_TITLES = (TITLE, 'Phiên âm Hán Việt', 'Dịch nghĩa', 'Toát yếu', 'Chú thích')


def content_fields(record, code):
    """Editable text sections on the selected face, with original source paths.

    Keep the full record in state/persistence. Missing sections are not invented.
    """
    faces = [(index, face) for index, face in enumerate(record.get('noi_dung', []))
             if str(face.get('ky_hieu')) == str(code)]
    if len(faces) != 1:
        raise ValueError('Exactly one inscription face must match the selected image.')
    face_index, face = faces[0]
    fields = []
    for title in CONTENT_TITLES:
        for section_index, section in enumerate(face.get('chuyen_muc', [])):
            if section.get('tieu_de') == title and isinstance(section.get('van_ban'), str):
                fields.append(dict(title=title, value=section['van_ban'],
                                   path=('noi_dung', face_index, 'chuyen_muc', section_index, 'van_ban')))
    return fields


def content_document(image_name, code, record):
    """Create the stable per-image document committed by Save content."""
    values = {}
    for field in content_fields(record, code):
        if field['title'] in values:
            raise ValueError(f'Duplicate content section: {field["title"]}')
        values[field['title']] = field['value']
    return {
        'image': Path(image_name).name,
        'inscription_code': str(code),
        'content': {title: values.get(title) for title in CONTENT_TITLES},
    }


def validate_content_document(document, image_name):
    if not isinstance(document, dict) or set(document) != {'image', 'inscription_code', 'content'}:
        raise ValueError('Invalid saved content document.')
    expected_image = Path(image_name).name
    if document['image'] != expected_image or document['inscription_code'] != Path(expected_image).stem:
        raise ValueError('Saved content does not belong to this image.')
    content = document['content']
    if not isinstance(content, dict) or set(content) != set(CONTENT_TITLES):
        raise ValueError('Saved content must contain the five configured sections.')
    if any(value is not None and not isinstance(value, str) for value in content.values()):
        raise ValueError('Saved content values must be text or null.')
    return document


def save_content_document(document, output_dir):
    validate_content_document(document, document.get('image') if isinstance(document, dict) else '')
    # This registry is the durable Save-all list. Save content never downloads a file.
    path = Path(output_dir) / '.state' / 'content.json'
    with CONTENT_LOCK:
        documents = read_json(path) if path.exists() else []
        if not isinstance(documents, list):
            raise ValueError('The saved-content registry must be a JSON array.')
        by_image = {}
        order = []
        for existing in documents:
            validate_content_document(existing, existing.get('image') if isinstance(existing, dict) else '')
            image = existing['image']
            if image in by_image:
                raise ValueError('The saved-content registry contains duplicate images.')
            by_image[image] = existing
            order.append(image)
        if document['image'] not in by_image:
            order.append(document['image'])
        by_image[document['image']] = document
        atomic_write(path, [by_image[image] for image in order])
    return path


def edit_content_field(record, code, path, value):
    if not isinstance(path, (tuple, list)) or not any(
            tuple(path) == field['path'] for field in content_fields(record, code)):
        raise ValueError('Only the five content sections of the selected inscription may be edited.')
    if not isinstance(value, str):
        raise ValueError('Section content must be a text string.')
    return edit_field(record, path, value)


def extract_source_content(image_name, source_json):
    records = read_json(source_json) if isinstance(source_json, (str, Path)) else source_json
    if not isinstance(records, list):
        raise ValueError('Source JSON must be an array of inscriptions.')
    code = Path(image_name).stem
    matches = [(ri, fi) for ri, r in enumerate(records)
               for fi, face in enumerate(r.get('noi_dung', [])) if str(face.get('ky_hieu')) == code]
    if len(matches) != 1:
        raise ValueError(f'Image code {code}: found {len(matches)} inscription faces; expected exactly one.')
    ri, fi = matches[0]
    record = deepcopy(records[ri])
    annotation_text(record, code)
    return dict(record=record, record_index=ri, face_index=fi, code=code)


def annotation_text(record, code):
    faces = [f for f in record.get('noi_dung', []) if str(f.get('ky_hieu')) == code]
    if len(faces) != 1:
        raise ValueError('The selected image code must exist exactly once.')
    sections = [s for s in faces[0].get('chuyen_muc', []) if s.get('tieu_de') == TITLE]
    if len(sections) != 1 or not isinstance(sections[0].get('van_ban'), str):
        raise ValueError('Exactly one original Han/Nom section with text content is required.')
    return sections[0]['van_ban']


def leaf_fields(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaf_fields(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaf_fields(v, path + (i,))
    else:
        yield path, value


def edit_field(record, path, value):
    import json
    result = deepcopy(record)
    target = result
    for part in path[:-1]:
        target = target[part]
    old = target[path[-1]]
    parsed = value if isinstance(old, str) else json.loads(value)
    if type(parsed) is not type(old):
        raise ValueError('The field data type must not change.')
    target[path[-1]] = parsed
    return result


def save_source_content(path, image_name, baseline, updated):
    annotation_text(updated, Path(image_name).stem)
    with SOURCE_LOCK:
        records = read_json(path)
        located = extract_source_content(image_name, records)
        if located['record'] != baseline:
            raise ValueError('Source content changed in another session. Reopen the image before saving.')
        records[located['record_index']] = deepcopy(updated)
        atomic_write(path, records)
