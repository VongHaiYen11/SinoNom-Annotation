"""Direct PDF image-XObject detection and native image loading."""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from .models import ImagePage


# PDF coordinates are points. A one-point tolerance accepts harmless
# floating-point rounding while still rejecting visibly separated images.
_STACK_POSITION_TOLERANCE = 1.0
_NATIVE_WIDTH_TOLERANCE = 1


def _single_display_rect(candidate: tuple[Any, list[pymupdf.Rect], list[list[float]], float]) -> pymupdf.Rect | None:
    """Return the only display rect for a candidate, if it has one."""
    rects = candidate[1]
    return rects[0] if len(rects) == 1 else None


def _can_stack_vertically(
    upper: tuple[Any, list[pymupdf.Rect], list[list[float]], float],
    lower: tuple[Any, list[pymupdf.Rect], list[list[float]], float],
) -> bool:
    """Whether two XObjects are adjoining slices of one vertically tiled image."""
    upper_item, lower_item = upper[0], lower[0]
    upper_rect, lower_rect = _single_display_rect(upper), _single_display_rect(lower)
    if upper_rect is None or lower_rect is None:
        return False

    upper_width, lower_width = int(upper_item[2]), int(lower_item[2])
    if abs(upper_width - lower_width) > _NATIVE_WIDTH_TOLERANCE:
        return False
    if (
        abs(upper_rect.x0 - lower_rect.x0) > _STACK_POSITION_TOLERANCE
        or abs(upper_rect.x1 - lower_rect.x1) > _STACK_POSITION_TOLERANCE
        or abs(upper_rect.y1 - lower_rect.y0) > _STACK_POSITION_TOLERANCE
    ):
        return False

    # Matching horizontal scales guards against neighbouring, unrelated images
    # that happen to share an edge on the PDF page.
    upper_scale = upper_rect.width / upper_width
    lower_scale = lower_rect.width / lower_width
    return math.isclose(upper_scale, lower_scale, rel_tol=0.01, abs_tol=0.001)


def _vertical_stack(
    candidates: list[tuple[Any, list[pymupdf.Rect], list[list[float]], float]],
) -> list[tuple[Any, list[pymupdf.Rect], list[list[float]], float]] | None:
    """Find the strongest chain of directly adjoining, equally wide image slices."""
    ordered = sorted(
        (candidate for candidate in candidates if _single_display_rect(candidate) is not None),
        key=lambda candidate: (_single_display_rect(candidate).y0, int(candidate[0][0])),  # type: ignore[union-attr]
    )
    chains: list[list[tuple[Any, list[pymupdf.Rect], list[list[float]], float]]] = []
    for start, first in enumerate(ordered):
        chain = [first]
        for candidate in ordered[start + 1:]:
            current_rect = _single_display_rect(chain[-1])
            candidate_rect = _single_display_rect(candidate)
            assert current_rect is not None and candidate_rect is not None
            if candidate_rect.y0 > current_rect.y1 + _STACK_POSITION_TOLERANCE:
                break
            if _can_stack_vertically(chain[-1], candidate):
                chain.append(candidate)
        if len(chain) > 1:
            chains.append(chain)

    if not chains:
        return None
    return max(
        chains,
        key=lambda chain: (
            sum(candidate[3] for candidate in chain),
            len(chain),
            -_single_display_rect(chain[0]).y0,  # type: ignore[union-attr]
            -int(chain[0][0][0]),
        ),
    )


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
            candidates.sort(
                key=lambda candidate: (
                    -candidate[3],
                    min((rect.y0 for rect in candidate[1]), default=0),
                    int(candidate[0][0]),
                )
            )
            parts_to_stack = _vertical_stack(candidates)
            selected = parts_to_stack or [candidates[0]]
            first, first_rects, first_transforms, first_coverage = selected[0]
            xref, smask, width, height = (int(first[0]), int(first[1]), int(first[2]), int(first[3]))
            parts = None
            composition = None
            method, reason = "Direct XObject", "dominant embedded image"
            if parts_to_stack:
                width = max(int(candidate[0][2]) for candidate in selected)
                height = sum(int(candidate[0][3]) for candidate in selected)
                parts = [
                    {
                        "xref": int(candidate[0][0]),
                        "smask": int(candidate[0][1]),
                        "width": int(candidate[0][2]),
                        "height": int(candidate[0][3]),
                    }
                    for candidate in selected
                ]
                composition = "vertical"
                method = "Composed direct XObjects"
                reason = "adjoining, equally wide vertically stacked XObjects"
            confidence = min(
                0.99,
                0.55 + sum(candidate[3] for candidate in selected) * 0.45
                + (0.12 if len(selected) == 1 else 0),
            )
            results.append(ImagePage(page=page_index + 1, asset_id=f"{page_index + 1}:{xref}", xref=xref, smask=smask, width=width, height=height, extension=str(first[7] or "bin"), image_count=len(images), meaningful_image_count=len(candidates), display_rects=[[rect.x0, rect.y0, rect.x1, rect.y1] for candidate in selected for rect in candidate[1]], transforms=[matrix for candidate in selected for matrix in candidate[2]], page_size=[page.rect.width, page.rect.height], text_blocks=len([block for block in page.get_text("blocks") if block[4].strip()]), drawings=len(page.get_drawings()), confidence=round(confidence, 2), extraction_method=method, reason=reason, parts=parts, composition=composition))
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
    """Load one native image XObject or a verified stack of source slices."""
    with pymupdf.open(pdf_path) as document:
        if entry.get("parts"):
            images = [
                _load_xobject(document, int(part["xref"]), int(part.get("smask", 0)))[0]
                for part in entry["parts"]
            ]
            mode = "RGBA" if any(image.mode in ("RGBA", "LA") for image in images) else "RGB"
            canvas = Image.new(mode, (max(image.width for image in images), sum(image.height for image in images)))
            y = 0
            for image in images:
                image = image.convert(mode)
                canvas.paste(image, (0, y), image if mode == "RGBA" else None)
                y += image.height
            return canvas, {"entry": {**entry, "extraction_method": "Composed direct XObjects"}}
        image, raw_bytes, extension = _load_xobject(document, int(entry["xref"]), int(entry.get("smask", 0)))
    return image, {"raw_bytes": raw_bytes, "extension": extension, "entry": entry}
