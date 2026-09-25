"""Local web fonts and a display-only font switcher for Han/Nom text."""
import json
from pathlib import Path
from urllib.parse import quote

FONT_DIR = Path(__file__).resolve().parents[2] / 'fonts'
FONT_FILES = {
    'Vietnamica NomNaTong': FONT_DIR / 'NomNaTong.ttf',
    'Vietnamica DengXian': FONT_DIR / 'DengXian.ttf',
    'Vietnamica PMingLiU': FONT_DIR / 'PMingLiU.ttf',
    'Vietnamica PMingLiU ExtB': FONT_DIR / 'PMingLiU-ExtB.ttf',
}
# Limit these faces to CJK so Vietnamese/Latin labels keep the UI font.
CJK_RANGE = ('U+2E80-2FFF,U+3000-303F,U+3100-312F,U+31A0-31EF,'
             'U+3400-4DBF,U+4E00-9FFF,U+F900-FAFF,U+FE30-FE4F,'
             'U+16FE0-18DFF,U+20000-323AF')
FONT_STACKS = {
    'NomNaTong': '"Vietnamica NomNaTong", "Vietnamica DengXian", "Vietnamica PMingLiU", "Vietnamica PMingLiU ExtB"',
    'DengXian': '"Vietnamica DengXian", "Vietnamica NomNaTong", "Vietnamica PMingLiU", "Vietnamica PMingLiU ExtB"',
    'PMingLiU': '"Vietnamica PMingLiU", "Vietnamica PMingLiU ExtB", "Vietnamica NomNaTong", "Vietnamica DengXian"',
}
FONT_CSS = '\n'.join(
    f'''@font-face {{
      font-family: "{family}";
      src: url("gradio_api/file={quote(str(path), safe='/')}") format("truetype");
      font-weight: 400; font-style: normal; font-display: swap;
      unicode-range: {CJK_RANGE};
    }}'''
    for family, path in FONT_FILES.items()
)
FONT_CSS += f'\n.gradio-container {{ --han-nom-font: {FONT_STACKS["NomNaTong"]}; }}\n'

FONT_PICKER = '''<div class="font-picker">
    <label for="han-nom-font">Han/Nom font</label>
    <select id="han-nom-font">
      <option value="NomNaTong">NomNaTong</option>
      <option value="DengXian">DengXian</option>
      <option value="PMingLiU">PMingLiU</option>
    </select>
    <p class="font-sample" aria-label="Font sample">永樂寺 · 𨴦 · 喃</p>
  </div>'''

FONT_PICKER_SCRIPT = f'''
const stacks = {json.dumps(FONT_STACKS)};
element.addEventListener('change', event => {{
  const choice = event.target.value;
  if (!Object.prototype.hasOwnProperty.call(stacks, choice)) return;
  // Only presentation changes. Never send annotation actions or replace state.
  element.closest('.gradio-container')?.style.setProperty('--han-nom-font', stacks[choice]);
}});
'''
