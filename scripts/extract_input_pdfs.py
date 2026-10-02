"""Build glyph profiles and extract PDFs in input/ using tap_1 settings."""

from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "tap_1.json"
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
PROFILE_DIR = ROOT / "data" / "glyph_profiles"
SUMMARY_PATH = OUTPUT_DIR / "extraction_summary.txt"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", help="Optional filename fragment; for example --only Tap-3",
    )
    args = parser.parse_args()

    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if args.only:
        pdfs = [pdf for pdf in pdfs if args.only.casefold() in pdf.name.casefold()]
    if not pdfs:
        print(f"No PDF files found in {INPUT_DIR}", file=sys.stderr)
        return 1

    summaries: list[str] = []
    for pdf in pdfs:
        config = json.loads(json.dumps(template))
        profile = PROFILE_DIR / f"{pdf.stem}.json"
        output = OUTPUT_DIR / f"{pdf.stem}.json"
        config["input_pdf_path"] = os.path.relpath(pdf, ROOT / "configs")
        config["paths"]["output_json"] = os.path.relpath(output, ROOT / "configs")
        config["paths"]["glyph_profile"] = os.path.relpath(profile, ROOT / "configs")

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", prefix=".batch_",
            dir=ROOT / "configs", delete=False,
        ) as config_file:
            json.dump(config, config_file, ensure_ascii=False, indent=2)
            config_path = Path(config_file.name)

        try:
            if profile.is_file() and profile.stat().st_size:
                print(f"\n=== {pdf.name}: reusing profile {profile.name} ===", flush=True)
            else:
                print(f"\n=== {pdf.name}: building glyph profile ===", flush=True)
                subprocess.run(
                    [sys.executable, "-m", "text_extraction.glyph_profile",
                     "--config", str(config_path)], cwd=ROOT, check=True,
                )
            print(f"=== {pdf.name}: extracting text ===", flush=True)
            subprocess.run(
                [sys.executable, "-m", "text_extraction.main",
                 "--config", str(config_path)], cwd=ROOT, check=True,
            )
            records = json.loads(output.read_text(encoding="utf-8"))
            issues_path = output.with_name(f"{output.stem}_invalid.json")
            issues = json.loads(issues_path.read_text(encoding="utf-8"))
            invalid_numbers = sorted({
                item["so_van_bia"] for item in issues
                if item.get("so_van_bia") is not None
            })
            unassigned_issue_count = sum(
                item.get("so_van_bia") is None for item in issues
            )
            invalid_count = len(invalid_numbers)
            valid_count = len(records)
            total_records = valid_count + invalid_count
            summary = (
                f"{pdf.name}: tổng record {total_records} "
                f"(JSON chính: {valid_count}, file _invalid: {invalid_count}); "
                f"record trong _invalid: "
                f"{', '.join(map(str, invalid_numbers)) if invalid_numbers else 'không có'}"
            )
            if unassigned_issue_count:
                summary += f"; issue không gắn với record: {unassigned_issue_count}"
            summaries.append(summary)
            print(summary)
        except subprocess.CalledProcessError as exc:
            print(f"Extraction failed for {pdf.name} (exit {exc.returncode})", file=sys.stderr)
            return exc.returncode or 1
        finally:
            config_path.unlink(missing_ok=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(summaries) + "\n", encoding="utf-8")
    print(f"Wrote extraction summary to {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
