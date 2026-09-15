#!/usr/bin/env python3
"""Export inscription records that contain characters absent from supplied fonts.

The input may be either the formatted JSON array produced by ``extract_pdf.py``
or a JSONL file.  The result retains the original record fields and appends
``ky_tu_khong_ho_tro`` with the unsupported characters and their JSON paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from fontTools.ttLib import TTFont


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load a JSON record array, an object containing ``records``, or JSONL."""
    source = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        records = []
        for line_number, line in enumerate(source.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Dòng {line_number} không phải JSON hợp lệ: {exc.msg}") from exc
            records.append(item)
    else:
        if isinstance(data, dict):
            data = data.get("records")
        if not isinstance(data, list):
            raise ValueError("JSON đầu vào phải là một mảng bản ghi, object có trường 'records', hoặc JSONL.")
        records = data
    if not all(isinstance(item, dict) for item in records):
        raise ValueError("Mỗi bản ghi phải là một JSON object.")
    return records


def supported_codepoints(font_paths: Iterable[Path]) -> set[int]:
    """Return the union of Unicode cmap entries from the supplied font files."""
    supported: set[int] = set()
    for path in font_paths:
        try:
            font = TTFont(path, lazy=True)
        except Exception as exc:  # FontTools exposes several exception classes.
            raise ValueError(f"Không đọc được font {path}: {exc}") from exc
        try:
            for table in font["cmap"].tables:
                if table.isUnicode():
                    supported.update(table.cmap)
        finally:
            font.close()
    return supported


def _text_values(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    """Yield strings and stable JSON-style paths, excluding object keys."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _text_values(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _text_values(item, f"{path}.{key}")


def unsupported_in_record(record: dict[str, Any], supported: set[int]) -> list[dict[str, Any]]:
    """Describe each unsupported character in a record once, with its locations."""
    counts: Counter[str] = Counter()
    locations: dict[str, list[str]] = defaultdict(list)
    for path, value in _text_values(record):
        for character in value:
            # Whitespace is layout rather than a glyph requirement.
            if not character.isspace() and ord(character) not in supported:
                counts[character] += 1
                if path not in locations[character]:
                    locations[character].append(path)
    return [
        {
            "ky_tu": character,
            "ma_unicode": f"U+{ord(character):04X}",
            "so_lan": counts[character],
            "vi_tri": locations[character],
        }
        for character in sorted(counts, key=ord)
    ]


def filter_records(records: list[dict[str, Any]], supported: set[int]) -> list[dict[str, Any]]:
    """Copy and return only records containing a glyph absent from all fonts."""
    result = []
    for record in records:
        unsupported = unsupported_in_record(record, supported)
        if unsupported:
            copied = deepcopy(record)
            copied["ky_tu_khong_ho_tro"] = unsupported
            result.append(copied)
    return result


def write_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Write pretty JSON or JSONL according to the output extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".jsonl":
        payload = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records)
    else:
        payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lọc văn bia có ký tự không được các font chỉ định hỗ trợ.")
    parser.add_argument("--input", required=True, type=Path, help="JSON array hoặc JSONL đầu vào.")
    parser.add_argument("--output", required=True, type=Path, help="JSON/JSONL chỉ chứa văn bia cần rà soát.")
    parser.add_argument("--font", required=True, action="append", type=Path, help="TTF/OTF/TTC tham chiếu; có thể lặp lại.")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.input)
        supported = supported_codepoints(args.font)
        if not supported:
            raise ValueError("Các font không có Unicode cmap để kiểm tra.")
        filtered = filter_records(records, supported)
        write_records(args.output, filtered)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Đã ghi {len(filtered)}/{len(records)} văn bia có ký tự không hỗ trợ vào {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
