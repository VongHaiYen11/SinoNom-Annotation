"""Build deterministic CID-outline glyph profiles from a PDF and its config."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import re
import sys

import pymupdf
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from text_extraction.config import load_config
from text_extraction.font_discovery import (
    load_reference_font,
    normalize_font_name,
    synchronize_encoded_fonts,
)
from text_extraction.output import atomic_write
from text_extraction.pdf_glyphs import embedded_glyphs, glyph_commands, signature
from text_extraction.types import EncodedFont, ExtractConfig, ExtractionError


LOGGER = logging.getLogger(__name__)
RASTER_WIDTH = 72
RASTER_HEIGHT = 101
_NUMBER = rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_FONT_RUN = re.compile(
    rb"/(?P<resource>[^\s/]+)\s+" + _NUMBER + rb"\s+Tf"
    rb"(?P<body>.*?)(?=/(?:[^\s/]+)\s+" + _NUMBER + rb"\s+Tf|\Z)",
    re.DOTALL,
)


def _font_matches_encoded(font_name: str, encoded_font_names: tuple[str, ...]) -> bool:
    normalized = normalize_font_name(font_name)
    return any(normalize_font_name(token) == normalized for token in encoded_font_names)


def used_type0_cids(
    document: pymupdf.Document,
    encoded_font_names: tuple[str, ...],
) -> dict[int, set[int]]:
    """Return CIDs actually displayed by selected Type0 Identity fonts."""
    result: dict[int, set[int]] = {}
    for page in document:
        resources = {
            row[4]: row
            for row in page.get_fonts(full=True)
            if row[2] == "Type0"
            and row[1].lower() in {"cff", "cid", "ttf", "otf"}
            and row[5] in {"Identity-H", "Identity-V"}
            and _font_matches_encoded(row[3], encoded_font_names)
        }
        for content_xref in page.get_contents():
            content = document.xref_stream(content_xref)
            for run in _FONT_RUN.finditer(content):
                row = resources.get(run.group("resource").decode("latin-1"))
                if row is None:
                    continue
                hexadecimal = b"".join(
                    re.findall(rb"<([0-9A-Fa-f\s]+)>", run.group("body"))
                )
                hexadecimal = re.sub(rb"\s+", b"", hexadecimal)
                if not hexadecimal or len(hexadecimal) % 4:
                    continue
                raw = bytes.fromhex(hexadecimal.decode("ascii"))
                result.setdefault(row[0], set()).update(
                    int.from_bytes(raw[index:index + 2], "big")
                    for index in range(0, len(raw), 2)
                )
    return result


def rasterize(commands: str) -> bytes:
    """Rasterize one normalized outline for deterministic visual matching."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{RASTER_WIDTH}" height="{RASTER_HEIGHT}" '
        'viewBox="0 0 1000 1400">'
        '<rect width="1000" height="1400" fill="white"/>'
        '<g transform="translate(0 1100) scale(1 -1)">'
        f'<path d="{commands}" fill="black"/>'
        "</g></svg>"
    )
    document = pymupdf.open(stream=svg.encode(), filetype="svg")
    try:
        return document[0].get_pixmap(
            colorspace=pymupdf.csGRAY, alpha=False
        ).samples
    finally:
        document.close()


def glyph_bounds(glyph, glyph_set=None):
    """Return rounded glyph bounds, or ``None`` for a blank outline."""
    pen = BoundsPen(glyph_set)
    glyph.draw(pen)
    if not pen.bounds:
        return None
    return tuple(round(value, 2) for value in pen.bounds)


def get_cached_reference_font(
    font_name: str,
    encoded_fonts: tuple[EncodedFont, ...],
    cache: dict[str, tuple[Path, TTFont]],
) -> tuple[Path, TTFont]:
    """Load the exact reference path recorded for one configured PDF font."""
    cache_key = normalize_font_name(font_name)
    if cache_key not in cache:
        matches = [
            encoded_font
            for encoded_font in encoded_fonts
            if normalize_font_name(encoded_font.pdf_name) == cache_key
        ]
        if len(matches) != 1:
            raise ExtractionError(
                f"No exact encoded_fonts mapping for embedded font {font_name!r}"
            )
        encoded_font = matches[0]
        if not encoded_font.reference_path.is_file():
            raise ExtractionError(
                f"Reference font does not exist: {encoded_font.reference_path}"
            )
        try:
            font = load_reference_font(encoded_font.reference_path, font_name)
        except (LookupError, OSError) as exc:
            raise ExtractionError(
                f"Cannot load configured reference font {encoded_font.reference_path}: {exc}"
            ) from exc
        cache[cache_key] = (encoded_font.reference_path, font)
    return cache[cache_key]


def unique_cmap_candidates(cmap: dict[int, str]) -> list[tuple[int, str]]:
    """Keep the lowest codepoint for each glyph represented in a cmap."""
    codepoints_by_glyph: dict[str, int] = {}
    for codepoint, glyph_name in cmap.items():
        previous = codepoints_by_glyph.get(glyph_name)
        if previous is None or codepoint < previous:
            codepoints_by_glyph[glyph_name] = codepoint
    return [(codepoint, glyph_name) for glyph_name, codepoint in codepoints_by_glyph.items()]


def _reference_pixels(
    font: TTFont, cache: dict[int, dict[str, bytes]]
) -> dict[str, bytes]:
    return cache.setdefault(id(font), {})


def match_font(
    document: pymupdf.Document,
    xref: int,
    reference_path: Path,
    font: TTFont,
    profile: dict[str, dict],
    reference_pixel_cache: dict[int, dict[str, bytes]],
    used_cids: set[int],
) -> None:
    """Match used embedded glyphs to Unicode glyphs by rasterized outlines."""
    source_glyphs = embedded_glyphs(document, xref)
    _, extension, font_type, _ = document.extract_font(xref)
    extension = extension.lower()
    if extension in {"cff", "cid"}:
        source_glyphs = tuple(
            source_glyph for source_glyph in source_glyphs
            if (match := re.fullmatch(r"cid(\d+)", source_glyph.name))
            and int(match.group(1)) in used_cids
        )
    elif extension in {"ttf", "otf"} and font_type == "Type0":
        if "CIDToGIDMap" in document.xref_object(xref, compressed=True):
            raise ExtractionError(
                f"Cannot safely build used-glyph profile for xref={xref}: "
                "CIDToGIDMap is not identity"
            )
        source_glyphs = tuple(
            source_glyph for glyph_id, source_glyph in enumerate(source_glyphs)
            if glyph_id in used_cids
        )
    else:
        raise ExtractionError(
            f"Cannot resolve PDF character codes for xref={xref}, "
            f"type={font_type}, ext={extension}"
        )

    units = font["head"].unitsPerEm
    glyph_set = font.getGlyphSet()
    candidates = unique_cmap_candidates(font.getBestCmap())
    reference_pixels = _reference_pixels(font, reference_pixel_cache)
    for source_glyph in source_glyphs:
        name = source_glyph.name
        glyph = source_glyph.glyph
        embedded_glyph_set = source_glyph.glyph_set
        commands = glyph_commands(glyph, glyph_set=embedded_glyph_set)
        digest = signature(commands)
        if digest in profile:
            continue
        if glyph_bounds(glyph, embedded_glyph_set) is None:
            profile[digest] = {
                "glyph": name,
                "codepoint": 32,
                "unicode": "U+0020",
                "char": " ",
            }
            continue
        pixels = rasterize(commands)
        ranked: list[tuple[int, int]] = []
        for codepoint, reference_name in candidates:
            if reference_name not in reference_pixels:
                reference_pixels[reference_name] = rasterize(
                    glyph_commands(glyph_set[reference_name], 1000 / units, glyph_set)
                )
            score = sum(
                abs(left - right)
                for left, right in zip(pixels, reference_pixels[reference_name])
            )
            ranked.append((score, codepoint))
        if not ranked:
            raise ExtractionError(
                f"Không tìm thấy candidate cho xref={xref}, glyph={name}, "
                f"reference={reference_path.name}"
            )
        ranked.sort()
        codepoint = ranked[0][1]
        profile[digest] = {
            "glyph": name,
            "codepoint": codepoint,
            "unicode": f"U+{codepoint:04X}",
            "char": chr(codepoint),
        }


def build_glyph_profile(
    pdf_path: Path, config: ExtractConfig
) -> dict[str, dict]:
    """Build a profile from the exact font mappings declared in config."""
    if not pdf_path.is_file():
        raise ExtractionError(f"Input PDF does not exist: {pdf_path}")
    if not config.encoded_fonts:
        raise ExtractionError("encoded_fonts is empty after font discovery")
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {pdf_path}: {exc}") from exc
    try:
        used_cids_by_xref = used_type0_cids(
            document,
            tuple(encoded_font.pdf_name for encoded_font in config.encoded_fonts),
        )
        fonts_by_xref = {
            row[0]: row
            for page_number in range(document.page_count)
            for row in document.get_page_fonts(page_number, full=True)
            if row[0] in used_cids_by_xref
        }
        profile: dict[str, dict] = {}
        reference_font_cache: dict[str, tuple[Path, TTFont]] = {}
        reference_pixel_cache: dict[int, dict[str, bytes]] = {}
        for xref, used_cids in sorted(used_cids_by_xref.items()):
            row = fonts_by_xref[xref]
            font_name = row[3]
            LOGGER.info(
                "Profiling %d used CIDs: %s (%s)", len(used_cids), font_name, row[2]
            )
            reference_path, reference_font = get_cached_reference_font(
                font_name, config.encoded_fonts, reference_font_cache
            )
            match_font(
                document,
                xref,
                reference_path,
                reference_font,
                profile,
                reference_pixel_cache,
                used_cids,
            )
    finally:
        document.close()
    if not profile:
        raise ExtractionError("No used CIDs found for configured encoded_fonts")
    return profile


def serialize_glyph_profile(profile: dict[str, dict]) -> str:
    """Serialize a reviewable, stable glyph-profile JSON object."""
    return json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def build_and_write_glyph_profile(pdf_path: Path, config: ExtractConfig) -> int:
    """Build and atomically persist the profile declared by one config."""
    profile = build_glyph_profile(pdf_path, config)
    atomic_write(config.glyph_profile, serialize_glyph_profile(profile))
    return len(profile)


def build_parser() -> argparse.ArgumentParser:
    """Build the config-only CLI for profile generation."""
    parser = argparse.ArgumentParser(
        description="Discover configured PDF fonts and build one CID glyph profile."
    )
    parser.add_argument("--config", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run profile generation without any source outside ``extraction``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        synchronize_encoded_fonts(args.config.resolve())
        config = load_config(args.config.resolve())
        count = build_and_write_glyph_profile(config.input_pdf_path, config)
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {count} glyph signatures to {config.glyph_profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
