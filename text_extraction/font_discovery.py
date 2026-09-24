"""Discover embedded CID fonts and persist their local reference mappings."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import sys

import pymupdf
from fontTools.ttLib import TTCollection, TTFont

from text_extraction.config import load_config
from text_extraction.output import atomic_write
from text_extraction.types import ExtractionError


LOGGER = logging.getLogger(__name__)
REFERENCE_FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"
STYLE_SUFFIXES = (
    "bolditalic",
    "regular",
    "oblique",
    "italic",
    "normal",
    "bold",
)
DEFAULT_STYLE_NAMES = frozenset({"regular", "roman", "book", "normal"})
SUPPORTED_EMBEDDED_FONTS = frozenset({"cff", "cid", "ttf", "otf"})
IDENTITY_ENCODINGS = frozenset({"Identity-H", "Identity-V"})
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True)
class FontDiscoveryResult:
    """The mapping written to one config and fonts without local references."""

    configured: tuple[str, ...]
    missing_reference: tuple[str, ...]
    changed: bool


def normalize_font_name(name: str) -> str:
    """Normalize a PDF or font-table name for family/style comparison."""
    name = _SUBSET_PREFIX.sub("", name)
    return "".join(character for character in name.casefold() if character.isalnum())


def canonical_pdf_font_name(name: str) -> str:
    """Drop only the random subset prefix, retaining a reviewable PDF name."""
    return _SUBSET_PREFIX.sub("", name)


def parse_pdf_font_name(font_name: str) -> tuple[str, str | None]:
    """Split one PDF font name into normalized family and optional style."""
    normalized_name = normalize_font_name(font_name)
    for style in STYLE_SUFFIXES:
        if normalized_name.endswith(style) and normalized_name != style:
            return normalized_name[:-len(style)], style
    return normalized_name, None


def _font_style_priority(font: TTFont, requested_style: str | None) -> int:
    styles = {
        normalize_font_name(name.toUnicode())
        for name in font["name"].names
        if name.nameID == 2
    }
    if requested_style is not None:
        return 0 if requested_style in styles else 1
    return 0 if styles & DEFAULT_STYLE_NAMES else 1


def load_reference_font(reference_path: Path, pdf_font_name: str) -> TTFont:
    """Load the exact configured reference file and select its matching face."""
    family, style = parse_pdf_font_name(pdf_font_name)
    with reference_path.open("rb") as font_file:
        is_collection = font_file.read(4) == b"ttcf"
    fonts = (
        TTCollection(reference_path).fonts
        if is_collection
        else (TTFont(reference_path),)
    )
    matches: list[tuple[int, int, TTFont]] = []
    for index, font in enumerate(fonts):
        family_names = [
            name.toUnicode() for name in font["name"].names if name.nameID == 1
        ]
        if any(normalize_font_name(name) == family for name in family_names):
            matches.append((_font_style_priority(font, style), index, font))
    if matches:
        return min(matches, key=lambda match: match[:2])[2]
    raise LookupError(
        f"Reference font {reference_path} does not match embedded font {pdf_font_name!r}"
    )


def find_reference_font(pdf_font_name: str) -> Path:
    """Search the repository's ``fonts`` directory once for one embedded font."""
    if not REFERENCE_FONTS_DIR.is_dir():
        raise ExtractionError(f"Reference font directory does not exist: {REFERENCE_FONTS_DIR}")
    _, style = parse_pdf_font_name(pdf_font_name)
    matches: list[tuple[int, str, Path]] = []
    for path in sorted(REFERENCE_FONTS_DIR.iterdir(), key=lambda item: item.name.casefold()):
        if path.suffix.casefold() not in {".ttf", ".otf", ".ttc", ".otc"}:
            continue
        try:
            font = load_reference_font(path, pdf_font_name)
        except (LookupError, OSError):
            continue
        matches.append((_font_style_priority(font, style), path.name.casefold(), path))
    if matches:
        return min(matches, key=lambda match: match[:2])[2]
    raise FileNotFoundError(
        f"No reference font in {REFERENCE_FONTS_DIR} matches {pdf_font_name!r}"
    )


def embedded_type0_font_names(pdf_path: Path) -> tuple[str, ...]:
    """Return eligible embedded CID font names found in a PDF, without duplicates."""
    if not pdf_path.is_file():
        raise ExtractionError(f"Input PDF does not exist: {pdf_path}")
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {pdf_path}: {exc}") from exc
    try:
        names: dict[str, str] = {}
        for page in document:
            for row in page.get_fonts(full=True):
                xref, extension, font_type, base_font, _, encoding = row[:6]
                if (
                    xref > 0
                    and font_type == "Type0"
                    and extension.casefold() in SUPPORTED_EMBEDDED_FONTS
                    and encoding in IDENTITY_ENCODINGS
                ):
                    name = canonical_pdf_font_name(base_font)
                    names.setdefault(normalize_font_name(name), name)
        return tuple(sorted(names.values(), key=str.casefold))
    finally:
        document.close()


def _config_relative_path(reference_path: Path, config_path: Path) -> str:
    """Store reference paths relative to the config, so it remains portable."""
    return os.path.relpath(reference_path, config_path.resolve().parent)


def synchronize_encoded_fonts(config_path: Path) -> FontDiscoveryResult:
    """Refresh ``encoded_fonts`` from the configured PDF before extraction.

    The resulting mapping records only embedded CID fonts that have a local
    reference file. Profile building subsequently opens these exact paths and
    never scans the reference-font directory.
    """
    config = load_config(config_path)
    matches: dict[str, str] = {}
    missing: list[str] = []
    for pdf_font_name in embedded_type0_font_names(config.input_pdf_path):
        try:
            reference_path = find_reference_font(pdf_font_name)
        except FileNotFoundError:
            missing.append(pdf_font_name)
            continue
        matches[pdf_font_name] = _config_relative_path(reference_path, config_path)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read config {config_path}: {exc}") from exc
    changed = raw.get("encoded_fonts") != matches
    if changed:
        raw["encoded_fonts"] = matches
        atomic_write(
            config_path,
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        )
    return FontDiscoveryResult(tuple(matches), tuple(missing), changed)


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone font-discovery command parser."""
    parser = argparse.ArgumentParser(
        description="Find embedded PDF fonts with local references and update one config."
    )
    parser.add_argument("--config", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Synchronize the encoded-font mapping for one document config."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        result = synchronize_encoded_fonts(args.config.resolve())
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name in result.missing_reference:
        LOGGER.warning("No local reference font found for embedded font: %s", name)
    action = "Updated" if result.changed else "Kept"
    print(f"{action} {len(result.configured)} encoded-font mappings in {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
