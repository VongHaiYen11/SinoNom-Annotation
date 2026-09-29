import math
from uuid import uuid4
from .state import invalidate


def validate_coordinates(bbox, size):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError('A bounding box must contain four coordinates.')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in bbox):
        raise ValueError('Coordinates must be finite numbers.')
    x1, y1, x2, y2 = bbox
    if not (0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1]):
        raise ValueError('Bounding box is outside the image or has invalid dimensions.')
    return list(bbox)


def add_bbox(state, bbox):
    coords = validate_coordinates(bbox, state['image_size'])
    uid = uuid4().hex
    state['regions'][uid] = dict(bbox=coords, status='intact')
    invalidate(state, clear=True)
    return uid


def update_bbox(state, region_uid, bbox):
    if region_uid not in state['regions']:
        raise ValueError('Region does not exist.')
    state['regions'][region_uid]['bbox'] = validate_coordinates(bbox, state['image_size'])
    box_id = state.get('box_id_by_region', {}).get(region_uid)
    if box_id in state.get('bounding_boxes', {}):
        state['bounding_boxes'][box_id]['bbox'] = list(state['regions'][region_uid]['bbox'])
        state['saved'] = False
    else:
        invalidate(state, clear=True)


def update_bboxes(state, boxes, active=None, selected=None):
    """Commit one completed frontend manipulation as a single transaction."""
    if not isinstance(boxes, dict) or not boxes:
        raise ValueError('A bounding-box commit must contain at least one box.')
    if any(uid not in state['regions'] for uid in boxes):
        raise ValueError('One or more committed regions do not exist.')
    validated = {
        uid: validate_coordinates(bbox, state['image_size'])
        for uid, bbox in boxes.items()
    }
    for uid, bbox in validated.items():
        state['regions'][uid]['bbox'] = bbox
        box_id = state.get('box_id_by_region', {}).get(uid)
        if box_id in state.get('bounding_boxes', {}):
            state['bounding_boxes'][box_id]['bbox'] = list(bbox)
    selected = list(dict.fromkeys(selected or []))
    if any(uid not in state['regions'] for uid in selected):
        raise ValueError('One or more selected regions do not exist.')
    state['selected_region_uids'] = selected
    state['selected_region_uid'] = active if active in selected else (selected[-1] if selected else None)
    mapped = set(state.get('box_id_by_region', {}))
    if set(state['regions']).issubset(mapped):
        state['saved'] = False
    else:
        invalidate(state, clear=True)


def delete_bbox(state, region_uid):
    if region_uid not in state['regions']:
        raise ValueError('Region does not exist.')
    box_id = state.get('box_id_by_region', {}).pop(region_uid, None)
    if box_id:
        state.get('region_uid_by_box_id', {}).pop(box_id, None)
        state.get('bounding_boxes', {}).pop(box_id, None)
        state.get('annotations', {}).pop(box_id, None)
        state['reading_order'] = [
            item for item in state.get('reading_order', [])
            if str(item) != str(box_id)
        ]
    del state['regions'][region_uid]
    if state['selected_region_uid'] == region_uid:
        state['selected_region_uid'] = None
    state['workflow'].update(alignment_valid=False, status_valid=False,
                             reading_order_valid=False)
    state['saved'] = False
