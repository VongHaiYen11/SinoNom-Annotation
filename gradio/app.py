"""CLI entrypoint; UI composition lives in ui.application."""
import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gradio as gr
from annotation.io import read_json
from annotation.text_extraction import normalize_content_titles
from ui.application import build_app, FONT_PRELOAD_JS
from ui.presentation import APP_CSS
REPO_ROOT = Path(__file__).resolve().parents[1]

def _config_relative(config_path, value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Config field {field} must be a non-empty path string.')
    path = Path(value).expanduser()
    return str(path.resolve() if path.is_absolute() else (config_path.parent / path).resolve())


def resolve_app_paths(options):
    """Fill omitted CLI paths from config while preserving CLI precedence."""
    paths_complete = all(
        getattr(options, name, None) for name in ('image_dir', 'source_json', 'output_dir'))
    config_path = Path(options.config).expanduser().resolve()
    try:
        config = read_json(config_path)
    except OSError as exc:
        raise ValueError(f'Cannot read app config {config_path}: {exc}') from exc
    if not isinstance(config, dict):
        raise ValueError('App config must be a JSON object.')
    paths = config.get('paths', {})
    gradio_paths = config.get('gradio', {})
    if (not paths_complete and
            (not isinstance(paths, dict) or not isinstance(gradio_paths, dict))):
        raise ValueError("Config must contain 'paths' and 'gradio' objects.")
    records_config = config.get('records', {})
    if not isinstance(records_config, dict):
        raise ValueError("Config field 'records' must be an object.")
    content_config = records_config.get('content', {})
    if not isinstance(content_config, dict):
        raise ValueError("Config field 'records.content' must be an object.")
    options.content_titles = normalize_content_titles(
        content_config.get('section_headings'))
    metadata_config = records_config.get('metadata', [])
    if not isinstance(metadata_config, list):
        raise ValueError("Config field 'records.metadata' must be an array.")
    show_metadata_fields = gradio_paths.get('show_metadata_fields', True)
    if not isinstance(show_metadata_fields, bool):
        raise ValueError("Config field 'gradio.show_metadata_fields' must be boolean.")
    options.metadata_fields = tuple(
        (item.get('label'), item.get('field'))
        for item in metadata_config
        if (show_metadata_fields and isinstance(item, dict)
            and item.get('type') == 'string')
    )
    options.annotation_title = content_config.get('start_heading')
    if (not isinstance(options.annotation_title, str) or
            not options.annotation_title.strip()):
        raise ValueError('Config field records.content.start_heading must be a non-empty string.')
    if options.annotation_title not in options.content_titles:
        raise ValueError('Config start_heading must also appear in section_headings.')
    if not options.image_dir:
        options.image_dir = _config_relative(config_path, gradio_paths.get('image_dir'), 'gradio.image_dir')
    if not options.source_json:
        options.source_json = _config_relative(config_path, paths.get('output_json'), 'paths.output_json')
    if not options.output_dir:
        options.output_dir = _config_relative(config_path, gradio_paths.get('output_dir'), 'gradio.output_dir')
    return options


def parser():
    p=argparse.ArgumentParser(description='Vietnamica character annotation workflow')
    p.add_argument('--config', default=str(REPO_ROOT / 'helpers/configs/tap_1.json'),
                   help='Config used for omitted image/source/output paths.')
    p.add_argument('--image-dir', default=None,
                   help='Override config gradio.image_dir.')
    p.add_argument('--source-json', default=None,
                   help='Override config paths.output_json.')
    p.add_argument('--output-dir', default=None,
                   help='Override config gradio.output_dir.')
    p.add_argument('--skip-detection', action='store_true',
                   help='Disable detection; load existing annotations or draw boxes manually.')
    p.add_argument('--vague-det-config', default=str(REPO_ROOT / 'text_detection/models/ckpts/damage_detect.py'))
    p.add_argument('--vague-det-weights', default=str(REPO_ROOT / 'text_detection/models/ckpts/damage_detect.pth'))
    p.add_argument('--ocr-det-executable', default=str(REPO_ROOT / 'text_detection/models/dists/det_model/det_model'))
    p.add_argument('--det-batch-size', type=int, default=1)
    p.add_argument('--img-size', type=int, default=2048)
    p.add_argument('--conf-thres', type=float, default=.45)
    p.add_argument('--iou-thres', type=float, default=.2)
    p.add_argument('--show-detection-logs', action='store_true',
                   help='Show stdout/stderr from the packaged OCR detector process.')
    p.add_argument('--port', type=int, default=None,
                   help='Server port. When omitted, Gradio selects the first available port.')
    p.add_argument('--server-name', default='127.0.0.1')
    p.add_argument('--share', action='store_true', help='Create a public Gradio link.')
    return p


def create_app(options):
    return build_app(resolve_app_paths(options))


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    args=parser().parse_args()
    create_app(args).queue().launch(server_name=args.server_name,server_port=args.port,share=args.share,css=APP_CSS,
        theme=gr.themes.Base(font=['Arial', 'sans-serif'], font_mono=['monospace']), footer_links=[],
        allowed_paths=[str(Path(args.image_dir).resolve())])
