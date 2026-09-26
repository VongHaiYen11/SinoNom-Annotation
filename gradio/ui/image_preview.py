"""Read-only full-image modal, independent of annotation canvas gestures."""
from pathlib import Path

SCRIPT = (Path(__file__).parent / 'assets/image_preview.js').read_text()
CSS = '''
.preview-open { width:100%; padding:10px; border:1px solid #42454c; border-radius:5px;
background:#17191c; color:#f4f4f5; cursor:pointer; }
.preview-dialog { width:92vw; height:90dvh; max-width:none; max-height:94dvh;
padding:16px; border:1px solid #42454c; border-radius:8px; background:#17191c; color:#f4f4f5; }
.preview-dialog::backdrop { background:#000b; }
.preview-dialog header { display:flex; justify-content:space-between; align-items:center; }
.preview-dialog button { padding:8px 16px; cursor:pointer; }
.preview-dialog img { display:block; width:100%; height:calc(100% - 48px); object-fit:contain; margin-top:12px; }
'''
MARKUP = '''<button type="button" class="preview-open">Preview image</button>
<dialog class="preview-dialog" aria-label="Image preview">
<header><strong>Image preview</strong><button type="button" class="preview-close">Close</button></header>
<img alt="Selected inscription" />
</dialog>'''
