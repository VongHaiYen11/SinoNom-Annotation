from copy import deepcopy
from .text_alignment import (align_text_with_missing, count_annotation_characters,
                             temporary_align_text, validate_bbox_text_count)


def new_state():
    return dict(image=None, image_path=None, image_size=None, image_url=None,
                content_preview_url=None, source_content=None,
                verified_content=None, draft_content=None, annotation_text='',
                regions={}, selected_region_uid=None, selected_region_uids=[],
                bounding_boxes={}, annotations={}, reading_order=[],
                text_sequence=[],
                text_token_ids=[], suspicious_token_ids=[],
                box_id_by_region={}, region_uid_by_box_id={}, selected_box_id=None,
                selected_token_id=None,
                revision=0, current_step=1,
                detection_loaded=False, crop=None, resized_image_size=None,
                source_mismatch=None,
                crop_saved=False, saved=False,
                workflow=dict(content_verified=False, bbox_valid=False,
                              alignment_valid=False, status_valid=False, reading_order_valid=False))


def invalidate(state, clear=False):
    state['workflow'].update(bbox_valid=False, alignment_valid=False,
                             status_valid=False, reading_order_valid=False)
    if clear:
        state['bounding_boxes'] = {}
        state['annotations'] = {}
        state['reading_order'] = []
        state['box_id_by_region'] = {}
        state['region_uid_by_box_id'] = {}
        state['selected_box_id'] = None
        state['selected_token_id'] = None
        state['text_token_ids'] = []
        state['suspicious_token_ids'] = []
    state['saved'] = False


def refresh_bbox_validation(state):
    """Refresh count validation without assigning characters or public box IDs."""
    state['workflow']['bbox_valid'] = validate_bbox_text_count(state)


def source_mismatch_confirmed(state):
    """Return whether the recorded source exception matches current state."""
    issue = state.get('source_mismatch')
    box_count = len(state['regions'])
    character_count = count_annotation_characters(state['annotation_text'])
    return bool(
        issue
        and (box_count != character_count or issue.get('issue_type') == 'other')
        and issue.get('source_text') == state['annotation_text']
        and issue.get('source_character_count') == character_count
        and issue.get('bounding_box_count') == box_count
    )


def _spatial_region_order(state):
    from text_detection.reading_order import sort_recognized_boxes

    remaining = [(uid, list(region['bbox'])) for uid, region in state['regions'].items()]
    boxes = [box for _, box in remaining]
    try:
        ordered_boxes = sort_recognized_boxes(
            boxes, state['image_size'][1], state['image_size'][0]
        )
    except ModuleNotFoundError as exc:
        if exc.name not in {'cv2', 'numpy', 'shapely'}:
            raise
        # Lightweight vertical Sino-Nôm order: right-to-left, then top-to-bottom.
        ordered_boxes = sorted(
            boxes,
            key=lambda box: (-((box[0] + box[2]) / 2), (box[1] + box[3]) / 2),
        )
    ordered_uids = []
    for ordered_box in ordered_boxes:
        for position, (uid, box) in enumerate(remaining):
            if box == list(ordered_box):
                ordered_uids.append(uid)
                remaining.pop(position)
                break
        else:
            raise ValueError('Reading-order output contains an unknown region.')
    if remaining:
        raise ValueError('Reading order does not contain every region.')
    return ordered_uids


def spatial_box_order(state):
    """Return public Box IDs in the detector's canonical spatial order."""
    ordered_uids = _spatial_region_order(state)
    try:
        return [int(state['box_id_by_region'][uid]) for uid in ordered_uids]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Every spatial region must have a numeric Box ID.') from exc


def initialize_alignment(state):
    """Assign canonical IDs/order and text when a 1:1 alignment exists."""
    refresh_bbox_validation(state)
    if (not state['workflow']['content_verified']
            or not (state['workflow']['bbox_valid'] or source_mismatch_confirmed(state))):
        raise ValueError('Bounding-box and character counts must match or have a confirmed source mismatch.')
    ordered_uids = _spatial_region_order(state)
    ids = list(range(1, len(ordered_uids) + 1))
    state['box_id_by_region'] = {uid: str(box_id) for uid, box_id in zip(ordered_uids, ids)}
    state['region_uid_by_box_id'] = {str(box_id): uid for uid, box_id in zip(ordered_uids, ids)}
    state['bounding_boxes'] = {
        str(box_id): deepcopy(state['regions'][uid])
        for uid, box_id in zip(ordered_uids, ids)
    }
    if state['workflow']['bbox_valid']:
        state['annotations'] = temporary_align_text(ids, state['annotation_text'])
        state['text_sequence'] = list(state['annotations'].values())
    elif state['source_mismatch']['issue_type'] == 'missing_text':
        state['annotations'] = align_text_with_missing(ids, state['annotation_text'])
        state['text_sequence'] = list(state['annotations'].values())
    elif state['source_mismatch']['issue_type'] == 'extra_text':
        from .text_alignment import characters
        sequence=characters(state['annotation_text'])
        state['text_sequence']=sequence
        state['annotations']=dict(zip(map(str,ids),sequence[:len(ids)]))
        state['source_mismatch']['excluded_characters']=sequence[len(ids):]
    else:
        state['annotations'] = {}
        state['text_sequence'] = []
    state['text_token_ids'] = [str(index) for index in range(1,len(state['text_sequence'])+1)]
    state['suspicious_token_ids'] = []
    state['reading_order'] = ids
    state['selected_box_id'] = state['box_id_by_region'].get(state['selected_region_uid'])
    selected_index = (ids.index(int(state['selected_box_id']))
                      if state['selected_box_id'] else None)
    state['selected_token_id'] = (state['text_token_ids'][selected_index]
                                  if selected_index is not None
                                  and selected_index < len(state['text_token_ids']) else None)
    from .status import synchronize_missing_statuses
    synchronize_missing_statuses(state)
    state['workflow']['alignment_valid'] = True
    state['workflow']['reading_order_valid'] = False


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
