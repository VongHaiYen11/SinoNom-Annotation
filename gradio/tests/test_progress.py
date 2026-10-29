"""Portable backups round-trip across fresh processes, folders and recovery IDs."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from annotation.io import atomic_write, read_json
from annotation.progress import ProgressBackup
from annotation.recovery import RecoveryStore
from annotation.state import new_state
from annotation.workflow import Workflow
from annotation.export import collect_annotations, collect_content_documents, collect_source_mismatches
from annotation.text_extraction import content_fields

TITLE = 'Nguyên văn chữ Hán Nôm'


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.old = self.make_engine('old')
        self.new = self.make_engine('new')
        self.store = RecoveryStore()

    def make_engine(self, name):
        root = self.root / name
        root.mkdir()
        for i in (1, 2):
            Image.new('RGB', (100, 100), 'white').save(root / f'{i}.png')
        source = root / 'source.json'
        atomic_write(source, [{'noi_dung': [dict(ky_hieu=str(i), chuyen_muc=[
            dict(tieu_de=TITLE, van_ban='甲甲')]) for i in (1, 2)]}])
        engine = Workflow(SimpleNamespace(source_json=source, output_dir=root / 'out',
            content_titles=(TITLE,), metadata_fields=(), annotation_title=TITLE, skip_detection=True))
        self.addCleanup(engine._preview_cache.cleanup)
        return engine

    def service(self, engine):
        return ProgressBackup(engine, [Path(engine.options.source_json).parent / f'{i}.png' for i in (1, 2)])

    def opened(self, engine=None, image=1):
        engine = engine or self.old
        state = engine.open_image(Path(engine.options.source_json).parent / f'{image}.png')
        state['unified_enabled'] = True
        return state

    def workspace(self, image=1, complete=False):
        state = self.old.apply(self.opened(image=image), 'next')
        model = deepcopy(state['workspace'])
        model['boxes'] = {f'b{i}': dict(bbox=[i*20, 5, i*20+10, 25], order=i,
            status='intact', damage_level=None, unknown=False, unavailable_font=False,
            expert_prediction=False, suspicious=False) for i in (1, 2)}
        model['confirmed'] = {'b1': model['entries'][0]['char_id']}
        if complete:
            model['confirmed']['b2'] = model['entries'][1]['char_id']
        model.update(selected_box='b2', selected_boxes=['b2'], selected_char=model['entries'][1]['char_id'])
        return self.old.apply(state, 'workspace_sync', {'model': model})

    def context(self, active=None, drafts=None):
        ctx = self.store.restore('old-tab', dict(active=dict(new_state(), unified_enabled=True), drafts={}))
        ctx.update(active=active or dict(new_state(), unified_enabled=True), drafts=drafts or {})
        for state in list(ctx['drafts'].values()) + [ctx['active']]:
            self.store.metadata(dict(ctx, active=state))
        self.store.checkpoint(ctx)
        return ctx

    def browser(self, ctx, **updates):
        meta = self.store.metadata(ctx)
        key = json.dumps([meta['application'], meta['tab'], meta['image'], meta['step']], separators=(',', ':'))
        return dict(application=self.store.application, drafts={key: dict(metadata=meta, **updates)})

    def saved(self, mismatch=False):
        state = self.workspace(complete=True)
        if mismatch:
            model = deepcopy(state['workspace'])
            model['entries'][1]['excluded'] = True
            model['entries'].insert(1, dict(char_id='miss', value='MISS', source_index=None,
                                            type='missing', excluded=False))
            model['confirmed']['b2'] = 'miss'
            state = self.old.apply(state, 'workspace_sync', {'model': model})
        state = self.old.apply(state, 'next')
        state = self.old.apply(state, 'crop', {'bbox': [1, 2, 90, 95]})
        state = self.old.apply(state, 'next')
        return self.old.apply(state, 'save')

    def test_content_typing_multiple_images_and_portable_identity(self):
        active = self.opened()
        other = self.opened(image=2)
        ctx = self.context(active, {other['image_path']: other})
        field = content_fields(active['draft_content'], active['code'], (TITLE,))[0]
        key = json.dumps(field['path'], ensure_ascii=False)
        browser = self.browser(ctx, section=key, typing={key: 'unfinished □@'},
                               ui={'content-value': 'unfinished □@'})
        backup = self.service(self.old).export(ctx, browser)
        serialized = json.dumps(backup, ensure_ascii=False)
        self.assertNotIn(str(self.root / 'old'), serialized)
        self.assertNotIn('gradio_api/file=', serialized)
        self.assertNotIn(self.store.application, serialized)
        prepared = self.service(self.new).prepare(json.loads(serialized))
        self.assertEqual(prepared['ui']['1.png']['typing'][key], 'unfinished □@')
        self.assertEqual(len(prepared['drafts']), 2)
        restored = self.service(self.new).commit(prepared)
        self.assertEqual(restored['active']['current_step'], 2)
        self.assertTrue(restored['active']['image_path'].startswith(str(self.root / 'new')))
        self.assertIn(str(self.new.preview_dir), restored['active']['image_url'])
        self.assertFalse(self.new.output.exists(), 'draft-only imports must not create saved results')

    def test_workspace_preserves_duplicates_conflicts_flags_history_and_latest_browser_edit(self):
        state = self.workspace()
        ctx = self.context(state)
        model = deepcopy(state['workspace'])
        model['boxes']['b2'].update(status='damaged', damage_level=None, suspicious=True,
                                    unavailable_font=True, expert_prediction=True)
        # A duplicate valid reference is an unfinished conflict, not malformed JSON.
        model['confirmed']['b2'] = model['entries'][0]['char_id']
        frame = {key: deepcopy(model[key]) for key in
                 ('entries', 'boxes', 'confirmed', 'selected_box', 'selected_char', 'selected_boxes')}
        model.update(undo=[frame], redo=[deepcopy(frame)], version=3)
        model['preferences'].update(reference_scroll=350, zoom=115)
        backup = self.service(self.old).export(ctx, self.browser(ctx, workspace=model))
        prepared = self.service(self.new).prepare(backup)
        restored = next(iter(prepared['drafts'].values()))
        self.assertEqual(restored['workspace'], model)
        self.assertEqual(restored['current_step'], 3)
        self.assertFalse(restored['workflow']['status_valid'])
        advanced = self.new.apply(restored, 'next')
        self.assertEqual(advanced['current_step'], 3)
        self.assertTrue(advanced['workspace_issues'])

    def test_crop_and_review_rerun_gates_and_preserve_invalid_crop_typing(self):
        for step in (6, 7):
            state = self.old.apply(self.workspace(complete=True), 'next')
            if step == 7:
                state = self.old.apply(state, 'next')
            ctx = self.context(state)
            viewer = dict(crop=[3, 4, 80, 90], zoom=130, draft='[not finished')
            browser = self.browser(ctx, viewer=viewer) if step == 6 else None
            backup = self.service(self.old).export(ctx, browser)
            prepared = self.service(self.new).prepare(backup)
            restored = next(iter(prepared['drafts'].values()))
            self.assertEqual(restored['current_step'], step)
            if step == 6:
                self.assertEqual(prepared['ui']['1.png']['viewer'], viewer)
            invalid = deepcopy(backup)
            invalid['drafts'][0]['workspace']['confirmed'] = {}
            with self.assertRaises(ValueError):
                self.service(self.new).prepare(invalid)

    def test_completed_results_import_export_and_unrelated_results_remain(self):
        self.saved()
        service = self.service(self.new)
        backup = self.service(self.old).export(self.context())
        prepared = service.prepare(backup)
        self.assertFalse(self.new.output.exists(), 'preview must not write output files')
        self.new.output.mkdir()
        unrelated = self.new.output / 'unrelated.json'
        unrelated.write_text('unrelated bytes')
        ctx = service.commit(prepared)
        self.assertIsNone(ctx['active']['image'])
        self.assertEqual(unrelated.read_text(), 'unrelated bytes')
        paths = list(service.images.values())
        docs = collect_annotations(paths, self.new.output)
        self.assertEqual(docs[0]['annotations'], {'1': '甲', '2': '甲'})
        self.assertEqual(len(collect_content_documents(paths, self.new.output)), 1)
        # Stable IDs and confirmations survive reopening a saved result after restore.
        opened = self.new.open_image(service.images['1.png'])
        reopened = self.new.apply(dict(opened, unified_enabled=True), 'next')
        self.assertEqual(len(reopened['workspace']['confirmed']), 2)
        self.assertEqual(service.summary(service.prepare(backup))['conflicts'], ['1.png'])

    def test_mixed_mismatch_roundtrip(self):
        self.saved(mismatch=True)
        backup = self.service(self.old).export(self.context())
        self.service(self.new).commit(self.service(self.new).prepare(backup))
        docs = collect_source_mismatches(list(self.service(self.new).images.values()), self.new.output)
        self.assertEqual(docs[0]['annotations'], {'1': '甲', '2': 'MISS'})
        self.assertEqual(set(docs[0]['issue_type']), {'missing_text', 'extra_text'})
        self.assertFalse((self.new.output / '1.json').exists())

    def test_invalid_files_dataset_schema_and_references_rejected(self):
        service = self.service(self.new)
        backup = self.service(self.old).export(self.context(self.workspace()))
        mutations = [lambda b: b.update(format='annotation'), lambda b: b.update(version=2),
            lambda b: b['schema'].update(annotation_title='different'),
            lambda b: b['dataset'][0].update(name='../1.png'),
            lambda b: b['dataset'][0].update(sha256='wrong'),
            lambda b: b['drafts'][0]['workspace']['confirmed'].update(b1='absent'),
            lambda b: b['drafts'][0]['workspace']['boxes']['b1'].update(bbox=[-1, 0, 20, 30]),
            lambda b: b['drafts'][0]['workspace']['boxes']['b1'].update(unknown='true')]
        for mutate in mutations:
            invalid = deepcopy(backup)
            mutate(invalid)
            with self.assertRaises((ValueError, KeyError)):
                service.prepare(invalid)
        Image.new('RGB', (100, 100), 'black').save(service.images['1.png'])
        with self.assertRaises(ValueError): service.prepare(backup)
        self.assertFalse(self.new.output.exists())

    def test_source_change_rejected_even_with_identical_images(self):
        backup = self.service(self.old).export(self.context(self.opened()))
        source = Path(self.new.options.source_json)
        data = read_json(source)
        data[0]['noi_dung'][0]['chuyen_muc'][0]['van_ban'] = 'changed'
        atomic_write(source, data)
        with self.assertRaises(ValueError): self.service(self.new).prepare(backup)

    def test_transaction_restores_every_file_on_write_failure(self):
        self.saved()
        shutil.copytree(self.old.output, self.new.output)
        backup = self.service(self.old).export(self.context())
        service = self.service(self.new)
        prepared = service.prepare(backup)
        def contents():
            return {str(p.relative_to(self.new.output)): p.read_bytes()
                    for p in self.new.output.rglob('*') if p.is_file()}
        before = contents()
        writes = 0
        def failing(path, data):
            nonlocal writes
            writes += 1
            if writes == 2: raise OSError('disk full')
            return atomic_write(path, data)
        with patch('annotation.progress.atomic_write', failing):
            with self.assertRaises(OSError): service.commit(prepared)
        self.assertEqual(contents(), before)


if __name__ == '__main__':
    unittest.main()
