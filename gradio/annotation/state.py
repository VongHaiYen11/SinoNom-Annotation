from copy import deepcopy
from .text_alignment import validate_bbox_text_count, temporary_align_text


def new_state():
    return dict(image=None, image_path=None, image_size=None, source_content=None,
                verified_content=None, draft_content=None, annotation_text='',
                regions={}, selected_region_uid=None, selected_region_uids=[],
                bounding_boxes={}, annotations={}, reading_order=[],
                box_id_by_region={}, region_uid_by_box_id={}, selected_box_id=None,
                revision=0, current_step=1,
                detection_loaded=False, crop=None, crop_saved=False, saved=False,
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
    state['saved'] = False


def refresh_bbox_validation(state):
    """Refresh count validation without assigning characters or public box IDs."""
    state['workflow']['bbox_valid'] = validate_bbox_text_count(state)


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


def initialize_alignment(state):
    """Assign canonical 1..n box IDs and text after status verification."""
    refresh_bbox_validation(state)
    if not state['workflow']['content_verified'] or not state['workflow']['bbox_valid']:
        raise ValueError('Bounding-box and character counts must match.')
    ordered_uids = _spatial_region_order(state)
    ids = list(range(1, len(ordered_uids) + 1))
    state['box_id_by_region'] = {uid: str(box_id) for uid, box_id in zip(ordered_uids, ids)}
    state['region_uid_by_box_id'] = {str(box_id): uid for uid, box_id in zip(ordered_uids, ids)}
    state['bounding_boxes'] = {
        str(box_id): deepcopy(state['regions'][uid])
        for uid, box_id in zip(ordered_uids, ids)
    }
    state['annotations'] = temporary_align_text(ids, state['annotation_text'])
    state['reading_order'] = ids
    state['selected_box_id'] = state['box_id_by_region'].get(state['selected_region_uid'])
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
