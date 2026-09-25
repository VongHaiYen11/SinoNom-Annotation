from copy import deepcopy
from .text_alignment import validate_bbox_text_count, temporary_align_text


def new_state():
    return dict(image=None, image_path=None, image_size=None, source_content=None,
                verified_content=None, draft_content=None, annotation_text='',
                bounding_boxes={}, annotations={}, reading_order=[], temporary_order=[],
                next_box_id=1, selected_box_id=None, revision=0, current_step=1,
                detection_loaded=False, crop=None, crop_saved=False, saved=False,
                workflow=dict(content_verified=False, bbox_valid=False,
                              alignment_valid=False, status_valid=False, reading_order_valid=False))


def invalidate(state, clear=False):
    state['workflow'].update(bbox_valid=False, alignment_valid=False,
                             status_valid=False, reading_order_valid=False)
    if clear:
        state['annotations'] = {}
        state['reading_order'] = list(state['temporary_order'])
    state['saved'] = False


def refresh_alignment(state):
    state['workflow']['bbox_valid'] = validate_bbox_text_count(state)
    if state['workflow']['content_verified'] and state['workflow']['bbox_valid']:
        if not state['workflow']['alignment_valid']:
            state['annotations'] = temporary_align_text(state['temporary_order'], state['annotation_text'])
            state['reading_order'] = list(state['temporary_order'])
            state['workflow']['alignment_valid'] = True


def set_verified_content(state, content, text):
    changed = text != state['annotation_text']
    state['verified_content'] = deepcopy(content)
    state['draft_content'] = deepcopy(content)
    state['workflow']['content_verified'] = True
    if changed:
        state['annotation_text'] = text
        invalidate(state, clear=True)
    state['saved'] = False


def require(state, key):
    if not state['workflow'][key]:
        raise ValueError('Complete the previous validation step: ' + key)
