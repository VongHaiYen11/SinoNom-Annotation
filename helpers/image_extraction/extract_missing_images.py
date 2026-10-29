"""Extract complete inscription faces requested by a copy report from configured PDFs.

Run from any directory: python helpers/image_extraction/extract_missing_images.py --dry-run
Images are ordered by PDF position and assigned before filtering missing IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
from pathlib import Path
import re
import sys

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from helpers.text_extraction.config import load_config, load_glyph_profile
from helpers.text_extraction.decoder import GlyphDecoder
from helpers.text_extraction.output import atomic_write
from helpers.text_extraction.parser import _match_label


def normalize_id(value: object) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"Invalid face ID: {value!r}")
    return str(int(text))


def missing_ids(report: dict) -> set[str]:
    values = list(report.get("missing_ids", []))
    for group in report.get("groups", []):
        values.extend(group.get("missing_ids", []))
    return {normalize_id(value) for value in values}


def inscription_ranges(lines, title_pattern: str, page_count: int):
    """Yield metadata IDs and spatial boundaries, including text-invalid records."""
    title = re.compile(title_pattern)
    starts = [(i, int(m.group("number"))) for i, line in enumerate(lines)
              if (m := title.fullmatch(line.text))]
    if not starts:
        raise ValueError("No inscription headings decoded")
    for pos, (index, number) in enumerate(starts):
        stop = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        ids = []
        for j in range(index + 1, stop):
            value = _match_label(lines[j].text, "Kí hiệu VNCHN")
            if value is None:
                continue
            # Numeric-only continuation lines belong to the metadata value.
            for following in lines[j + 1:stop]:
                if (value.strip() and not value.rstrip().endswith(("/", ",", ";"))) or not re.fullmatch(r"[\d\s/.,;–-]+", following.text):
                    break
                value += " " + following.text
            ids = [normalize_id(x) for x in re.findall(r"\d+", value)]
            break
        first = lines[index]
        next_line = lines[stop] if stop < len(lines) else None
        yield {"so_van_bia": number, "ids": ids,
               "start": (first.page_number, first.y0),
               "end": (next_line.page_number, next_line.y0) if next_line else (page_count + 1, 0)}


def group_strips(images: list[dict]) -> list[dict]:
    """Join vertically adjacent strips with matching edges and pixel density."""
    groups = []
    for info in sorted(images, key=lambda im: (im["bbox"][1], im["bbox"][0])):
        rect = pymupdf.Rect(info["bbox"])
        # Small inline glyph images and decorative marks are not rubbings.
        if rect.width < 60 or rect.height < 35 or info["width"] < 150:
            continue
        scale = max(info["width"] / rect.width, info["height"] / rect.height)
        candidates = []
        for group in groups:
            previous = pymupdf.Rect(group["bbox"])
            if (abs(previous.x0 - rect.x0) <= 1 and abs(previous.x1 - rect.x1) <= 1
                    and abs(previous.y1 - rect.y0) <= 1
                    and abs(group["scale"] - scale) <= 0.03 * scale):
                candidates.append(group)
        if len(candidates) == 1:
            group = candidates[0]
            group["bbox"] = list(pymupdf.Rect(group["bbox"]) | rect)
            group["scale"] = max(group["scale"], scale)
            group["strips"] += 1
        else:
            groups.append({"bbox": list(rect), "scale": scale, "strips": 1})
    return sorted(groups, key=lambda g: (g["bbox"][1], g["bbox"][0]))


def face_candidates(document, inscription):
    start_page, start_y = inscription["start"]
    end_page, end_y = inscription["end"]
    faces = []
    for page_number in range(start_page, min(end_page, len(document)) + 1):
        page = document[page_number - 1]
        images = []
        for info in page.get_image_info():
            rect = pymupdf.Rect(info["bbox"])
            if page_number == start_page and rect.y0 < start_y:
                continue
            if page_number == end_page and rect.y1 > end_y:
                continue
            images.append(info)
        for group in group_strips(images):
            faces.append({"page": page_number, **group})
    return faces


def export_face(document, face, destination: Path):
    # Rendering the exact image region honors PDF transforms, soft masks and
    # strip placement; native pixel density avoids a fixed-DPI resize.
    page = document[face["page"] - 1]
    rect = pymupdf.Rect(face["bbox"])
    if page.rotation:
        rect = rect * page.rotation_matrix
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(face["scale"], face["scale"]),
                             clip=rect, colorspace=pymupdf.csRGB, alpha=False)
    temporary = destination.with_suffix(".tmp.png")
    try:
        pixmap.save(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


# Explicit, user-verified exceptions. Pages are one-based PDF pages.
VERIFIED_FACES = {
    ("tap_3", 103): [("20325", 507)],
    ("tap_3", 104): [("20324", 510)],
    ("tap_3", 87): [("35273", 450)],
    ("tap_2", 50): [("22695", 362), ("22696", 363), ("22697", 364)],
    ("tap_4", 146): [("33651a", 548), ("33651b", 549)],
    ("tap_3", 130): [("45233", 611), ("45234", 612)],
    ("tap_4", 162): [("48889", 603)],
    ("tap_4", 143): [("42893", 535)],
}


def verified_matches(document, inscription, volume, requested):
    """Return only confirmed pages; a missing/ambiguous page still needs review."""
    assignments = VERIFIED_FACES.get((volume, inscription["so_van_bia"]))
    if assignments is None:
        return None
    result = {}
    for name, page_number in assignments:
        identifier = normalize_id(re.match(r"[0-9]+", name).group())
        if identifier not in requested:
            continue
        faces = [{"page": page_number, **group} for group in
                 group_strips(document[page_number - 1].get_image_info())]
        result.setdefault(identifier, []).append({"name": name, "page": page_number,
                                                  "candidates": faces,
                                                  "face": faces[0] if len(faces) == 1 else None})
    return result


def run(args) -> dict:
    requested = missing_ids(json.loads(args.report.read_text(encoding="utf-8")))
    matches = {identifier: [] for identifier in requested}
    errors = []
    configs = sorted(args.config_dir.glob("tap_*.json"))
    if not configs:
        raise ValueError(f"No tap_*.json configs in {args.config_dir}")
    # Analyze all volumes before writing: duplicate IDs must never win silently.
    for path in configs:
        print(f"Analyzing {path.name}...", flush=True)
        try:
            config = load_config(path.resolve())
            with pymupdf.open(config.input_pdf_path) as document:
                decoder = GlyphDecoder(document, load_glyph_profile(config.glyph_profile),
                                       tuple(font.pdf_name for font in config.encoded_fonts))
                lines = decoder.extract_lines(config.top_margin, config.bottom_margin,
                                              config.footnote_start_pattern,
                                              config.footnote_max_font_size)
                for inscription in inscription_ranges(lines, config.title_pattern, len(document)):
                    verified = verified_matches(document, inscription, path.stem, requested)
                    if verified is not None:
                        for identifier, outputs in verified.items():
                            matches[identifier].append({
                                "id": identifier, "volume": path.stem,
                                "pdf": str(config.input_pdf_path),
                                "so_van_bia": inscription["so_van_bia"],
                                "metadata_page": inscription["start"][0],
                                "outputs": outputs, "verified_override": True,
                                "status": "planned" if all(o["face"] for o in outputs) else "needs_review",
                                "reason": "User-confirmed face/page assignment",
                            })
                        continue
                    targets = requested.intersection(inscription["ids"])
                    if not targets:
                        continue
                    faces = face_candidates(document, inscription)
                    valid = len(faces) == len(inscription["ids"]) and len(set(inscription["ids"])) == len(inscription["ids"])
                    for identifier in targets:
                        item = {"id": identifier, "volume": path.stem,
                                "pdf": str(config.input_pdf_path), "so_van_bia": inscription["so_van_bia"],
                                "metadata_page": inscription["start"][0],
                                "ids": inscription["ids"], "candidates": faces,
                                "status": "planned" if valid else "needs_review"}
                        if valid:
                            item["face"] = faces[inscription["ids"].index(identifier)]
                        else:
                            item["reason"] = "Image count differs from ID count, or repeated metadata IDs"
                        matches[identifier].append(item)
        except Exception as exc:
            errors.append({"config": str(path), "error": str(exc)})
            print(f"  ERROR: {exc}", file=sys.stderr)
    results = []
    for identifier in sorted(requested, key=int):
        options = matches[identifier]
        if not options:
            item = {"id": identifier, "status": "not_found"}
        elif len(options) > 1:
            item = {"id": identifier, "status": "needs_review", "reason": "ID belongs to multiple inscriptions", "matches": options}
        else:
            item = options[0]
        if item["status"] == "planned":
            outputs = item.get("outputs", [{"name": identifier, "face": item.get("face")}])
            for output in outputs:
                destination = args.output_dir / f"{output['name'].zfill(5)}.png"
                output["destination"] = str(destination)
                if errors:
                    output.update(status="needs_review", reason="Incomplete volume scan; duplicate IDs cannot be excluded")
                elif destination.exists() and not args.overwrite:
                    output["status"] = "already_exists"
                elif args.dry_run:
                    output["status"] = "planned"
                else:
                    try:
                        args.output_dir.mkdir(parents=True, exist_ok=True)
                        with pymupdf.open(item["pdf"]) as document:
                            export_face(document, output["face"], destination)
                        output["status"] = "extracted"
                    except Exception as exc:
                        output.update(status="needs_review", reason=f"Export failed: {exc}")
            item["outputs"] = outputs
            statuses = {o["status"] for o in outputs}
            item["status"] = ("needs_review" if "needs_review" in statuses else
                              "extracted" if "extracted" in statuses else
                              "planned" if "planned" in statuses else "already_exists")
        results.append(item)
    report = {"input_report": str(args.report.resolve()), "dry_run": args.dry_run,
              "totals": dict(Counter(item["status"] for item in results)),
              "errors": errors, "results": results}
    if not args.dry_run:
        atomic_write(args.output_dir / "extraction_report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["totals"], ensure_ascii=False))
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "helpers/image_extraction/copy_report.json")
    parser.add_argument("--config-dir", type=Path, default=ROOT / "helpers" / "configs")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/extracted_images")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    try:
        report = run(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1 if report["errors"] or any(item["status"] in {"needs_review", "not_found"} for item in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
