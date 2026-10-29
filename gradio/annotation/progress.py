"""Portable, versioned work-in-progress backups. Never trust imported runtime state."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from PIL import Image

from .bbox import validate_coordinates
from .export import collect_annotations, collect_content_documents, collect_source_mismatches
from .io import (atomic_write, read_json, rollback_saved_files, validate_document,
                 validate_source_mismatch_document)
from .state import new_state, set_verified_content
from .text_extraction import (CONTENT_LOCK, annotation_text, content_document, content_fields,
                              edit_content_field, validate_content_document)
from .workspace import materialize_workspace, sync_workspace
from crop.crop import validate_crop_coordinates, validate_resized_image_size

FORMAT = 'vietnamica-progress'
VERSION = 1
MAX_BACKUP_BYTES = 128 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def schema(engine):
    return dict(content_titles=list(engine.content_titles),
                metadata_fields=[list(field) for field in engine.metadata_fields],
                annotation_title=engine.annotation_title)


def _record(engine, state, record):
    return content_document(state['image'], state['code'], record,
                            engine.content_titles, engine.metadata_fields)


def _restore_record(engine, state, document):
    validate_content_document(document, state['image'], engine.verification_titles)
    result = deepcopy(state['source_content'])
    for field in content_fields(result, state['code'], engine.content_titles, engine.metadata_fields):
        result = edit_content_field(result, state['code'], field['path'],
                                    document['content'][field['title']] or '',
                                    engine.content_titles, engine.metadata_fields)
    return result


def _workspace(state, model):
    """Validate structure and history, while allowing unfinished semantic conflicts."""
    if not isinstance(model, dict):
        raise ValueError('Bản nháp annotation không hợp lệ.')
    model = deepcopy(model)
    # sync_workspace accepts unfinished relationships; portable imports additionally
    # reject dangling IDs, invalid primitive types, and poisoned undo frames.
    def frame(raw):
        if not isinstance(raw, dict):
            raise ValueError('Lịch sử annotation không hợp lệ.')
        candidate = dict(raw, preferences=model.get('preferences', {}), undo=[], redo=[])
        scratch = deepcopy(state)
        scratch.pop('workspace', None)
        sync_workspace(scratch, candidate)
        ids = {entry['char_id'] for entry in candidate['entries']}
        if any(type(entry.get('source_index')) is not int for entry in candidate['entries']
               if entry['type'] == 'original'):
            raise ValueError('Chỉ số ký tự gốc phải là số nguyên.')
        for uid, box in candidate['boxes'].items():
            if box.get('order') is not None and type(box['order']) is not int:
                raise ValueError('Thứ tự box phải là số nguyên hoặc null.')
            if box.get('status') not in (None, '', 'intact', 'damaged'):
                raise ValueError('Trạng thái box không hợp lệ.')
            if box.get('damage_level') is not None and (type(box['damage_level']) is not int
                                                       or box['damage_level'] not in (1, 2, 3)):
                raise ValueError('Mức hư hại không hợp lệ.')
            if any(type(box.get(key)) is not bool for key in
                   ('unknown', 'unavailable_font', 'expert_prediction', 'suspicious')):
                raise ValueError('Các cờ annotation phải là boolean.')
        if any(uid not in candidate['boxes'] or char not in ids
               for uid, char in candidate.get('confirmed', {}).items()):
            raise ValueError('Cặp gán tham chiếu box hoặc ký tự không tồn tại.')
        for key in ('selected_box', 'selected_char'):
            selected = candidate.get(key)
            available = candidate['boxes'] if key == 'selected_box' else ids
            if selected is not None and selected not in available:
                raw[key] = None
        if not isinstance(raw.get('selected_boxes', []), list):
            raise ValueError('Danh sách box được chọn không hợp lệ.')
        raw['selected_boxes'] = [uid for uid in raw.get('selected_boxes', []) if uid in candidate['boxes']]
        return raw
    frame(model)
    scroll = model.get('preferences', {}).get('reference_scroll', 0)
    if type(scroll) not in (int, float) or not math.isfinite(scroll) or scroll < 0:
        raise ValueError('Vị trí cuộn nội dung không hợp lệ.')
    for key in ('undo', 'redo'):
        if not isinstance(model.get(key, []), list) or len(model.get(key, [])) > 50:
            raise ValueError('Lịch sử undo/redo không hợp lệ.')
        model[key] = [frame(item) for item in model.get(key, [])]
    scratch = deepcopy(state)
    scratch.pop('workspace', None)
    sync_workspace(scratch, model)
    return scratch['workspace']


def _browser_ui(engine, state, raw):
    if not isinstance(raw, dict):
        raise ValueError('Dữ liệu giao diện không hợp lệ.')
    result = {}
    fields = {json.dumps(f['path'], ensure_ascii=False): f for f in content_fields(
        state['draft_content'], state['code'], engine.content_titles, engine.metadata_fields)}
    for key in ('content',):
        if key in raw:
            parsed = json.loads(raw[key])
            if not isinstance(parsed, dict) or set(parsed) != set(fields):
                raise ValueError('Bản nháp nội dung không khớp các mục hiện tại.')
            for path, entry in parsed.items():
                expected = fields[path]
                if (not isinstance(entry, dict) or entry.get('title') != expected['title']
                        or entry.get('path') != list(expected['path']) or not isinstance(entry.get('value'), str)):
                    raise ValueError('Bản nháp nội dung không hợp lệ.')
            result[key] = json.dumps(parsed, ensure_ascii=False)
    if 'typing' in raw:
        if not isinstance(raw['typing'], dict) or any(k not in fields or not isinstance(v, str)
                                                     for k, v in raw['typing'].items()):
            raise ValueError('Nội dung đang gõ không hợp lệ.')
        result['typing'] = deepcopy(raw['typing'])
    if 'section' in raw:
        if raw['section'] not in fields:
            raise ValueError('Mục đang chọn không tồn tại.')
        result['section'] = raw['section']
    if 'ui' in raw:
        if not isinstance(raw['ui'], dict):
            raise ValueError('Dữ liệu ô nhập không hợp lệ.')
        result['ui'] = {k: v for k, v in raw['ui'].items()
                        if k in ('content-value', 'content-draft-bridge', 'crop-coordinates')}
        if any(not isinstance(v, str) for v in result['ui'].values()):
            raise ValueError('Giá trị ô nhập phải là chuỗi.')
        bridge = result['ui'].get('content-draft-bridge')
        if bridge is not None:
            # Validate the hidden input too; it will be submitted by Continue.
            _browser_ui(engine, state, {'content': bridge})
    if 'viewer' in raw:
        viewer = raw['viewer']
        if not isinstance(viewer, dict):
            raise ValueError('Bản nháp crop không hợp lệ.')
        crop = validate_crop_coordinates(viewer['crop'], state['image_size'])
        zoom = viewer.get('zoom', 100)
        if type(zoom) not in (int, float) or not math.isfinite(zoom) or not 25 <= zoom <= 500:
            raise ValueError('Mức zoom crop không hợp lệ.')
        if viewer.get('draft') is not None and not isinstance(viewer['draft'], str):
            raise ValueError('Tọa độ đang gõ không hợp lệ.')
        result['viewer'] = dict(crop=crop, zoom=zoom, draft=viewer.get('draft'))
    return result


class ProgressBackup:
    def __init__(self, engine, images):
        self.engine = engine
        self.images = {Path(path).name: Path(path).resolve() for path in images}
        if len(self.images) != len(images):
            raise ValueError('Tên ảnh phải duy nhất trong bộ dữ liệu.')

    def identity(self, name):
        path = self.images.get(name)
        if path is None:
            raise ValueError(f'Không tìm thấy ảnh: {name}')
        with Image.open(path) as image:
            size = list(image.size)
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(chunk)
        source = self.engine._source_content_for(name)
        return dict(name=name, size=size, sha256=sha.hexdigest(), source_sha256=digest(source['record']))

    def _draft(self, state, browser=None):
        engine = self.engine
        state = deepcopy(state)
        model = state.get('workspace')
        # A saved image reopened in Content Verification may not have mounted the
        # workspace yet. Capture its loaded relationships too, without advancing it.
        verified = state.get('verified_content')
        if not model and state.get('regions') and state['current_step'] == 2:
            advanced = engine.apply(state, 'next')
            model = advanced.get('workspace')
            verified = advanced.get('verified_content')
        raw = browser or {}
        if state['current_step'] == 3 and raw.get('workspace') is not None:
            model = raw['workspace']
        return dict(image=state['image'], step=state['current_step'],
                    records={key: _record(engine, state, value) if value is not None else None
                             for key, value in dict(draft=state['draft_content'],
                                 source=state['source_content'], baseline=state['source_baseline'],
                                 verified=verified).items()},
                    workspace=deepcopy(model), crop=state.get('crop'),
                    resized_image_size=state.get('resized_image_size'),
                    detection_loaded=bool(state.get('detection_loaded')),
                    browser={k: deepcopy(raw[k]) for k in ('content', 'typing', 'section', 'ui', 'viewer') if k in raw})

    def export(self, ctx, browser=None):
        engine = self.engine
        raw_records = (browser or {}).get('drafts', {})
        if not isinstance(raw_records, dict):
            raise ValueError('Dữ liệu bản nháp trình duyệt không hợp lệ.')
        states = dict(ctx.get('drafts', {}))
        active = ctx['active']
        if active.get('image_path'):
            states[active['image_path']] = active
        drafts = []
        for state in states.values():
            if not state.get('image'):
                continue
            # Only merge browser data belonging to the live application/tab/generation.
            applicable = [record for record in raw_records.values()
                if isinstance(record, dict) and record.get('metadata', {}).get('image') == state['image_path']
                and record['metadata'].get('step') == state['current_step']
                and record['metadata'].get('tab') == ctx.get('_recovery', {}).get('tab')
                and record['metadata'].get('generation') == ctx.get('_recovery', {}).get('generations', {}).get(state['image_path'])
                and record['metadata'].get('application') == (browser or {}).get('application')]
            drafts.append(self._draft(state, applicable[-1] if applicable else None))
        paths = list(self.images.values())
        annotations = collect_annotations(paths, engine.output, allow_empty=True)
        mismatches = collect_source_mismatches(paths, engine.output, allow_empty=True)
        content = {doc['image']: doc for doc in collect_content_documents(
            paths, engine.output, allow_empty=True, titles=engine.verification_titles)}
        saved = []
        for kind, docs in (('annotation', annotations), ('source_mismatch', mismatches)):
            for doc in docs:
                name = doc['image']
                state = engine.open_image(self.images[name])
                entry = dict(image=name, kind=kind, document=doc,
                             content=content.get(name) or _record(engine, state, state['draft_content']))
                meta = engine.output / '.state' / ('source_mismatches' if kind == 'source_mismatch' else '') / (self.images[name].stem + '.json')
                if meta.is_file():
                    entry['workspace'] = read_json(meta).get('workspace')
                saved.append(entry)
        names = sorted({item['image'] for item in drafts + saved})
        if not names:
            raise ValueError('Chưa có tiến trình để tải.')
        result = dict(format=FORMAT, version=VERSION, created_at=datetime.now(timezone.utc).isoformat(),
                      schema=schema(engine), dataset=[self.identity(name) for name in names],
                      active_image=active.get('image'), drafts=drafts, saved=saved)
        # A backup must itself be importable; validation never requires draft completion.
        self.prepare(result)
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BACKUP_BYTES:
            raise ValueError('Tiến trình vượt quá giới hạn 128 MB.')
        return result

    def read(self, path):
        if Path(path).stat().st_size > MAX_BACKUP_BYTES:
            raise ValueError('File tiến trình vượt quá 128 MB.')
        return read_json(path)

    def restore_draft(self, item):
        engine = self.engine
        name = item['image']
        state = engine.open_image(self.images[name], load_saved=False)
        state['unified_enabled'] = True
        records = item['records']
        for key in ('draft', 'source', 'baseline'):
            if records.get(key) is None:
                raise ValueError('Thiếu nội dung trong bản nháp.')
        restored = {key: _restore_record(engine, state, document) if document is not None else None
                    for key, document in records.items()}
        if set(restored) != {'draft', 'source', 'baseline', 'verified'}:
            raise ValueError('Các nhóm nội dung bản nháp không hợp lệ.')
        step = item['step']
        if type(step) is not int or step not in (2, 3, 6, 7):
            raise ValueError('Bước phục hồi không được hỗ trợ.')
        if restored['verified'] is not None:
            text = annotation_text(restored['verified'], state['code'], engine.annotation_title)
            set_verified_content(state, restored['verified'], text)
        elif step != 2 or item.get('workspace') is not None:
            raise ValueError('Thiếu nội dung đã xác nhận cho workspace.')
        if item.get('workspace') is not None:
            model = _workspace(state, item['workspace'])
            sync_workspace(state, model)
        elif step != 2:
            raise ValueError('Thiếu workspace.')
        state.update(source_content=restored['source'], source_baseline=restored['baseline'],
                     draft_content=restored['draft'], current_step=step,
                     detection_loaded=item['detection_loaded'], saved=False)
        if type(state['detection_loaded']) is not bool:
            raise ValueError('Trạng thái detection không hợp lệ.')
        state['resized_image_size'] = validate_resized_image_size(item['resized_image_size'])
        state['crop'] = validate_crop_coordinates(item['crop'], state['image_size'])
        if step in (6, 7):
            # Re-run the domain gates instead of trusting workflow flags from a file.
            state['current_step'] = 3
            state = engine.apply(state, 'next')
            if state['current_step'] != 6:
                raise ValueError('Annotation chưa đủ điều kiện vào bước Crop.')
            if step == 7:
                state = engine.apply(state, 'next')
                if state['current_step'] != 7:
                    raise ValueError('Annotation chưa đủ điều kiện vào bước Review.')
        ui = _browser_ui(engine, state, item.get('browser', {}))
        return state, ui

    def prepare(self, data):
        """Validate everything into an isolated candidate; never write output files."""
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError('Hãy chọn file tiến trình Vietnamica, không phải JSON annotation.')
        if type(data.get('version')) is not int or data['version'] != VERSION:
            raise ValueError('Phiên bản file tiến trình không được hỗ trợ.')
        datetime.fromisoformat(data['created_at'])
        if data['schema'] != schema(self.engine):
            raise ValueError('Cấu hình mục nội dung/annotation không tương thích.')
        identities = data['dataset']
        if not isinstance(identities, list) or not identities:
            raise ValueError('Bộ dữ liệu backup không hợp lệ.')
        by_name = {}
        for item in identities:
            name = item['name']
            if not isinstance(name, str) or name in by_name:
                raise ValueError('Tên ảnh trong backup bị trùng hoặc không hợp lệ.')
            current = self.identity(name)
            if item != current:
                raise ValueError(f'{name}: ảnh hoặc nội dung nguồn không khớp backup.')
            by_name[name] = current
        drafts, ui = {}, {}
        if not isinstance(data['drafts'], list) or not isinstance(data['saved'], list):
            raise ValueError('Danh sách tiến trình không hợp lệ.')
        for item in data['drafts']:
            name = item['image']
            if name not in by_name or name in ui:
                raise ValueError('Ảnh trong bản nháp không hợp lệ hoặc bị trùng.')
            state, browser = self.restore_draft(item)
            drafts[state['image_path']] = state
            ui[name] = browser
        active_name = data['active_image']
        if active_name is not None and active_name not in ui:
            raise ValueError('Ảnh đang làm không có trong các bản nháp.')
        saved, seen = [], set()
        for item in data['saved']:
            name = item['image']
            if name not in by_name or name in seen:
                raise ValueError('Kết quả đã lưu bị trùng hoặc không thuộc bộ dữ liệu.')
            seen.add(name)
            state = self.engine.open_image(self.images[name], load_saved=False)
            record = _restore_record(self.engine, state, item['content'])
            doc = deepcopy(item['document'])
            if item['kind'] == 'annotation':
                if not isinstance(doc, dict) or set(doc) != {'image', 'bounding_boxes', 'annotations', 'image_resize', 'crop'}:
                    raise ValueError('Định dạng annotation không hợp lệ.')
                validate_document(doc, name, state['image_size'])
            elif item['kind'] == 'source_mismatch':
                validate_source_mismatch_document(doc, name, state['image_size'])
            else:
                raise ValueError('Loại kết quả không được hỗ trợ.')
            workspace = item.get('workspace')
            text = annotation_text(record, state['code'], self.engine.annotation_title)
            if workspace is not None:
                set_verified_content(state, record, text)
                workspace = _workspace(state, workspace)
                sync_workspace(state, workspace)
                materialize_workspace(state)
                if (state['bounding_boxes'] != doc.get('bounding_boxes')
                        or state['annotations'] != doc.get('annotations')):
                    raise ValueError(f'{name}: workspace không khớp kết quả đã lưu.')
            saved.append(dict(image=name, kind=item['kind'], document=doc,
                              content=deepcopy(item['content']), workspace=workspace, text=text))
        if set(by_name) != set(ui) | seen:
            raise ValueError('Backup có ảnh không được tham chiếu.')
        return dict(active_name=active_name, drafts=drafts, ui=ui, saved=saved,
                    created_at=data['created_at'])

    def summary(self, prepared):
        names = [item['image'] for item in prepared['saved']]
        conflicts = [name for name in names if any(path.exists() for path in self._paths(name)[:2])]
        steps = {2: 'Kiểm tra nội dung', 3: 'Annotation Workspace', 6: 'Crop', 7: 'Review'}
        active = prepared['active_name']
        state = prepared['drafts'].get(str(self.images.get(active)), {})
        return dict(created_at=prepared['created_at'], active_image=active,
                    step=steps.get(state.get('current_step')), drafts=len(prepared['drafts']),
                    saved=len(names), conflicts=conflicts)

    def _paths(self, name):
        filename = self.images[name].stem + '.json'
        out = self.engine.output
        return (out / filename, out / 'source_mismatches' / filename,
                out / '.state' / filename, out / '.state' / 'source_mismatches' / filename)

    def commit(self, prepared):
        """Caller only replaces the live session after this transaction succeeds."""
        engine = self.engine
        paths = [engine.output / '.state' / 'content.json']
        for item in prepared['saved']:
            paths.extend(self._paths(item['image']))
        with CONTENT_LOCK, rollback_saved_files(paths):
            registry_path = paths[0]
            registry = read_json(registry_path) if registry_path.exists() else []
            if not isinstance(registry, list):
                raise ValueError('Danh sách nội dung đã lưu không hợp lệ.')
            for doc in registry:
                validate_content_document(doc, doc.get('image', ''), None)
            replacing = {item['image'] for item in prepared['saved']}
            registry = [doc for doc in registry if doc['image'] not in replacing]
            for item in prepared['saved']:
                normal, mismatch, normal_meta, mismatch_meta = self._paths(item['image'])
                is_mismatch = item['kind'] == 'source_mismatch'
                target, other = (mismatch, normal) if is_mismatch else (normal, mismatch)
                meta, other_meta = (mismatch_meta, normal_meta) if is_mismatch else (normal_meta, mismatch_meta)
                atomic_write(target, item['document'])
                other.unlink(missing_ok=True)
                sidecar = dict(document_hash=digest(item['document']),
                               text_hash=hashlib.sha256(item['text'].encode('utf-8')).hexdigest())
                if item['workspace'] is not None:
                    sidecar['workspace'] = item['workspace']
                atomic_write(meta, sidecar)
                other_meta.unlink(missing_ok=True)
                registry.append(item['content'])
            if prepared['saved']:
                atomic_write(registry_path, registry)
        active = (prepared['drafts'].get(str(self.images[prepared['active_name']]))
                  if prepared['active_name'] else dict(new_state(), unified_enabled=True))
        return dict(active=deepcopy(active), drafts=deepcopy(prepared['drafts']))
