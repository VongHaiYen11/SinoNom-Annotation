"""Validation and atomic UTF-8 JSONL output."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from extraction.models import ExtractionError
from extraction.text import is_invalid_text_character

def validate_json_value(value: Any, location: str = "record") -> None:
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


def serialize_jsonl(records: list[dict[str, Any]]) -> str:
    for index, record in enumerate(records):
        if not record or next(reversed(record)) != "noi_dung":
            raise ExtractionError(f"Record {index} does not end with field 'noi_dung'")
        validate_json_value(record, f"record[{index}]")
    return "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)


def atomic_write(path: Path, content: str) -> None:
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
