"""Bundled web-font fallback for Han/Nom text."""
from pathlib import Path
from urllib.parse import quote

FONT_DIR = Path(__file__).resolve().parents[2] / 'fonts'
FONT_FILES = {
    'Vietnamica NomNaTong': FONT_DIR / 'NomNaTong.ttf',
    'Vietnamica DengXian': FONT_DIR / 'DengXian.ttf',
}
# Limit these faces to CJK so Vietnamese/Latin labels keep the UI font.
CJK_RANGE = ('U+2E80-2FFF,U+3000-303F,U+3100-312F,U+31A0-31EF,'
             'U+3400-4DBF,U+4E00-9FFF,U+F900-FAFF,U+FE30-FE4F,'
             'U+16FE0-18DFF,U+20000-323AF')
DEFAULT_FONT_STACK = '"Vietnamica NomNaTong", "Vietnamica DengXian"'
FONT_CSS = '\n'.join(
    f'''@font-face {{
      font-family: "{family}";
      src: url("gradio_api/file={quote(str(path), safe='/')}") format("truetype");
      font-weight: 400; font-style: normal; font-display: swap;
      unicode-range: {CJK_RANGE};
    }}'''
    for family, path in FONT_FILES.items()
)
FONT_CSS += f'\n.gradio-container {{ --han-nom-font: {DEFAULT_FONT_STACK}; }}\n'
