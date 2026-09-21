"""UI-independent workflow helpers for image extraction sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .detection import extract_image_pages, load_embedded_image
from .models import MAX_DCI_HEIGHT, MAX_DCI_WIDTH, MAX_LONGEST_DIMENSION
from .processing import process_image
from .storage import save_processed_page


def create_session(pdf_path: str | Path) -> dict[str, Any]:
    """Scan a PDF and return serializable state suitable for any UI or CLI."""
    return {"pdf": str(pdf_path), "pages": extract_image_pages(pdf_path), "crops": {}, "crop_modes": {}}


def page_entry(session: dict[str, Any], page_number: int) -> dict[str, Any]:
    return next(entry for entry in session["pages"] if entry["page"] == page_number)


def preview(image: Image.Image, crop_box: tuple[int, int, int, int], crop_mode: str) -> dict[str, Any]:
    """Generate the same image that the persistence layer will write."""
    limit = (MAX_DCI_WIDTH, MAX_DCI_HEIGHT) if crop_mode == "dci_4k" else (MAX_LONGEST_DIMENSION, MAX_LONGEST_DIMENSION)
    return process_image(image, "manual", crop_box, max_width=limit[0], max_height=limit[1])


def save_entry(session: dict[str, Any], entry: dict[str, Any]) -> Path:
    page_key = str(entry["page"])
    crop = session.get("crops", {}).get(page_key)
    mode = session.get("crop_modes", {}).get(page_key, "free")
    return save_processed_page(session["pdf"], entry, tuple(crop) if crop else None, crop_mode=mode)


__all__ = ["create_session", "load_embedded_image", "page_entry", "preview", "save_entry"]
