from .state import require, source_mismatch_confirmed
from .text_alignment import (align_text_with_missing, temporary_align_text,
                             validate_bbox_text_count)


def validate_reading_order(state):
    order = state['reading_order']
    return (all(type(i) is int and i > 0 for i in order)
            and len(order) == len(set(order)) == len(state['bounding_boxes'])
            and {str(i) for i in order} == set(state['bounding_boxes']))


def update_reading_order(state, order):
    require(state, 'alignment_valid')
    require(state, 'status_valid')
    candidate = dict(state, reading_order=order)
    if (not (validate_bbox_text_count(state) or source_mismatch_confirmed(state))
            or not validate_reading_order(candidate)):
        raise ValueError('Reading order has missing, duplicate, or invalid IDs.')
    # Geometry and status stay attached to their Box IDs. Source characters
    # are assigned by position in reading order: character 1 goes to order[0],
    # character 2 to order[1], and so on.
    state['reading_order'] = list(order)
    if validate_bbox_text_count(state):
        state['annotations'] = temporary_align_text(order, state['annotation_text'])
    elif (source_mismatch_confirmed(state)
          and state['source_mismatch']['issue_type'] == 'missing_source_characters'):
        state['annotations'] = align_text_with_missing(order, state['annotation_text'])
    state['workflow']['reading_order_valid'] = False
    state['saved'] = False


def build_text_sequence(state):
    if not validate_reading_order(state):
        raise ValueError('Invalid reading order.')
    return ''.join(state['annotations'][str(i)] for i in state['reading_order'])
