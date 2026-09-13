"""Configuration and glyph-profile loading with validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from extraction.models import (
    DEFAULT_BOTTOM_MARGIN, DEFAULT_CONTENT_SECTIONS, DEFAULT_CONTENT_START,
    DEFAULT_ENCODED_FONTS, DEFAULT_MARKER_PATTERN, DEFAULT_TITLE_PATTERN,
    DEFAULT_TOP_MARGIN, ExtractConfig, ExtractionError, MetadataSpec,
)

def _require_string(value: Any, name: str) -> str:
    """Validate a required non-blank string from configuration."""
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"Config field {name!r} must be a non-empty string")
    return value


def _resolve_path(config_dir: Path, value: Any, name: str) -> Path:
    """Resolve a configured path relative to its config file."""
    path = Path(_require_string(value, name)).expanduser()
    return path if path.is_absolute() else (config_dir / path).resolve()


def load_config(path: Path) -> ExtractConfig:
    """Load one per-PDF JSON config; relative paths use the config directory."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExtractionError("The config root must be a JSON object")

    raw_metadata = raw.get("metadata")
    if not isinstance(raw_metadata, list) or not raw_metadata:
        raise ExtractionError("Config field 'metadata' must be a non-empty list")
    metadata: list[MetadataSpec] = []
    seen_fields: set[str] = set()
    for index, item in enumerate(raw_metadata):
        if not isinstance(item, dict):
            raise ExtractionError(f"metadata[{index}] must be an object")
        spec = MetadataSpec(
            label=_require_string(item.get("label"), f"metadata[{index}].label"),
            field=_require_string(item.get("field"), f"metadata[{index}].field"),
            type=item.get("type", "string"),
            required=item.get("required", True),
        )
        if spec.type not in {"string", "identifiers"}:
            raise ExtractionError(
                f"metadata[{index}].type must be 'string' or 'identifiers'"
            )
        if not isinstance(spec.required, bool):
            raise ExtractionError(f"metadata[{index}].required must be boolean")
        if spec.field in seen_fields or spec.field in {"so_van_bia", "noi_dung"}:
            raise ExtractionError(f"Duplicate or reserved output field: {spec.field}")
        seen_fields.add(spec.field)
        metadata.append(spec)

    def string_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = raw.get(name, list(default))
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ExtractionError(f"Config field {name!r} must be a string list")
        return tuple(value)

    margins = raw.get("page_margins", {})
    if not isinstance(margins, dict):
        raise ExtractionError("Config field 'page_margins' must be an object")
    try:
        top_margin = float(margins.get("top", DEFAULT_TOP_MARGIN))
        bottom_margin = float(margins.get("bottom", DEFAULT_BOTTOM_MARGIN))
    except (TypeError, ValueError) as exc:
        raise ExtractionError("Page margins must be numbers") from exc
    if top_margin < 0 or bottom_margin < 0:
        raise ExtractionError("Page margins cannot be negative")

    expected = raw.get("expected_record_count")
    if expected is not None and (not isinstance(expected, int) or expected < 1):
        raise ExtractionError("expected_record_count must be a positive integer")
    consecutive = raw.get("require_consecutive_numbers", True)
    if not isinstance(consecutive, bool):
        raise ExtractionError("require_consecutive_numbers must be boolean")

    config_dir = path.resolve().parent
    config = ExtractConfig(
        input_pdf=_resolve_path(config_dir, raw.get("input_pdf"), "input_pdf"),
        output_jsonl=_resolve_path(config_dir, raw.get("output_jsonl"), "output_jsonl"),
        glyph_profile=_resolve_path(config_dir, raw.get("glyph_profile"), "glyph_profile"),
        metadata=tuple(metadata),
        title_pattern=_require_string(raw.get("title_pattern", DEFAULT_TITLE_PATTERN), "title_pattern"),
        content_start=_require_string(raw.get("content_start", DEFAULT_CONTENT_START), "content_start"),
        content_sections=string_tuple("content_sections", DEFAULT_CONTENT_SECTIONS),
        marker_pattern=_require_string(raw.get("marker_pattern", DEFAULT_MARKER_PATTERN), "marker_pattern"),
        encoded_fonts=string_tuple("encoded_fonts", DEFAULT_ENCODED_FONTS),
        top_margin=top_margin,
        bottom_margin=bottom_margin,
        expected_record_count=expected,
        require_consecutive_numbers=consecutive,
    )
    for name, pattern in (("title_pattern", config.title_pattern), ("marker_pattern", config.marker_pattern)):
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ExtractionError(f"Invalid {name}: {exc}") from exc
        required_group = "number" if name == "title_pattern" else "id"
        if required_group not in compiled.groupindex:
            raise ExtractionError(f"{name} must define group (?P<{required_group}>...)")
    return config


def load_glyph_profile(path: Path) -> dict[str, str]:
    """Read and validate the signature-to-Unicode glyph profile."""
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read glyph profile {path}: {exc}") from exc
    if not isinstance(profile, dict) or not profile:
        raise ExtractionError("Glyph profile must be a non-empty JSON object")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in profile.items()):
        raise ExtractionError("Glyph profile entries must map strings to strings")
    return profile

