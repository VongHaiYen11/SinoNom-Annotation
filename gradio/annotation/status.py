from .state import require


def update_status(state, box_id, status):
    if status not in ('intact', 'damaged') or str(box_id) not in state['bounding_boxes']:
        raise ValueError('Invalid box or status.')
    state['bounding_boxes'][str(box_id)]['status'] = status
    state['saved'] = False


def confirm_status(state):
    require(state, 'alignment_valid')
    if any(b['status'] not in ('intact', 'damaged') for b in state['bounding_boxes'].values()):
        raise ValueError('Every box must have a status.')
    state['workflow']['status_valid'] = True
