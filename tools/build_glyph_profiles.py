#!/usr/bin/env python3
"""Build the deterministic glyph-signature map used by extract_pdf.py.

This is a maintainer utility.  The proprietary reference fonts are deliberately
not committed; pass paths to legally obtained copies when rebuilding a profile.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
from pathlib import Path

import pymupdf
from fontTools.cffLib import CFFFontSet
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

RASTER_WIDTH = 72
RASTER_HEIGHT = 101


def glyph_commands(glyph, scale: float = 1, glyph_set=None) -> str:
    path_pen = SVGPathPen(glyph_set)
    pen = path_pen if scale == 1 else TransformPen(path_pen, (scale, 0, 0, scale, 0, 0))
    glyph.draw(pen)
    return path_pen.getCommands()


def rasterize(commands: str) -> bytes:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{RASTER_WIDTH}" '
        f'height="{RASTER_HEIGHT}" viewBox="0 0 1000 1400">'
        '<rect width="1000" height="1400" fill="white"/>'
        '<g transform="translate(0 1100) scale(1 -1)">'
        f'<path d="{commands}" fill="black"/></g></svg>'
    )
    document = pymupdf.open(stream=svg.encode(), filetype="svg")
    return document[0].get_pixmap(colorspace=pymupdf.csGRAY, alpha=False).samples


def signature(commands: str) -> str:
    return hashlib.sha256(commands.encode("utf-8")).hexdigest()[:24]


def glyph_bounds(glyph, glyph_set=None, scale: float = 1):
    pen = BoundsPen(glyph_set)
    glyph.draw(pen)
    return tuple(round(value * scale, 2) for value in pen.bounds) if pen.bounds else None


def bounds_distance(left, right) -> float:
    if left is None or right is None:
        return 0 if left == right else float("inf")
    return sum(abs(a - b) for a, b in zip(left, right))


def unicode_priority(codepoint: int):
    # Palatino maps Latin capital Eth and Vietnamese D with stroke to the same
    # outline. This corpus is Vietnamese, so prefer the Vietnamese code point.
    if codepoint in {0x0110, 0x0111}:
        return -1, codepoint
    if 0x4E00 <= codepoint <= 0x9FFF:
        return 0, codepoint
    if 0x3400 <= codepoint <= 0x4DBF:
        return 1, codepoint
    if codepoint <= 0x2FFF:
        return 2, codepoint
    if codepoint <= 0x3134F:
        return 3, codepoint
    return 4, codepoint


def cff_top(document: pymupdf.Document, xref: int):
    font_bytes = document.extract_font(xref)[3]
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(font_bytes), None)
    return cff[cff.fontNames[0]]


def match_subset(
    document: pymupdf.Document,
    xref: int,
    reference_path: Path,
    profile: dict[str, str],
    allowed,
    font_number: int = 0,
) -> None:
    top = cff_top(document, xref)
    font = TTFont(reference_path, fontNumber=font_number)
    units = font["head"].unitsPerEm
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    metrics = font["hmtx"].metrics
    candidates = [(cp, name) for cp, name in cmap.items() if allowed(cp)]
    reference_pixels: dict[str, bytes] = {}

    for name in top.charset[1:]:
        glyph = top.CharStrings[name]
        commands = glyph_commands(glyph)
        pixels = rasterize(commands)
        digest = signature(commands)
        if digest in profile:
            continue
        if glyph_bounds(glyph) is None:
            profile[digest] = " "
            continue
        ranked = []
        for codepoint, reference_name in candidates:
            width = metrics[reference_name][0] * 1000 / units
            if abs(width - glyph.width) > 15:
                continue
            if reference_name not in reference_pixels:
                reference_pixels[reference_name] = rasterize(
                    glyph_commands(glyph_set[reference_name], 1000 / units, glyph_set)
                )
            score = sum(abs(a - b) for a, b in zip(pixels, reference_pixels[reference_name]))
            ranked.append((score, unicode_priority(codepoint), codepoint))
        if not ranked:
            raise RuntimeError(f"No candidate for xref={xref}, glyph={name}")
        ranked.sort()
        profile[digest] = chr(ranked[0][2])


def match_nomna(document: pymupdf.Document, reference_path: Path, profile: dict[str, str]) -> None:
    font = TTFont(reference_path)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    exact = collections.defaultdict(list)
    all_reference = []
    for codepoint, name in cmap.items():
        glyph = glyph_set[name]
        item = (codepoint, name, glyph.width, glyph_bounds(glyph, glyph_set))
        exact[(round(glyph.width, 2), item[3])].append(item)
        all_reference.append(item)

    xrefs = sorted(
        {
            row[0]
            for page_number in range(document.page_count)
            for row in document.get_page_fonts(page_number, full=True)
            if "NomNaTong" in row[3]
        }
    )
    reference_pixels: dict[str, bytes] = {}
    for xref in xrefs:
        top = cff_top(document, xref)
        for name in top.charset[1:]:
            glyph = top.CharStrings[name]
            commands = glyph_commands(glyph)
            digest = signature(commands)
            if digest in profile:
                continue
            bounds = glyph_bounds(glyph)
            candidates = exact.get((round(glyph.width, 2), bounds), [])
            if not candidates:
                candidates = [
                    item
                    for _, _, item in sorted(
                        (
                            bounds_distance(bounds, item[3]),
                            unicode_priority(item[0]),
                            item,
                        )
                        for item in all_reference
                        if abs(item[2] - glyph.width) < 0.1
                    )[:30]
                ]
            if len(candidates) == 1:
                profile[digest] = chr(candidates[0][0])
                continue
            pixels = rasterize(commands)
            ranked = []
            for codepoint, reference_name, _, _ in candidates:
                if reference_name not in reference_pixels:
                    reference_pixels[reference_name] = rasterize(
                        glyph_commands(glyph_set[reference_name], glyph_set=glyph_set)
                    )
                score = sum(
                    abs(a - b) for a, b in zip(pixels, reference_pixels[reference_name])
                )
                ranked.append((score, unicode_priority(codepoint), codepoint))
            if not ranked:
                raise RuntimeError(f"No NomNaTong candidate for xref={xref}, glyph={name}")
            ranked.sort()
            profile[digest] = chr(ranked[0][2])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--nomna", required=True, type=Path)
    parser.add_argument("--palatino", required=True, type=Path)
    parser.add_argument("--palatino-bold", required=True, type=Path)
    parser.add_argument("--palatino-italic", required=True, type=Path)
    parser.add_argument("--palatino-bold-italic", required=True, type=Path)
    parser.add_argument("--pmingliu", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    document = pymupdf.open(args.pdf)
    profile: dict[str, str] = {}
    latin = lambda cp: (32 <= cp <= 0x024F) or (0x1E00 <= cp <= 0x1EFF) or (0x2000 <= cp <= 0x20CF)
    for xref, path in (
        (29, args.palatino),
        (30, args.palatino_bold),
        (54, args.palatino_italic),
        (73, args.palatino_bold_italic),
        (84, args.palatino),
        (86, args.palatino_italic),
    ):
        match_subset(document, xref, path, profile, latin)
    match_nomna(document, args.nomna, profile)
    if args.pmingliu:
        pmingliu_xrefs = sorted(
            {
                row[0]
                for page_number in range(document.page_count)
                for row in document.get_page_fonts(page_number, full=True)
                if "PMingLiU" in row[3]
            }
        )
        for xref in pmingliu_xrefs:
            match_subset(
                document,
                xref,
                args.pmingliu,
                profile,
                lambda cp: 0x3000 <= cp <= 0x3134F,
                1,
            )

    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {len(profile)} glyph signatures to {args.output}")


if __name__ == "__main__":
    main()
