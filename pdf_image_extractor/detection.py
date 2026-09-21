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
            candidates.sort(key=lambda candidate: min((rect.y0 for rect in candidate[1]), default=0))
            first, _, _, _ = candidates[0]
            xref, smask, width, height = (int(first[0]), int(first[1]), int(first[2]), int(first[3]))
            parts = None
            method, reason, composition = "Direct XObject", "dominant embedded image", None
            if len(candidates) > 1:
                parts = [{"xref": int(item[0]), "smask": int(item[1]), "width": int(item[2]), "height": int(item[3])} for item, _, _, _ in candidates]
                width, height = max(part["width"] for part in parts), sum(part["height"] for part in parts)
                method, reason, composition = "Composed direct XObjects", "one visible image composed from vertically stacked XObjects", "vertical"
            confidence = min(0.99, 0.55 + sum(candidate[3] for candidate in candidates) * 0.45 + (0.12 if len(candidates) == 1 else 0))
            results.append(ImagePage(page=page_index + 1, asset_id=f"{page_index + 1}:{xref}", xref=xref, smask=smask, width=width, height=height, extension=str(first[7] or "bin"), image_count=len(images), meaningful_image_count=len(candidates), display_rects=[[rect.x0, rect.y0, rect.x1, rect.y1] for _, rects, _, _ in candidates for rect in rects], transforms=[matrix for _, _, transforms, _ in candidates for matrix in transforms], page_size=[page.rect.width, page.rect.height], text_blocks=len([block for block in page.get_text("blocks") if block[4].strip()]), drawings=len(page.get_drawings()), confidence=round(confidence, 2), extraction_method=method, reason=reason, parts=parts, composition=composition))
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
    """Load an XObject (or its native stacked parts) at source resolution."""
    with pymupdf.open(pdf_path) as document:
        if entry.get("parts"):
            images = [_load_xobject(document, part["xref"], part.get("smask", 0))[0] for part in entry["parts"]]
            mode = "RGBA" if any(image.mode in ("RGBA", "LA") for image in images) else "RGB"
            canvas = Image.new(mode, (max(image.width for image in images), sum(image.height for image in images)))
            y = 0
            for image in images:
                image = image.convert(mode); canvas.paste(image, (0, y), image if mode == "RGBA" else None); y += image.height
            return canvas, {"entry": {**entry, "extraction_method": "Composed direct XObjects"}}
        image, raw_bytes, extension = _load_xobject(document, int(entry["xref"]), int(entry.get("smask", 0)))
    return image, {"raw_bytes": raw_bytes, "extension": extension, "entry": entry}
