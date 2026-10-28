"""Stable editor identities and validation, projected into the existing export."""
from collections import Counter
from copy import deepcopy
from uuid import uuid4

from .bbox import validate_coordinates
from .text_alignment import characters
from .status import STATUS_FIELDS, apply_character_flags, normalize_flags, validate_flags


def active_entries(model):
    return [entry for entry in model['entries'] if not entry['excluded']]


def ensure_workspace(state, reset_boxes=False):
    model = state.get('workspace')
    source = characters(state['annotation_text'])
    if model and [e['value'] for e in model['entries'] if e['type'] == 'original'] == source:
        if reset_boxes:
            model = deepcopy(model)
            model.update(boxes=deepcopy(state['regions']), confirmed={}, undo=[], redo=[])
            state['workspace'] = model
        else:
            return model
    else:
        pending = state.pop('pending_workspace', None)
        if pending and [e['value'] for e in pending.get('entries', []) if e.get('type') == 'original'] == source:
            state['workspace'] = deepcopy(pending)
            sync_workspace(state, pending)
            return state['workspace']
        model = dict(entries=[dict(char_id=uuid4().hex, value=value,
                                  source_index=index, type='original', excluded=False)
                              for index, value in enumerate(source, 1)],
                     boxes=deepcopy(state['regions']), confirmed={},
                     selected_box=None, selected_char=None, selected_boxes=[],
                     preferences=dict(reference_open=True, reference_width=280,
                                      reference_scroll=0, zoom=100, visibility='dim'),
                     undo=[], redo=[])
        state['workspace'] = model
    # Use the established sorter only to initialize order, never to overwrite edits.
    from .state import calculate_spatial_order
    ordered = calculate_spatial_order({uid: box['bbox'] for uid, box in model['boxes'].items()}, state['image_size'])
    for index, uid in enumerate(ordered, 1):
        box = model['boxes'][uid]
        box.setdefault('order', index)
        if box['order'] is None:
            box['order'] = index
        box.setdefault('damage_level', None)
        for flag in ('unknown', 'unavailable_font', 'expert_prediction', 'suspicious'):
            box.setdefault(flag, False)
    model['selected_box'] = next(iter(model['boxes']), None)
    state['regions'] = deepcopy(model['boxes'])
    return model


def sync_workspace(state, raw):
    """Accept unfinished states, but reject malformed identities/source/geometry."""
    if not isinstance(raw, dict) or not isinstance(raw.get('entries'), list) or not isinstance(raw.get('boxes'), dict):
        raise ValueError('Invalid workspace snapshot.')
    entries = raw['entries']
    if any(not isinstance(entry,dict) for entry in entries):
        raise ValueError('Invalid content entry.')
    ids = [entry.get('char_id') for entry in entries]
    if any(not isinstance(uid, str) or not uid for uid in ids) or len(ids) != len(set(ids)):
        raise ValueError('Content IDs must be unique non-empty strings.')
    originals = []
    for entry in entries:
        if type(entry.get('excluded')) is not bool:
            raise ValueError('Excluded must be a boolean.')
        if entry.get('type') == 'original':
            originals.append(entry)
        elif entry.get('type') != 'missing' or entry.get('value') != 'MISS' or entry.get('source_index') is not None:
            raise ValueError('Inserted entries must contain literal MISS.')
    source = characters(state['annotation_text'])
    if ([e.get('value') for e in originals] != source
            or [e.get('source_index') for e in originals] != list(range(1, len(source)+1))):
        raise ValueError('Original reference content cannot be changed in the workspace.')
    old = state.get('workspace')
    if old:
        old_ids = {e['source_index']: e['char_id'] for e in old['entries'] if e['type'] == 'original'}
        if any(old_ids.get(e['source_index']) != e['char_id'] for e in originals):
            raise ValueError('Original character IDs cannot change.')
    for uid, box in raw['boxes'].items():
        if not isinstance(uid, str) or not uid or not isinstance(box, dict):
            raise ValueError('Invalid box identity.')
        validate_coordinates(box.get('bbox'), state['image_size'])
    confirmed = raw.get('confirmed', {})
    if not isinstance(confirmed, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in confirmed.items()):
        raise ValueError('Invalid confirmed relationships.')
    model = deepcopy(raw)
    prefs=model.get('preferences', {})
    if (not isinstance(prefs,dict) or type(prefs.get('reference_open',True)) is not bool
            or type(prefs.get('reference_width',280)) not in (int,float)
            or not 130 <= prefs.get('reference_width',280) <= 600
            or type(prefs.get('zoom',100)) not in (int,float)
            or not 25 <= prefs.get('zoom',100) <= 500
            or prefs.get('visibility','dim') not in ('all','dim','selected')):
        raise ValueError('Invalid workspace display preferences.')
    model.setdefault('preferences',{})
    if type(model.get('version',0)) is not int or model.get('version',0)<0:
        raise ValueError('Invalid workspace revision.')
    for key in ('undo', 'redo'):
        if not isinstance(model.get(key, []), list):
            raise ValueError('Invalid workspace history.')
        model[key] = model.get(key, [])[-50:]
    state['workspace'] = model
    state['regions'] = deepcopy(model['boxes'])
    state['selected_region_uid'] = model.get('selected_box')
    state['saved'] = False
    state.pop('workspace_issues', None)
    return model


def spatial_insert(state, uid):
    """Insert a new region near its spatial successor without reordering old boxes."""
    from .state import calculate_spatial_order
    model = state['workspace']; boxes = model['boxes']
    spatial = calculate_spatial_order({key:b['bbox'] for key,b in boxes.items()}, state['image_size'])
    current = sorted((key for key in boxes if key != uid),
                     key=lambda key: boxes[key].get('order') or len(boxes)+1)
    successors = spatial[spatial.index(uid)+1:]
    successor = next((key for key in successors if key in current), None)
    current.insert(current.index(successor) if successor else len(current), uid)
    for index,key in enumerate(current,1): boxes[key]['order'] = index
    entries=active_entries(model)
    index=boxes[uid]['order']-1
    model['selected_char']=entries[index]['char_id'] if index<len(entries) else None
    state['regions'] = deepcopy(boxes)


def workspace_issues(state):
    model = state['workspace']
    entries = {e['char_id']: e for e in model['entries']}
    active = active_entries(model)
    indices = {e['char_id']: i for i,e in enumerate(active, 1)}
    boxes = model['boxes']; confirmed = model['confirmed']; issues = []

    def add(reason, uid=None, char_id=None):
        box = boxes.get(uid, {})
        issues.append(dict(reason=reason, box_id=uid, char_id=char_id,
                           reading_order=box.get('order'), bbox=box.get('bbox')))
    if not boxes:
        add('Draw at least one bounding box.')
    orders = Counter(box.get('order') for box in boxes.values()
                     if type(box.get('order')) is int)
    missing = sorted(set(range(1, len(boxes)+1)) - set(orders))
    if missing:
        add('Missing reading orders: ' + ', '.join(map(str, missing)))
    used = Counter(confirmed.values())
    for uid, box in boxes.items():
        order = box.get('order')
        if type(order) is not int or not 1 <= order <= len(boxes):
            add('Reading order must be an integer from 1 to the number of boxes.', uid)
        elif orders[order] > 1:
            add('Duplicate reading order.', uid)
        if box.get('status') not in ('intact', 'damaged'):
            add('Assign status: intact or damaged.', uid)
        elif box['status'] == 'damaged' and (type(box.get('damage_level')) is not int or box['damage_level'] not in (1,2,3)):
            add('Select damage level 1, 2 or 3.', uid)
        elif box['status'] == 'intact' and box.get('damage_level') is not None:
            add('Intact boxes cannot have a damage level.', uid)
        char_id = confirmed.get(uid)
        if not char_id:
            add('Confirm the alignment.', uid)
            continue
        entry = entries.get(char_id)
        if not entry:
            add('Confirmed character does not exist.', uid, char_id)
            continue
        if entry['excluded']:
            add('Confirmed character is excluded. Include it or remove the confirmation.', uid, char_id)
        elif indices[char_id] != order:
            add('Confirmed alignment conflicts with the effective sequence.', uid, char_id)
        if used[char_id] > 1:
            add('Character is confirmed with more than one box.', uid, char_id)
        try:
            validate_flags(box)
            expected = deepcopy(box)
            apply_character_flags(expected, entry['value'])
            normalize_flags(expected, entry['value'] == 'MISS')
            if any(expected.get(key) != box.get(key) for key in STATUS_FIELDS):
                add('Apply the mandatory character rules before confirming.', uid, char_id)
        except (ValueError, KeyError, TypeError) as exc:
            add(str(exc), uid, char_id)
    for uid, char_id in confirmed.items():
        if uid not in boxes:
            add('Confirmed box does not exist.', uid, char_id)
    for entry in active:
        if not used[entry['char_id']]:
            add('Content entry has no confirmed box.', char_id=entry['char_id'])
    return issues


def materialize_workspace(state):
    issues = workspace_issues(state)
    if issues:
        raise ValueError('Resolve workspace issues before continuing.')
    model = state['workspace']; active = active_entries(model)
    ordered = sorted(model['boxes'], key=lambda uid: model['boxes'][uid]['order'])
    state['regions'] = deepcopy(model['boxes'])
    state['box_id_by_region'] = {uid: str(i) for i,uid in enumerate(ordered,1)}
    state['region_uid_by_box_id'] = {str(i):uid for i,uid in enumerate(ordered,1)}
    state['bounding_boxes'] = {str(i):deepcopy(model['boxes'][uid]) for i,uid in enumerate(ordered,1)}
    state['annotations'] = {str(i):entry['value'] for i,entry in enumerate(active,1)}
    state['reading_order'] = list(range(1,len(ordered)+1))
    excluded = [e['value'] for e in model['entries'] if e['excluded'] and e['type'] == 'original']
    state['text_sequence'] = [e['value'] for e in active] + excluded
    state['text_token_ids'] = [e['char_id'] for e in active]
    types = []
    if any(e['type'] == 'missing' for e in active): types.append('missing_text')
    if excluded: types.append('extra_text')
    state['source_mismatch'] = (dict(issue_type=types[0] if len(types)==1 else 'mixed',
        source_text=state['annotation_text'], source_character_count=len(characters(state['annotation_text'])),
        bounding_box_count=len(ordered), excluded_characters=excluded, note='') if types else None)
    state['workflow'].update(content_verified=True, bbox_valid=True, alignment_valid=True,
                             status_valid=True, reading_order_valid=True)


def issues_text(image, issues):
    lines = [f'Annotation issues — {image}', f'Total issues: {len(issues)}', '']
    for index, issue in enumerate(issues,1):
        lines.append(f"{index}. Box: {issue['box_id'] or '—'} | Reading order: {issue['reading_order']} | "
                     f"Coordinates: {issue['bbox']} | Character ID: {issue['char_id'] or '—'}\n   {issue['reason']}")
    return '\n'.join(lines)
