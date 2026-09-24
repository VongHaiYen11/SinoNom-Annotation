"""Transactional application actions. UI receives only accepted state snapshots."""
import base64
import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path
from PIL import Image
from .state import new_state, set_verified_content, refresh_alignment, require, invalidate
from .text_extraction import extract_source_content, annotation_text, edit_field, save_source_content
from .text_alignment import count_annotation_characters
from .bbox import add_bbox, update_bbox, delete_bbox
from .status import update_status, confirm_status
from .reading_order import update_reading_order, validate_reading_order
from .io import load_annotation, validate_document, read_json, atomic_write, save_annotation, final_document
from .detection_adapter import detect
from crop.crop import save_crop_coordinates

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
        if saved.exists():
            doc = load_annotation(saved, path.name, size)
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
        if crop_path.exists():
            crop = read_json(crop_path)
            if crop['image'] != path.name:
                raise ValueError('Crop không thuộc ảnh này.')
            from .bbox import validate_coordinates
            state['crop'] = validate_coordinates(crop['crop']['top_left'] + crop['crop']['bottom_right'], size)
        log.info('Loaded image %s; extracted source ky_hieu=%s', path.name, state['code'])
        return state

    def apply(self, original, action, payload=None):
        s = deepcopy(original)
        payload = payload or {}
        if not s.get('image'):
            raise ValueError('Hãy chọn ảnh trước.')
        if 'revision' in payload and (payload['revision'] != s['revision'] or payload.get('image') != s['image']):
            raise ValueError('Thao tác đã cũ. Giao diện được đồng bộ lại; vui lòng thử lại.')
        step = s['current_step']
        if action == 'back':
            s['current_step'] = max(1, step - 1)
        elif action == 'field':
            if step != 2:
                raise ValueError('Chỉ chỉnh content tại Step 2.')
            s['draft_content'] = edit_field(s['draft_content'], payload['path'], payload['value'])
            s['workflow']['content_verified'] = False
            s['saved'] = False
        elif action in ('undo', 'original'):
            s['draft_content'] = deepcopy(s['source_baseline'] if action == 'undo' else s['source_content'])
            s['workflow']['content_verified'] = False
        elif action == 'save_content':
            text = annotation_text(s['draft_content'], s['code'])
            if not count_annotation_characters(text):
                raise ValueError('Annotation text rỗng sau khi bỏ dấu câu/whitespace.')
            save_source_content(self.options.source_json, s['image'], s['source_baseline'], s['draft_content'])
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
                raise ValueError('Chỉ chỉnh bbox tại Step 3.')
            if action == 'detect':
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
                raise ValueError('Box không tồn tại.')
            s['selected_box_id'] = key
        elif action == 'status':
            if step != 5:
                raise ValueError('Chỉnh status tại Step 5.')
            update_status(s, payload['id'], payload['status'])
        elif action == 'reorder':
            if step != 6:
                raise ValueError('Đổi thứ tự tại Step 6.')
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
                s['current_step'] = 4
            elif step == 4:
                require(s, 'alignment_valid')
                s['current_step'] = 5
            elif step == 5:
                confirm_status(s)
                s['current_step'] = 6
            elif step == 6:
                require(s, 'status_valid')
                require(s, 'alignment_valid')
                if not validate_reading_order(s):
                    raise ValueError('Reading order không hợp lệ.')
                s['workflow']['reading_order_valid'] = True
                final_document(s)
                s['current_step'] = 7
            elif step == 7:
                if not s['saved']:
                    raise ValueError('Hãy Save annotation trước khi chuyển sang Crop.')
                s['current_step'] = 8
        elif action == 'save':
            if step != 7:
                raise ValueError('Save tại Step 7.')
            path = save_annotation(s, self.output)
            atomic_write(self.output / '.state' / path.name,
                         dict(text_hash=fingerprint(s['annotation_text']),
                              document_hash=fingerprint(json.dumps(final_document(s), sort_keys=True, ensure_ascii=False)),
                              temporary_order=s['temporary_order'], next_box_id=s['next_box_id']))
            s['saved'] = True
            log.info('Saved annotation %s', path)
        elif action == 'crop':
            if step != 8:
                raise ValueError('Crop chỉ tại bước cuối.')
            from .bbox import validate_coordinates
            s['crop'] = validate_coordinates(payload['bbox'], s['image_size'])
        elif action == 'save_crop':
            if step != 8:
                raise ValueError('Crop chỉ tại bước cuối.')
            save_crop_coordinates(s['image'], s['crop'], s['image_size'], self.output / 'crops')
        else:
            raise ValueError('Action không hợp lệ: ' + action)
        s['revision'] += 1
        return s
