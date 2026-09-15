"""Create a visually faithful PDF with an invisible, searchable Unicode layer."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import tempfile

import pymupdf
from fontTools.ttLib import TTFont, TTLibError

from extraction.decoder import GlyphDecoder
from extraction.models import ExtractConfig, ExtractionError, TextLine
from extraction.config import load_glyph_profile


@dataclass(frozen=True)
class _UnicodeFont:
    embed_path: Path
    cmap: dict[int, str]
    metrics: dict[str, tuple[int, int]]
    units_per_em: int


def _load_unicode_font(font_path: Path, temporary_dir: Path) -> _UnicodeFont:
    try:
        candidates: list[tuple[int, TTFont]] = []
        for font_number in range(16):
            try:
                candidate = TTFont(font_path, fontNumber=font_number)
            except (IndexError, TTLibError):
                break
            candidates.append((font_number, candidate))
        if not candidates:
            raise ValueError("font collection contains no faces")
        _, font = max(candidates, key=lambda item: len(item[1].getBestCmap()))
        embed_path = temporary_dir / f"unicode-{len(list(temporary_dir.iterdir()))}.ttf"
        font.save(embed_path)
        return _UnicodeFont(
            embed_path,
            font.getBestCmap(),
            font["hmtx"].metrics,
            font["head"].unitsPerEm,
        )
    except Exception as exc:
        raise ExtractionError(f"Cannot read Unicode font {font_path}: {exc}") from exc


def _require_font_coverage(lines: list[TextLine], fonts: list[_UnicodeFont]) -> None:
    coverage = set().union(*(font.cmap for font in fonts))
    missing = sorted(
        {ord(char) for line in lines for char in line.text if not char.isspace()}
        - coverage
    )
    if missing:
        preview = ", ".join(f"U+{codepoint:04X}" for codepoint in missing[:12])
        suffix = " …" if len(missing) > 12 else ""
        raise ExtractionError(
            f"Unicode fonts do not cover extracted text: {preview}{suffix}"
        )


def _font_runs(text: str, fonts: list[_UnicodeFont]) -> list[tuple[int, str]]:
    runs: list[tuple[int, str]] = []
    current_index: int | None = None
    for char in text:
        index = next((i for i, font in enumerate(fonts) if ord(char) in font.cmap), 0)
        if index != current_index:
            runs.append((index, char))
            current_index = index
        else:
            runs[-1] = (index, runs[-1][1] + char)
    return runs


def _advance(text: str, font: _UnicodeFont, font_size: float) -> float:
    return sum(font.metrics[font.cmap[ord(char)]][0] for char in text) * font_size / font.units_per_em


def export_searchable_pdf(
    config: ExtractConfig,
    output_pdf: Path,
    unicode_fonts: list[Path],
    dpi: int = 150,
    pages: set[int] | None = None,
) -> None:
    """Rasterize original pages and add an invisible Unicode text layer.

    The source PDF is never modified.  The raster background avoids retaining
    its broken text layer, so copy/search sees only the newly embedded Unicode.
    """
    if dpi < 72:
        raise ExtractionError("DPI must be at least 72")
    if not config.input_pdf.is_file():
        raise ExtractionError(f"Input PDF does not exist: {config.input_pdf}")
    if not unicode_fonts:
        raise ExtractionError("At least one Unicode font is required")
    if any(not font.is_file() for font in unicode_fonts):
        raise ExtractionError("One or more Unicode fonts do not exist")
    if any(font.suffix.lower() != ".ttf" for font in unicode_fonts):
        raise ExtractionError(
            "Unicode fonts must be standalone .ttf files; use tools/extract_ttc_face.py"
        )

    profile = load_glyph_profile(config.glyph_profile)
    source = pymupdf.open(config.input_pdf)
    try:
        decoder = GlyphDecoder(source, profile, config.encoded_fonts)
        lines = decoder.extract_lines(
            config.top_margin,
            config.bottom_margin,
            config.footnote_start_pattern,
            config.footnote_min_y,
            config.footnote_max_font_size,
        )
        with tempfile.TemporaryDirectory(prefix="searchable-pdf-") as directory:
            fonts = [_load_unicode_font(font, Path(directory)) for font in unicode_fonts]
            by_page: dict[int, list[TextLine]] = defaultdict(list)
            for line in lines:
                by_page[line.page_number].append(line)
            selected_lines = [
                line for page, page_lines in by_page.items()
                if pages is None or page in pages
                for line in page_lines
            ]
            _require_font_coverage(selected_lines, fonts)

            result = pymupdf.open()
            try:
                scale = dpi / 72
                for page_index, source_page in enumerate(source):
                    if pages is not None and page_index + 1 not in pages:
                        continue
                    page = result.new_page(width=source_page.rect.width, height=source_page.rect.height)
                    pixmap = source_page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale), alpha=False
                    )
                    page.insert_image(page.rect, pixmap=pixmap)
                    for line in by_page[page_index + 1]:
                        baseline = line.y1 - max(1.0, line.font_size * 0.18)
                        x = line.x0
                        font_size = max(line.font_size, 1.0)
                        for font_index, text in _font_runs(line.text, fonts):
                            font = fonts[font_index]
                            page.insert_text(
                                (x, baseline), text, fontsize=font_size,
                                fontname=f"unicode_layer_{font_index}",
                                fontfile=str(font.embed_path), render_mode=3, overlay=True,
                            )
                            x += _advance(text, font, font_size)
                output_pdf.parent.mkdir(parents=True, exist_ok=True)
                result.save(output_pdf, garbage=4, deflate=True)
            finally:
                result.close()
    finally:
        source.close()
