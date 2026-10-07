import math
import logging
from uuid import uuid4
from .state import invalidate, refresh_bbox_validation, source_mismatch_confirmed

log = logging.getLogger(__name__)


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
    state['regions'][uid] = dict(bbox=coords, status='intact', unknown=False, unavailable_font=False, expert_prediction=False)
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
    """Replace regions with one complete frontend snapshot.

    ``boxes`` accepts the legacy ``{id: bbox}`` shape and the canonical
    ``{id: box}`` shape.  Existing/new metadata is retained; this function
    never merges missing backend regions back into the snapshot.
    """
    if not isinstance(boxes, dict):
        raise ValueError('A bounding-box commit must be an object keyed by box ID.')
    
    # Pre-validate all coordinates before mutating state
    normalized = {}
    for uid, value in boxes.items():
        if not isinstance(uid, str) or not uid:
            raise ValueError('Every bounding box must have a unique string ID.')
        box = dict(value) if isinstance(value, dict) else dict(state['regions'].get(uid, {}), bbox=value)
        box['bbox'] = validate_coordinates(box.get('bbox'), state['image_size'])
        box.setdefault('status', 'intact')
        from .status import normalize_flags
        for flag in ('unknown', 'unavailable_font', 'expert_prediction'):
            box.setdefault(flag, False)
        if box['status'] not in {'intact', 'damaged'}:
            raise ValueError(f'Invalid status for box {uid}.')
        normalize_flags(box)
        normalized[uid] = box

    # Replacement semantics are deliberate: deleted frontend IDs stay deleted.
    state['regions'] = normalized

    selected = list(dict.fromkeys(selected or []))
    selected = [uid for uid in selected if uid in state['regions']]
    state['selected_region_uids'] = selected
    state['selected_region_uid'] = active if active in state['regions'] else (selected[-1] if selected else next(iter(state['regions']), None))

    invalidate(state, clear=True)


def sync_draft_boxes(state, payload, materialize_alignment=True):
    """Synchronize frontend draft boxes, statuses, unknowns, and orders to Python state."""
    boxes = payload.get('boxes')
    if not isinstance(boxes, dict):
        return

    log.info('APPLY: frontend/Python received count=%d IDs=%s', len(boxes), list(boxes))

    previous_count = len(state['regions'])
    update_bboxes(state, boxes, payload.get('active'), payload.get('selected'))
    if len(state['regions']) != previous_count:
        # Keep the draft issue, but a changed count requires a new
        # confirmation even if the user later restores the original count.
        if state.get('source_mismatch'):
            state['source_mismatch']['invalidated'] = True

    statuses = payload.get('statuses', {})
    for uid, status in statuses.items():
        if uid in state['regions'] and status in {'intact', 'damaged'}:
            state['regions'][uid]['status'] = status
    from .status import FLAGS, normalize_flags
    for flag, field in zip(FLAGS, ('unknowns', 'unavailable_fonts', 'expert_predictions')):
        for uid, value in payload.get(field, {}).items():
            if uid in state['regions']:
                state['regions'][uid][flag] = value
    for uid, box in state['regions'].items():
        normalize_flags(box)

    # Orders are draft metadata and may be incomplete.  Apply saves progress;
    # only a complete 1..N set materializes the public alignment mapping.
    orders = payload.get('orders', {})
    if not orders:
        orders = {uid: box.get('order') for uid, box in state['regions'].items()}
    for uid in state['regions']:
        state['regions'][uid]['order'] = orders.get(uid)
    if orders and isinstance(orders, dict):
        val_orders = {}
        for uid in state['regions']:
            o = orders.get(uid)
            if o is not None:
                try:
                    parsed = int(o)
                    if isinstance(o, bool) or float(o) != parsed or parsed < 1:
                        raise ValueError
                    val_orders[uid] = parsed
                except (ValueError, TypeError):
                    pass
        n = len(state['regions'])
        if (materialize_alignment and len(val_orders) == n
                and sorted(val_orders.values()) == list(range(1, n + 1))):
            ordered_uids = sorted(state['regions'].keys(), key=lambda u: val_orders[u])
            if state['workflow'].get('content_verified'):
                refresh_bbox_validation(state)
            if (state['workflow'].get('content_verified')
                    and (state['workflow'].get('bbox_valid')
                         or source_mismatch_confirmed(state))):
                from .state import initialize_alignment
                initialize_alignment(state, ordered_uids=ordered_uids)
    log.info('APPLY: persisted draft count=%d IDs=%s',
             len(state['regions']), list(state['regions']))


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
