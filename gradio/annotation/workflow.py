"""Transactional application actions. UI receives only accepted state snapshots."""
import hashlib
import json
import logging
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote
from PIL import Image
from .state import (new_state, set_verified_content, refresh_bbox_validation,
                    initialize_alignment, require, invalidate,
                    source_mismatch_confirmed)
from .text_extraction import (annotation_text, edit_content_field,
                              save_source_content, content_document, save_content_document)
from .text_alignment import count_annotation_characters
from .bbox import add_bbox, update_bbox, update_bboxes, delete_bbox
from .status import (update_status, replace_statuses, confirm_status,
                     synchronize_missing_statuses)
from .reading_order import (update_reading_order, update_text_sequence,
                            validate_reading_order)
from .io import (atomic_write, final_document,
                 final_source_mismatch_document, load_annotation,
                 load_source_mismatch, read_json, save_annotation,
                 save_source_mismatch, validate_document,
                 validate_source_mismatch_type)
from .detection_adapter import detect
from crop.crop import (save_crop_coordinates, crop_bbox, default_crop,
                       validate_crop_coordinates, validate_resized_image_size)

log = logging.getLogger(__name__)


def _source_mismatch_from_document(document):
    return {key: deepcopy(document[key]) for key in (
        'source_text', 'source_character_count', 'bounding_box_count',
        'issue_type', 'note',
    )}


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _load_regions(state, document):
    """Hydrate internal regions while preserving a saved public ID mapping."""
    state['regions'] = {}
    state['box_id_by_region'] = {}
    state['region_uid_by_box_id'] = {}
    for box_id, box in document['bounding_boxes'].items():
        uid = uuid4().hex
        state['regions'][uid] = deepcopy(box)
        state['box_id_by_region'][uid] = box_id
        state['region_uid_by_box_id'][box_id] = uid
    state['bounding_boxes'] = deepcopy(document['bounding_boxes'])
    state['annotations'] = deepcopy(document.get('annotations', {}))
    state['reading_order'] = list(document['reading_order'])


class Workflow:
    def __init__(self, options):
        self.options = options
        self.output = Path(options.output_dir)
        self._preview_cache = tempfile.TemporaryDirectory(prefix='vietnamica-preview-')
        self.preview_dir = Path(self._preview_cache.name)
        self._source_records = None
        self._source_mtime_ns = None
        self._source_locations = None

    def _cached_source_records(self):
        """Avoid reparsing the complete extraction JSON for every opened image."""
        source = Path(self.options.source_json)
        mtime_ns = source.stat().st_mtime_ns
        if self._source_records is None or mtime_ns != self._source_mtime_ns:
            self._source_records = read_json(source)
            self._source_mtime_ns = mtime_ns
            locations = {}
            for record_index, record in enumerate(self._source_records):
                for face_index, face in enumerate(record.get('noi_dung', [])):
                    locations.setdefault(str(face.get('ky_hieu')), []).append((record_index, face_index))
            self._source_locations = locations
        return self._source_records

    def _source_content_for(self, image_name):
        records = self._cached_source_records()
        code = Path(image_name).stem
        matches = self._source_locations.get(code, [])
        if len(matches) != 1:
            raise ValueError(f'Image code {code}: found {len(matches)} inscription faces; expected exactly one.')
        record_index, face_index = matches[0]
        record = deepcopy(records[record_index])
        # Keep the same schema validation as the public extraction adapter.
        annotation_text(record, code)
        return dict(record=record, record_index=record_index, face_index=face_index, code=code)

    def open_image(self, path):
        state = new_state()
        path = Path(path).resolve()
        with Image.open(path) as im:
            size = list(im.size)
            # Serve ordinary JPEGs without decoding/re-encoding or expanding
            # them into large PNG files. Normalize other formats/orientations
            # once, retaining the original pixel dimensions for box alignment.
            stat = path.stat()
            key = fingerprint(f'{path}:{stat.st_mtime_ns}:{stat.st_size}')
            preview_path = self.preview_dir / (key + '.jpg')
            if not preview_path.exists():
                if im.format == 'JPEG' and im.mode in ('RGB', 'L') and im.getexif().get(274, 1) == 1:
                    shutil.copyfile(path, preview_path)
                else:
                    im.convert('RGB').save(preview_path, format='JPEG', quality=95, subsampling=0)
        located = self._source_content_for(path.name)
        state.update(image=path.name, image_path=str(path), image_size=size,
                     resized_image_size=list(size),
                     image_url='gradio_api/file=' + quote(str(preview_path), safe='/'),
                     source_content=deepcopy(located['record']), source_baseline=deepcopy(located['record']),
                     draft_content=deepcopy(located['record']), code=located['code'], current_step=2)
        saved = self.output / (path.stem + '.json')
        mismatch_saved = self.output / 'source_mismatches' / (path.stem + '.json')
        if saved.exists() and mismatch_saved.exists():
            raise ValueError('Both a normal annotation and source mismatch exist for this image.')
        saved_crop = None
        persisted = saved if saved.exists() else mismatch_saved if mismatch_saved.exists() else None
        if persisted:
            is_mismatch = persisted == mismatch_saved
            doc = (load_source_mismatch(persisted, path.name, size) if is_mismatch
                   else load_annotation(persisted, path.name, size))
            saved_crop = doc.get('crop')
            if doc.get('image_resize'):
                state['resized_image_size'] = validate_resized_image_size(
                    doc['image_resize']['output_size'])
            _load_regions(state, doc)
            if is_mismatch:
                state['source_mismatch'] = _source_mismatch_from_document(doc)
            state['detection_loaded'] = True
            state['loaded_document'] = deepcopy(doc)
            state['loaded_region_uid_by_box_id'] = deepcopy(state['region_uid_by_box_id'])
            meta = (self.output / '.state' /
                    ('source_mismatches' if is_mismatch else '') / (path.stem + '.json'))
            if meta.exists():
                sidecar = read_json(meta)
                if sidecar.get('document_hash') == fingerprint(json.dumps(doc, sort_keys=True, ensure_ascii=False)):
                    state['loaded_meta'] = sidecar
        state['crop'] = default_crop(state['resized_image_size'])
        crop_path = self.output / 'crops' / (path.stem + '.json')
        if saved_crop is not None:
            state['crop'] = crop_bbox(saved_crop, state['resized_image_size'])
            state['crop_saved'] = True
        elif crop_path.exists():
            crop = read_json(crop_path)
            if crop['image'] != path.name:
                raise ValueError('Crop does not belong to this image.')
            if crop.get('image_resize'):
                state['resized_image_size'] = validate_resized_image_size(
                    crop['image_resize']['output_size'])
            state['crop'] = crop_bbox(crop['crop'], state['resized_image_size'])
            state['crop_saved'] = True
        log.info('Loaded image %s; extracted source ky_hieu=%s', path.name, state['code'])
        return state

    def apply(self, original, action, payload=None):
        # Selection changes only two scalar fields. Box editing changes the
        # region/workflow branches. Avoid copying the potentially large source
        # record for these high-frequency canvas actions.
        if action == 'select':
            s = original.copy()
        elif action in ('add', 'update', 'commit_boxes', 'delete', 'detect'):
            s = original.copy()
            s['regions'] = deepcopy(original['regions'])
            s['workflow'] = original['workflow'].copy()
        else:
            s = deepcopy(original)
        payload = payload or {}
        if not s.get('image'):
            raise ValueError('Select an image first.')
        if 'revision' in payload and (payload['revision'] != s['revision'] or payload.get('image') != s['image']):
            raise ValueError('This action is out of date. The interface has been refreshed; please try again.')
        step = s['current_step']
        if action == 'back':
            s['current_step'] = max(1, step - 1)
        elif action == 'field':
            if step != 2:
                raise ValueError('Edit content in Step 2.')
            s['draft_content'] = edit_content_field(s['draft_content'], s['code'], payload['path'], payload['value'])
            s['workflow']['content_verified'] = False
            s['saved'] = False
        elif action in ('undo', 'original'):
            s['draft_content'] = deepcopy(s['source_baseline'] if action == 'undo' else s['source_content'])
            s['workflow']['content_verified'] = False
        elif action == 'save_content':
            text = annotation_text(s['draft_content'], s['code'])
            if not count_annotation_characters(text):
                raise ValueError('Annotation text contains no characters after normalization.')
            content_doc = content_document(s['image'], s['code'], s['draft_content'])
            save_source_content(self.options.source_json, s['image'], s['source_baseline'], s['draft_content'])
            # The persisted source changed; refresh lazily on the next image open.
            self._source_records = None
            self._source_mtime_ns = None
            self._source_locations = None
            save_content_document(content_doc, self.output)
            loaded_mapping = deepcopy(s.get('loaded_region_uid_by_box_id', {}))
            text_changed = text != s['annotation_text']
            set_verified_content(s, s['draft_content'], text)
            if text_changed:
                s['source_mismatch'] = None
            s['source_baseline'] = deepcopy(s['verified_content'])
            # Exact restore is allowed only with matching source AND document fingerprints.
            meta = s.pop('loaded_meta', None)
            if meta and meta.get('text_hash') == fingerprint(text) and 'loaded_document' in s:
                document = deepcopy(s['loaded_document'])
                s['bounding_boxes'] = document['bounding_boxes']
                s['reading_order'] = document['reading_order']
                s['annotations'] = document.get('annotations', {})
                s['region_uid_by_box_id'] = loaded_mapping
                s['box_id_by_region'] = {uid: box_id for box_id, uid in loaded_mapping.items()}
                if 'issue_type' in document:
                    s['source_mismatch'] = _source_mismatch_from_document(document)
                s['workflow'].update(bbox_valid=True, alignment_valid=True)
                synchronize_missing_statuses(s)
            s.pop('loaded_document', None)
            s.pop('loaded_region_uid_by_box_id', None)
            refresh_bbox_validation(s)
            if s['workflow']['bbox_valid']:
                s['source_mismatch'] = None
        elif action in ('add', 'update', 'commit_boxes', 'delete', 'detect'):
            require(s, 'content_verified')
            if step != 3:
                raise ValueError('Edit bounding boxes in Step 3.')
            if action == 'detect':
                if getattr(self.options, 'skip_detection', False):
                    raise ValueError('Detection is disabled (--skip-detection). Draw boxes manually.')
                # Detection IDs are discarded; Gradio owns hidden region identity.
                doc = detect(s['image_path'], self.options)
                validate_document(doc, s['image'], s['image_size'])
                s['regions'] = {uuid4().hex: deepcopy(box) for box in doc['bounding_boxes'].values()}
                s['selected_region_uid'] = next(iter(s['regions']), None)
                s['selected_region_uids'] = [s['selected_region_uid']] if s['selected_region_uid'] else []
                s['detection_loaded'] = True
                invalidate(s, clear=True)
            elif action == 'add':
                if payload.get('boxes'):
                    update_bboxes(s,payload['boxes'],payload.get('active'),
                                  payload.get('selected'))
                s['selected_region_uid'] = add_bbox(s, payload['bbox'])
                s['selected_region_uids'] = [s['selected_region_uid']]
            elif action == 'update':
                update_bbox(s, payload.get('uid') or payload.get('id') or s['selected_region_uid'], payload['bbox'])
            elif action == 'commit_boxes':
                update_bboxes(s, payload.get('boxes'), payload.get('active'), payload.get('selected'))
            else:
                selected = payload.get('ids') or [payload.get('uid') or payload.get('id') or s['selected_region_uid']]
                selected = list(dict.fromkeys(selected))
                if not selected or any(uid not in s['regions'] for uid in selected):
                    raise ValueError('One or more selected regions do not exist.')
                for uid in selected:
                    delete_bbox(s, uid)
                s['selected_region_uids'] = [uid for uid in s.get('selected_region_uids', []) if uid in s['regions']]
                s['selected_region_uid'] = s['selected_region_uids'][-1] if s['selected_region_uids'] else next(iter(s['regions']), None)
            if action in ('add', 'delete', 'detect'):
                s['source_mismatch'] = None
            refresh_bbox_validation(s)
            if s['workflow']['bbox_valid']:
                s['source_mismatch'] = None
        elif action == 'confirm_source_mismatch':
            if step != 3:
                raise ValueError('Confirm a source mismatch in Step 3.')
            require(s, 'content_verified')
            refresh_bbox_validation(s)
            if s['workflow']['bbox_valid']:
                raise ValueError('Source mismatch can only be confirmed when the counts differ.')
            issue_type = payload.get('issue_type')
            note = payload.get('note', '')
            character_count = count_annotation_characters(s['annotation_text'])
            box_count = len(s['regions'])
            try:
                validate_source_mismatch_type(issue_type, character_count, box_count)
            except ValueError as exc:
                raise ValueError('Select a source mismatch type that matches the count difference.') from exc
            if not isinstance(note, str):
                raise ValueError('Source mismatch note must be text.')
            s['source_mismatch'] = {
                'source_text': s['annotation_text'],
                'source_character_count': character_count,
                'bounding_box_count': box_count,
                'issue_type': issue_type,
                'note': note.strip(),
            }
            invalidate(s, clear=True)
        elif action == 'clear_source_mismatch':
            if step != 3:
                raise ValueError('Clear a source mismatch in Step 3.')
            s['source_mismatch'] = None
            invalidate(s, clear=True)
        elif action == 'select':
            if step == 3:
                uid = payload.get('uid') or payload.get('id')
                if uid not in s['regions']:
                    raise ValueError('Region does not exist.')
                s['selected_region_uid'] = uid
                selected = list(s.get('selected_region_uids', []))
                if payload.get('toggle'):
                    was_selected = uid in selected
                    selected = [item for item in selected if item != uid] if was_selected else selected + [uid]
                    if not was_selected:
                        s['selected_region_uid'] = uid
                    elif s['selected_region_uid'] == uid:
                        s['selected_region_uid'] = selected[-1] if selected else None
                else:
                    selected = [uid]
                s['selected_region_uids'] = selected
            else:
                key = str(payload['id'])
                if key not in s['bounding_boxes']:
                    raise ValueError('Box does not exist.')
                s['selected_box_id'] = key
                s['selected_region_uid'] = s['region_uid_by_box_id'].get(key)
        elif action == 'status':
            if step != 5:
                raise ValueError('Edit status in Step 5.')
            box_id = str(payload.get('id') or s['selected_box_id'])
            update_status(s, s['region_uid_by_box_id'].get(box_id), payload['status'])
        elif action == 'statuses':
            if step != 5:
                raise ValueError('Edit statuses in Step 5.')
            replace_statuses(s, payload.get('statuses'))
        elif action == 'reorder':
            if step != 4:
                raise ValueError('Edit reading order in Step 4.')
            update_reading_order(s, payload['order'])
        elif action == 'reorder_text':
            if step != 4:
                raise ValueError('Edit reading order in Step 4.')
            update_text_sequence(s, payload['sequence'])
        elif action == 'next':
            if step == 1:
                s['current_step'] = 2
            elif step == 2:
                s = self.apply(s, 'save_content')
                s['current_step'] = 3
            elif step == 3:
                refresh_bbox_validation(s)
                if not (s['workflow']['bbox_valid'] or source_mismatch_confirmed(s)):
                    raise ValueError('Match the box and character counts or confirm a source mismatch.')
                if not s['workflow']['alignment_valid']:
                    initialize_alignment(s)
                s['current_step'] = 4
            elif step == 4:
                require(s, 'alignment_valid')
                if not validate_reading_order(s):
                    raise ValueError('Invalid reading order.')
                s['workflow']['reading_order_valid'] = True
                s['current_step'] = 5
            elif step == 5:
                require(s, 'alignment_valid')
                require(s, 'reading_order_valid')
                confirm_status(s)
                (final_source_mismatch_document(s) if source_mismatch_confirmed(s)
                 else final_document(s))
                s['current_step'] = 6
            elif step == 6:
                # Crop is independent. Review still requires a valid annotation.
                (final_source_mismatch_document(s) if source_mismatch_confirmed(s)
                 else final_document(s))
                s['current_step'] = 7
        elif action == 'save':
            if step != 7:
                raise ValueError('Save the image in Step 7.')
            mismatch = source_mismatch_confirmed(s)
            path = (save_source_mismatch(s, self.output) if mismatch
                    else save_annotation(s, self.output))
            document = (final_source_mismatch_document(s) if mismatch else final_document(s))
            meta_root = self.output / '.state' / ('source_mismatches' if mismatch else '')
            atomic_write(meta_root / path.name,
                         dict(text_hash=fingerprint(s['annotation_text']),
                              document_hash=fingerprint(json.dumps(document, sort_keys=True, ensure_ascii=False))))
            stale_meta = self.output / '.state' / ('' if mismatch else 'source_mismatches') / path.name
            stale_meta.unlink(missing_ok=True)
            s['saved'] = True
            s['crop_saved'] = True
            log.info('Saved annotation %s', path)
        elif action == 'crop':
            if step != 6:
                raise ValueError('Edit crop in Step 6.')
            s['crop'] = validate_crop_coordinates(payload['bbox'], s['image_size'])
            s['crop_saved'] = False
            s['saved'] = False
        elif action == 'save_crop':
            if step != 6:
                raise ValueError('Save crop in Step 6.')
            save_crop_coordinates(s['image'], s['crop'], s['resized_image_size'],
                                  self.output / 'crops', source_size=s['image_size'])
            s['crop_saved'] = True
        else:
            raise ValueError('Invalid action: ' + action)
        s['revision'] += 1
        return s
