"""Reload a connection against the same application, without detection or saving."""
import json
import gradio as gr
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from annotation.recovery import RecoveryStore
from annotation.state import new_state
from annotation.io import atomic_write
from app import create_app, parser
from PIL import Image


class RecoveryTests(unittest.TestCase):
    def test_workflow_reload_errors_undo_and_save(self):
        from test_ui import GradioCallbacks
        with tempfile.TemporaryDirectory() as folder:
            cb, _, image = GradioCallbacks().current_app(Path(folder).resolve(), '永')
            reload = lambda: cb['restore_session'](json.dumps({'tab': 'workflow'}))
            opened = cb['open_image'](reload().session, str(image))
            ctx = opened.session
            original = opened.board['value']['recovery']['generation']
            undone = cb['undo'](ctx)
            self.assertNotEqual(undone.board['value']['recovery']['generation'], original)
            self.assertEqual(reload().session['active']['current_step'], 2)
            advanced = cb['advance'](undone.session, undone.content_bridge)
            ctx = advanced.session
            self.assertEqual(reload().session['active']['current_step'], 3)
            boxes = {'local': dict(bbox=[0,0,10,10], status='intact', order=1)}
            model=deepcopy(ctx['active']['workspace'])
            model['boxes']={'local':dict(boxes['local'],damage_level=None,unknown=False,
                unavailable_font=False,expert_prediction=False,suspicious=False)}
            rejected=cb['on_workspace_action'](ctx,gr.EventData(None,dict(action='continue',model=model)))
            self.assertEqual(reload().session['active']['current_step'],3)
            self.assertTrue(rejected.session['active']['workspace_issues'])
            model['confirmed']={'local':model['entries'][0]['char_id']}
            cropped=cb['on_workspace_action'](rejected.session,gr.EventData(None,dict(action='continue',model=model)))
            self.assertEqual(reload().session['active']['current_step'], 6)
            reviewed = cb['advance'](cropped.session, selection=json.dumps({'crop': [1,2,90,95]}))
            self.assertEqual(reload().session['active']['current_step'], 7)
            self.assertEqual(reload().session['active']['crop'], [1,2,90,95])
            saved = cb['save'](reviewed.session)
            restored = reload()
            self.assertEqual(restored.session['active']['current_step'], 1)
            self.assertEqual(restored.session['drafts'], {})
            self.assertEqual(restored.board['value']['recovery']['discardImage'], str(image))
            self.assertTrue((Path(folder)/'out'/'1.json').is_file())
            self.assertEqual(saved.session['active'], restored.session['active'])

    def test_connections_are_isolated_and_snapshots_do_not_alias(self):
        store = RecoveryStore()
        initial = dict(active=new_state(), drafts={})
        ctx = store.restore('a', initial)
        ctx['active'].update(image_path='/1.png', current_step=4)
        meta = store.checkpoint(ctx)
        ctx['active']['current_step'] = 7
        self.assertEqual(store.restore('a', initial)['active']['current_step'], 4)
        self.assertEqual(store.restore('b', initial)['active']['current_step'], 1)
        restored = store.restore('a', initial)
        store.rotate(restored, '/1.png')
        self.assertNotEqual(store.metadata(restored)['generation'], meta['generation'])
        self.assertNotEqual(RecoveryStore().application, store.application)

    def test_reload_restores_steps_content_and_preserves_unsaved_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root/'1.png'
            Image.new('RGB', (100, 100), 'white').save(image)
            source = root/'source.json'
            atomic_write(source, [{'noi_dung': [{'ky_hieu': '1', 'chuyen_muc': [
                {'tieu_de': 'Nguyên văn chữ Hán Nôm', 'van_ban': '甲乙'}]}]}])
            app = create_app(parser().parse_args([
                '--image-dir', str(root), '--source-json', str(source),
                '--output-dir', str(root/'out'), '--skip-detection']))
            callbacks = {f.fn.__name__: f.fn for f in app.fns.values() if f.fn}
            restore = callbacks['restore_session']
            ctx = restore(json.dumps({'tab': 'a'})).session
            opened = callbacks['open_image'](ctx, str(image.resolve()))
            metadata = opened.board['value']['recovery']
            bridge_index = next(i for i, value in enumerate(opened)
                                if isinstance(value, str) and '"path"' in value)
            fields = json.loads(opened[bridge_index])
            section = next(iter(fields))
            record = dict(metadata=metadata, section=section,
                          typing={section: 'unfinished input'},
                          board={'boxes': {}}, ui={'content-value': 'unfinished input'})
            with patch('annotation.workflow.detect', side_effect=AssertionError('Must not detect')):
                resumed = restore(json.dumps({'tab': 'a', 'drafts': {'draft': record}}))
            self.assertEqual(resumed.session['active']['image_path'], str(image.resolve()))
            self.assertEqual(resumed.session['active']['current_step'], 2)
            self.assertEqual(resumed.field_value, 'unfinished input')
            self.assertEqual(json.loads(resumed[bridge_index])[section]['value'], 'unfinished input')
            self.assertFalse((root/'out'/'1.json').exists())
            self.assertIsNone(restore(json.dumps({'tab': 'b'})).session['active']['image'])
            # A callback with an invalid transition still checkpoints its actual step.
            ctx = deepcopy(resumed.session)
            ctx['active']['current_step'] = 3
            ctx['active']['regions'] = {'r': dict(bbox=[0,0,10,10], status='intact',
                damage_level=None, unknown=False, unavailable_font=False,
                expert_prediction=False, suspicious=False, order=None)}
            callbacks['go_back'](ctx)
            self.assertEqual(restore(json.dumps({'tab': 'a'})).session['active']['current_step'], 2)
            # A stale generation cannot replace content from a newer workflow state.
            record['metadata']['generation'] = 'stale'
            stale = restore(json.dumps({'tab': 'a', 'drafts': {'draft': record}}))
            self.assertNotEqual(stale.field_value, 'unfinished input')
            for invalid in ('null', '[]', '{broken'):
                self.assertEqual(restore(invalid).session['active']['current_step'], 1)


if __name__ == '__main__':
    unittest.main()
