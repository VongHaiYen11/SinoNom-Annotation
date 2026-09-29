from .state import source_mismatch_confirmed
from .text_alignment import MISSING_ANNOTATION


EDITABLE_STATUSES = ('intact', 'damaged')
UNKNOWN_STATUS = 'unknown'


def synchronize_missing_statuses(state):
    """Keep legacy unknown statuses editable as intact/damaged."""
    for box_id, region_uid in state['region_uid_by_box_id'].items():
        current = state['regions'][region_uid]['status']
        status = 'intact' if current == UNKNOWN_STATUS else current
        state['regions'][region_uid]['status'] = status
        state['bounding_boxes'][box_id]['status'] = status


def update_status(state, region_uid, status):
    if region_uid not in state['regions']:
        raise ValueError('Invalid region or status.')
    box_id = state['box_id_by_region'].get(region_uid)
    if status not in EDITABLE_STATUSES:
        raise ValueError('Every box must be intact or damaged.')
    state['regions'][region_uid]['status'] = status
    if box_id:
        state['bounding_boxes'][box_id]['status'] = status
    state['saved'] = False


def replace_statuses(state, statuses):
    """Atomically replace the status of every editable region."""
    if not isinstance(statuses, dict) or set(statuses) != set(state['regions']):
        raise ValueError('Statuses must contain every region exactly once.')
    for region_uid, status in statuses.items():
        box_id = state['box_id_by_region'].get(region_uid)
        if status not in EDITABLE_STATUSES:
            raise ValueError('Every box must be intact or damaged.')
    for region_uid, status in statuses.items():
        state['regions'][region_uid]['status'] = status
        box_id = state['box_id_by_region'].get(region_uid)
        if box_id in state['bounding_boxes']:
            state['bounding_boxes'][box_id]['status'] = status
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
            state['bounding_boxes'][box_id]['status'] = state['regions'][region_uid]['status']
    state['workflow']['status_valid'] = True
