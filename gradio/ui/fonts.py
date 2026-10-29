"""Bundled web-font fallback for Han/Nom text."""
import json
from pathlib import Path
from urllib.parse import quote

FONT_DIR = Path(__file__).resolve().parents[2] / 'fonts'
FONT_FILES = {
    'Vietnamica NomNaTong': FONT_DIR / 'NomNaTong.ttf',
    'Vietnamica DengXian': FONT_DIR / 'DengXian.ttf',
    'PMingLiU': FONT_DIR / 'PMingLiU.ttf',
    'PMingLiU-ExtB': FONT_DIR / 'PMingLiU-ExtB.ttf',
}
# Limit these faces to CJK so Vietnamese/Latin labels keep the UI font.
CJK_RANGE = ('U+2E80-2FFF,U+3000-303F,U+3100-312F,U+31A0-31EF,'
             'U+3400-4DBF,U+4E00-9FFF,U+F900-FAFF,U+FE30-FE4F,'
             'U+16FE0-18DFF,U+20000-323AF')
DEFAULT_FONT_STACK = ', '.join(f'"{family}"' for family in FONT_FILES)
# Faces are registered exclusively by the streaming loader (no duplicate CSS fetch).
FONT_CSS = f'\n.gradio-container {{ --han-nom-font: {DEFAULT_FONT_STACK}; }}\n'


def font_manifest():
    """Metadata only; absent files remain retryable HTTP errors in the UI."""
    return [dict(name=family,
                 url=f"gradio_api/file={quote(str(path), safe='/')}",
                 size=path.stat().st_size if path.is_file() else None)
            for family, path in FONT_FILES.items()]


FONT_PRELOAD_JS = "() => (" + (
    Path(__file__).parent / 'assets/font_loader.js').read_text() + ")(" + json.dumps(
        font_manifest(), ensure_ascii=False) + ", " + json.dumps(CJK_RANGE) + ")"
