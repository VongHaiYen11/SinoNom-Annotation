def detect(image_path, options):
    from pathlib import Path
    from text_detection import run_stage1
    from text_detection.main import build_detection_document
    return build_detection_document(Path(image_path), run_stage1(str(image_path), options))
