"""Backward-compatible launcher for the local Gradio image application."""

from pdf_image_extractor.gradio_ui import main


if __name__ == "__main__":
    raise SystemExit(main())
