import unittest
try:
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
