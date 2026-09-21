"""Report JSON records containing characters absent from a supported charset."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Input JSON must contain a list of records")
    return data


def _unsupported(value: Any, supported: set[int], path: str, findings: dict[str, Counter[str]]) -> None:
    if isinstance(value, str):
        for character in value:
            if ord(character) not in supported:
                findings.setdefault(character, Counter())[path] += 1
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _unsupported(item, supported, f"{path}[{index}]", findings)
    elif isinstance(value, dict):
        for key, item in value.items():
            _unsupported(item, supported, f"{path}.{key}", findings)


def filter_records(records: list[dict[str, Any]], supported_codepoints: set[int]) -> list[dict[str, Any]]:
    """Return copies of records containing unsupported characters and evidence."""
    result = []
    for record in records:
        findings: dict[str, Counter[str]] = {}
        _unsupported(record, supported_codepoints, "$", findings)
        if findings:
            copied = dict(record)
            copied["ky_tu_khong_ho_tro"] = [{"ky_tu": character, "ma_unicode": f"U+{ord(character):04X}", "so_lan": sum(paths.values()), "vi_tri": list(paths)} for character, paths in sorted(findings.items())]
            result.append(copied)
    return result


def write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
