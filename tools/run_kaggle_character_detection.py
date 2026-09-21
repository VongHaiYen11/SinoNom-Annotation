#!/usr/bin/env python3
"""Bootstrap and run AutoHDR character detection in a Kaggle notebook.

Example:
    !python tools/run_kaggle_character_detection.py \
        --image output/book/page_003/final/book.001.jpg
"""

from __future__ import annotations

import argparse
import platform
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = PROJECT_ROOT / "character_detection" / "models" / "det_model"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def log(step: int, message: str) -> None:
    """Print notebook-friendly progress immediately."""
    print(f"[Step {step}] {message}", flush=True)


def first_final_image() -> Path | None:
    """Return the first saved final image in deterministic path order."""
    output_root = PROJECT_ROOT / "output"
    if not output_root.is_dir():
        return None
    images = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path.parent.name == "final" and path.suffix.lower() in IMAGE_SUFFIXES
    )
    return images[0] if images else None


def ensure_linux_x86_64() -> None:
    """Fail early because the released executable is Linux x86_64 only."""
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"x86_64", "amd64"}:
        raise RuntimeError(
            "The released det_model executable requires Linux x86_64. "
            f"Current platform: {platform.system()} {platform.machine()}."
        )


def make_executable(model: Path) -> None:
    """Grant the current user execute permission without changing other bits."""
    model.chmod(model.stat().st_mode | stat.S_IXUSR)


def install_dependencies() -> None:
    """Install this project's optional local character-detection extra."""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", f"{PROJECT_ROOT}[character-detection]"],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install optional dependencies and create character annotations for one saved final image."
    )
    parser.add_argument("--image", type=Path, help="Final JPEG/PNG to process (defaults to the first output/**/final image).")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="AutoHDR Linux x86_64 detector executable.")
    parser.add_argument("--output", type=Path, help="JSON output path (defaults beside the image).")
    parser.add_argument("--device", default="cpu", help="Torch device, e.g. cpu or cuda (default: cpu).")
    parser.add_argument("--skip-install", action="store_true", help="Do not run pip install before detection.")
    args = parser.parse_args(argv)

    print("AutoHDR character detection for Kaggle", flush=True)
    log(1, f"Checking platform: {platform.system()} {platform.machine()}")
    ensure_linux_x86_64()
    log(1, "Platform is compatible with the released detector binary.")

    log(2, "Selecting final image.")
    image = args.image or first_final_image()
    if image is None or not image.is_file():
        parser.error("No final image found; provide one with --image path/to/final.jpg.")
    image = image.resolve()
    log(2, f"Using image: {image}")

    log(3, "Checking detector model.")
    model = args.model.resolve()
    if not model.is_file():
        parser.error(f"Detector executable not found: {model}")
    log(3, f"Using model: {model} ({model.stat().st_size / (1024 * 1024):.1f} MiB)")

    log(4, "Granting execute permission to the model.")
    make_executable(model)
    log(4, "Model is executable.")
    if not args.skip_install:
        log(5, "Installing project and optional character-detection dependencies. This can take several minutes.")
        install_dependencies()
        log(5, "Dependencies installed.")
    else:
        log(5, "Skipping dependency installation as requested.")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "detect_characters.py"),
        str(image),
        "--model",
        str(model),
        "--device",
        args.device,
    ]
    if args.output:
        command.extend(("--output", str(args.output.resolve())))
        expected_output = args.output.resolve()
    else:
        expected_output = image.with_suffix(".characters.json")
    log(6, "Starting detector process and writing annotations.")
    print("       Command: " + " ".join(command), flush=True)
    subprocess.run(command, check=True)
    if not expected_output.is_file():
        raise RuntimeError(f"Detector finished but expected output was not created: {expected_output}")
    log(7, f"Done. Annotation JSON: {expected_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
