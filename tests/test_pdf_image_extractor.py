import io
import tempfile
import unittest
from pathlib import Path

import pymupdf
from PIL import Image

from pdf_image_extractor.core import _fit_longest_dimension, get_center_16_9_crop, process_image
from pdf_image_extractor.detection import extract_image_pages, load_embedded_image


def _png_bytes(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, colour).save(stream, "PNG")
    return stream.getvalue()


def _write_image_pdf(path: Path, images: list[tuple[tuple[int, int], tuple[int, int, int], tuple[float, float, float, float]]]) -> None:
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    for size, colour, rect in images:
        page.insert_image(pymupdf.Rect(rect), stream=_png_bytes(size, colour))
    document.save(path)
    document.close()


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


class EmbeddedImageCompositionTests(unittest.TestCase):
    def test_adjoining_equally_wide_slices_are_composed(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "stacked.pdf"
            _write_image_pdf(
                pdf_path,
                [
                    ((300, 200), (255, 0, 0), (50, 20, 350, 220)),
                    ((300, 200), (0, 0, 255), (50, 220, 350, 420)),
                ],
            )
            entry = extract_image_pages(pdf_path)[0]
            image, _ = load_embedded_image(pdf_path, entry)

        self.assertEqual(entry["extraction_method"], "Composed direct XObjects")
        self.assertEqual(entry["composition"], "vertical")
        self.assertEqual(len(entry["parts"]), 2)
        self.assertEqual(image.size, (300, 400))
        self.assertEqual(image.getpixel((150, 100)), (255, 0, 0))
        self.assertEqual(image.getpixel((150, 300)), (0, 0, 255))

    def test_slices_with_a_visible_gap_are_not_composed(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "gapped.pdf"
            _write_image_pdf(
                pdf_path,
                [
                    ((300, 200), (255, 0, 0), (50, 20, 350, 220)),
                    ((300, 200), (0, 0, 255), (50, 225, 350, 425)),
                ],
            )
            entry = extract_image_pages(pdf_path)[0]

        self.assertEqual(entry["extraction_method"], "Direct XObject")
        self.assertIsNone(entry["parts"])

    def test_slices_with_different_native_widths_are_not_composed(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "different-widths.pdf"
            _write_image_pdf(
                pdf_path,
                [
                    ((300, 200), (255, 0, 0), (50, 20, 350, 220)),
                    ((280, 200), (0, 0, 255), (50, 220, 350, 420)),
                ],
            )
            entry = extract_image_pages(pdf_path)[0]

        self.assertEqual(entry["extraction_method"], "Direct XObject")
        self.assertIsNone(entry["parts"])


if __name__ == "__main__":
    unittest.main()
