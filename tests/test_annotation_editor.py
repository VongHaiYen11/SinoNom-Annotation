import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pdf_image_extractor.annotation_editor import apply_pending, current_record, load_annotation, move_to_image, save_annotation, save_current_annotation


class AnnotationEditorTests(unittest.TestCase):
    def test_save_overwrites_boxes_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "page.jpg"
            Image.new("RGB", (100, 200), "white").save(image_path)
            annotation_path = root / "page.characters.json"
            annotation_path.write_text(json.dumps({
                "source_image": str(image_path),
                "reading_order": "autohdr_coordinate_heuristic",
                "custom_metadata": "preserved",
                "detections": [{"bbox_xyxy": [1, 2, 10, 20], "confidence": 0.9}],
            }), encoding="utf-8")
            session = load_annotation(annotation_path)
            session = apply_pending(session, [{"bbox_xyxy": [-2, 3, 110, 300], "confidence": None, "annotation_source": "manual"}])
            save_annotation(session)
            saved = json.loads(annotation_path.read_text(encoding="utf-8"))
            self.assertEqual("preserved", saved["custom_metadata"])
            self.assertEqual([0, 3, 100, 200], saved["detections"][0]["bbox_xyxy"])
            self.assertEqual([[0, 3], [100, 3], [100, 200], [0, 200]], saved["detections"][0]["corners"])

    def test_collection_navigation_keeps_pending_edits_until_one_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("one.jpg", "two.jpg"):
                Image.new("RGB", (100, 200), "white").save(root / name)
            annotation_path = root / "character_annotations.json"
            annotation_path.write_text(json.dumps({
                "annotation_type": "character_detection_collection",
                "images": [
                    {"image_name": "one.jpg", "image_path": "one.jpg", "detections": [{"bbox_xyxy": [1, 2, 10, 20]}]},
                    {"image_name": "two.jpg", "image_path": "two.jpg", "detections": []},
                ],
            }), encoding="utf-8")
            session = load_annotation(annotation_path)
            session = apply_pending(session, [{"bbox_xyxy": [3, 4, 11, 21]}])
            session = move_to_image(session, 1)
            self.assertEqual("two.jpg", current_record(session)["image_name"])
            save_annotation(session)
            saved = json.loads(annotation_path.read_text(encoding="utf-8"))
            self.assertEqual([3, 4, 11, 21], saved["images"][0]["detections"][0]["bbox_xyxy"])
            self.assertNotIn("_resolved_image_path", saved["images"][0])

    def test_save_current_does_not_write_other_pending_image_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("one.jpg", "two.jpg"):
                Image.new("RGB", (100, 200), "white").save(root / name)
            annotation_path = root / "character_annotations.json"
            annotation_path.write_text(json.dumps({"images": [
                {"image_name": "one.jpg", "image_path": "one.jpg", "detections": [{"bbox_xyxy": [1, 1, 10, 10]}]},
                {"image_name": "two.jpg", "image_path": "two.jpg", "detections": [{"bbox_xyxy": [2, 2, 20, 20]}]},
            ]}), encoding="utf-8")
            session = apply_pending(load_annotation(annotation_path), [{"bbox_xyxy": [3, 3, 30, 30]}])
            session = move_to_image(session, 1)
            session = apply_pending(session, [{"bbox_xyxy": [4, 4, 40, 40]}])
            save_current_annotation(session)
            saved = json.loads(annotation_path.read_text(encoding="utf-8"))
            self.assertEqual([1, 1, 10, 10], saved["images"][0]["detections"][0]["bbox_xyxy"])
            self.assertEqual([4, 4, 40, 40], saved["images"][1]["detections"][0]["bbox_xyxy"])
