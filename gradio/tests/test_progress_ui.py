"""Exercise download, preview and explicit confirmation through real UI callbacks."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, parser
from annotation.io import atomic_write
from PIL import Image

TITLE = 'Nguyên văn chữ Hán Nôm'


class ProgressUICallbacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def build(self, name):
        root = self.root / name
        root.mkdir()
        Image.new('RGB', (100, 100), 'white').save(root / '1.png')
        atomic_write(root / 'source.json', [{'noi_dung': [dict(ky_hieu='1', chuyen_muc=[
            dict(tieu_de=TITLE, van_ban='甲乙')])]}])
        app = create_app(parser().parse_args(['--image-dir', str(root), '--source-json', str(root / 'source.json'),
            '--output-dir', str(root / 'out'), '--skip-detection']))
        callbacks = {f.fn.__name__: f.fn for f in app.fns.values() if f.fn}
        return root, app, callbacks

    def test_preview_is_read_only_confirm_rebinds_metadata_and_restores_typing(self):
        old_root, _, old = self.build('old')
        opened = old['open_image'](old['restore_session']('{"tab":"old-tab"}').session, str(old_root / '1.png'))
        metadata = opened.recovery_notice
        fields = json.loads(opened.content_bridge)
        section = next(key for key, value in fields.items() if value['title'] == TITLE)
        record = dict(metadata=metadata, content=opened.content_bridge, section=section,
                      typing={section: '甲乙□未保存'}, ui={'content-value': '甲乙□未保存'})
        request = json.dumps(dict(application=metadata['application'], drafts={'old': record}), ensure_ascii=False)
        payload = json.loads(old['download_progress'](opened.session, request))
        backup_path = self.root / payload['name']
        backup_path.write_text(payload['content'])
        new_root, new_app, new = self.build('new')
        initial = new['restore_session']('{"tab":"new-tab"}').session
        before = deepcopy(initial)
        pending, markup, visible = new['preview_progress'](str(backup_path))
        self.assertTrue(visible['visible'])
        self.assertIn('1.png', markup)
        self.assertEqual(initial, before)
        self.assertFalse((new_root / 'out').exists())
        result = new['restore_progress'](initial, pending, str(backup_path))
        ctx = result[0]
        self.assertEqual(ctx['active']['current_step'], 2)
        self.assertEqual(ctx['active']['image_path'], str(new_root / '1.png'))
        seed = ctx['_progress_seed']['records']
        restored_meta = next(iter(seed.values()))['metadata']
        self.assertNotEqual(restored_meta['application'], metadata['application'])
        self.assertNotEqual(restored_meta['generation'], metadata['generation'])
        self.assertEqual(restored_meta['tab'], 'new-tab')
        callback = next(f for f in new_app.fns.values() if f.fn and f.fn.__name__ == 'restore_progress')
        value_index = next(i for i, component in enumerate(callback.outputs)
                           if getattr(component, 'elem_id', None) == 'content-value')
        self.assertEqual(result[value_index], '甲乙□未保存')
        self.assertIsNone(result[-4])
        self.assertFalse(result[-2]['visible'])
        reloaded = new['restore_session']('{"tab":"new-tab"}').session
        self.assertEqual(reloaded['active']['image'], '1.png')
        self.assertFalse((new_root / 'out').exists())

    def test_invalid_preview_and_changed_upload_do_not_replace_current_session(self):
        root, _, cb = self.build('app')
        initial = cb['restore_session']('{}').session
        path = root / 'wrong.json'
        atomic_write(path, {'image': '1.png', 'annotations': {}})
        pending, _, visible = cb['preview_progress'](str(path))
        self.assertIsNone(pending)
        self.assertFalse(visible['visible'])
        opened = cb['open_image'](initial, str(root / '1.png'))
        downloaded = json.loads(cb['download_progress'](opened.session, '{}'))
        path.write_text(downloaded['content'])
        pending, _, _ = cb['preview_progress'](str(path))
        original = deepcopy(opened.session)
        path.write_text('{}')
        result = cb['restore_progress'](opened.session, pending, str(path))
        self.assertEqual(opened.session, original)
        self.assertEqual(result[0], {'__type__': 'update'})
        self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
