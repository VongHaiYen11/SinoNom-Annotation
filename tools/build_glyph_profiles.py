from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re

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
    pen = (
        path_pen
        if scale == 1
        else TransformPen(path_pen, (scale, 0, 0, scale, 0, 0))
    )
    glyph.draw(pen)
    return path_pen.getCommands()


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


def signature(commands: str) -> str:
    return hashlib.sha256(commands.encode("utf-8")).hexdigest()[:24]


def glyph_bounds(glyph, glyph_set=None):
    pen = BoundsPen(glyph_set)
    glyph.draw(pen)
    if not pen.bounds:
        return None
    return tuple(round(value, 2) for value in pen.bounds)


def normalize_font_name(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name)

    return (
        name
        .lower()
        .replace(",", "")
        .replace("-", "")
        .replace(" ", "")
    )


def find_reference_font(font_name: str, reference_dir: Path) -> Path:
    target = normalize_font_name(font_name)
    for path in reference_dir.glob("*.ttf"):
        print(target, normalize_font_name(path.stem) )
        if normalize_font_name(path.stem) == target:
            return path

    raise FileNotFoundError(
        f"Không tìm thấy reference font cho {font_name!r} trong {reference_dir}"
    )


def load_embedded_font(document: pymupdf.Document, xref: int):
    basename, ext, font_type, content = document.extract_font(xref)
    if not content:
        raise RuntimeError(
            f"Font không có embedded data: xref={xref}, type={font_type}, ext={ext}"
        )

    ext = ext.lower()

    if ext in {"ttf", "otf"}:
        font = TTFont(io.BytesIO(content))
        units = font["head"].unitsPerEm
        glyph_set = font.getGlyphSet()
        return [
            (name, glyph_set[name])
            for name in glyph_set.keys()
        ]

    if ext in {"cff", "cid"}:
        cff = CFFFontSet()
        cff.decompile(io.BytesIO(content), None)
        top = cff[cff.fontNames[0]]
        return [
            (name, top.CharStrings[name])
            for name in top.charset[1:]
        ]

    if ext in {"pfa", "pfb"}:
        raise RuntimeError(
            f"Type1 PFA/PFB cần xử lý qua file tạm; xref={xref}, ext={ext}"
        )

    raise RuntimeError(
        f"Không hỗ trợ embedded font: xref={xref}, type={font_type}, ext={ext}"
    )


def match_font(
    document: pymupdf.Document,
    xref: int,
    reference_path: Path,
    profile: dict[str, dict],
) -> None:
    embedded_glyphs = load_embedded_font(document, xref)

    font = TTFont(reference_path)
    units = font["head"].unitsPerEm
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    metrics = font["hmtx"].metrics

    candidates = list(cmap.items())
    reference_pixels: dict[str, bytes] = {}

    for name, glyph in embedded_glyphs:
        commands = glyph_commands(glyph)
        digest = signature(commands)

        if digest in profile:
            continue

        if glyph_bounds(glyph) is None:
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

    for page_number in range(document.page_count):
        for row in document.get_page_fonts(page_number, full=True):
            xref = row[0]
            font_type = row[2]
            font_name = row[3]

            if xref in processed_xrefs:
                continue

            processed_xrefs.add(xref)
            print(f"Processing font: {font_name} ({font_type})")

            reference_font = find_reference_font(font_name, reference_dir)
            match_font(document, xref, reference_font, profile)

    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(profile)} glyph signatures to {args.output}")


if __name__ == "__main__":
    main()

# python script_name.py --pdf duong/dan/file.pdf --output ketqua.json