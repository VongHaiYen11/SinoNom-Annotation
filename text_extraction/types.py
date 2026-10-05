"""Shared immutable data contracts for the extraction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

class ExtractionError(RuntimeError):
    """Raised when extraction cannot continue without losing correctness."""


@dataclass(frozen=True)
class MetadataSpec:
    label: str
    field: str
    type: str
    required: bool


@dataclass(frozen=True)
class EncodedFont:
    """One embedded PDF font and its exact local Unicode reference font."""

    pdf_name: str
    reference_path: Path


@dataclass(frozen=True)
class ExtractConfig:
    input_pdf_path: Path
    output_json: Path
    glyph_profile: Path
    metadata: tuple[MetadataSpec, ...]
    title_pattern: str
    content_start: str
    content_sections: tuple[str, ...]
    marker_pattern: str
    encoded_fonts: tuple[EncodedFont, ...]
    top_margin: float
    bottom_margin: float
    footnote_start_pattern: str | None
    footnote_max_font_size: float | None
    require_consecutive_numbers: bool


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
