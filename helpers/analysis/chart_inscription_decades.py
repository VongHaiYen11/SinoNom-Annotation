"""Extract Gregorian years from inscription metadata and count ten-year bins."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
YEAR_PATTERN = re.compile(r"(?<!\w)[12]\d{3}(?!\w)")


def extract_years(value: object) -> list[int]:
    """Read explicit Gregorian years only; do not guess from reign names."""
    if not isinstance(value, str):
        return []
    return sorted({int(match.group()) for match in YEAR_PATTERN.finditer(value)})


def analyze(input_dir: Path, multiple_years: str) -> list[dict]:
    paths = sorted(input_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"No JSON files found in {input_dir}")
    rows = []
    for path in paths:
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError(f"{path}: expected an array of inscription records")
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(f"{path}: record {index} is not an object")
            raw = record.get("nien_dai", "")
            years = extract_years(raw)
            year = None
            if len(years) == 1:
                year = years[0]
            elif years and multiple_years != "exclude":
                year = years[0] if multiple_years == "earliest" else years[-1]
            rows.append({
                "source_file": path.name,
                "record_index": index,
                "so_van_bia": record.get("so_van_bia", ""),
                "ten_bia": record.get("ten_bia", ""),
                "nien_dai": raw,
                "candidate_years": ";".join(map(str, years)),
                "selected_year": year if year is not None else "",
                "decade_start": year // 10 * 10 if year is not None else "",
                "status": "missing_year" if not years else (
                    "multiple_years" if len(years) > 1 else "ok"
                ),
            })
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "outputs" / "merged_records")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "inscription_decades")
    parser.add_argument("--multiple-years", choices=["earliest", "latest", "exclude"], default="earliest",
                        help="How to handle inscriptions with multiple explicit years (default: earliest)")
    args = parser.parse_args()
    rows = analyze(args.input_dir, args.multiple_years)
    counts = Counter(row["decade_start"] for row in rows if row["selected_year"] != "")
    if not counts:
        parser.error("No explicit Gregorian years found")
    bins = list(range(min(counts), max(counts) + 1, 10))
    decade_rows = [{"decade_start": start, "decade_end": start + 9,
                    "count": counts[start]} for start in bins]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "inscription_years.csv", rows, list(rows[0]))
    write_csv(args.output_dir / "records_needing_review.csv",
              [row for row in rows if row["status"] != "ok"], list(rows[0]))
    write_csv(args.output_dir / "decade_counts.csv", decade_rows,
              ["decade_start", "decade_end", "count"])
    total_counted = sum(counts.values())
    summary = {
        "total_records": len(rows), "counted_records": total_counted,
        "excluded_records": len(rows) - total_counted,
        "missing_year_records": sum(row["status"] == "missing_year" for row in rows),
        "multiple_year_records": sum(row["status"] == "multiple_years" for row in rows),
        "multiple_year_policy": args.multiple_years,
        "counting_unit": "One JSON record, regardless of number of inscription faces",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fig, ax = plt.subplots(figsize=(max(12, len(bins) * 0.42), 6))
    bars = ax.bar(range(len(bins)), [counts[start] for start in bins], color="#2878a0")
    ax.bar_label(bars, padding=3, fontsize=8)
    ax.set_xticks(range(len(bins)), [f"{start}–{start + 9}" for start in bins],
                  rotation=60, ha="right", fontsize=8)
    ax.set_xlabel("Thập kỉ (năm dương lịch)")
    ax.set_ylabel("Số văn bia")
    ax.set_title(f"Số văn bia theo thập kỉ — toàn bộ merged_records\n"
                 f"{total_counted}/{len(rows)} văn bia có năm được chọn; "
                 f"{len(rows) - total_counted} văn bia chưa đưa vào biểu đồ")
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_ylim(0, max(counts.values()) * 1.15)
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    for extension in ("png", "svg"):
        fig.savefig(args.output_dir / f"inscription_decades.{extension}", dpi=180)
    plt.close(fig)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Outputs: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
