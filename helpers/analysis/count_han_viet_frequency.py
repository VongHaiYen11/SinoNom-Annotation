"""Count Hán Việt syllables and adjacent two-syllable pairs per volume.

Run: python helpers/analysis/count_han_viet_frequency.py --top 20
Optional: --input-dir outputs/merged_records --output-dir outputs/han_viet_frequency
Default stdout is a JSON report with the top 20 entries per list. Use --top 0
for all entries, or --format text for readable output. report.json always
contains the complete sorted lists, regardless of --top.
Pairs are adjacent syllables, not necessarily lexical compound words.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parents[2]
FIELDS = ["term", "count", "frequency_pct", "inscription_count", "inscription_pct"]
SUMMARY_HEADING = re.compile(r"^\s*toát\s+yếu\b", re.MULTILINE)


def segments(text: str) -> tuple[list[list[str]], bool]:
    """Normalize transcription; punctuation, damage and nonletters break pairs."""
    text = unicodedata.normalize("NFC", text).replace("Ð", "Đ").replace("ð", "đ").lower()
    heading = SUMMARY_HEADING.search(text)
    if heading:
        text = text[:heading.start()]
    result: list[list[str]] = []
    words: list[str] = []
    letters: list[str] = []

    def finish_word() -> None:
        if letters:
            words.append("".join(letters))
            letters.clear()

    def finish_segment() -> None:
        finish_word()
        if words:
            result.append(words.copy())
            words.clear()

    for char in text:
        # Count Latin-script transcription only, not residual Hán/Nôm glyphs.
        if unicodedata.category(char).startswith("L") and "LATIN" in unicodedata.name(char, ""):
            letters.append(char)
        elif char.isspace():
            finish_word()
        else:
            finish_segment()
    finish_segment()
    return result, heading is not None


def frequency_rows(counts: Counter, documents: Counter, valid: int) -> list[dict]:
    total = sum(counts.values())
    return [
        {"term": term, "count": count,
         "frequency_pct": round(100 * count / total, 6),
         "inscription_count": documents[term],
         "inscription_pct": round(100 * documents[term] / valid, 6)}
        for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def analyze_volume(path: Path) -> tuple[dict, dict[str, list[dict]]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected an array of inscription records")
    counts = {kind: Counter() for kind in ("single", "pairs")}
    documents = {kind: Counter() for kind in counts}
    valid = 0
    missing = []
    contaminated = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: record {index} must be an object")
        local = {kind: Counter() for kind in counts}
        identity = {"record_index": index, "so_van_bia": record.get("so_van_bia")}
        for face in record.get("noi_dung", []):
            for section in face.get("chuyen_muc", []):
                if section.get("tieu_de", "").strip() != "Phiên âm Hán Việt":
                    continue
                text = section.get("van_ban", "")
                if not isinstance(text, str):
                    raise ValueError(f"{path}: record {index} transcription must be text")
                parts, trimmed = segments(text)
                if trimmed:
                    contaminated.append({**identity, "ky_hieu": face.get("ky_hieu")})
                for words in parts:
                    local["single"].update(words)
                    local["pairs"].update(f"{a} {b}" for a, b in zip(words, words[1:]))
        if not local["single"]:
            missing.append(identity)
            continue
        valid += 1
        for kind in counts:
            counts[kind].update(local[kind])
            documents[kind].update(local[kind].keys())
    summary = {
        "source_file": path.name, "total_inscriptions": len(records),
        "valid_inscriptions": valid, "missing_transcriptions": len(missing),
        "missing_records": missing, "contaminated_sections": len(contaminated),
        "trimmed_sections": contaminated,
        "total_single": sum(counts["single"].values()),
        "total_pairs": sum(counts["pairs"].values()),
        "single_types_below_20": sum(count < 20 for count in counts["single"].values()),
        "pair_types_below_20": sum(count < 20 for count in counts["pairs"].values()),
    }
    return summary, {kind: frequency_rows(counts[kind], documents[kind], valid) for kind in counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "outputs" / "merged_records")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "han_viet_frequency")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be nonnegative")
    paths = sorted(args.input_dir.glob("*.json"))
    if not paths:
        parser.error(f"No JSON files found in {args.input_dir}")
    # Validate and analyze all inputs before writing any results.
    analyses = [(path, *analyze_volume(path)) for path in paths]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    volumes = []
    for path, summary, tables in analyses:
        summaries.append(summary)
        volumes.append({**summary, **tables})
        if args.format == "text":
            print(f"\n{path.stem}: {summary['valid_inscriptions']}/{summary['total_inscriptions']} bia hợp lệ")
            print(f"Số tiếng đơn khác nhau xuất hiện dưới 20 lần: {summary['single_types_below_20']}")
            print(f"Số cặp hai tiếng khác nhau xuất hiện dưới 20 lần: {summary['pair_types_below_20']}")
        for kind, rows in tables.items():
            output = args.output_dir / f"{path.stem}_{kind}.csv"
            with output.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            if args.format == "text":
                print("Tiếng đơn:" if kind == "single" else "Cặp hai tiếng:")
                for row in (rows[:args.top] if args.top else rows):
                    print(f"  {row['term']}: {row['count']} lần; {row['inscription_count']} bia")
    (args.output_dir / "summary.json").write_text(
        json.dumps({"volumes": summaries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "pair_definition": "Adjacent two-syllable pairs, not necessarily compound words",
        "sort_order": "count descending, term ascending",
        "volumes": volumes,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        printed = {**report, "top": args.top, "volumes": [
            {**volume, **{kind: volume[kind][:args.top] if args.top else volume[kind]
                         for kind in ("single", "pairs")}}
            for volume in volumes
        ]}
        print(json.dumps(printed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
