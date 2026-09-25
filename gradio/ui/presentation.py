"""Read-only workbench presentation; workflow decisions stay in annotation/."""
import html
from pathlib import Path
from annotation.text_alignment import count_annotation_characters
from .fonts import FONT_CSS

APP_CSS = FONT_CSS + (Path(__file__).parent / 'assets/workbench.css').read_text()
LABELS = ('Image', 'Content', 'Bounding Boxes', 'Status', 'Reading Order', 'Crop', 'Review')
SECTION_LABELS = {
    'Nguyên văn chữ Hán Nôm': 'Original Han/Nom text',
    'Phiên âm Hán Việt': 'Sino-Vietnamese transcription',
    'Dịch nghĩa': 'Translation', 'Toát yếu': 'Summary', 'Chú thích': 'Notes',
}


def header(state):
    step = state['current_step']; workflow = state['workflow']
    complete = [bool(state['image']), workflow['content_verified'],
                workflow['content_verified'] and workflow['bbox_valid'] and workflow['alignment_valid'],
                workflow['content_verified'] and workflow['status_valid'],
                workflow['content_verified'] and workflow['reading_order_valid'],
                state['crop_saved'], state['saved']]
    filename = html.escape(state['image'] or 'No image selected')
    status = 'Saved' if state['saved'] else 'Draft'
    steps = []
    for index, label in enumerate(LABELS, 1):
        active = index == step; done = complete[index - 1]
        cls = ' is-active' if active else ' is-complete' if done else ''
        current = ' aria-current="step"' if active else ''
        mark = '✓' if done and not active else str(index)
        steps.append(f'<li class="stepper-item{cls}"{current}><span class="stepper-dot">{mark}</span>{label}</li>')
    return f'''<header class="app-header">
      <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">▧</span>
        <div><h1>Sino-Nôm Annotation Tool</h1><div class="file-name"><span class="file-dot"></span>{filename}</div></div></div>
      <div class="save-indicator">{'✓' if state['saved'] else '○'} {status}</div>
    </header><nav aria-label="Annotation workflow"><ol class="stepper">{''.join(steps)}</ol></nav>'''


def panel_heading(state):
    return f'<div class="panel-heading"><h2>{LABELS[state["current_step"]-1]}</h2></div>'


def panel_summary(state):
    if state['current_step'] not in (3, 7):
        return ''
    boxes = state['bounding_boxes']; count = count_annotation_characters(state['annotation_text'])
    matched = state['workflow']['content_verified'] and len(boxes) == count and count > 0
    label = 'Counts match' if matched else 'Content not verified' if not state['workflow']['content_verified'] else 'Count mismatch'
    return f'''<section class="section panel-summary"><h3>Validation</h3>
      <div class="validation-badge">{'✓' if matched else '!'} {label}</div>
      <dl><div><dt>Bounding boxes</dt><dd>{len(boxes)}</dd></div>
      <div><dt>Characters</dt><dd>{count}</dd></div></dl></section>'''


def status_rows(state):
    return [[key, box['status']] for key, box in state['bounding_boxes'].items()]


def footer(state):
    step = state['current_step']
    return f'<div class="footer-step-label">{LABELS[step-1]} <span>/</span> {step} of 7</div>'
