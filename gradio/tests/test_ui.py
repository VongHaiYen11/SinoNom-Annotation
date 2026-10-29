"""Exercise real Gradio callbacks without requiring a browser or ML assets."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app,parser,resolve_app_paths
from annotation.io import atomic_write
from PIL import Image
import gradio as gr


class GradioCallbacks(unittest.TestCase):
    def test_fonts_preload_pmingliu(self):
        from ui.fonts import FONT_CSS, FONT_FILES, DEFAULT_FONT_STACK, font_manifest
        from app import FONT_PRELOAD_JS
        for family in ('PMingLiU', 'PMingLiU-ExtB'):
            self.assertTrue(FONT_FILES[family].is_file())
            self.assertNotIn("@font-face", FONT_CSS)
            spec = next(item for item in font_manifest() if item["name"] == family)
            self.assertEqual(spec["size"], FONT_FILES[family].stat().st_size)
            self.assertIn("gradio_api/file=", spec["url"])
            self.assertIn(f'"{family}"', DEFAULT_FONT_STACK)
            self.assertIn(family, FONT_PRELOAD_JS)


    def test_cli_paths_override_config_and_missing_paths_use_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            config=root/'config.json'
            config.write_text(json.dumps({
                'paths': {'output_json': 'source.json'},
                'gradio': {'image_dir': 'images', 'output_dir': 'annotations'},
                'records': {'content': {
                    'start_heading': 'Nguyên văn chữ Hán Nôm',
                    'section_headings': ['Nguyên văn chữ Hán Nôm'],
                }},
            }))
            override=root/'override-images'
            options=parser().parse_args([
                '--config',str(config),'--image-dir',str(override),
            ])
            resolve_app_paths(options)
            self.assertEqual(options.image_dir,str(override))
            self.assertEqual(options.source_json,str(root/'source.json'))
            self.assertEqual(options.output_dir,str(root/'annotations'))

            missing=root/'missing.json'
            explicit=parser().parse_args([
                '--config',str(missing),'--image-dir','images',
                '--source-json','source.json','--output-dir','annotations',
            ])
            with self.assertRaisesRegex(ValueError, 'Cannot read app config'):
                resolve_app_paths(explicit)


    def test_cli_lets_gradio_choose_an_available_port_by_default(self):
        self.assertIsNone(parser().parse_args([]).port)
        self.assertEqual(parser().parse_args(['--port','7861']).port,7861)


    def current_app(self,root,text,skip_detection=True):
        image=root/'1.png';Image.new('RGB',(100,100),'white').save(image)
        source=root/'source.json'
        atomic_write(source,[{'noi_dung':[{'ky_hieu':'1','chuyen_muc':[
            {'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':text}]}]}])
        args=['--image-dir',str(root),'--source-json',str(source),'--output-dir',str(root/'out')]
        if skip_detection: args.append('--skip-detection')
        app=create_app(parser().parse_args(args))
        self.app=app
        cb={f.fn.__name__:f.fn for f in app.fns.values() if f.fn}
        cb.update(save=cb['save_image'],undo=cb['undo_content'],back=cb['go_back'])
        opened=cb['open_image'](cb['restore_session']('{}').session,str(image))
        cb['advance']=lambda ctx,draft=None,**kw:list(cb['next_with_progress'](ctx,draft,**kw))[-1]
        return cb,opened,image

    def test_only_current_controls_and_handlers_are_registered(self):
        with tempfile.TemporaryDirectory() as folder:
            cb,opened,_=self.current_app(Path(folder).resolve(),'甲乙')
            self.assertNotIn('on_action',cb)
            self.assertNotIn('apply_status_changes',cb)
            self.assertNotIn('run_detection',cb)
            callback=next(f for f in self.app.fns.values() if f.fn and f.fn.__name__=='open_image')
            self.assertEqual(len(opened),len(callback.outputs))
            self.assertNotIn('status_id',opened._fields)
            advanced=cb['advance'](opened.session,opened.content_bridge)
            self.assertEqual(advanced.session['active']['current_step'],3)
            self.assertTrue(advanced.workspace_board['visible'])
            self.assertFalse(advanced.board['visible'])
            self.assertFalse(advanced.control_panel['visible'])

    def test_framework_postprocess_accepts_named_callback_outputs(self):
        import asyncio
        from gradio.state_holder import SessionState
        with tempfile.TemporaryDirectory() as folder:
            _,opened,_=self.current_app(Path(folder).resolve(),'甲乙')
            callback=next(f for f in self.app.fns.values() if f.fn and f.fn.__name__=='open_image')
            processed=asyncio.run(self.app.postprocess_data(callback,opened,SessionState(self.app)))
            self.assertEqual(len(processed),len(callback.outputs))
            ids={c['props'].get('elem_id') for c in self.app.get_config_file()['components']}
            self.assertTrue({'unified-annotation','annotation-board'}<=ids)
            self.assertFalse({'status-radio','suspicious-toggle','sort-boxes','manual-box-order'} & ids)

    def test_content_verification_submits_drafts_without_mutating_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();cb,opened,_=self.current_app(root,'永')
            source=(root/'source.json').read_bytes()
            draft=json.loads(opened.content_bridge)
            entry=next(e for e in draft.values() if e['title']=='Nguyên văn chữ Hán Nôm')
            entry['value']='甲乙'
            advanced=cb['advance'](opened.session,json.dumps(draft,ensure_ascii=False))
            self.assertEqual(advanced.session['active']['annotation_text'],'甲乙')
            self.assertEqual((root/'source.json').read_bytes(),source)
            invalid=cb['advance'](opened.session,'{}')
            self.assertEqual(invalid.session['active']['current_step'],2)
            self.assertEqual(invalid.field,gr.skip())
            self.assertEqual(invalid.field_value,gr.skip())

    def test_image_navigation_does_not_restore_transient_picker_as_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            cb,opened,image=self.current_app(Path(folder).resolve(),'甲')
            ctx=opened.session
            for _ in range(3):
                ctx=cb['back'](ctx).session
                self.assertEqual(ctx['active']['current_step'],1)
                ctx=cb['open_image'](ctx,str(image)).session
                self.assertEqual(ctx['active']['current_step'],2)
                self.assertNotIn(str(image),ctx['drafts'])


if __name__=='__main__': unittest.main()
