"""Validation and atomic UTF-8 JSON-array output."""

from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from text_extraction.types import ExtractionError
from text_extraction.text import is_invalid_text_character

def validate_json_value(value: Any, location: str = "record") -> None:
    """Recursively reject invalid Unicode before JSON serialization."""
    if isinstance(value, str):
        for char in value:
            if is_invalid_text_character(char) and char != "\n":
                raise ExtractionError(f"Invalid Unicode character U+{ord(char):04X} in {location}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_json_value(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_json_value(item, f"{location}.{key}")


def serialize_json(records: list[dict[str, Any]]) -> str:
    """Serialize validated records as one compact UTF-8 JSON array."""
    _validate_records(records)
    return json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n"


def serialize_pretty_json(records: list[dict[str, Any]]) -> str:
    """Serialize records as indented JSON for human review."""
    _validate_records(records)
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def prepare_records_for_output(
    records: list[dict[str, Any]],
    content_layout: str = "preserve",
    strip_literal_backslashes: bool = False,
) -> list[dict[str, Any]]:
    """Return a copy with optional display-oriented cleanup of ``van_ban``.

    ``preserve`` keeps source line breaks. ``space`` joins PDF line breaks into
    spaces; ``no-space`` removes them. A literal backslash is distinct from
    JSON's escaped representation of a newline and is removed only when
    explicitly requested.
    """
    if content_layout not in {"preserve", "space", "no-space"}:
        raise ExtractionError(
            "content_layout must be 'preserve', 'space', or 'no-space'"
        )
    prepared = deepcopy(records)
    for record in prepared:
        for face in record.get("noi_dung", []):
            for section in face.get("chuyen_muc", []):
                text = section.get("van_ban")
                if not isinstance(text, str):
                    continue
                if content_layout == "space":
                    text = re.sub(r"\s*\n\s*", " ", text)
                    text = re.sub(r" {2,}", " ", text).strip()
                elif content_layout == "no-space":
                    text = re.sub(r"\s*\n\s*", "", text)
                if strip_literal_backslashes:
                    text = text.replace("\\", "")
                section["van_ban"] = text
    return prepared


def _validate_records(records: list[dict[str, Any]]) -> None:
    """Validate record ordering and every nested JSON value."""
    for index, record in enumerate(records):
        if not record or next(reversed(record)) != "noi_dung":
            raise ExtractionError(f"Record {index} does not end with field 'noi_dung'")
        validate_json_value(record, f"record[{index}]")


def atomic_write(path: Path, content: str) -> None:
    """Write content atomically so a failed extraction preserves old output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
