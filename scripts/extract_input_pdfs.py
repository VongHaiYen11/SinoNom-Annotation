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
        except subprocess.CalledProcessError as exc:
            print(f"Extraction failed for {pdf.name} (exit {exc.returncode})", file=sys.stderr)
            return exc.returncode or 1
        finally:
            config_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
