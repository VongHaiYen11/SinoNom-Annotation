from .state import source_mismatch_confirmed
from .text_alignment import MISSING_ANNOTATION


EDITABLE_STATUSES = ('intact', 'damaged')
FLAGS = ('unknown', 'unavailable_font', 'expert_prediction')


def validate_flags(box):
    for flag in FLAGS:
        if flag not in box or not isinstance(box[flag], bool):
            raise ValueError(f'{flag} must be a boolean.')
    if box['unknown'] and (box['status'] != 'damaged' or box['unavailable_font'] or box['expert_prediction']):
        raise ValueError('Unknown requires damaged and cannot coexist with other flags.')


def normalize_flags(box, missing=False):
    if missing:
        for flag in FLAGS:
            box[flag] = False
    elif box['status'] != 'damaged':
        box['unknown'] = False
    validate_flags(box)


def synchronize_missing_statuses(state):
    """Synchronize all flags and clear character flags on MISS boxes."""
    for box_id, region_uid in state['region_uid_by_box_id'].items():
        box = state['regions'][region_uid]
        normalize_flags(box, state.get('annotations', {}).get(str(box_id)) == MISSING_ANNOTATION)
        state['bounding_boxes'][box_id].update({key: box[key] for key in ('status', *FLAGS)})


def update_status(state, region_uid, status, unknown=None, unavailable_font=None, expert_prediction=None, *, default_expert_damage=True):
    if region_uid not in state['regions'] or status not in EDITABLE_STATUSES:
        raise ValueError('Invalid region or status.')
    old = state['regions'][region_uid]
    unknown = old['unknown'] if unknown is None else unknown
    unavailable_font = old['unavailable_font'] if unavailable_font is None else unavailable_font
    expert_prediction = old['expert_prediction'] if expert_prediction is None else expert_prediction
    for value in (unknown, unavailable_font, expert_prediction):
        if not isinstance(value, bool):
            raise ValueError('Flags must be boolean.')
    if unknown and not old['unknown']:
        unavailable_font = expert_prediction = False
    elif (unavailable_font and not old['unavailable_font']) or (expert_prediction and not old['expert_prediction']):
        unknown = False
    if default_expert_damage and expert_prediction and not old['expert_prediction']:
        status = 'damaged'
    box = dict(old, status=status, unknown=unknown if status == 'damaged' else False,
               unavailable_font=unavailable_font, expert_prediction=expert_prediction)
    box_id = state['box_id_by_region'].get(region_uid)
    normalize_flags(box, state.get('annotations', {}).get(str(box_id)) == MISSING_ANNOTATION)
    state['regions'][region_uid] = box
    if box_id in state['bounding_boxes']:
        state['bounding_boxes'][box_id].update({key: box[key] for key in ('status', *FLAGS)})
    state['saved'] = False


def replace_statuses(state, statuses, unknowns=None, unavailable_fonts=None, expert_predictions=None):
    """Validate the complete update before changing any region."""
    if not isinstance(statuses, dict) or set(statuses) != set(state['regions']):
        raise ValueError('Statuses must contain every region exactly once.')
    maps = (unknowns, unavailable_fonts, expert_predictions)
    for values in maps:
        if values is not None and (not isinstance(values, dict) or
                any(not isinstance(value, bool) for value in values.values())):
            raise ValueError('Flags must be mappings of region IDs to booleans.')
    from copy import deepcopy
    candidate = deepcopy(state)
    for uid, status in statuses.items():
        values = [mapping.get(uid, candidate['regions'][uid][flag]) if mapping is not None
                  else candidate['regions'][uid][flag] for flag, mapping in zip(FLAGS, maps)]
        update_status(candidate, uid, status, *values, default_expert_damage=False)
    state.update(candidate)


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
            for flag in FLAGS:
                state['bounding_boxes'][box_id][flag] = state['regions'][region_uid][flag]
    state['workflow']['status_valid'] = True
