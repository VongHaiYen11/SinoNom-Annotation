"""Shared visual language for the local Gradio annotation workspaces."""

WORKSPACE_CSS = """
:root {
  --app-bg: #f4f6f8;
  --panel-bg: #ffffff;
  --canvas-bg: #171b22;
  --border: #d9dee7;
  --border-strong: #b9c3d0;
  --text: #18212f;
  --muted: #657185;
  --accent: #2367d1;
  --accent-strong: #174da4;
  --success: #18794e;
  --danger: #c23b43;
  --radius: 6px;
  --panel-gap: 12px;
}

.gradio-container {
  max-width: 1680px !important;
  margin: 0 auto !important;
  padding: 16px 20px 24px !important;
  background: var(--app-bg) !important;
  color: var(--text) !important;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.workspace-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 0 0 14px; margin-bottom: 14px; border-bottom: 1px solid var(--border);
}
.workspace-title { font-size: 17px; font-weight: 700; color: var(--text); line-height: 1.25; }
.workspace-subtitle { margin-top: 3px; color: var(--muted); font-size: 12px; line-height: 1.35; }
.workspace-badge { white-space: nowrap; padding: 5px 8px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.workspace-grid { gap: var(--panel-gap) !important; align-items: stretch !important; }
.workspace-sidebar, .workspace-inspector, .workspace-canvas {
  min-width: 0; background: var(--panel-bg); border: 1px solid var(--border); border-radius: var(--radius);
}
.workspace-sidebar, .workspace-inspector { padding: 14px !important; }
.workspace-canvas { padding: 14px !important; }
.workspace-section { margin: 0 0 14px !important; padding: 0 0 14px !important; border-bottom: 1px solid #edf0f4; }
.workspace-section:last-child { margin-bottom: 0 !important; padding-bottom: 0 !important; border-bottom: 0; }
.section-kicker { margin: 0 0 8px; color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.status-panel { font-size: 13px; line-height: 1.55; }
.status-panel h3, .workspace-inspector h3 { margin: 0 0 8px; color: var(--text); font-size: 13px; line-height: 1.35; }
.status-panel p { margin: 0; }
.gradio-container label > span, .gradio-container .block-label { color: #4d5a6d !important; font-size: 12px !important; font-weight: 600 !important; }
.gradio-container input, .gradio-container textarea, .gradio-container button, .gradio-container .wrap { border-radius: var(--radius) !important; }
.gradio-container input, .gradio-container textarea, .gradio-container .wrap { border-color: var(--border-strong) !important; box-shadow: none !important; }
.gradio-container input:focus, .gradio-container textarea:focus, .gradio-container .wrap:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 2px rgb(35 103 209 / 14%) !important; }
.gradio-container button { min-height: 36px !important; border-color: var(--border-strong) !important; box-shadow: none !important; font-size: 13px !important; font-weight: 600 !important; }
.gradio-container button.primary { background: var(--accent) !important; border-color: var(--accent) !important; }
.gradio-container button.primary:hover { background: var(--accent-strong) !important; border-color: var(--accent-strong) !important; }
.gradio-container .accordion { border-color: var(--border) !important; border-radius: var(--radius) !important; box-shadow: none !important; }
.gradio-container .accordion .label-wrap { font-size: 12px !important; font-weight: 650 !important; }
.gradio-container .prose { color: var(--muted); font-size: 12px; }
.gradio-container .prose p { line-height: 1.55; }
.workspace-canvas .image-container { background: #f9fafb !important; border: 1px solid var(--border) !important; border-radius: var(--radius) !important; }
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
