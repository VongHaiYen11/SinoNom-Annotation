"""Backward-compatible imports for extraction support helpers.

New code should import the focused modules in :mod:`extraction` directly.
"""

from extraction.config import load_config, load_glyph_profile
from extraction.jsonl import atomic_write, serialize_jsonl, validate_json_value
from extraction.models import ExtractConfig, ExtractionError, MetadataSpec, TextLine
from extraction.text import clean_extracted_text, is_invalid_text_character, normalize_line

__all__ = [
    "ExtractConfig", "ExtractionError", "MetadataSpec", "TextLine",
    "atomic_write", "clean_extracted_text", "is_invalid_text_character",
    "load_config", "load_glyph_profile", "normalize_line", "serialize_jsonl",
    "validate_json_value",
]
