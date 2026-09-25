from .state import require


def update_status(state, region_uid, status):
    if status not in ('intact', 'damaged') or region_uid not in state['regions']:
        raise ValueError('Invalid region or status.')
    state['regions'][region_uid]['status'] = status
    box_id = state['box_id_by_region'].get(region_uid)
    if box_id:
        state['bounding_boxes'][box_id]['status'] = status
    state['saved'] = False


def confirm_status(state):
    require(state, 'bbox_valid')
    if any(b['status'] not in ('intact', 'damaged') for b in state['regions'].values()):
        raise ValueError('Every region must have a status.')
    state['workflow']['status_valid'] = True
