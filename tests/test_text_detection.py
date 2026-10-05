from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from text_detection.fusion import (calculate_iou, calculate_smaller_box_coverage,
                                   fuse_localizations)
from text_detection.main import build_detection_document, main
from text_detection.pipeline import (
    _damage_boxes_from_prediction,
    _ocr_boxes_from_detection,
    iter_detection_pipeline,
)
from text_detection.reading_order import sort_recognized_boxes
from text_detection.runtime.det_wrapper import det_model


class _Tensor:
    """Minimal tensor double for testing model-output conversion without Torch."""

    def __init__(self, value):
        self.value = value

    def cpu(self):
        return self

    def numpy(self):
        return self.value


class TextDetectionTests(unittest.TestCase):
    def test_packaged_detector_output_is_suppressed_by_default(self) -> None:
        process = Mock()
        process.poll.return_value = None
        process.pid = 42
        model = det_model('/tmp/det_model')
        with patch('text_detection.runtime.det_wrapper.subprocess.Popen', return_value=process) as popen, \
             patch('text_detection.runtime.det_wrapper.time.sleep'), \
             patch.object(model, '_connect_with_retry', return_value=True):
            model.start()

        popen.assert_called_once_with(
            ['/tmp/det_model', '12345'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        model.cleanup()

    def test_detector_initialization_needs_no_dataset_registration(self) -> None:
        init_detector = Mock(return_value=object())
        modules = {
            'mmdet': SimpleNamespace(),
            'mmdet.apis': SimpleNamespace(
                init_detector=init_detector, inference_detector=Mock(),
            ),
            'cv2': SimpleNamespace(),
            'numpy': SimpleNamespace(),
            'torch': SimpleNamespace(
                cuda=SimpleNamespace(is_available=lambda: False), device=str,
            ),
            'PIL': SimpleNamespace(Image=object()),
        }
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / 'model'
            asset.touch()
            options = SimpleNamespace(
                vague_det_config=asset, vague_det_weights=asset,
                ocr_det_executable=asset,
            )
            with patch.dict('sys.modules', modules):
                detection_run = iter_detection_pipeline('page.png', options)
                self.assertEqual('loading_models', next(detection_run).phase)
                self.assertEqual('preprocessing', next(detection_run).phase)
                detection_run.close()
        init_detector.assert_called_once_with(
            str(asset), str(asset), device='cpu', palette='random',
        )

    @staticmethod
    def _result():
        damage_boxes = [[120, 450, 180, 520]]
        normal_boxes = [[120, 350, 180, 420], [220, 350, 280, 420]]
        return SimpleNamespace(
            damage_boxes=damage_boxes,
            normal_boxes=normal_boxes,
            fused_boxes=damage_boxes + normal_boxes,
            ordered_boxes=[normal_boxes[0], normal_boxes[1], damage_boxes[0]],
            num_normal=2,
            num_damaged=1,
        )

    def test_damage_boxes_replace_overlapping_ocr_boxes(self) -> None:
        damage_boxes = [[11, 11, 29, 29]]
        ocr_boxes = [[10, 10, 30, 30], [40, 10, 50, 30]]

        fused, normal, removed = fuse_localizations(damage_boxes, ocr_boxes)

        self.assertAlmostEqual(calculate_iou(damage_boxes[0], ocr_boxes[0]), 0.81)
        self.assertEqual({0}, removed)
        self.assertEqual([[40, 10, 50, 30]], normal)
        self.assertEqual(damage_boxes + normal, fused)

    def test_contained_damage_box_replaces_loose_ocr_box(self) -> None:
        damage_boxes = [[15, 15, 25, 25]]
        ocr_boxes = [[10, 10, 30, 30], [40, 10, 50, 30]]

        # IoU alone is only 0.25, but the damaged region is fully contained.
        self.assertAlmostEqual(calculate_iou(damage_boxes[0], ocr_boxes[0]), 0.25)
        self.assertAlmostEqual(calculate_smaller_box_coverage(damage_boxes[0], ocr_boxes[0]), 1.0)
        fused, normal, removed = fuse_localizations(damage_boxes, ocr_boxes)

        self.assertEqual({0}, removed)
        self.assertEqual([ocr_boxes[1]], normal)
        self.assertEqual([ocr_boxes[0]] + normal, fused)

    def test_model_outputs_are_normalized_to_integer_xyxy_boxes(self) -> None:
        prediction = SimpleNamespace(
            pred_instances=SimpleNamespace(
                bboxes=_Tensor([[1.2, 2.8, 30.1, 40.7], [5, 6, 7, 8]]),
                scores=_Tensor([0.31, 0.3]),
            )
        )

        self.assertEqual([[1, 3, 30, 41]], _damage_boxes_from_prediction(prediction))
        self.assertEqual(
            [[1, 3, 30, 41]],
            _ocr_boxes_from_detection({"page.jpg": [[1.2, 2.8, 30.1, 40.7, 0.9]]}),
        )

    def test_empty_box_set_needs_no_optional_layout_dependencies(self) -> None:
        self.assertEqual([], sort_recognized_boxes([], image_height=50, image_width=100))

    def test_missing_model_asset_has_actionable_error(self) -> None:
        detection_run = iter_detection_pipeline("page.png", SimpleNamespace())

        self.assertEqual("loading_models", next(detection_run).phase)
        with self.assertRaisesRegex(FileNotFoundError, "vague-det-config"):
            next(detection_run)

    def test_json_document_uses_box_ids_for_global_reading_order(self) -> None:
        document = build_detection_document(Path("bia_001.jpg"), self._result())

        self.assertEqual("bia_001.jpg", document["image"])
        self.assertEqual(
            {
                "1": {"bbox": [120, 450, 180, 520], "status": "damaged"},
                "2": {"bbox": [120, 350, 180, 420], "status": "intact"},
                "3": {"bbox": [220, 350, 280, 420], "status": "intact"},
            },
            document["bounding_boxes"],
        )
        self.assertEqual([2, 3, 1], document["reading_order"])

    def test_main_writes_one_image_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "bia_001.jpg"
            output_path = Path(directory) / "detections.json"
            image_path.touch()

            with patch("text_detection.main.run_detection_pipeline", return_value=self._result()):
                exit_code = main(
                    [str(image_path), "--output", str(output_path)]
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(
                build_detection_document(image_path, self._result()),
                json.loads(output_path.read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
