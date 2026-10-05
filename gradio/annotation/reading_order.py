from collections import Counter

from .state import require, source_mismatch_confirmed, spatial_box_order
from .text_alignment import (align_text_with_missing, temporary_align_text,
                             validate_bbox_text_count, characters)


def validate_reading_order(state):
    """Validate the internal coordinate-slot order.

    New annotation documents do not persist this derived value.  It remains
    in workflow state so older documents can be loaded and the UI can address
    the detector's spatial slots without recomputing them on every render.
    """
    order = state.get('reading_order', list(map(int, state['bounding_boxes'])))
    return (all(type(i) is int and i > 0 for i in order)
            and len(order) == len(set(order)) == len(state['bounding_boxes'])
            and {str(i) for i in order} == set(state['bounding_boxes']))


def update_text_sequence(state, sequence):
    """Assign a user-arranged text sequence to spatially ordered boxes."""
    require(state, 'alignment_valid')
    extra=(source_mismatch_confirmed(state)
           and state['source_mismatch']['issue_type'] == 'extra_text')
    expected=(characters(state['annotation_text']) if extra
              else list(state['annotations'].values()))
    if (not isinstance(sequence, list)
            or any(not isinstance(value, str) or not value for value in sequence)
            or Counter(sequence) != Counter(expected)):
        raise ValueError('Text sequence has missing, duplicate, or invalid items.')
    current_values=list(state.get('text_sequence') or state['annotations'].values())
    current_ids=list(map(str,state.get('text_token_ids',[])))
    if len(current_ids) != len(current_values) or len(set(current_ids)) != len(current_ids):
        current_ids=[str(index) for index in range(1,len(current_values)+1)]
    remaining=list(zip(current_values,current_ids))
    token_order=[]
    for value in sequence:
        match=next((index for index,item in enumerate(remaining) if item[0]==value),None)
        if match is None:
            raise ValueError('Text sequence token mapping is invalid.')
        token_order.append(remaining.pop(match)[1])
    _apply_text_sequence(state,sequence,token_order,extra)


def update_text_tokens(state, sequence, token_order):
    """Assign a browser-arranged sequence while preserving duplicate token identity."""
    require(state, 'alignment_valid')
    extra=(source_mismatch_confirmed(state)
           and state['source_mismatch']['issue_type'] == 'extra_text')
    expected=(characters(state['annotation_text']) if extra
              else list(state['annotations'].values()))
    current_ids=list(map(str,state.get('text_token_ids',[])))
    if not isinstance(token_order,list) or len(current_ids) != len(token_order):
        raise ValueError('Text token order is invalid.')
    token_order=list(map(str,token_order))
    if len(set(token_order)) != len(token_order) or set(token_order) != set(current_ids):
        raise ValueError('Text token order is invalid.')
    if (not isinstance(sequence,list) or Counter(sequence) != Counter(expected)):
        raise ValueError('Text sequence has missing, duplicate, or invalid items.')
    _apply_text_sequence(state,sequence,token_order,extra)


def _apply_text_sequence(state, sequence, token_order, extra):
    order = list(state.get('reading_order') or spatial_box_order(state))
    if (not extra and len(order) != len(sequence)):
        raise ValueError('Text sequence and bounding-box counts do not match.')
    kept=sequence[:len(order)]
    state['reading_order'] = order
    state['annotations'] = {
        str(box_id): value for box_id, value in zip(order, kept)
    }
    state['text_sequence']=list(sequence)
    state['text_token_ids']=list(token_order)
    selected_token = str(state.get('selected_token_id') or '')
    if selected_token in state['text_token_ids']:
        position = state['text_token_ids'].index(selected_token)
        state['selected_box_id'] = (str(order[position])
                                    if position < len(order) else None)
        state['selected_region_uid'] = state['region_uid_by_box_id'].get(
            state['selected_box_id'])
    if extra:
        state['source_mismatch']['excluded_characters']=list(sequence[len(order):])
    from .status import synchronize_missing_statuses
    synchronize_missing_statuses(state)
    state['workflow']['status_valid'] = False
    state['workflow']['reading_order_valid'] = False
    state['saved'] = False


def suspicious_box_ids(state):
    """Return the boxes currently receiving suspicious character tokens."""
    tokens=list(map(str,state.get('text_token_ids',[])))
    suspicious=set(map(str,state.get('suspicious_token_ids',[])))
    if not tokens or not suspicious or not state.get('bounding_boxes'):
        return []
    order=list(map(str,state.get('reading_order') or spatial_box_order(state)))
    return [box_id for box_id,token_id in zip(order,tokens) if token_id in suspicious]


def restore_suspicious_tokens(state, box_ids):
    order=list(map(str,state.get('reading_order') or spatial_box_order(state)))
    tokens=list(map(str,state.get('text_token_ids',[])))
    by_box=dict(zip(order,tokens))
    unknown=set(map(str,box_ids))-set(by_box)
    if unknown:
        raise ValueError('Suspicious details reference an unknown Box ID.')
    state['suspicious_token_ids']=[by_box[str(box_id)] for box_id in map(str,box_ids)]


def token_id_for_box(state, box_id):
    """Resolve a spatial coordinate slot to its currently assigned token."""
    order = list(map(str, state.get('reading_order') or spatial_box_order(state)))
    tokens = list(map(str, state.get('text_token_ids', [])))
    mapping = dict(zip(order, tokens))
    return mapping.get(str(box_id))


def build_text_sequence(state):
    if not validate_reading_order(state):
        raise ValueError('Invalid coordinate-slot order.')
    order = state.get('reading_order') or spatial_box_order(state)
    return ''.join(state['annotations'][str(i)] for i in order)
