import unittest
from pathlib import Path

from pdf_image_extractor.character_annotations import default_detector_executable, detection_payload


class _Detection:
    bbox_xyxy = (1, 2, 3, 4)
    confidence = 0.9
    corners = ((1, 2), (3, 2), (3, 4), (1, 4))


class _Result:
    image_size = (100, 200)
    detections = [_Detection()]


class CharacterAnnotationAdapterTests(unittest.TestCase):
    def test_converts_public_detector_result_to_local_schema(self):
        payload = detection_payload("page.jpg", _Result())
        self.assertEqual((100, 200), (payload["image_width"], payload["image_height"]))
        self.assertEqual([1, 2, 3, 4], payload["detections"][0]["bbox_xyxy"])

    def test_default_model_location_is_repository_local(self):
        self.assertEqual(Path("character_detection/models/det_model"), default_detector_executable().relative_to(Path(__file__).parents[1]))
