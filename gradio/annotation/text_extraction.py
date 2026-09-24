"""Adapter for the inspected text_extraction JSON schema; UI is schema agnostic."""
from copy import deepcopy
from pathlib import Path
from threading import RLock
from .io import read_json, atomic_write

SOURCE_LOCK = RLock()
TITLE = 'Nguyên văn chữ Hán Nôm'


def extract_source_content(image_name, source_json):
    records = read_json(source_json) if isinstance(source_json, (str, Path)) else source_json
    if not isinstance(records, list):
        raise ValueError('Source JSON phải là array các văn bia.')
    code = Path(image_name).stem
    matches = [(ri, fi) for ri, r in enumerate(records)
               for fi, face in enumerate(r.get('noi_dung', [])) if str(face.get('ky_hieu')) == code]
    if len(matches) != 1:
        raise ValueError(f'ky_hieu={code}: tìm thấy {len(matches)} mặt bia; cần đúng một.')
    ri, fi = matches[0]
    record = deepcopy(records[ri])
    annotation_text(record, code)
    return dict(record=record, record_index=ri, face_index=fi, code=code)


def annotation_text(record, code):
    faces = [f for f in record.get('noi_dung', []) if str(f.get('ky_hieu')) == code]
    if len(faces) != 1:
        raise ValueError('Không được làm mất hoặc trùng ky_hieu của ảnh đang chọn.')
    sections = [s for s in faces[0].get('chuyen_muc', []) if s.get('tieu_de') == TITLE]
    if len(sections) != 1 or not isinstance(sections[0].get('van_ban'), str):
        raise ValueError('Cần đúng một chuyên mục Nguyên văn chữ Hán Nôm có van_ban.')
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
        raise ValueError('Giữ nguyên kiểu dữ liệu của field.')
    target[path[-1]] = parsed
    return result


def save_source_content(path, image_name, baseline, updated):
    annotation_text(updated, Path(image_name).stem)
    with SOURCE_LOCK:
        records = read_json(path)
        located = extract_source_content(image_name, records)
        if located['record'] != baseline:
            raise ValueError('Source đã được sửa bởi session khác. Hãy mở lại ảnh để tránh ghi đè.')
        records[located['record_index']] = deepcopy(updated)
        atomic_write(path, records)
