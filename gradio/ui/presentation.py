"""Read-only workbench presentation; workflow decisions stay in annotation/."""
import html
from pathlib import Path
from annotation.text_alignment import count_annotation_characters
from annotation.state import source_mismatch_confirmed
from .fonts import FONT_CSS
from .icons import ALERT, CHECK

APP_CSS = FONT_CSS + (Path(__file__).parent / 'assets/workbench.css').read_text()
LABELS = ('Image', 'Content', 'Bounding Boxes & Sort', 'Status & Order', 'Crop', 'Review')
SECTION_LABELS = {
    'Nguyên văn chữ Hán Nôm': 'Nguyên văn chữ Hán Nôm',
    'Phiên âm Hán Việt': 'Phiên âm Hán Việt',
    'Dịch nghĩa': 'Dịch nghĩa', 'Toát yếu': 'Toát yếu', 'Chú thích': 'Chú thích',
}


def app_identity(state):
    filename = html.escape(state['image'] or 'No image selected')
    return f'''<header class="app-header">
      <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">文</span>
        <div><h1>Sino-Nôm Annotation Tool</h1><div class="file-name">{filename}</div></div></div>
    </header>'''


def workflow_progress(state):
    step = display_step(state['current_step'])
    steps = []
    for index, label in enumerate(LABELS, 1):
        active = index == step; done = index < step
        cls = ' is-active' if active else ' is-complete' if done else ''
        current = ' aria-current="step"' if active else ''
        mark = CHECK if done and not active else str(index)
        steps.append(f'''<li class="stepper-item{cls}"{current}>
            <span class="stepper-dot">{mark}</span><span class="stepper-label">{label}</span></li>''')
    return f'''<nav aria-label="Annotation workflow">
      <ol class="stepper">{''.join(steps)}</ol>
    </nav>'''


def header(state):
    """Combined markup retained for presentation-level tests and consumers."""
    return app_identity(state) + workflow_progress(state)


def panel_heading(state):
    step = display_step(state['current_step'])
    return f'''<div class="panel-heading">
      <span class="panel-eyebrow">Inspector</span>
      <h2>{LABELS[step-1]}</h2>
    </div>'''


def panel_summary(state):
    if state['current_step'] not in (3, 7):
        return ''
    boxes = (state['regions'] if state['current_step'] == 3 or (
        state['current_step'] == 7 and source_mismatch_confirmed(state)
        and state['source_mismatch']['issue_type'] == 'other') else state['bounding_boxes'])
    count = count_annotation_characters(state['annotation_text'])
    matched = state['workflow']['content_verified'] and len(boxes) == count and count > 0
    confirmed = source_mismatch_confirmed(state)
    label = ('Content not verified' if not state['workflow']['content_verified']
             else 'Confirmed Mismatch' if confirmed
             else 'Counts match' if matched
             else 'Count mismatch')
    delta = len(boxes) - count
    return f'''<section class="section sidebar-section panel-summary"><h3>Validation</h3>
      <div class="validation-badge{' is-count-match' if matched else ''}">{CHECK if matched else ALERT}<span>{label}</span></div>
      <dl><div><dt>Bounding boxes</dt><dd>{len(boxes)}</dd></div>
      <div><dt>Characters</dt><dd>{count}</dd></div>
      <div><dt>Difference (boxes − characters)</dt><dd>{delta:+d}</dd></div></dl></section>'''


def status_rows(state):
    return [[box['status']] for box in state['regions'].values()]


def footer(state):
    step = display_step(state['current_step'])
    return f'<div class="footer-step-label">{LABELS[step-1]} <span>/</span> {step} of 6</div>'


def display_step(step):
    if step <= 4:
        return step
    if step == 6:
        return 5
    if step == 7:
        return 6
    return 4
