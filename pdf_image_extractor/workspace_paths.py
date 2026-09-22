"""Local input and annotation-artifact paths shared by the Gradio workspaces."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_INPUT_DIR = PROJECT_ROOT / "input"


def local_pdf_choices() -> list[tuple[str, str]]:
    """Return input PDFs as compact labels with absolute paths as values."""
    if not LOCAL_INPUT_DIR.is_dir():
        return []
    return [
        (path.relative_to(PROJECT_ROOT).as_posix(), str(path))
        for path in sorted(LOCAL_INPUT_DIR.rglob("*.pdf"), key=lambda item: item.as_posix().lower())
        if path.is_file()
    ]


def annotation_collection_path(pdf_path: str | Path) -> Path:
    """Return the established PDF-level character-annotation collection path."""
    return PROJECT_ROOT / "output" / Path(pdf_path).stem / "character_annotations.json"
