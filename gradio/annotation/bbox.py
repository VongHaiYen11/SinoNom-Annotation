import math
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
    key = str(state['next_box_id'])
    state['next_box_id'] += 1
    state['bounding_boxes'][key] = dict(bbox=coords, status='intact')
    state['temporary_order'].append(int(key))
    state['reading_order'].append(int(key))
    invalidate(state)
    return key


def update_bbox(state, box_id, bbox):
    key = str(box_id)
    if key not in state['bounding_boxes']:
        raise ValueError('Box ID does not exist.')
    state['bounding_boxes'][key]['bbox'] = validate_coordinates(bbox, state['image_size'])
    invalidate(state)


def delete_bbox(state, box_id):
    key = str(box_id)
    if key not in state['bounding_boxes']:
        raise ValueError('Box ID does not exist.')
    del state['bounding_boxes'][key]
    state['annotations'].pop(key, None)
    for field in ('temporary_order', 'reading_order'):
        state[field] = [i for i in state[field] if str(i) != key]
    if state['selected_box_id'] == key:
        state['selected_box_id'] = None
    invalidate(state)
