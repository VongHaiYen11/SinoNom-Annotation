"""Shared data models and output limits for embedded-image extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass

MAX_DCI_WIDTH = 2160
MAX_DCI_HEIGHT = 4096
MAX_LONGEST_DIMENSION = 4096
DCI_PORTRAIT_RATIO = MAX_DCI_WIDTH / MAX_DCI_HEIGHT


@dataclass
class ImagePage:
    """One extractable visual image asset discovered in a PDF page."""

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
    sequence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
