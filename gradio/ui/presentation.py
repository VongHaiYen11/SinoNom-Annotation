"""Read-only workbench presentation; workflow decisions stay in annotation/."""
import html
from pathlib import Path
from .fonts import FONT_CSS
from .icons import CHECK

APP_CSS = FONT_CSS + (Path(__file__).parent / 'assets/workbench.css').read_text()
SECTION_LABELS = {
    title: title for title in ('Nguyên văn chữ Hán Nôm', 'Phiên âm Hán Việt',
                              'Dịch nghĩa', 'Toát yếu', 'Chú thích',
                              'Tên bia', 'Địa điểm', 'Niên đại')
}
UNIFIED_LABELS = ('Content Verification', 'Annotation Workspace', 'Crop', 'Review & Save')


def steps_for(state):
    return UNIFIED_LABELS, {1:1,2:1,3:2,4:2,5:2,6:3,7:4}[state['current_step']]


def app_identity(state):
    filename = html.escape(state['image'] or 'No image selected')
    return f'''<header class="app-header">
      <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">文</span>
        <div><h1>Sino-Nôm Annotation Tool</h1><div class="file-name">{filename}</div></div></div>
    </header>'''


def workflow_progress(state):
    labels, step = steps_for(state)
    steps = []
    for index, label in enumerate(labels, 1):
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
    labels, step = steps_for(state)
    return f'''<div class="panel-heading">
      <span class="panel-eyebrow">Inspector</span>
      <h2>{labels[step-1]}</h2>
    </div>'''


def footer(state):
    labels, step = steps_for(state)
    return f'<div class="footer-step-label">{labels[step-1]} <span>/</span> {step} of {len(labels)}</div>'
