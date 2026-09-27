"""Read-only full-image modal, independent of annotation canvas gestures."""
from pathlib import Path

SCRIPT = (Path(__file__).parent / 'assets/image_preview.js').read_text()
CSS = '''
.preview-open { width:100%; min-height:var(--button-height,40px); padding:8px 12px; border:1px solid #42454c; border-radius:var(--radius-sm,4px);
background:#17191c; color:#f4f4f5; cursor:pointer; }
.preview-dialog { display:none; flex-direction:column; gap:16px; width:min(92vw,var(--page-max-width,1600px)); height:90dvh; max-width:none; max-height:94dvh;
padding:16px; border:1px solid #42454c; border-radius:var(--radius-md,8px); background:#17191c; color:#f4f4f5; }
.preview-dialog[open] { display:flex; }
.preview-dialog::backdrop { background:#000b; }
.preview-dialog header { display:flex; justify-content:space-between; align-items:center; }
.preview-dialog button { min-height:var(--button-height,40px); padding:8px 16px; cursor:pointer; }
.preview-dialog img { display:block; flex:1 1 auto; width:100%; min-height:0; object-fit:contain; }
'''
MARKUP = '''<button type="button" class="preview-open">Preview image</button>
<dialog class="preview-dialog" aria-label="Image preview">
<header><strong>Image preview</strong><button type="button" class="preview-close">Close</button></header>
<img alt="Selected inscription" />
</dialog>'''
