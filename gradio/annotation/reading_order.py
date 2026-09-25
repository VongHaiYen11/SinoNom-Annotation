from .state import require
from .text_alignment import validate_bbox_text_count


def validate_reading_order(state):
    order = state['reading_order']
    return (all(type(i) is int and i > 0 for i in order)
            and len(order) == len(set(order)) == len(state['bounding_boxes'])
            and {str(i) for i in order} == set(state['bounding_boxes']))


def update_reading_order(state, order):
    require(state, 'alignment_valid')
    require(state, 'status_valid')
    candidate = dict(state, reading_order=order)
    if not validate_bbox_text_count(state) or not validate_reading_order(candidate):
        raise ValueError('Reading order has missing, duplicate, or invalid IDs.')
    state['reading_order'] = list(order)
    state['workflow']['reading_order_valid'] = False
    state['saved'] = False


def build_text_sequence(state):
    if not validate_reading_order(state):
        raise ValueError('Invalid reading order.')
    return ''.join(state['annotations'][str(i)] for i in state['reading_order'])
