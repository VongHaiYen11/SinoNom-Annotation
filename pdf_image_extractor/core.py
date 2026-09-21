"""Core image extraction, classification, and native-resolution crop operations."""

from __future__ import annotations

import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

MAX_WIDTH = 2160
MAX_HEIGHT = 3840
TARGET_RATIO = MAX_WIDTH / MAX_HEIGHT


@dataclass
class ImagePage:
    page: int
    asset_id: str
    xref: int
    smask: int
    width: int
    height: int
    extension: str
    image_count: int
    meaningful_image_count: int
    display_rects: list[list[float]]
    transforms: list[list[float]]
    page_size: list[float]
    text_blocks: int
    drawings: int
    confidence: float
    extraction_method: str
    reason: str
    parts: list[dict[str, Any]] | None = None
    composition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_center_16_9_crop(width: int, height: int) -> tuple[int, int, int, int]:
    """Return the largest centered integer 9:16 (vertical 4K) box in an image.

    The historical function name is retained as the requested public API.
    """
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive")
    ratio = width / height
    if math.isclose(ratio, TARGET_RATIO, rel_tol=0, abs_tol=1e-12):
        return (0, 0, width, height)
    if ratio > TARGET_RATIO:
        crop_h = height
        crop_w = round(height * TARGET_RATIO)
        left = (width - crop_w) // 2
        return (left, 0, left + crop_w, height)
    crop_w = width
    crop_h = round(width / TARGET_RATIO)
    top = (height - crop_h) // 2
    return (0, top, width, top + crop_h)


def _normalise_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(round(v)) for v in box)
    left, right = sorted((max(0, left), min(width, right)))
    top, bottom = sorted((max(0, top), min(height, bottom)))
    if right <= left or bottom <= top:
        raise ValueError("Crop box must have a positive area inside the image")
    return left, top, right, bottom


def process_image(
    image: Image.Image,
    crop_mode: str = "center",
    crop_box: tuple[int, int, int, int] | None = None,
    max_width: int = MAX_WIDTH,
    max_height: int = MAX_HEIGHT,
) -> dict[str, Any]:
    """Crop from the supplied original image and downscale only when required.

    ``crop_box`` is always in original-image pixel coordinates. Manual boxes are
    accepted as supplied; the UI keeps them 9:16. This function never upscales.
    """
    if max_width <= 0 or max_height <= 0:
        raise ValueError("Maximum dimensions must be positive")
    if crop_mode == "center":
        box = get_center_16_9_crop(*image.size)
    elif crop_box is not None:
        box = _normalise_box(crop_box, *image.size)
    else:
        raise ValueError("Manual processing requires crop_box")
    cropped = image.crop(box)
    crop_w, crop_h = cropped.size
    scale = min(1.0, max_width / crop_w, max_height / crop_h)
    downscaled = scale < 1.0
    if downscaled:
        final_size = (max(1, round(crop_w * scale)), max(1, round(crop_h * scale)))
        cropped = cropped.resize(final_size, Image.Resampling.LANCZOS)
    return {
        "image": cropped,
        "crop_box": box,
        "crop_size": (crop_w, crop_h),
        "final_size": cropped.size,
        "upscaled": False,
        "downscaled": downscaled,
    }


def _image_instances(page: pymupdf.Page, xref: int) -> tuple[list[pymupdf.Rect], list[list[float]]]:
    rects = list(page.get_image_rects(xref))
    transforms: list[list[float]] = []
    try:
        for info in page.get_image_info(xrefs=True):
            if info.get("xref") == xref:
                transform = info.get("transform")
                if transform:
                    transforms.append([float(v) for v in transform])
    except Exception:
        pass
    return rects, transforms


def extract_image_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Find pages whose primary content is one dominant embedded image XObject.

    The heuristic requires a reasonably sized image and at least 20% page-area
    coverage (or 50% when it is the sole XObject), avoiding logos and bullets.
    """
    results: list[ImagePage] = []
    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            images = page.get_images(full=True)
            page_area = max(page.rect.width * page.rect.height, 1.0)
            text_blocks = [b for b in page.get_text("blocks") if b[4].strip()]
            drawings = page.get_drawings()
            candidates: list[tuple[tuple[Any, ...], list[pymupdf.Rect], list[list[float]], float]] = []
            for item in images:
                xref, smask, width, height = int(item[0]), int(item[1]), int(item[2]), int(item[3])
                rects, transforms = _image_instances(page, xref)
                coverage = max((r.get_area() / page_area for r in rects), default=0.0)
                # Decorative images are generally low-pixel and low-display-area.
                meaningful = width >= 200 and height >= 200 and (coverage >= 0.20 or (len(images) == 1 and coverage >= 0.05))
                if meaningful:
                    candidates.append((item, rects, transforms, coverage))
            if not candidates:
                continue
            candidates.sort(key=lambda entry: min((r.y0 for r in entry[1]), default=0))
            item, rects, transforms, coverage = candidates[0]
            xref, smask, width, height = int(item[0]), int(item[1]), int(item[2]), int(item[3])
            parts = None
            composition = None
            method = "Direct XObject"
            reason = "dominant embedded image"
            if len(candidates) > 1:
                # This collection stores one tall visible photograph as adjoining
                # image strips. Combine their native XObjects in display order.
                parts = [
                    {"xref": int(candidate[0][0]), "smask": int(candidate[0][1]), "width": int(candidate[0][2]), "height": int(candidate[0][3])}
                    for candidate in candidates
                ]
                width = max(part["width"] for part in parts)
                height = sum(part["height"] for part in parts)
                composition = "vertical"
                method = "Composed direct XObjects"
                reason = "one visible image composed from vertically stacked XObjects"
            confidence = min(0.99, 0.55 + sum(candidate[3] for candidate in candidates) * 0.45 + (0.12 if len(candidates) == 1 else 0))
            results.append(ImagePage(
                page=page_index + 1, asset_id=f"{page_index + 1}:{xref}",
                xref=xref, smask=smask, width=width, height=height,
                extension=str(item[7] or "bin"), image_count=len(images), meaningful_image_count=len(candidates),
                display_rects=[[r.x0, r.y0, r.x1, r.y1] for candidate in candidates for r in candidate[1]],
                transforms=[matrix for candidate in candidates for matrix in candidate[2]],
                page_size=[page.rect.width, page.rect.height], text_blocks=len(text_blocks), drawings=len(drawings),
                confidence=round(confidence, 2), extraction_method=method, reason=reason,
                parts=parts, composition=composition,
            ))
    return [result.to_dict() for result in results]


def _load_xobject(doc: pymupdf.Document, xref: int, smask: int = 0) -> tuple[Image.Image, bytes, str]:
    """Load one native XObject, including its soft mask when available."""
    raw = doc.extract_image(xref)
    raw_bytes = raw["image"]
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
    except Exception:
        pix = pymupdf.Pixmap(doc, xref)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        raw["ext"] = "png"
        raw_bytes = b""
    if smask:
        raw_bytes = raw["image"]
        try:
            mask = Image.open(io.BytesIO(doc.extract_image(smask)["image"])).convert("L")
            if mask.size == image.size:
                image = image.convert("RGBA")
                image.putalpha(mask)
                raw_bytes, raw["ext"] = b"", "png"
        except Exception:
            pass
    return image, raw_bytes, raw.get("ext", "png")


def load_embedded_image(pdf_path: str | Path, entry: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    """Load an original XObject, or directly compose its native image strips."""
    with pymupdf.open(pdf_path) as doc:
        if entry.get("parts"):
            loaded = [_load_xobject(doc, part["xref"], part.get("smask", 0))[0] for part in entry["parts"]]
            mode = "RGBA" if any(image.mode in ("RGBA", "LA") for image in loaded) else "RGB"
            loaded = [image.convert(mode) for image in loaded]
            canvas = Image.new(mode, (max(image.width for image in loaded), sum(image.height for image in loaded)))
            y = 0
            for image in loaded:
                canvas.paste(image, (0, y), image if mode == "RGBA" else None)
                y += image.height
            return canvas, {"raw_bytes": b"", "extension": "png", "entry": {**entry, "extraction_method": "Composed direct XObjects"}}
        image, raw_bytes, extension = _load_xobject(doc, int(entry["xref"]), int(entry.get("smask", 0)))
    return image, {"raw_bytes": raw_bytes, "extension": extension, "entry": entry}


def save_processed_page(
    pdf_path: str | Path, entry: dict[str, Any], crop_box: tuple[int, int, int, int] | None,
    output_format: str = "PNG", output_root: str | Path = "output",
) -> Path:
    """Extract, process, and persist one page entirely from its original XObject."""
    image, source = load_embedded_image(pdf_path, entry)
    result = process_image(image, "manual" if crop_box else "center", crop_box)
    pdf_stem = Path(pdf_path).stem
    page_dir = Path(output_root) / pdf_stem / f"page_{entry['page']:03d}"
    original_dir, final_dir = page_dir / "original", page_dir / "final"
    original_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    ext = str(source["extension"]).lower().replace("jpeg", "jpg")
    original_path = original_dir / f"image.{ext if source['raw_bytes'] else 'png'}"
    if source["raw_bytes"]:
        original_path.write_bytes(source["raw_bytes"])
    else:
        image.save(original_path, "PNG")
    fmt = output_format.upper()
    final_path = final_dir / f"image.{fmt.lower().replace('jpeg', 'jpg')}"
    final = result["image"]
    if fmt == "JPEG":
        if final.mode in ("RGBA", "LA"):
            background = Image.new("RGB", final.size, "white")
            background.paste(final, mask=final.getchannel("A"))
            final = background
        elif final.mode != "RGB":
            final = final.convert("RGB")
        final.save(final_path, "JPEG", quality=95, optimize=True, progressive=True)
    else:
        final.save(final_path, "PNG")
    left, top, right, bottom = result["crop_box"]
    metadata = {
        "page": entry["page"], "source": "embedded_pdf_image", "xref": entry["xref"],
        "asset_id": entry.get("asset_id"),
        "extraction_method": source["entry"]["extraction_method"],
        "original_width": image.width, "original_height": image.height,
        "crop_x": left, "crop_y": top, "crop_width": right-left, "crop_height": bottom-top,
        "final_width": result["final_size"][0], "final_height": result["final_size"][1],
        "upscaled": False, "downscaled": result["downscaled"],
        "crop_mode": "manual_9_16" if crop_box else "center_9_16",
        "original_file": str(original_path), "final_file": str(final_path),
    }
    (page_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return page_dir
