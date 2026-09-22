"""Direct PDF image-XObject detection and native image loading."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from .models import ImagePage


def _instances(page: pymupdf.Page, xref: int) -> tuple[list[pymupdf.Rect], list[list[float]]]:
    rects = list(page.get_image_rects(xref))
    transforms: list[list[float]] = []
    try:
        for info in page.get_image_info(xrefs=True):
            if info.get("xref") == xref and info.get("transform"):
                transforms.append([float(value) for value in info["transform"]])
    except Exception:
        pass
    return rects, transforms


def extract_image_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Detect meaningful embedded page images without rendering PDF pages."""
    results: list[ImagePage] = []
    with pymupdf.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            images = page.get_images(full=True)
            page_area = max(page.rect.get_area(), 1.0)
            candidates = []
            for item in images:
                xref, width, height = int(item[0]), int(item[2]), int(item[3])
                rects, transforms = _instances(page, xref)
                coverage = max((rect.get_area() / page_area for rect in rects), default=0.0)
                if width >= 200 and height >= 200 and (coverage >= 0.20 or len(images) == 1 and coverage >= 0.05):
                    candidates.append((item, rects, transforms, coverage))
            if not candidates:
                continue
            # A page can contain several meaningful image XObjects. They remain
            # independent assets: select the visually dominant one, never compose
            # separate XObjects into a synthetic image.
            candidates.sort(
                key=lambda candidate: (
                    -candidate[3],
                    min((rect.y0 for rect in candidate[1]), default=0),
                    int(candidate[0][0]),
                )
            )
            first, first_rects, first_transforms, first_coverage = candidates[0]
            xref, smask, width, height = (int(first[0]), int(first[1]), int(first[2]), int(first[3]))
            confidence = min(0.99, 0.55 + first_coverage * 0.45 + (0.12 if len(candidates) == 1 else 0))
            results.append(ImagePage(page=page_index + 1, asset_id=f"{page_index + 1}:{xref}", xref=xref, smask=smask, width=width, height=height, extension=str(first[7] or "bin"), image_count=len(images), meaningful_image_count=len(candidates), display_rects=[[rect.x0, rect.y0, rect.x1, rect.y1] for rect in first_rects], transforms=first_transforms, page_size=[page.rect.width, page.rect.height], text_blocks=len([block for block in page.get_text("blocks") if block[4].strip()]), drawings=len(page.get_drawings()), confidence=round(confidence, 2), extraction_method="Direct XObject", reason="dominant embedded image"))
    for sequence, result in enumerate(results, start=1):
        result.sequence = sequence
    return [result.to_dict() for result in results]


def _load_xobject(document: pymupdf.Document, xref: int, smask: int = 0) -> tuple[Image.Image, bytes, str]:
    raw = document.extract_image(xref)
    raw_bytes = raw["image"]
    try:
        image = Image.open(io.BytesIO(raw_bytes)); image.load()
    except Exception:
        pixmap = pymupdf.Pixmap(document, xref)
        image, raw_bytes, raw["ext"] = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples), b"", "png"
    if smask:
        try:
            mask = Image.open(io.BytesIO(document.extract_image(smask)["image"])).convert("L")
            if mask.size == image.size:
                image = image.convert("RGBA"); image.putalpha(mask); raw_bytes, raw["ext"] = b"", "png"
        except Exception:
            pass
    return image, raw_bytes, raw.get("ext", "png")


def load_embedded_image(pdf_path: str | Path, entry: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    """Load one native image XObject at source resolution."""
    with pymupdf.open(pdf_path) as document:
        image, raw_bytes, extension = _load_xobject(document, int(entry["xref"]), int(entry.get("smask", 0)))
    return image, {"raw_bytes": raw_bytes, "extension": extension, "entry": entry}
