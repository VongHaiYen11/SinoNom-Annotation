"""Shared immutable models and extraction defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_TITLE_PATTERN = r"^VĂN BIA SỐ\s+(?P<number>\d+)\s*$"
DEFAULT_CONTENT_START = "Nguyên văn chữ Hán Nôm"
DEFAULT_CONTENT_SECTIONS = (
    "Nguyên văn chữ Hán Nôm",
    "Phiên âm Hán Việt",
    "Dịch nghĩa",
    "Toát yếu",
    "Chú thích",
)
DEFAULT_MARKER_PATTERN = r"^\s*<\s*(?P<id>\d+)\s*>?\s*(?P<rest>.*)$"
DEFAULT_ENCODED_FONTS = ("PalatinoLinotype", "NomNaTong", "PMingLiU")
DEFAULT_TOP_MARGIN = 40.0
DEFAULT_BOTTOM_MARGIN = 45.0


class ExtractionError(RuntimeError):
    """Raised when extraction cannot continue without losing correctness."""


@dataclass(frozen=True)
class MetadataSpec:
    label: str
    field: str
    type: str = "string"
    required: bool = True


@dataclass(frozen=True)
class ExtractConfig:
    input_pdf: Path
    output_jsonl: Path
    glyph_profile: Path
    metadata: tuple[MetadataSpec, ...]
    title_pattern: str = DEFAULT_TITLE_PATTERN
    content_start: str = DEFAULT_CONTENT_START
    content_sections: tuple[str, ...] = DEFAULT_CONTENT_SECTIONS
    marker_pattern: str = DEFAULT_MARKER_PATTERN
    encoded_fonts: tuple[str, ...] = DEFAULT_ENCODED_FONTS
    top_margin: float = DEFAULT_TOP_MARGIN
    bottom_margin: float = DEFAULT_BOTTOM_MARGIN
    expected_record_count: int | None = None
    require_consecutive_numbers: bool = True


@dataclass(frozen=True)
class TextLine:
    text: str
    page_number: int
    y0: float = 0.0

