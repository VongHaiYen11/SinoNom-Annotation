"""Small inline SVG icons with geometry independent of the active font."""


def icon(paths: str, css_class: str = "ui-icon") -> str:
    return (
        f'<svg class="{css_class}" viewBox="0 0 16 16" aria-hidden="true" '
        'focusable="false" fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


CHECK = icon('<path d="m3 8 3 3 7-7"/>')
CIRCLE = icon('<circle cx="8" cy="8" r="5.25"/>')
DOCUMENT = icon('<rect x="3" y="2.5" width="10" height="11" rx="1"/><path d="M5.5 6h5M5.5 8.5h5M5.5 11h3"/>')
WARNING = icon('<path d="M8 2.25 14 13H2L8 2.25Z"/><path d="M8 6v3.25M8 11.5h.01"/>')
ALERT = icon('<circle cx="8" cy="8" r="5.5"/><path d="M8 4.75v4M8 11.25h.01"/>')
ARROW_RIGHT = icon('<path d="M3 8h10M9 4l4 4-4 4"/>', 'ui-icon sequence-arrow')
