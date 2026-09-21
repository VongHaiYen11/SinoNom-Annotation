import unittest

from PIL import Image

from pdf_image_extractor.core import _fit_longest_dimension, get_center_16_9_crop, process_image


class CenterCropTests(unittest.TestCase):
    def test_required_sizes(self):
        cases = [
            ((6000, 4000), (2109, 4000)), ((5000, 3000), (1582, 3000)),
            ((4000, 3000), (1582, 3000)), ((3840, 2160), (1139, 2160)),
            ((3000, 2000), (1055, 2000)), ((1920, 1080), (570, 1080)),
            ((3000, 5000), (2160, 4096)),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = process_image(Image.new("RGB", source))
                self.assertEqual(result["final_size"], expected)
                self.assertLessEqual(result["final_size"][0], 2160)
                self.assertLessEqual(result["final_size"][1], 4096)
                self.assertFalse(result["upscaled"])
                # Integer crop dimensions necessarily introduce at most a pixel
                # of rounding error (e.g. 3000×1688).
                self.assertLess(abs(result["crop_size"][0] / result["crop_size"][1] - 2160/4096), 0.001)

    def test_center_boxes(self):
        self.assertEqual(get_center_16_9_crop(6000, 4000), (1945, 0, 4054, 4000))
        self.assertEqual(get_center_16_9_crop(3000, 5000), (181, 0, 2818, 5000))

    def test_stored_images_cap_longest_dimension_without_upscaling(self):
        self.assertEqual(_fit_longest_dimension(Image.new("RGB", (8000, 2000))).size, (4096, 1024))
        self.assertEqual(_fit_longest_dimension(Image.new("RGB", (1920, 1080))).size, (1920, 1080))


if __name__ == "__main__":
    unittest.main()
