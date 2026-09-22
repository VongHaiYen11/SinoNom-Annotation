"""Shared visual language for the local Gradio annotation workspaces."""

import gradio as gr


WORKSPACE_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.orange,
    neutral_hue=gr.themes.colors.zinc,
    radius_size=gr.themes.sizes.radius_sm,
).set(
    body_background_fill="#0b0b0c",
    body_background_fill_dark="#0b0b0c",
    body_text_color="#f4f4f5",
    body_text_color_dark="#f4f4f5",
    body_text_color_subdued="#a1a1aa",
    body_text_color_subdued_dark="#a1a1aa",
    background_fill_primary="#151516",
    background_fill_primary_dark="#151516",
    background_fill_secondary="#0b0b0c",
    background_fill_secondary_dark="#0b0b0c",
    block_background_fill="#151516",
    block_background_fill_dark="#151516",
    block_border_color="#303034",
    block_border_color_dark="#303034",
    block_label_background_fill="#151516",
    block_label_background_fill_dark="#151516",
    block_label_text_color="#a1a1aa",
    block_label_text_color_dark="#a1a1aa",
    input_background_fill="#232325",
    input_background_fill_dark="#232325",
    input_background_fill_focus="#232325",
    input_background_fill_focus_dark="#232325",
    input_border_color="#4a4a50",
    input_border_color_dark="#4a4a50",
    input_border_color_focus="#f97316",
    input_border_color_focus_dark="#f97316",
    input_placeholder_color="#a1a1aa",
    input_placeholder_color_dark="#a1a1aa",
    button_primary_background_fill="#f97316",
    button_primary_background_fill_dark="#f97316",
    button_primary_background_fill_hover="#ea580c",
    button_primary_background_fill_hover_dark="#ea580c",
    button_primary_border_color="#f97316",
    button_primary_border_color_dark="#f97316",
    button_primary_text_color="#17120d",
    button_primary_text_color_dark="#17120d",
    button_secondary_background_fill="#232325",
    button_secondary_background_fill_dark="#232325",
    button_secondary_background_fill_hover="#303033",
    button_secondary_background_fill_hover_dark="#303033",
    button_secondary_border_color="#4a4a50",
    button_secondary_border_color_dark="#4a4a50",
    button_secondary_text_color="#f4f4f5",
    button_secondary_text_color_dark="#f4f4f5",
    code_background_fill="#232325",
    code_background_fill_dark="#232325",
    link_text_color="#fdba74",
    link_text_color_dark="#fdba74",
    accordion_text_color="#f4f4f5",
    accordion_text_color_dark="#f4f4f5",
    slider_color="#f97316",
    slider_color_dark="#f97316",
    error_background_fill="#321517",
    error_background_fill_dark="#321517",
    error_text_color="#fecaca",
    error_text_color_dark="#fecaca",
)

WORKSPACE_CSS = """
:root {
  --app-bg: #0b0b0c;
  --panel-bg: #151516;
  --canvas-bg: #0f0f10;
  --control-bg: #232325;
  --control-hover: #303033;
  --border: #303034;
  --border-strong: #4a4a50;
  --text: #f4f4f5;
  --muted: #a1a1aa;
  --accent: #f97316;
  --accent-strong: #ea580c;
  --accent-text: #17120d;
  --success: #86efac;
  --danger: #fca5a5;
  --radius: 4px;
  --panel-gap: 12px;
}

body { background: var(--app-bg) !important; color: var(--text) !important; }
.gradio-container {
  max-width: 1680px !important;
  min-height: 100vh !important;
  margin: 0 auto !important;
  padding: 16px 20px 24px !important;
  background: var(--app-bg) !important;
  color: var(--text) !important;
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.workspace-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 0 0 14px; margin-bottom: 14px; border-bottom: 1px solid var(--border);
}
.workspace-title { font-size: 17px; font-weight: 700; color: var(--text); line-height: 1.25; letter-spacing: -.01em; }
.workspace-subtitle { margin-top: 3px; color: var(--muted); font-size: 12px; line-height: 1.35; }
.workspace-badge { white-space: nowrap; padding: 5px 8px; border: 1px solid var(--border-strong); border-radius: 999px; color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.workspace-grid { gap: var(--panel-gap) !important; align-items: stretch !important; }
.workspace-sidebar, .workspace-inspector, .workspace-canvas {
  min-width: 0; background: var(--panel-bg); border: 1px solid var(--border); border-radius: var(--radius);
}
.workspace-sidebar, .workspace-inspector { padding: 14px !important; }
.workspace-canvas { padding: 14px !important; }
.workspace-section { margin: 0 0 14px !important; padding: 0 0 14px !important; border-bottom: 1px solid var(--border); }
.workspace-section:last-child { margin-bottom: 0 !important; padding-bottom: 0 !important; border-bottom: 0; }
.section-kicker { margin: 0 0 8px; color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.status-panel { font-size: 13px; line-height: 1.55; }
.status-panel h3, .workspace-inspector h3 { margin: 0 0 8px; color: var(--text); font-size: 13px; line-height: 1.35; }
.status-panel p { margin: 0; color: var(--text); }
.gradio-container .prose, .gradio-container .prose p, .gradio-container .prose li, .gradio-container .prose strong { color: inherit; }
.gradio-container label > span, .gradio-container .block-label { color: var(--muted) !important; font-size: 12px !important; font-weight: 600 !important; }
.gradio-container input, .gradio-container textarea, .gradio-container button, .gradio-container .wrap { border-radius: var(--radius) !important; }
.gradio-container input, .gradio-container textarea, .gradio-container .wrap, .gradio-container .input-container {
  background: var(--control-bg) !important; color: var(--text) !important; border-color: var(--border-strong) !important; box-shadow: none !important;
}
.gradio-container input::placeholder, .gradio-container textarea::placeholder { color: var(--muted) !important; opacity: .8; }
.gradio-container input:focus, .gradio-container textarea:focus, .gradio-container .wrap:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 2px rgb(249 115 22 / 20%) !important; }
.gradio-container input[type="range"] { accent-color: var(--accent); }
.gradio-container button { min-height: 36px !important; background: var(--control-bg) !important; color: var(--text) !important; border-color: var(--border-strong) !important; box-shadow: none !important; font-size: 13px !important; font-weight: 600 !important; }
.gradio-container button:hover:not(:disabled) { background: var(--control-hover) !important; border-color: #64646b !important; }
.gradio-container button.primary { background: var(--accent) !important; color: var(--accent-text) !important; border-color: var(--accent) !important; }
.gradio-container button.primary:hover:not(:disabled) { background: var(--accent-strong) !important; border-color: var(--accent-strong) !important; }
.gradio-container button:disabled { background: #1b1b1d !important; color: #6b6b73 !important; border-color: #2d2d31 !important; opacity: 1 !important; }
.gradio-container .accordion { background: var(--panel-bg) !important; border-color: var(--border) !important; border-radius: var(--radius) !important; box-shadow: none !important; }
.gradio-container .accordion .label-wrap { color: var(--text) !important; font-size: 12px !important; font-weight: 650 !important; }
.gradio-container .prose { color: var(--muted); font-size: 12px; }
.gradio-container .prose p { line-height: 1.55; }
.gradio-container .wrap-inner, .gradio-container .options, .gradio-container [role="listbox"], .gradio-container [role="option"] { background: var(--control-bg) !important; color: var(--text) !important; }
.gradio-container [role="option"]:hover, .gradio-container [role="option"][aria-selected="true"] { background: var(--control-hover) !important; }
.gradio-container .icon-button, .gradio-container button.secondary { color: var(--text) !important; }
.workspace-canvas .image-container { background: var(--canvas-bg) !important; border: 1px solid var(--border) !important; border-radius: var(--radius) !important; }
.workspace-canvas .image-container button { background: #202022 !important; color: var(--text) !important; }
@media (max-width: 900px) {
  .gradio-container { padding: 12px !important; }
  .workspace-grid { flex-direction: column !important; }
  .workspace-sidebar, .workspace-inspector { width: 100% !important; }
  .workspace-canvas { order: -1; }
}
@media (max-width: 560px) {
  .workspace-header { align-items: flex-start; flex-direction: column; gap: 8px; }
  .workspace-badge { white-space: normal; }
}
"""
