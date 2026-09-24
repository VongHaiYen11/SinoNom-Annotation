"""Exercise real Gradio callbacks without requiring a browser or ML assets."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app, parser
from annotation.state import new_state
from annotation.io import atomic_write
from PIL import Image


class GradioCallbacks(unittest.TestCase):
    def test_ui_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();images=root/'images';images.mkdir()
            path=images/'12305.png';Image.new('RGB',(100,100),'white').save(path)
            source=root/'source.json'
            atomic_write(source,[{'noi_dung':[{'ky_hieu':'12305','chuyen_muc':[{'tieu_de':'Nguyên văn chữ Hán Nôm','van_ban':'永寺樂'}]}]}])
            options=parser().parse_args(['--image-dir',str(images),'--source-json',str(source),'--output-dir',str(root/'out')])
            app=create_app(options)
            functions=[f.fn for f in app.fns.values() if f.fn]
            open_image=next(f for f in functions if f.__name__=='open_image')
            result=open_image(dict(active=new_state(),drafts={}),str(path))
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],2)
            lambdas=[f for f in functions if f.__name__=='<lambda>']
            def action(name):
                return next(f for f in lambdas if f.__defaults__==(name,))
            ctx=action('save_content')(ctx)[0]
            self.assertTrue(ctx['active']['workflow']['content_verified'])
            with self.assertLogs('app',level='ERROR'), patch('annotation.workflow.detect',side_effect=RuntimeError('fixture model unavailable')):
                result=action('next')(ctx)
            ctx=result[0];self.assertEqual(ctx['active']['current_step'],3)
            self.assertIn('fixture model unavailable',result[2])
            add=action('add')
            for x in (0,20,40):ctx=add(ctx,None,x,0,x+10,10)[0]
            for _ in range(3):ctx=action('next')(ctx)[0]
            self.assertEqual(ctx['active']['current_step'],6)
            ctx=action('next')(ctx)[0]
            self.assertEqual(ctx['active']['current_step'],7)
            ctx=action('save')(ctx)[0]
            self.assertTrue(ctx['active']['saved'])
            self.assertTrue((root/'out/12305.json').exists())
            ctx=action('next')(ctx)[0]
            self.assertEqual(ctx['active']['current_step'],8)
            # Session switching must preserve drafts, while reset reloads saved data.
            restored=open_image(ctx,str(path))[0]
            self.assertEqual(restored['active']['current_step'],8)
            reset=open_image(ctx,str(path),True)[0]
            self.assertEqual(reset['active']['current_step'],2)
            self.assertEqual(reset['active']['annotations'],{'1':'永','2':'寺','3':'樂'})


if __name__=='__main__':unittest.main()
