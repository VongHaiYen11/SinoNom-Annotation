"""Transactional application actions. UI receives only accepted state snapshots."""
import base64
import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from PIL import Image
from .state import (new_state, set_verified_content, refresh_bbox_validation,
                    initialize_alignment, require, invalidate)
from .text_extraction import (extract_source_content, annotation_text, edit_content_field,
                              save_source_content, content_document, save_content_document)
from .text_alignment import count_annotation_characters
from .bbox import add_bbox, update_bbox, delete_bbox
from .status import update_status, confirm_status
from .reading_order import update_reading_order, validate_reading_order
from .io import load_annotation, validate_document, read_json, atomic_write, save_annotation, final_document
from .detection_adapter import detect
from crop.crop import (save_crop_coordinates, crop_bbox, default_crop,
                       validate_crop_coordinates)

log = logging.getLogger(__name__)


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

    def open_image(self, path):
        state = new_state()
        path = Path(path).resolve()
        with Image.open(path) as im:
            size = list(im.size)
            import io
            stream = io.BytesIO()
            im.convert('RGB').save(stream, format='JPEG')
        located = extract_source_content(path.name, self.options.source_json)
        state.update(image=path.name, image_path=str(path), image_size=size,
                     image_url='data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode(),
                     source_content=deepcopy(located['record']), source_baseline=deepcopy(located['record']),
                     draft_content=deepcopy(located['record']), code=located['code'], current_step=2)
        saved = self.output / (path.stem + '.json')
        saved_crop = None
        if saved.exists():
            doc = load_annotation(saved, path.name, size)
            saved_crop = doc.get('crop')
            _load_regions(state, doc)
            state['detection_loaded'] = True
            state['loaded_document'] = {k: deepcopy(doc[k]) for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')}
            state['loaded_region_uid_by_box_id'] = deepcopy(state['region_uid_by_box_id'])
            meta = self.output / '.state' / (path.stem + '.json')
            if meta.exists():
                sidecar = read_json(meta)
                if sidecar.get('document_hash') == fingerprint(json.dumps(doc, sort_keys=True, ensure_ascii=False)):
                    state['loaded_meta'] = sidecar
        state['crop'] = default_crop(size)
        crop_path = self.output / 'crops' / (path.stem + '.json')
        if saved_crop is not None:
            state['crop'] = crop_bbox(saved_crop, size)
            state['crop_saved'] = True
        elif crop_path.exists():
            crop = read_json(crop_path)
            if crop['image'] != path.name:
                raise ValueError('Crop does not belong to this image.')
            state['crop'] = crop_bbox(crop['crop'], size)
            state['crop_saved'] = True
        log.info('Loaded image %s; extracted source ky_hieu=%s', path.name, state['code'])
        return state

    def apply(self, original, action, payload=None):
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
            save_content_document(content_doc, self.output)
            loaded_mapping = deepcopy(s.get('loaded_region_uid_by_box_id', {}))
            set_verified_content(s, s['draft_content'], text)
            s['source_baseline'] = deepcopy(s['verified_content'])
            # Exact restore is allowed only with matching source AND document fingerprints.
            meta = s.pop('loaded_meta', None)
            if meta and meta.get('text_hash') == fingerprint(text) and 'loaded_document' in s:
                document = deepcopy(s['loaded_document'])
                s['bounding_boxes'] = document['bounding_boxes']
                s['reading_order'] = document['reading_order']
                s['annotations'] = document['annotations']
                s['region_uid_by_box_id'] = loaded_mapping
                s['box_id_by_region'] = {uid: box_id for box_id, uid in loaded_mapping.items()}
                s['workflow'].update(bbox_valid=True, alignment_valid=True)
            s.pop('loaded_document', None)
            s.pop('loaded_region_uid_by_box_id', None)
            refresh_bbox_validation(s)
        elif action in ('add', 'update', 'delete', 'detect'):
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
                s['detection_loaded'] = True
                invalidate(s, clear=True)
            elif action == 'add':
                s['selected_region_uid'] = add_bbox(s, payload['bbox'])
            elif action == 'update':
                update_bbox(s, payload.get('uid') or payload.get('id') or s['selected_region_uid'], payload['bbox'])
            else:
                delete_bbox(s, payload.get('uid') or payload.get('id') or s['selected_region_uid'])
            refresh_bbox_validation(s)
        elif action == 'select':
            if step in (3, 4):
                uid = payload.get('uid') or payload.get('id')
                if uid not in s['regions']:
                    raise ValueError('Region does not exist.')
                s['selected_region_uid'] = uid
            else:
                key = str(payload['id'])
                if key not in s['bounding_boxes']:
                    raise ValueError('Box does not exist.')
                s['selected_box_id'] = key
                s['selected_region_uid'] = s['region_uid_by_box_id'].get(key)
        elif action == 'status':
            if step != 4:
                raise ValueError('Edit status in Step 4.')
            update_status(s, payload.get('uid') or payload.get('id') or s['selected_region_uid'], payload['status'])
        elif action == 'reorder':
            if step != 5:
                raise ValueError('Edit reading order in Step 5.')
            update_reading_order(s, payload['order'])
        elif action == 'next':
            if step == 1:
                s['current_step'] = 2
            elif step == 2:
                require(s, 'content_verified')
                s['current_step'] = 3
            elif step == 3:
                refresh_bbox_validation(s)
                require(s, 'bbox_valid')
                s['current_step'] = 4
            elif step == 4:
                confirm_status(s)
                if not s['workflow']['alignment_valid']:
                    initialize_alignment(s)
                s['current_step'] = 5
            elif step == 5:
                require(s, 'status_valid')
                require(s, 'alignment_valid')
                if not validate_reading_order(s):
                    raise ValueError('Invalid reading order.')
                s['workflow']['reading_order_valid'] = True
                final_document(s)
                s['current_step'] = 6
            elif step == 6:
                # Crop is independent. Review still requires a valid annotation.
                final_document(s)
                s['current_step'] = 7
        elif action == 'save':
            if step != 7:
                raise ValueError('Save the image in Step 7.')
            path = save_annotation(s, self.output)
            atomic_write(self.output / '.state' / path.name,
                         dict(text_hash=fingerprint(s['annotation_text']),
                              document_hash=fingerprint(json.dumps(final_document(s), sort_keys=True, ensure_ascii=False))))
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
            save_crop_coordinates(s['image'], s['crop'], s['image_size'], self.output / 'crops')
            s['crop_saved'] = True
        else:
            raise ValueError('Invalid action: ' + action)
        s['revision'] += 1
        return s
