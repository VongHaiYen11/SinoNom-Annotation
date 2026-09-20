"""Shared immutable models and extraction defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    output_json: Path
    glyph_profile: Path
    metadata: tuple[MetadataSpec, ...]
    title_pattern: str = DEFAULT_TITLE_PATTERN
    content_start: str = DEFAULT_CONTENT_START
    content_sections: tuple[str, ...] = DEFAULT_CONTENT_SECTIONS
    marker_pattern: str = DEFAULT_MARKER_PATTERN
    encoded_fonts: tuple[str, ...] = DEFAULT_ENCODED_FONTS
    top_margin: float = DEFAULT_TOP_MARGIN
    bottom_margin: float = DEFAULT_BOTTOM_MARGIN
    footnote_start_pattern: str | None = None
    footnote_max_font_size: float | None = None
    expected_record_count: int | None = None
    require_consecutive_numbers: bool = True


@dataclass(frozen=True)
class TextCharacter:
    """One reconstructed PDF character and the evidence used to decode it."""

    text: str
    bbox: tuple[float, float, float, float]
    font_name: str
    font_size: float
    font_xref: int | None
    status: str  # matched, fallback, or unresolved


@dataclass(frozen=True)
class TextSpan:
    """A reconstructed rawdict span; retained for review and later filters."""

    text: str
    bbox: tuple[float, float, float, float]
    font_name: str
    font_size: float
    font_xref: int | None
    characters: tuple[TextCharacter, ...] = ()


@dataclass(frozen=True)
class TextLine:
    text: str
    page_number: int
    y0: float = 0.0
    x0: float = 0.0
    y1: float = 0.0
    font_size: float = 0.0
    block_number: int | None = None
    line_number: int | None = None
    spans: tuple[TextSpan, ...] = field(default_factory=tuple)


@dataclass
class DecodeStatistics:
    """Counts reported after each document extraction."""

    total_characters: int = 0
    profile_matched: int = 0
    fallback: int = 0
    unresolved: int = 0
