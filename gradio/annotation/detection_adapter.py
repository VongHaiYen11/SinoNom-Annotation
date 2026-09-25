def detect(image_path, options):
    from pathlib import Path
    from text_detection import run_detection_pipeline
    from text_detection.main import build_detection_document
    return build_detection_document(Path(image_path), run_detection_pipeline(str(image_path), options))
