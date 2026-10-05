from .state import source_mismatch_confirmed
from .text_alignment import MISSING_ANNOTATION


EDITABLE_STATUSES = ('intact', 'damaged')
UNKNOWN_STATUS = 'unknown'


def synchronize_missing_statuses(state):
    """Keep legacy unknown statuses editable as intact/damaged and ensure unknown flag exists."""
    for box_id, region_uid in state['region_uid_by_box_id'].items():
        current = state['regions'][region_uid]['status']
        status = 'intact' if current == UNKNOWN_STATUS else current
        is_unknown = bool(state['regions'][region_uid].get('unknown', False)) if status == 'damaged' else False
        if state.get('annotations', {}).get(str(box_id)) == MISSING_ANNOTATION:
            is_unknown = False
        state['regions'][region_uid]['status'] = status
        state['regions'][region_uid]['unknown'] = is_unknown
        state['bounding_boxes'][box_id]['status'] = status
        state['bounding_boxes'][box_id]['unknown'] = is_unknown


def update_status(state, region_uid, status, unknown=False):
    if region_uid not in state['regions']:
        raise ValueError('Invalid region or status.')
    box_id = state['box_id_by_region'].get(region_uid)
    if status not in EDITABLE_STATUSES:
        raise ValueError('Every box must be intact or damaged.')
    is_unknown = bool(unknown) if status == 'damaged' else False
    state['regions'][region_uid]['status'] = status
    state['regions'][region_uid]['unknown'] = is_unknown
    if box_id and box_id in state.get('bounding_boxes', {}):
        state['bounding_boxes'][box_id]['status'] = status
        state['bounding_boxes'][box_id]['unknown'] = is_unknown
    state['saved'] = False


def replace_statuses(state, statuses, unknowns=None):
    """Atomically replace the status and unknown flag of every editable region."""
    if not isinstance(statuses, dict) or set(statuses) != set(state['regions']):
        raise ValueError('Statuses must contain every region exactly once.')
    if unknowns is not None and not isinstance(unknowns, dict):
        raise ValueError('Unknowns must be a mapping of region IDs to boolean flags.')
    for region_uid, status in statuses.items():
        if status not in EDITABLE_STATUSES:
            raise ValueError('Every box must be intact or damaged.')
    for region_uid, status in statuses.items():
        is_unknown = bool(unknowns.get(region_uid, False)) if (unknowns and status == 'damaged') else False
        state['regions'][region_uid]['status'] = status
        state['regions'][region_uid]['unknown'] = is_unknown
        box_id = state['box_id_by_region'].get(region_uid)
        if box_id in state['bounding_boxes']:
            state['bounding_boxes'][box_id]['status'] = status
            state['bounding_boxes'][box_id]['unknown'] = is_unknown
    state['saved'] = False


def confirm_status(state):
    if not (state['workflow']['bbox_valid'] or source_mismatch_confirmed(state)):
        raise ValueError('Bounding-box and character counts must match or have a confirmed source mismatch.')
    synchronize_missing_statuses(state)
    for region_uid, box_id in state['box_id_by_region'].items():
        if state['regions'][region_uid]['status'] not in EDITABLE_STATUSES:
            raise ValueError('Every region must have a valid status.')
    # Regions are the editable source of truth. Re-copy every known status at
    # the step boundary so Reading Order, Review, and export cannot retain a
    # stale bounding-box status after returning to this step.
    for region_uid, box_id in state['box_id_by_region'].items():
        if region_uid in state['regions'] and box_id in state['bounding_boxes']:
            status = state['regions'][region_uid]['status']
            is_unknown = bool(state['regions'][region_uid].get('unknown', False)) if status == 'damaged' else False
            state['bounding_boxes'][box_id]['status'] = status
            state['bounding_boxes'][box_id]['unknown'] = is_unknown
    state['workflow']['status_valid'] = True
