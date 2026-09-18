"""Shared glyph-outline helpers for profile building and PDF decoding."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import pymupdf
from fontTools.cffLib import CFFFontSet
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont, TTLibError

from extraction.models import ExtractionError


@dataclass(frozen=True)
class EmbeddedGlyph:
    """One outline exactly as enumerated by the profile builder."""

    name: str
    glyph: object
    glyph_set: object | None


def glyph_commands(glyph, scale: float = 1, glyph_set=None) -> str:
    """Return deterministic SVG path commands for a glyph outline."""
    path_pen = SVGPathPen(glyph_set)
    pen = (
        path_pen
        if scale == 1
        else TransformPen(path_pen, (scale, 0, 0, scale, 0, 0))
    )
    glyph.draw(pen)
    return path_pen.getCommands()


def signature(commands: str) -> str:
    """Return the stable short hash used as the glyph-profile key."""
    return hashlib.sha256(commands.encode("utf-8")).hexdigest()[:24]


def cff_top(document: pymupdf.Document, xref: int):
    """Load the top CFF font from one embedded PDF font resource."""
    _, extension, font_type, content = document.extract_font(xref)
    if not content:
        raise ExtractionError(
            f"Embedded font has no data: xref={xref}, type={font_type}, ext={extension}"
        )
    if extension.lower() not in {"cff", "cid"}:
        raise ExtractionError(
            f"Embedded font is not CFF/CID: xref={xref}, type={font_type}, ext={extension}"
        )

    cff = CFFFontSet()
    cff.decompile(io.BytesIO(content), None)
    return cff[cff.fontNames[0]]


def embedded_glyphs(document: pymupdf.Document, xref: int) -> tuple[EmbeddedGlyph, ...]:
    """Enumerate every outline format supported by the glyph-profile builder.

    This is intentionally the common boundary for profile construction and
    extraction.  Type1 is excluded because the builder does not produce
    compatible signatures for it either.
    """
    _, extension, font_type, content = document.extract_font(xref)
    if not content:
        raise ExtractionError(
            f"Embedded font has no data: xref={xref}, type={font_type}, ext={extension}"
        )
    extension = extension.lower()
    if extension in {"ttf", "otf"}:
        try:
            font = TTFont(io.BytesIO(content))
        except TTLibError as exc:
            raise ExtractionError(f"Cannot parse embedded font xref={xref}: {exc}") from exc
        glyph_set = font.getGlyphSet()
        return tuple(EmbeddedGlyph(name, glyph_set[name], glyph_set) for name in glyph_set)
    if extension in {"cff", "cid"}:
        top = cff_top(document, xref)
        return tuple(EmbeddedGlyph(name, top.CharStrings[name], None) for name in top.charset[1:])
    if extension in {"pfa", "pfb"}:
        raise ExtractionError(
            f"Type1 is not supported by the glyph-profile builder: xref={xref}, ext={extension}"
        )
    raise ExtractionError(
        f"Unsupported embedded font: xref={xref}, type={font_type}, ext={extension}"
    )
