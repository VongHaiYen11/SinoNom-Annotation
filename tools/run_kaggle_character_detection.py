#!/usr/bin/env python3
"""Run AutoHDR over final images and write one PDF-level annotation collection.

Example:
    !python tools/run_kaggle_character_detection.py \
        --output-dir output/tap1-short-21-page
"""

from __future__ import annotations

import argparse
import platform
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
def default_model() -> Path:
    """Support both released model layouts: file or ``det_model/det_model``."""
    model_path = PROJECT_ROOT / "character_detection" / "models" / "det_model"
    nested_executable = model_path / "det_model"
    return nested_executable if nested_executable.is_file() else model_path
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def log(step: int, message: str) -> None:
    print(f"[Step {step}] {message}", flush=True)


def final_images(output_directory: Path) -> list[Path]:
    """Find saved final images in deterministic PDF page/order order."""
    return sorted(
        path.resolve()
        for path in output_directory.rglob("*")
        if path.is_file() and path.parent.name == "final" and path.suffix.lower() in IMAGE_SUFFIXES
    )


def default_output_directory() -> Path | None:
    """Select the first PDF output directory containing a final image."""
    output_root = PROJECT_ROOT / "output"
    if not output_root.is_dir():
        return None
    candidates = sorted({path.parent.parent.parent for path in final_images(output_root)})
    return candidates[0] if candidates else None


def ensure_linux_x86_64() -> None:
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"x86_64", "amd64"}:
        raise RuntimeError(
            "The released det_model executable requires Linux x86_64. "
            f"Current platform: {platform.system()} {platform.machine()}."
        )


def install_dependencies() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", f"{PROJECT_ROOT}[character-detection]"],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect characters in every saved final image and write one collection JSON for a PDF output folder."
    )
    parser.add_argument("--output-dir", type=Path, help="PDF output folder, e.g. output/tap1-short-21-page. Defaults to the first eligible folder.")
    parser.add_argument("--image", type=Path, action="append", help="Optional final image to process. Repeat to select specific images only.")
    parser.add_argument("--model", type=Path, default=default_model(), help="AutoHDR Linux x86_64 detector executable.")
    parser.add_argument("--output", type=Path, help="Collection JSON path (default: <output-dir>/character_annotations.json).")
    parser.add_argument("--device", default="cpu", help="Torch device, e.g. cpu or cuda (default: cpu).")
    parser.add_argument("--confidence-threshold", type=float, default=.45, help="Keep detections at or above this confidence (default: 0.45).")
    parser.add_argument("--skip-install", action="store_true", help="Do not run pip install before detection.")
    args = parser.parse_args(argv)
    if not 0 <= args.confidence_threshold <= 1:
        parser.error("--confidence-threshold must be between 0 and 1.")

    print("AutoHDR character detection collection for Kaggle", flush=True)
    log(1, f"Checking platform: {platform.system()} {platform.machine()}")
    ensure_linux_x86_64()
    log(1, "Platform is compatible with the released detector binary.")

    log(2, "Selecting PDF output folder and final images.")
    output_directory = (args.output_dir or default_output_directory())
    if output_directory is None:
        parser.error("No PDF output folder found; provide --output-dir output/<pdf_name>.")
    output_directory = output_directory.resolve()
    if not output_directory.is_dir():
        parser.error(f"PDF output folder not found: {output_directory}")
    images = [path.resolve() for path in args.image] if args.image else final_images(output_directory)
    missing = [path for path in images if not path.is_file()]
    if missing:
        parser.error(f"Final image not found: {missing[0]}")
    if not images:
        parser.error(f"No final JPEG/PNG images found under: {output_directory}")
    log(2, f"Found {len(images)} final image(s) under: {output_directory}")
    for index, image in enumerate(images, start=1):
        print(f"       {index}/{len(images)} {image.relative_to(output_directory) if image.is_relative_to(output_directory) else image}", flush=True)

    log(3, "Checking detector model.")
    model = args.model.resolve()
    if not model.is_file():
        parser.error(f"Detector executable not found: {model}")
    model.chmod(model.stat().st_mode | stat.S_IXUSR)
    log(3, f"Using executable model: {model} ({model.stat().st_size / (1024 * 1024):.1f} MiB)")

    if not args.skip_install:
        log(4, "Installing project and optional character-detection dependencies. This can take several minutes.")
        install_dependencies()
        log(4, "Dependencies installed.")
    else:
        log(4, "Skipping dependency installation as requested.")

    log(5, "Starting one detector process for all selected images.")
    from pdf_image_extractor.character_annotations import detect_character_collection, write_annotations

    def progress(index: int, image: Path) -> None:
        log(5, f"Detecting image {index}/{len(images)}: {image.name}")

    collection = detect_character_collection(
        images,
        model,
        output_directory,
        device=args.device,
        confidence_threshold=args.confidence_threshold,
        progress=progress,
    )
    output = (args.output or output_directory / "character_annotations.json").resolve()
    write_annotations(output, collection)
    counts = [len(record["detections"]) for record in collection["images"]]
    log(6, f"Done. Wrote {len(collection['images'])} image annotation record(s), {sum(counts)} total box(es), to: {output}")
    for image, count in zip(images, counts, strict=True):
        log(6, f"{image.name}: {count} box(es) at confidence >= {args.confidence_threshold:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
