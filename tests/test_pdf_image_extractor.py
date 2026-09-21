import unittest

from PIL import Image

from pdf_image_extractor.core import get_center_16_9_crop, process_image


class CenterCropTests(unittest.TestCase):
    def test_required_sizes(self):
        cases = [
            ((6000, 4000), (2160, 3840)), ((5000, 3000), (1688, 3000)),
            ((4000, 3000), (1688, 3000)), ((3840, 2160), (1215, 2160)),
            ((3000, 2000), (1125, 2000)), ((1920, 1080), (608, 1080)),
            ((3000, 5000), (2160, 3840)),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = process_image(Image.new("RGB", source))
                self.assertEqual(result["final_size"], expected)
                self.assertLessEqual(result["final_size"][0], 2160)
                self.assertLessEqual(result["final_size"][1], 3840)
                self.assertFalse(result["upscaled"])
                # Integer crop dimensions necessarily introduce at most a pixel
                # of rounding error (e.g. 3000×1688).
                self.assertLess(abs(result["crop_size"][0] / result["crop_size"][1] - 9/16), 0.001)

    def test_center_boxes(self):
        self.assertEqual(get_center_16_9_crop(6000, 4000), (1875, 0, 4125, 4000))
        self.assertEqual(get_center_16_9_crop(3000, 5000), (94, 0, 2906, 5000))


if __name__ == "__main__":
    unittest.main()
