"""Local JPEG output and metadata persistence for extracted images."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from .detection import load_embedded_image
from .models import MAX_LONGEST_DIMENSION
from .processing import fit_longest_dimension, process_image


def image_filename(pdf_path: str | Path, sequence: int) -> str:
    book = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(pdf_path).stem).strip("_") or "book"
    return f"{book}.{sequence:03d}.jpg"


def save_jpeg(image: Image.Image, path: Path) -> None:
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A")); image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.save(path, "JPEG", quality=95, optimize=True, progressive=True)


def save_processed_page(pdf_path: str | Path, entry: dict[str, Any], crop_box: tuple[int, int, int, int] | None, output_root: str | Path = "output", crop_mode: str = "free") -> Path:
    """Persist original and final JPEGs plus metadata for one extracted asset."""
    image, source = load_embedded_image(pdf_path, entry)
    if crop_mode == "dci_4k":
        result = process_image(image, "manual" if crop_box else "center", crop_box)
    else:
        result = process_image(image, "manual", crop_box or (0, 0, image.width, image.height), max_width=MAX_LONGEST_DIMENSION, max_height=MAX_LONGEST_DIMENSION)
    page_dir = Path(output_root) / Path(pdf_path).stem / f"page_{entry['page']:03d}"
    original_dir, final_dir = page_dir / "original", page_dir / "final"
    original_dir.mkdir(parents=True, exist_ok=True); final_dir.mkdir(parents=True, exist_ok=True)
    filename = image_filename(pdf_path, int(entry.get("sequence", entry["page"])))
    original_path, final_path = original_dir / filename, final_dir / filename
    save_jpeg(fit_longest_dimension(image), original_path); save_jpeg(fit_longest_dimension(result["image"]), final_path)
    left, top, right, bottom = result["crop_box"]
    metadata = {"page": entry["page"], "source": "embedded_pdf_image", "xref": entry["xref"], "asset_id": entry.get("asset_id"), "sequence": entry.get("sequence", entry["page"]), "filename": filename, "extraction_method": source["entry"]["extraction_method"], "original_width": image.width, "original_height": image.height, "crop_x": left, "crop_y": top, "crop_width": right - left, "crop_height": bottom - top, "final_width": result["final_size"][0], "final_height": result["final_size"][1], "upscaled": False, "downscaled": result["downscaled"], "crop_mode": "dci_4k_portrait" if crop_mode == "dci_4k" else "free", "original_file": str(original_path), "final_file": str(final_path)}
    (page_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return page_dir
