from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import pymupdf
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont

from extraction.glyphs import embedded_glyphs, glyph_commands, signature

RASTER_WIDTH = 72
RASTER_HEIGHT = 101

STYLE_SUFFIXES = (
    "bolditalic",
    "regular",
    "oblique",
    "italic",
    "normal",
    "bold",
)
DEFAULT_STYLE_NAMES = frozenset({"regular", "roman", "book", "normal"})


def rasterize(commands: str) -> bytes:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{RASTER_WIDTH}" height="{RASTER_HEIGHT}" '
        f'viewBox="0 0 1000 1400">'
        '<rect width="1000" height="1400" fill="white"/>'
        '<g transform="translate(0 1100) scale(1 -1)">'
        f'<path d="{commands}" fill="black"/>'
        "</g></svg>"
    )

    document = pymupdf.open(stream=svg.encode(), filetype="svg")
    return document[0].get_pixmap(
        colorspace=pymupdf.csGRAY, 
        alpha=False
    ).samples


def glyph_bounds(glyph, glyph_set=None):
    pen = BoundsPen(glyph_set)
    glyph.draw(pen)
    if not pen.bounds:
        return None
    return tuple(round(value, 2) for value in pen.bounds)


def normalize_font_name(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name)
    return "".join(character for character in name.lower() if character.isalnum())


def parse_pdf_font_name(font_name: str) -> tuple[str, str | None]:
    normalized_name = normalize_font_name(font_name)

    for style in STYLE_SUFFIXES:
        if normalized_name.endswith(style) and normalized_name != style:
            return normalized_name[:-len(style)], style

    return normalized_name, None


def font_style_priority(font: TTFont, requested_style: str | None) -> int:
    styles = {
        normalize_font_name(name.toUnicode())
        for name in font["name"].names
        if name.nameID == 2
    }

    if requested_style is not None:
        return 0 if requested_style in styles else 1

    return 0 if styles & DEFAULT_STYLE_NAMES else 1


def load_reference_font(
    reference_path: Path,
    family: str,
    style: str | None,
) -> TTFont:
    with reference_path.open("rb") as font_file:
        is_collection = font_file.read(4) == b"ttcf"

    fonts = TTCollection(reference_path).fonts if is_collection else (TTFont(reference_path),)
    matches = []

    for index, font in enumerate(fonts):
        family_names = [
            name.toUnicode()
            for name in font["name"].names
            if name.nameID == 1
        ]

        if any(normalize_font_name(name) == family for name in family_names):
            matches.append((font_style_priority(font, style), index, font))

    if matches:
        return min(matches, key=lambda match: match[:2])[2]

    raise LookupError(
        f"Không tìm thấy family name khớp với {family!r} "
        f"trong font collection {reference_path}"
    )


def find_reference_font(
    font_name: str,
    reference_dir: Path,
) -> tuple[Path, TTFont]:
    family, style = parse_pdf_font_name(font_name)
    matches = []

    for path in sorted(reference_dir.iterdir(), key=lambda candidate: candidate.name.casefold()):
        if path.suffix.lower() not in {".ttf", ".otf", ".ttc", ".otc"}:
            continue

        try:
            font = load_reference_font(path, family, style)
        except LookupError:
            continue

        matches.append((font_style_priority(font, style), path.name.casefold(), path, font))

    if matches:
        _, _, path, font = min(matches, key=lambda match: match[:2])
        return path, font

    raise FileNotFoundError(
        f"Không tìm thấy reference font cho {font_name!r} trong {reference_dir}"
    )


def get_cached_reference_font(
    font_name: str,
    reference_dir: Path,
    reference_font_cache: dict[str, tuple[Path, TTFont]],
) -> tuple[Path, TTFont]:
    """Cache selected reference fonts to support faster runs without changing matching logic."""
    cache_key = normalize_font_name(font_name)

    if cache_key not in reference_font_cache:
        reference_font_cache[cache_key] = find_reference_font(
            font_name, reference_dir
        )

    return reference_font_cache[cache_key]


def unique_cmap_candidates(cmap: dict[int, str]) -> list[tuple[int, str]]:
    """Remove duplicate glyph candidates to support faster runs without changing matching logic."""
    codepoints_by_glyph: dict[str, int] = {}

    for codepoint, glyph_name in cmap.items():
        previous_codepoint = codepoints_by_glyph.get(glyph_name)
        if previous_codepoint is None or codepoint < previous_codepoint:
            codepoints_by_glyph[glyph_name] = codepoint

    return [
        (codepoint, glyph_name)
        for glyph_name, codepoint in codepoints_by_glyph.items()
    ]


def get_reference_pixel_cache(
    font: TTFont,
    reference_pixel_cache: dict[int, dict[str, bytes]],
) -> dict[str, bytes]:
    """Reuse reference rasters to support faster runs without changing matching logic."""
    return reference_pixel_cache.setdefault(id(font), {})


def match_font(
    document: pymupdf.Document,
    xref: int,
    reference_path: Path,
    font: TTFont,
    profile: dict[str, dict],
    reference_pixel_cache: dict[int, dict[str, bytes]],
) -> None:
    source_glyphs = embedded_glyphs(document, xref)

    units = font["head"].unitsPerEm
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()

    candidates = unique_cmap_candidates(cmap)
    reference_pixels = get_reference_pixel_cache(font, reference_pixel_cache)

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
        ranked = []

        for codepoint, reference_name in candidates:

            if reference_name not in reference_pixels:
                reference_pixels[reference_name] = rasterize(
                    glyph_commands(
                        glyph_set[reference_name], 
                        1000 / units, 
                        glyph_set
                    )
                )

            score = sum(
                abs(a - b)
                for a, b in zip(pixels, reference_pixels[reference_name])
            )
            ranked.append((score, codepoint))

        if not ranked:
            raise RuntimeError(
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    reference_dir = Path("fonts/reference")
    document = pymupdf.open(args.pdf)

    profile: dict[str, dict] = {}
    processed_xrefs = set()
    reference_font_cache: dict[str, tuple[Path, TTFont]] = {}
    reference_pixel_cache: dict[int, dict[str, bytes]] = {}

    for page_number in range(document.page_count):
        for row in document.get_page_fonts(page_number, full=True):
            xref = row[0]
            font_type = row[2]
            font_name = row[3]

            if xref in processed_xrefs:
                continue

            processed_xrefs.add(xref)
            print(f"Processing font: {font_name} ({font_type})")

            reference_path, reference_font = get_cached_reference_font(
                font_name,
                reference_dir,
                reference_font_cache,
            )
            match_font(
                document,
                xref,
                reference_path,
                reference_font,
                profile,
                reference_pixel_cache,
            )

    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(profile)} glyph signatures to {args.output}")


if __name__ == "__main__":
    main()

# python script_name.py --pdf duong/dan/file.pdf --output ketqua.json

# uv run python -m cProfile -s cumulative tools/build_glyph_profiles.py \
#   --pdf "..." \
#   --output "..."