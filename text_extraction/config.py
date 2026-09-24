"""Configuration and glyph-profile loading with validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from text_extraction.types import EncodedFont, ExtractConfig, ExtractionError, MetadataSpec

def _require_string(value: Any, name: str) -> str:
    """Validate a required non-blank string from configuration."""
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"Config field {name!r} must be a non-empty string")
    return value


def _resolve_path(config_dir: Path, value: Any, name: str) -> Path:
    """Resolve a configured path relative to its config file."""
    path = Path(_require_string(value, name)).expanduser()
    return path if path.is_absolute() else (config_dir / path).resolve()


def _require_object(value: Any, name: str) -> dict[str, Any]:
    """Validate one explicitly configured JSON object."""
    if not isinstance(value, dict):
        raise ExtractionError(f"Config field {name!r} must be an object")
    return value


def _require_exact_keys(
    value: dict[str, Any], name: str, keys: set[str]
) -> None:
    """Reject both missing and stale keys so every behavior is intentional."""
    missing = keys - value.keys()
    unknown = value.keys() - keys
    if missing:
        raise ExtractionError(f"Config field {name!r} is missing: {', '.join(sorted(missing))}")
    if unknown:
        raise ExtractionError(f"Config field {name!r} has unknown keys: {', '.join(sorted(unknown))}")


def _require_string_list(value: Any, name: str) -> tuple[str, ...]:
    """Read a non-empty list of non-blank strings without a fallback."""
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ExtractionError(f"Config field {name!r} must be a non-empty string list")
    return tuple(value)


def _require_non_negative_number(value: Any, name: str) -> float:
    """Read a page margin from configuration."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExtractionError(f"Config field {name!r} must be a number")
    number = float(value)
    if number < 0:
        raise ExtractionError(f"Config field {name!r} cannot be negative")
    return number


def _parse_metadata(value: Any) -> tuple[MetadataSpec, ...]:
    """Validate explicitly declared record metadata fields."""
    if not isinstance(value, list) or not value:
        raise ExtractionError("Config field 'records.metadata' must be a non-empty list")
    metadata: list[MetadataSpec] = []
    seen_fields: set[str] = set()
    for index, item in enumerate(value):
        name = f"records.metadata[{index}]"
        item = _require_object(item, name)
        _require_exact_keys(item, name, {"label", "field", "type", "required"})
        spec = MetadataSpec(
            label=_require_string(item["label"], f"{name}.label"),
            field=_require_string(item["field"], f"{name}.field"),
            type=_require_string(item["type"], f"{name}.type"),
            required=item["required"],
        )
        if spec.type not in {"string", "identifiers"}:
            raise ExtractionError(f"{name}.type must be 'string' or 'identifiers'")
        if not isinstance(spec.required, bool):
            raise ExtractionError(f"{name}.required must be boolean")
        if spec.field in seen_fields or spec.field in {"so_van_bia", "noi_dung"}:
            raise ExtractionError(f"Duplicate or reserved output field: {spec.field}")
        seen_fields.add(spec.field)
        metadata.append(spec)
    return tuple(metadata)


def _parse_encoded_fonts(
    value: Any, config_dir: Path
) -> tuple[EncodedFont, ...]:
    """Read explicit PDF-font to local-reference-font mappings."""
    if not isinstance(value, dict):
        raise ExtractionError("Config field 'encoded_fonts' must be an object")
    fonts: list[EncodedFont] = []
    normalized_names: set[str] = set()
    for pdf_name, reference_path in value.items():
        name = _require_string(pdf_name, "encoded_fonts key")
        normalized = "".join(character for character in name.casefold() if character.isalnum())
        if normalized in normalized_names:
            raise ExtractionError(f"Duplicate encoded font name: {name}")
        normalized_names.add(normalized)
        fonts.append(
            EncodedFont(
                pdf_name=name,
                reference_path=_resolve_path(
                    config_dir, reference_path, f"encoded_fonts.{name}"
                ),
            )
        )
    return tuple(fonts)


def _parse_footnotes(value: Any) -> tuple[str | None, float | None]:
    """Read an explicit footnote filter, or an explicit null to disable it."""
    if value is None:
        return None, None
    footnotes = _require_object(value, "page_filter.footnotes")
    _require_exact_keys(footnotes, "page_filter.footnotes", {"start_pattern", "max_font_size"})
    pattern = _require_string(
        footnotes["start_pattern"], "page_filter.footnotes.start_pattern"
    )
    max_font_size = footnotes["max_font_size"]
    if isinstance(max_font_size, bool) or not isinstance(max_font_size, (int, float)):
        raise ExtractionError("page_filter.footnotes.max_font_size must be a number")
    max_font_size = float(max_font_size)
    if max_font_size <= 0:
        raise ExtractionError("page_filter.footnotes.max_font_size must be positive")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ExtractionError(f"Invalid page_filter.footnotes.start_pattern: {exc}") from exc
    return pattern, max_font_size


def load_config(path: Path) -> ExtractConfig:
    """Load the required PDF-specific JSON configuration.

    Every value that changes decoding or parsing behavior is declared in the
    file.  This loader deliberately has no document-specific defaults and
    rejects stale keys from previous schema versions.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read config {path}: {exc}") from exc
    root = _require_object(raw, "root")
    _require_exact_keys(
        root,
        "root",
        {"input_pdf_path", "paths", "encoded_fonts", "page_filter", "records"},
    )

    paths = _require_object(root["paths"], "paths")
    _require_exact_keys(paths, "paths", {"output_json", "glyph_profile"})
    page_filter = _require_object(root["page_filter"], "page_filter")
    _require_exact_keys(page_filter, "page_filter", {"margins", "footnotes"})
    margins = _require_object(page_filter["margins"], "page_filter.margins")
    _require_exact_keys(margins, "page_filter.margins", {"top", "bottom"})
    records = _require_object(root["records"], "records")
    _require_exact_keys(
        records,
        "records",
        {"title_pattern", "metadata", "content", "face_marker_pattern", "require_consecutive_numbers"},
    )
    content = _require_object(records["content"], "records.content")
    _require_exact_keys(content, "records.content", {"start_heading", "section_headings"})

    consecutive = records["require_consecutive_numbers"]
    if not isinstance(consecutive, bool):
        raise ExtractionError("records.require_consecutive_numbers must be boolean")
    footnote_start_pattern, footnote_max_font_size = _parse_footnotes(
        page_filter["footnotes"]
    )

    config_dir = path.resolve().parent
    config = ExtractConfig(
        input_pdf_path=_resolve_path(
            config_dir, root["input_pdf_path"], "input_pdf_path"
        ),
        output_json=_resolve_path(config_dir, paths["output_json"], "paths.output_json"),
        glyph_profile=_resolve_path(config_dir, paths["glyph_profile"], "paths.glyph_profile"),
        metadata=_parse_metadata(records["metadata"]),
        title_pattern=_require_string(records["title_pattern"], "records.title_pattern"),
        content_start=_require_string(content["start_heading"], "records.content.start_heading"),
        content_sections=_require_string_list(
            content["section_headings"], "records.content.section_headings"
        ),
        marker_pattern=_require_string(
            records["face_marker_pattern"], "records.face_marker_pattern"
        ),
        encoded_fonts=_parse_encoded_fonts(root["encoded_fonts"], config_dir),
        top_margin=_require_non_negative_number(margins["top"], "page_filter.margins.top"),
        bottom_margin=_require_non_negative_number(
            margins["bottom"], "page_filter.margins.bottom"
        ),
        footnote_start_pattern=footnote_start_pattern,
        footnote_max_font_size=footnote_max_font_size,
        require_consecutive_numbers=consecutive,
    )
    for name, pattern, required_group in (
        ("records.title_pattern", config.title_pattern, "number"),
        ("records.face_marker_pattern", config.marker_pattern, "id"),
    ):
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ExtractionError(f"Invalid {name}: {exc}") from exc
        if required_group not in compiled.groupindex:
            raise ExtractionError(f"{name} must define group (?P<{required_group}>...)")
    return config


def load_glyph_profile(path: Path) -> dict[str, dict[str, Any]]:
    """Read and validate the signature-to-Unicode glyph profile."""
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read glyph profile {path}: {exc}") from exc
    if not isinstance(profile, dict) or not profile:
        raise ExtractionError("Glyph profile must be a non-empty JSON object")
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in profile.items():
        if not isinstance(key, str):
            raise ExtractionError("Glyph profile signatures must be strings")
        # This is deliberately the exact on-disk schema emitted by
        # text_extraction.glyph_profile. Extraction must never infer Unicode
        # from an older flat profile or from PyMuPDF's unreliable text value.
        if not isinstance(value, dict):
            raise ExtractionError(
                "Glyph profile entries must be objects emitted by text_extraction.glyph_profile"
            )
        char = value.get("char")
        codepoint = value.get("codepoint")
        unicode_name = value.get("unicode")
        glyph = value.get("glyph")
        if not isinstance(char, str) or not isinstance(codepoint, int) or not isinstance(unicode_name, str) or not isinstance(glyph, str):
            raise ExtractionError(
                "Glyph profile entries must include string glyph/unicode/char and integer codepoint"
            )
        if char != chr(codepoint) or unicode_name != f"U+{codepoint:04X}":
            raise ExtractionError(f"Invalid Unicode fields for glyph profile signature {key}")
        normalized[key] = value
    return normalized
