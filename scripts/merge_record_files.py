"""Merge valid, manual-review and tag-corrected JSON arrays by volume prefix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

TYPE_PATTERN = re.compile(
    r"^(?P<prefix>.+)_(?P<kind>valid|manual-review|tag-corrected)\.json$",
    re.IGNORECASE,
)
BARE_VALID_PATTERN = re.compile(r"^(?P<prefix>Tap-.+)\.json$", re.IGNORECASE)
TYPE_ORDER = {"valid": 0, "tag-corrected": 1, "manual-review": 2}


def face_key(face: object) -> str | None:
    """Normalize face identifiers using Gradio's numeric ID fallback."""
    if not isinstance(face, dict):
        return None
    value = face.get("ky_hieu")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    code = str(value).strip()
    if not code:
        return None
    return str(int(code)) if code.isdigit() else code


def collect_sources(directories: list[Path]) -> dict[str, list[tuple[str, Path]]]:
    """Find recognized files and group them by their shared volume prefix."""
    grouped: dict[str, list[tuple[str, Path]]] = {}
    for directory in directories:
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name.casefold()):
            match = TYPE_PATTERN.fullmatch(path.name)
            if match:
                prefix = match.group("prefix")
                kind = match.group("kind").casefold()
            else:
                # Extracted primary JSONs use the bare volume stem; _invalid
                # and other JSON files are deliberately excluded.
                match = BARE_VALID_PATTERN.fullmatch(path.name)
                if match is None or "_invalid" in path.stem.casefold():
                    continue
                prefix = match.group("prefix")
                kind = "valid"
            grouped.setdefault(prefix, []).append((kind, path))
    return grouped


def config_heading(prefix: str, config_dir: Path) -> str:
    """Load the required source heading from the matching volume config."""
    match = re.match(r"Tap-(\d+)_", prefix, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot determine volume config for {prefix}")
    config_path = config_dir / f"tap_{match.group(1)}.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {config_path}: {exc}") from exc
    heading = config.get("records", {}).get("content", {}).get("start_heading")
    if not isinstance(heading, str) or not heading.strip():
        raise ValueError(f"Missing records.content.start_heading in {config_path}")
    return heading


def gradio_compatible_face(face: object, heading: str) -> bool:
    """Check the face fields Gradio requires when opening an image."""
    key = face_key(face)
    if key is None or not isinstance(face, dict):
        return False
    sections = face.get("chuyen_muc")
    if not isinstance(sections, list):
        return False
    matches = [section for section in sections
               if isinstance(section, dict) and section.get("tieu_de") == heading]
    return len(matches) == 1 and isinstance(matches[0].get("van_ban"), str)


def image_codes(image_dir: Path | None) -> set[str] | None:
    """Return normalized image stems, or None when no image check is available."""
    if image_dir is None or not image_dir.is_dir():
        return None
    codes = set()
    for path in image_dir.iterdir():
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES:
            key = face_key({"ky_hieu": path.stem})
            if key is not None:
                codes.add(key)
    return codes


def merge_grouped(
    grouped: dict[str, list[tuple[str, Path]]], output_directory: Path,
    config_dir: Path, image_dir: Path | None = None,
) -> list[Path]:
    """Merge faces per ID, choosing the highest-priority source for duplicates."""
    output_directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for prefix, sources in sorted(grouped.items(), key=lambda item: item[0].casefold()):
        heading = config_heading(prefix, config_dir)
        available_images = image_codes(image_dir)
        # A winner stores (priority, record, face). The highest priority face
        # for every image ID wins; distinct faces from the same record remain.
        winners: dict[str, tuple[int, int, dict, dict]] = {}
        dropped_without_id = 0
        dropped_incompatible = 0
        dropped_without_image = 0
        source_count = 0
        for kind, path in sorted(
            sources, key=lambda item: (TYPE_ORDER[item[0]], item[1].name.casefold())
        ):
            try:
                content = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Cannot read {path}: {exc}") from exc
            if not isinstance(content, list):
                raise ValueError(f"Expected a JSON array in {path}")
            for record_index, record in enumerate(content):
                if not isinstance(record, dict) or not isinstance(record.get("noi_dung"), list):
                    raise ValueError(f"Expected record with noi_dung array in {path}[{record_index}]")
                source_count += 1
                for face_index, face in enumerate(record["noi_dung"]):
                    key = face_key(face)
                    if key is None:
                        dropped_without_id += 1
                        continue
                    if not gradio_compatible_face(face, heading):
                        dropped_incompatible += 1
                        continue
                    if available_images is not None and key not in available_images:
                        dropped_without_image += 1
                        continue
                    previous = winners.get(key)
                    # On equal source priority, later filenames/records in the
                    # stable traversal win deterministically.
                    if previous is None or TYPE_ORDER[kind] >= previous[0]:
                        winners[key] = (TYPE_ORDER[kind], source_count - 1, record, face)

        # Keep the winning faces together by their original winning record.
        grouped_records: dict[int, dict] = {}
        for _key, (priority, source_index, record, face) in winners.items():
            entry = grouped_records.setdefault(
                source_index,
                {key: value for key, value in record.items() if key != "noi_dung"} | {"noi_dung": []},
            )
            entry["noi_dung"].append(face)
        records = list(grouped_records.values())
        records.sort(key=lambda record: (
            record.get("so_van_bia") is None,
            record.get("so_van_bia", 0) if isinstance(record.get("so_van_bia"), (int, float)) else 0,
        ))

        output = output_directory / f"{prefix}.json"
        output.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(output)
        print(
            f"{prefix}: merged {len(sources)} files -> {output} "
            f"({len(records)} records, {len(winners)} unique Gradio-ready face IDs; "
            f"skipped: {dropped_without_id} without ID, {dropped_incompatible} "
            f"Gradio-incompatible, {dropped_without_image} without image)"
        )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directories", nargs="*", type=Path,
        help="Folders containing JSON files (default: examples and output)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("merged_records"),
        help="Destination for merged files (default: merged_records)",
    )
    parser.add_argument("--config-dir", type=Path, default=Path("configs"))
    parser.add_argument(
        "--image-dir", type=Path,
        help="Optional image folder; when supplied, IDs without matching images are skipped",
    )
    args = parser.parse_args(argv)
    directories = args.directories or [Path("examples"), Path("output")]
    directories = [path.expanduser().resolve() for path in directories]
    missing = [path for path in directories if not path.is_dir()]
    if missing:
        print("error: not a directory: " + ", ".join(map(str, missing)), file=sys.stderr)
        return 1

    try:
        grouped = collect_sources(directories)
        outputs = merge_grouped(
            grouped, args.output_dir.expanduser().resolve(),
            args.config_dir.expanduser().resolve(),
            args.image_dir.expanduser().resolve() if args.image_dir else None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not outputs:
        print("No matching JSON files found", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
