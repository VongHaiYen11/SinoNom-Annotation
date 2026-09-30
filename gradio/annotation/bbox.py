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
    state['regions'][uid] = dict(bbox=coords, status='intact', unknown=False)
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
    
    # Pre-validate all coordinates before mutating state
    validated = {
        uid: validate_coordinates(bbox, state['image_size'])
        for uid, bbox in boxes.items()
    }
    
    # Remove regions deleted on frontend
    for uid in list(state['regions'].keys()):
        if uid not in boxes:
            delete_bbox(state, uid)

    # Update or add regions
    for uid, bbox in validated.items():
        if uid not in state['regions']:
            state['regions'][uid] = dict(bbox=bbox, status='intact', unknown=False)
        else:
            state['regions'][uid]['bbox'] = bbox

        box_id = state.get('box_id_by_region', {}).get(uid)
        if box_id in state.get('bounding_boxes', {}):
            state['bounding_boxes'][box_id]['bbox'] = list(bbox)

    selected = list(dict.fromkeys(selected or []))
    selected = [uid for uid in selected if uid in state['regions']]
    state['selected_region_uids'] = selected
    state['selected_region_uid'] = active if active in state['regions'] else (selected[-1] if selected else next(iter(state['regions']), None))

    mapped = set(state.get('box_id_by_region', {}))
    if set(state['regions']).issubset(mapped):
        state['saved'] = False
    else:
        invalidate(state, clear=True)


def sync_draft_boxes(state, payload):
    """Synchronize frontend draft boxes, statuses, unknowns, and orders to Python state."""
    boxes = payload.get('boxes')
    if not isinstance(boxes, dict) or not boxes:
        return

    update_bboxes(state, boxes, payload.get('active'), payload.get('selected'))

    statuses = payload.get('statuses', {})
    unknowns = payload.get('unknowns', {})
    for uid, status in statuses.items():
        if uid in state['regions'] and status in {'intact', 'damaged', 'unknown'}:
            state['regions'][uid]['status'] = status
    for uid, unk in unknowns.items():
        if uid in state['regions']:
            state['regions'][uid]['unknown'] = bool(unk)

    orders = payload.get('orders', {})
    if orders and isinstance(orders, dict):
        val_orders = {}
        for uid in state['regions']:
            o = orders.get(uid)
            if o is not None:
                try:
                    val_orders[uid] = int(o)
                except (ValueError, TypeError):
                    pass
        n = len(state['regions'])
        if len(val_orders) == n and sorted(val_orders.values()) == list(range(1, n + 1)):
            from copy import deepcopy
            from .state import source_mismatch_confirmed
            ordered_uids = sorted(state['regions'].keys(), key=lambda u: val_orders[u])
            ids = list(range(1, n + 1))
            state['box_id_by_region'] = {uid: str(box_id) for uid, box_id in zip(ordered_uids, ids)}
            state['region_uid_by_box_id'] = {str(box_id): uid for uid, box_id in zip(ordered_uids, ids)}
            state['bounding_boxes'] = {
                str(box_id): deepcopy(state['regions'][uid])
                for uid, box_id in zip(ordered_uids, ids)
            }
            if state['workflow'].get('content_verified'):
                if state['workflow'].get('bbox_valid'):
                    from .text_alignment import temporary_align_text
                    state['annotations'] = temporary_align_text(ids, state['annotation_text'])
                    state['text_sequence'] = list(state['annotations'].values())
                    state['text_token_ids'] = [str(i) for i in range(1, len(state['text_sequence']) + 1)]
                    state['reading_order'] = ids
                    state['workflow']['alignment_valid'] = True
                elif source_mismatch_confirmed(state):
                    state['reading_order'] = ids
                    state['workflow']['alignment_valid'] = True


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

