"""Transactional application actions. UI receives only accepted state snapshots."""
import base64
import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path
from PIL import Image
from .state import new_state, set_verified_content, refresh_alignment, require, invalidate
from .text_extraction import (extract_source_content, annotation_text, edit_content_field,
                              save_source_content, content_document, save_content_document)
from .text_alignment import count_annotation_characters
from .bbox import add_bbox, update_bbox, delete_bbox
from .status import update_status, confirm_status
from .reading_order import update_reading_order, validate_reading_order
from .io import load_annotation, validate_document, read_json, atomic_write, save_annotation, final_document
from .detection_adapter import detect
from crop.crop import save_crop_coordinates, crop_bbox

log = logging.getLogger(__name__)


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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
            state.update({k: deepcopy(doc[k]) for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')})
            state['temporary_order'] = list(doc['reading_order'])
            state['next_box_id'] = max(map(int, doc['bounding_boxes']), default=0) + 1
            state['detection_loaded'] = True
            state['loaded_document'] = {k: deepcopy(doc[k]) for k in ('image', 'bounding_boxes', 'reading_order', 'annotations')}
            meta = self.output / '.state' / (path.stem + '.json')
            if meta.exists():
                sidecar = read_json(meta)
                if sidecar.get('document_hash') == fingerprint(json.dumps(doc, sort_keys=True, ensure_ascii=False)):
                    order = sidecar.get('temporary_order', [])
                    if validate_reading_order(dict(state, reading_order=order)):
                        state['temporary_order'] = order
                        state['next_box_id'] = max(state['next_box_id'], int(sidecar['next_box_id']))
                        state['loaded_meta'] = sidecar
        state['crop'] = [0, 0, *size]
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
            set_verified_content(s, s['draft_content'], text)
            s['source_baseline'] = deepcopy(s['verified_content'])
            # Exact restore is allowed only with matching source AND document fingerprints.
            meta = s.pop('loaded_meta', None)
            if meta and meta.get('text_hash') == fingerprint(text) and 'loaded_document' in s:
                s.update(deepcopy(s['loaded_document']))
                s['workflow'].update(bbox_valid=True, alignment_valid=True)
            s.pop('loaded_document', None)
            refresh_alignment(s)
        elif action in ('add', 'update', 'delete', 'detect'):
            require(s, 'content_verified')
            if step != 3:
                raise ValueError('Edit bounding boxes in Step 3.')
            if action == 'detect':
                if getattr(self.options, 'skip_detection', False):
                    raise ValueError('Detection is disabled (--skip-detection). Draw boxes manually.')
                # Re-running uses fresh IDs beyond the previous high-water mark.
                doc = detect(s['image_path'], self.options)
                validate_document(doc, s['image'], s['image_size'])
                old_next = s['next_box_id']
                ids = {k: str(old_next + i) for i, k in enumerate(doc['bounding_boxes'])}
                s['bounding_boxes'] = {ids[k]: v for k, v in doc['bounding_boxes'].items()}
                s['temporary_order'] = [int(ids[str(i)]) for i in doc['reading_order']]
                s['next_box_id'] += len(ids)
                s['detection_loaded'] = True
                invalidate(s, clear=True)
            elif action == 'add':
                s['selected_box_id'] = add_bbox(s, payload['bbox'])
            elif action == 'update':
                update_bbox(s, payload['id'], payload['bbox'])
            else:
                delete_bbox(s, payload['id'])
            refresh_alignment(s)
        elif action == 'select':
            key = str(payload['id'])
            if key not in s['bounding_boxes']:
                raise ValueError('Box does not exist.')
            s['selected_box_id'] = key
        elif action == 'status':
            if step != 4:
                raise ValueError('Edit status in Step 4.')
            update_status(s, payload['id'], payload['status'])
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
                refresh_alignment(s)
                require(s, 'bbox_valid')
                require(s, 'alignment_valid')
                s['current_step'] = 4
            elif step == 4:
                require(s, 'alignment_valid')
                confirm_status(s)
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
                              document_hash=fingerprint(json.dumps(final_document(s), sort_keys=True, ensure_ascii=False)),
                              temporary_order=s['temporary_order'], next_box_id=s['next_box_id']))
            s['saved'] = True
            s['crop_saved'] = True
            log.info('Saved annotation %s', path)
        elif action == 'crop':
            if step != 6:
                raise ValueError('Edit crop in Step 6.')
            from .bbox import validate_coordinates
            s['crop'] = validate_coordinates(payload['bbox'], s['image_size'])
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
