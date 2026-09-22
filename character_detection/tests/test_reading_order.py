import unittest
from unittest.mock import Mock
try:
    import numpy as np
    import torch
    from character_detection.detector import CharacterDetector
    from character_detection.reading_order import sort_boxes_reading_order
    ERROR = None
except ModuleNotFoundError as error:
    ERROR = error

@unittest.skipIf(ERROR is not None, f'missing runtime dependency: {ERROR}')
class TestDetectionOutput(unittest.TestCase):
    def test_four_corners(self):
        self.assertEqual(CharacterDetector._token((10,20,30,50),.9).corners, ((10,20),(30,20),(30,50),(10,50)))
    def test_order_keeps_boxes(self):
        boxes=[[10,10,20,30],[10,40,20,60],[50,10,60,30],[50,40,60,60]]
        self.assertCountEqual(sort_boxes_reading_order(boxes,80,80),boxes)

    def test_detect_sends_batched_nchw_tensor(self):
        detector = CharacterDetector.__new__(CharacterDetector)
        detector.device = torch.device("cpu")
        detector.image_size = 64
        detector.confidence_threshold = .45
        detector.iou_threshold = .2
        detector.invert = True
        detector.client = Mock(side_effect=[32, torch.zeros((1, 1, 6))])
        detector.detect(np.zeros((40, 80, 3), dtype=np.uint8), reading_order=False)
        tensor = detector.client.call_args_list[1].args[0]
        self.assertEqual(tensor.ndim, 4)
        self.assertEqual(tensor.shape[:2], (1, 3))
