"""Unicode cleanup and line normalization for PDF text."""

from __future__ import annotations

import re
import unicodedata

def is_invalid_text_character(char: str) -> bool:
    return char == "\ufffd" or unicodedata.category(char) in {"Cc", "Cs"}


def clean_extracted_text(text: str) -> str:
    """Remove undecoded/control characters received from a PDF."""
    return "".join(char for char in text if not is_invalid_text_character(char))


def normalize_line(text: str) -> str:
    text = clean_extracted_text(unicodedata.normalize("NFC", text)).replace("\u00a0", " ")
    return re.sub(r"[\t\f\v ]+", " ", text).strip()


