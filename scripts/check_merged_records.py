"""Check whether merged extraction JSON files can serve as Gradio sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VOLUME_PATTERN = re.compile(r"^Tap-(\d+)_", re.IGNORECASE)


def normalized_code(value: object) -> str | None:
    """Mirror Gradio's exact ID match plus numeric leading-zero fallback."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    code = str(value)
    return str(int(code)) if code.isdigit() else code


def load_config(config_path: Path) -> tuple[str, list[str]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    content = config.get("records", {}).get("content", {})
    heading = content.get("start_heading")
    headings = content.get("section_headings", [])
    if not isinstance(heading, str) or not heading.strip() or not isinstance(headings, list):
        raise ValueError(f"Invalid content headings in {config_path}")
    return heading, headings


def check_file(path: Path, config_dir: Path, image_dir: Path | None) -> tuple[int, int]:
    """Print problems for one merged JSON and return error/warning counts."""
    match = VOLUME_PATTERN.match(path.name)
    if not match:
        print(f"SKIP {path.name}: filename does not identify Tap-N")
        return 0, 0
    config_path = config_dir / f"tap_{match.group(1)}.json"
    if not config_path.is_file():
        print(f"FAIL {path.name}: missing config {config_path}")
        return 1, 0
    heading, headings = load_config(config_path)
    if heading not in headings:
        print(f"FAIL {path.name}: start heading is absent from section_headings")
        return 1, 0
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL {path.name}: cannot read JSON: {exc}")
        return 1, 0
    if not isinstance(records, list):
        print(f"FAIL {path.name}: source JSON must be an array")
        return 1, 0

    errors = 0
    warnings = 0
    locations: dict[str, list[str]] = {}
    face_count = 0
    for record_index, record in enumerate(records):
        loc = f"record[{record_index}]"
        if not isinstance(record, dict):
            print(f"FAIL {path.name}: {loc} is not an object")
            errors += 1
            continue
        faces = record.get("noi_dung")
        if not isinstance(faces, list):
            print(f"FAIL {path.name}: {loc}.noi_dung must be an array")
            errors += 1
            continue
        for face_index, face in enumerate(faces):
            face_loc = f"{loc}.noi_dung[{face_index}]"
            if not isinstance(face, dict):
                print(f"FAIL {path.name}: {face_loc} is not an object")
                errors += 1
                continue
            code = face.get("ky_hieu")
            key = normalized_code(code)
            if key is None or not str(code).strip():
                print(f"FAIL {path.name}: {face_loc}.ky_hieu is missing or invalid")
                errors += 1
                continue
            face_count += 1
            locations.setdefault(key, []).append(face_loc)
            sections = face.get("chuyen_muc")
            if not isinstance(sections, list):
                print(f"FAIL {path.name}: {face_loc}.chuyen_muc must be an array")
                errors += 1
                continue
            matching = [section for section in sections
                        if isinstance(section, dict) and section.get("tieu_de") == heading]
            if len(matching) != 1 or not isinstance(matching[0].get("van_ban"), str):
                print(f"FAIL {path.name}: {code} needs exactly one text section {heading!r}")
                errors += 1

    duplicates = {key: locs for key, locs in locations.items() if len(locs) > 1}
    for code, locs in sorted(duplicates.items()):
        print(f"FAIL {path.name}: image code {code} maps to {len(locs)} faces ({'; '.join(locs)})")
        errors += 1

    image_count = 0
    if image_dir is None:
        print(f"INFO {path.name}: no image directory supplied; image matching not checked")
    elif not image_dir.is_dir():
        print(f"FAIL {path.name}: image directory does not exist: {image_dir}")
        errors += 1
    else:
        image_stems = sorted({p.stem for p in image_dir.iterdir()
                              if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES})
        image_count = len(image_stems)
        for code in image_stems:
            key = normalized_code(code)
            matches = locations.get(key, []) if key is not None else []
            if len(matches) != 1:
                print(f"FAIL {path.name}: image {code!r} matches {len(matches)} faces; expected one")
                errors += 1
        if not image_stems:
            print(f"WARN {path.name}: image directory has no supported image files")
            warnings += 1

    status = "PASS" if not errors else "FAIL"
    image_summary = "images unchecked" if image_dir is None else f"{image_count} images checked"
    print(f"{status} {path.name}: {len(records)} records, {face_count} faces; {image_summary}; {errors} errors, {warnings} warnings")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("merged_records"))
    parser.add_argument("--config-dir", type=Path, default=Path("configs"))
    parser.add_argument("--image-dir", type=Path,
                        help="Optional folder of Gradio images to match by filename stem")
    args = parser.parse_args(argv)
    directory = args.directory.expanduser().resolve()
    config_dir = args.config_dir.expanduser().resolve()
    if not directory.is_dir():
        print(f"error: not a directory: {directory}", file=sys.stderr)
        return 2
    files = sorted(directory.glob("Tap-*.json"), key=lambda p: p.name.casefold())
    if not files:
        print(f"No Tap-*.json files found in {directory}", file=sys.stderr)
        return 2
    total_errors = total_warnings = 0
    try:
        for path in files:
            errors, warnings = check_file(
                path, config_dir,
                args.image_dir.expanduser().resolve() if args.image_dir else None,
            )
            total_errors += errors
            total_warnings += warnings
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"\nTotal: {total_errors} errors, {total_warnings} warnings")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
