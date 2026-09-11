#!/usr/bin/env python3
"""Extract inscriptions from a PDF into deterministic UTF-8 JSONL.

The PDFs used by this project contain CID-keyed subset fonts without reliable
ToUnicode maps.  ``GlyphDecoder`` therefore maps each embedded glyph outline to
Unicode through a pre-built glyph profile.  See ``tools/build_glyph_profiles.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Pattern

import pymupdf

from tools.build_glyph_profiles import cff_top, glyph_commands, signature


DEFAULT_TITLE_PATTERN = r"^VĂN BIA SỐ\s+(?P<number>\d+)\s*$"
DEFAULT_CONTENT_START = "Nguyên văn chữ Hán Nôm"
DEFAULT_CONTENT_SECTIONS = (
    "Nguyên văn chữ Hán Nôm",
    "Phiên âm Hán Việt",
    "Dịch nghĩa",
    "Toát yếu",
    "Chú thích",
)
DEFAULT_MARKER_PATTERN = r"^\s*<\s*(?P<id>\d+)\s*>?\s*(?P<rest>.*)$"
DEFAULT_ENCODED_FONTS = ("PalatinoLinotype", "NomNaTong", "PMingLiU")
DEFAULT_TOP_MARGIN = 40.0
DEFAULT_BOTTOM_MARGIN = 45.0


class ExtractionError(RuntimeError):
    """Raised when extraction cannot continue without losing correctness."""


@dataclass(frozen=True)
class MetadataSpec:
    label: str
    field: str
    type: str = "string"
    required: bool = True


@dataclass(frozen=True)
class ExtractConfig:
    input_pdf: Path
    output_jsonl: Path
    glyph_profile: Path
    metadata: tuple[MetadataSpec, ...]
    title_pattern: str = DEFAULT_TITLE_PATTERN
    content_start: str = DEFAULT_CONTENT_START
    content_sections: tuple[str, ...] = DEFAULT_CONTENT_SECTIONS
    marker_pattern: str = DEFAULT_MARKER_PATTERN
    encoded_fonts: tuple[str, ...] = DEFAULT_ENCODED_FONTS
    top_margin: float = DEFAULT_TOP_MARGIN
    bottom_margin: float = DEFAULT_BOTTOM_MARGIN
    expected_record_count: int | None = None
    require_consecutive_numbers: bool = True


@dataclass(frozen=True)
class TextLine:
    text: str
    page_number: int
    y0: float = 0.0


@dataclass(frozen=True)
class _PageFont:
    xref: int
    is_cid_cff: bool
    resource: str


@dataclass(frozen=True)
class _FontRun:
    font_name: str
    x: float
    y: float
    cids: tuple[int, ...]
    xref: int


@dataclass
class _SectionAccumulator:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class _FaceAccumulator:
    identifier: str | None
    sections: list[_SectionAccumulator] = field(default_factory=list)

    def add(self, section_title: str, text: str) -> None:
        section = next(
            (item for item in self.sections if item.title == section_title), None
        )
        if section is None:
            section = _SectionAccumulator(section_title)
            self.sections.append(section)
        section.lines.append(text)


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"Config field {name!r} must be a non-empty string")
    return value


def _resolve_path(config_dir: Path, value: Any, name: str) -> Path:
    path = Path(_require_string(value, name)).expanduser()
    return path if path.is_absolute() else (config_dir / path).resolve()


def load_config(path: Path) -> ExtractConfig:
    """Load one per-PDF JSON config; relative paths use the config directory."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExtractionError("The config root must be a JSON object")

    raw_metadata = raw.get("metadata")
    if not isinstance(raw_metadata, list) or not raw_metadata:
        raise ExtractionError("Config field 'metadata' must be a non-empty list")
    metadata: list[MetadataSpec] = []
    seen_fields: set[str] = set()
    for index, item in enumerate(raw_metadata):
        if not isinstance(item, dict):
            raise ExtractionError(f"metadata[{index}] must be an object")
        spec = MetadataSpec(
            label=_require_string(item.get("label"), f"metadata[{index}].label"),
            field=_require_string(item.get("field"), f"metadata[{index}].field"),
            type=item.get("type", "string"),
            required=item.get("required", True),
        )
        if spec.type not in {"string", "identifiers"}:
            raise ExtractionError(
                f"metadata[{index}].type must be 'string' or 'identifiers'"
            )
        if not isinstance(spec.required, bool):
            raise ExtractionError(f"metadata[{index}].required must be boolean")
        if spec.field in seen_fields or spec.field in {"so_van_bia", "noi_dung"}:
            raise ExtractionError(f"Duplicate or reserved output field: {spec.field}")
        seen_fields.add(spec.field)
        metadata.append(spec)

    def string_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = raw.get(name, list(default))
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ExtractionError(f"Config field {name!r} must be a string list")
        return tuple(value)

    margins = raw.get("page_margins", {})
    if not isinstance(margins, dict):
        raise ExtractionError("Config field 'page_margins' must be an object")
    try:
        top_margin = float(margins.get("top", DEFAULT_TOP_MARGIN))
        bottom_margin = float(margins.get("bottom", DEFAULT_BOTTOM_MARGIN))
    except (TypeError, ValueError) as exc:
        raise ExtractionError("Page margins must be numbers") from exc
    if top_margin < 0 or bottom_margin < 0:
        raise ExtractionError("Page margins cannot be negative")

    expected = raw.get("expected_record_count")
    if expected is not None and (not isinstance(expected, int) or expected < 1):
        raise ExtractionError("expected_record_count must be a positive integer")
    consecutive = raw.get("require_consecutive_numbers", True)
    if not isinstance(consecutive, bool):
        raise ExtractionError("require_consecutive_numbers must be boolean")

    config_dir = path.resolve().parent
    config = ExtractConfig(
        input_pdf=_resolve_path(config_dir, raw.get("input_pdf"), "input_pdf"),
        output_jsonl=_resolve_path(
            config_dir, raw.get("output_jsonl"), "output_jsonl"
        ),
        glyph_profile=_resolve_path(
            config_dir, raw.get("glyph_profile"), "glyph_profile"
        ),
        metadata=tuple(metadata),
        title_pattern=_require_string(
            raw.get("title_pattern", DEFAULT_TITLE_PATTERN), "title_pattern"
        ),
        content_start=_require_string(
            raw.get("content_start", DEFAULT_CONTENT_START), "content_start"
        ),
        content_sections=string_tuple(
            "content_sections", DEFAULT_CONTENT_SECTIONS
        ),
        marker_pattern=_require_string(
            raw.get("marker_pattern", DEFAULT_MARKER_PATTERN), "marker_pattern"
        ),
        encoded_fonts=string_tuple("encoded_fonts", DEFAULT_ENCODED_FONTS),
        top_margin=top_margin,
        bottom_margin=bottom_margin,
        expected_record_count=expected,
        require_consecutive_numbers=consecutive,
    )
    for name, pattern in (
        ("title_pattern", config.title_pattern),
        ("marker_pattern", config.marker_pattern),
    ):
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ExtractionError(f"Invalid {name}: {exc}") from exc
        required_group = "number" if name == "title_pattern" else "id"
        if required_group not in compiled.groupindex:
            raise ExtractionError(f"{name} must define group (?P<{required_group}>...)")
    return config


def load_glyph_profile(path: Path) -> dict[str, str]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read glyph profile {path}: {exc}") from exc
    if not isinstance(profile, dict) or not profile:
        raise ExtractionError("Glyph profile must be a non-empty JSON object")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in profile.items()
    ):
        raise ExtractionError("Glyph profile entries must map strings to strings")
    return profile


def _font_basename(name: str) -> str:
    return re.sub(r"^[A-Z]{6}\+", "", name).replace(" ", "")


class GlyphDecoder:
    """Decode CID subset fonts with a deterministic outline-signature profile."""

    def __init__(
        self,
        document: pymupdf.Document,
        profile: dict[str, str],
        encoded_fonts: Iterable[str],
    ) -> None:
        self.document = document
        self.profile = profile
        self.encoded_fonts = tuple(encoded_fonts)
        self._font_maps: dict[int, dict[int, str]] = {}

    def _is_encoded(self, font_name: str) -> bool:
        return any(token in font_name for token in self.encoded_fonts)

    def _page_fonts(self, page: pymupdf.Page) -> dict[str, tuple[_PageFont, ...]]:
        result: dict[str, list[_PageFont]] = {}
        for row in page.get_fonts(full=True):
            xref, extension, font_type, basefont, resource = row[:5]
            normalized = _font_basename(basefont)
            result.setdefault(normalized, []).append(
                _PageFont(
                    xref=xref,
                    is_cid_cff=(
                        extension.lower() in {"cff", "cid"} and font_type == "Type0"
                    ),
                    resource=resource,
                )
            )
        return {name: tuple(fonts) for name, fonts in result.items()}

    @staticmethod
    def _font_info(
        font_name: str, page_fonts: dict[str, tuple[_PageFont, ...]]
    ) -> tuple[_PageFont, ...]:
        normalized = _font_basename(font_name)
        if normalized in page_fonts:
            return page_fonts[normalized]
        matches = [
            (len(name), fonts)
            for name, fonts in page_fonts.items()
            if name.startswith(normalized) or normalized.startswith(name)
        ]
        if not matches:
            return ()
        longest = max(length for length, _ in matches)
        best = [fonts for length, fonts in matches if length == longest]
        return best[0] if len(best) == 1 else ()

    def _page_font_runs(
        self,
        page: pymupdf.Page,
        page_fonts: dict[str, tuple[_PageFont, ...]],
    ) -> dict[tuple[str, float, float, int], list[_FontRun]]:
        """Read font-resource choices that PyMuPDF omits from raw text spans.

        PyMuPDF identifies spans by the base font name. A page can, however,
        contain multiple subset resources with that same name and different CID
        tables. The content stream retains the resource name (for example C10
        versus C13), so keep it as a narrowly scoped disambiguation hint.
        """
        resources = {
            font.resource: (name, font)
            for name, fonts in page_fonts.items()
            for font in fonts
        }
        number = rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        pattern = re.compile(
            rb"(?P<a>" + number + rb")\s+(?P<b>" + number + rb")\s+"
            rb"(?P<c>" + number + rb")\s+(?P<d>" + number + rb")\s+"
            rb"(?P<e>" + number + rb")\s+(?P<f>" + number + rb")\s+Tm\s+"
            rb"/(?P<resource>[^\s/]+)\s+" + number + rb"\s+Tf\s+"
            rb"(?P<show>\[.*?\]\s*TJ|<[0-9A-Fa-f\s]+>\s*Tj)",
            re.DOTALL,
        )
        result: dict[tuple[str, float, float, int], list[_FontRun]] = {}
        for content_xref in page.get_contents():
            content = self.document.xref_stream(content_xref)
            for match in pattern.finditer(content):
                resource = match.group("resource").decode("latin-1")
                resource_info = resources.get(resource)
                if resource_info is None:
                    continue
                font_name, font = resource_info
                if not font.is_cid_cff:
                    continue
                hexadecimal = b"".join(
                    re.findall(rb"<([0-9A-Fa-f\s]+)>", match.group("show"))
                )
                hexadecimal = re.sub(rb"\s+", b"", hexadecimal)
                if not hexadecimal or len(hexadecimal) % 4:
                    continue
                raw = bytes.fromhex(hexadecimal.decode("ascii"))
                cids = tuple(
                    int.from_bytes(raw[index : index + 2], "big")
                    for index in range(0, len(raw), 2)
                )
                point = pymupdf.Point(
                    float(match.group("e")), float(match.group("f"))
                ) * page.transformation_matrix
                run = _FontRun(font_name, point.x, point.y, cids, font.xref)
                key = (font_name, round(point.x, 2), round(point.y, 2), cids[0])
                if run not in result.setdefault(key, []):
                    result[key].append(run)
        return result

    def _build_font_map(self, xref: int) -> dict[int, str]:
        top = cff_top(self.document, xref)
        result: dict[int, str] = {}
        for glyph_name in top.charset:
            match = re.fullmatch(r"cid(\d+)", glyph_name)
            if match is None:
                continue
            cid = int(match.group(1))
            commands = glyph_commands(top.CharStrings[glyph_name])
            digest = signature(commands)
            if digest not in self.profile:
                raise ExtractionError(
                    f"Glyph profile is missing signature {digest} "
                    f"for font xref={xref}, CID={cid}"
                )
            result[cid] = self.profile[digest]
        return result

    def decode_span(
        self,
        text: str,
        font_name: str,
        page_fonts: dict[str, tuple[_PageFont, ...]],
        page_number: int,
        chars: list[dict[str, Any]] | None = None,
        font_runs: dict[tuple[str, float, float, int], list[_FontRun]] | None = None,
    ) -> str:
        if not self._is_encoded(font_name):
            return text
        font_candidates = self._font_info(font_name, page_fonts)
        if not font_candidates:
            raise ExtractionError(
                f"Cannot resolve embedded font {font_name!r} on page {page_number}"
            )
        cid_candidates = tuple(font for font in font_candidates if font.is_cid_cff)
        if not cid_candidates:
            return text

        for font in cid_candidates:
            xref = font.xref
            if xref in self._font_maps:
                continue
            try:
                self._font_maps[xref] = self._build_font_map(xref)
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError(
                    f"Cannot decode embedded font {font_name!r}, xref={xref}, "
                    f"page={page_number}: {exc}"
                ) from exc

        assignments: list[int | None] = [None] * len(text)
        if len(cid_candidates) == 1:
            assignments = [cid_candidates[0].xref] * len(text)
        elif chars is not None and font_runs is not None:
            normalized = _font_basename(font_name)
            cids = tuple(ord(char) for char in text)

            def common_prefix(left: tuple[int, ...], right: tuple[int, ...]) -> int:
                length = 0
                for left_item, right_item in zip(left, right):
                    if left_item != right_item:
                        break
                    length += 1
                return length

            for index, char_info in enumerate(chars):
                origin = char_info.get("origin")
                if not origin:
                    continue
                key = (
                    normalized,
                    round(float(origin[0]), 2),
                    round(float(origin[1]), 2),
                    cids[index],
                )
                matches = [
                    (common_prefix(cids[index:], run.cids), run)
                    for run in font_runs.get(key, [])
                ]
                matches = [item for item in matches if item[0]]
                if not matches:
                    continue
                length, run = max(matches, key=lambda item: item[0])
                assignments[index : index + length] = [run.xref] * length

            # TJ arrays are sometimes split into several raw spans at spacing
            # adjustments. Those later spans have no text-matrix start of their
            # own, so align their CID sequence with a run on the same baseline.
            all_runs = {
                run
                for runs in font_runs.values()
                for run in runs
                if run.font_name == normalized
            }
            for index, char_info in enumerate(chars):
                if assignments[index] is not None:
                    continue
                origin = char_info.get("origin")
                if not origin:
                    continue
                candidates: list[tuple[int, _FontRun]] = []
                for run in all_runs:
                    if abs(run.y - float(origin[1])) > 0.02:
                        continue
                    for offset in range(len(run.cids)):
                        length = common_prefix(cids[index:], run.cids[offset:])
                        if length:
                            candidates.append((length, run))
                if not candidates:
                    continue
                longest = max(length for length, _ in candidates)
                best_xrefs = {
                    run.xref for length, run in candidates if length == longest
                }
                if len(best_xrefs) == 1:
                    assignments[index : index + longest] = [
                        next(iter(best_xrefs))
                    ] * longest

        decoded: list[str] = []
        for index, char in enumerate(text):
            cid = ord(char)
            if chars is not None and chars[index].get("synthetic"):
                decoded.append(char)
                continue
            xref = assignments[index]
            if xref is None:
                possible = [
                    font.xref
                    for font in cid_candidates
                    if cid in self._font_maps[font.xref]
                ]
                values = {self._font_maps[item][cid] for item in possible}
                if len(values) == 1:
                    decoded.append(next(iter(values)))
                    continue
                raise ExtractionError(
                    f"Cannot disambiguate CID mapping on page {page_number}, "
                    f"font={font_name!r}, CID={cid}, xrefs={possible}"
                )
            font_map = self._font_maps[xref]
            if cid not in font_map:
                raise ExtractionError(
                    f"Missing CID mapping on page {page_number}, "
                    f"font={font_name!r}, xref={xref}, CID={cid}"
                )
            decoded.append(font_map[cid])
        return "".join(decoded)

    def extract_lines(
        self, top_margin: float, bottom_margin: float
    ) -> list[TextLine]:
        output: list[TextLine] = []
        for page_index, page in enumerate(self.document):
            page_number = page_index + 1
            fonts = self._page_fonts(page)
            font_runs = self._page_font_runs(page, fonts)
            page_lines: list[tuple[float, float, str]] = []
            raw = page.get_text("rawdict", sort=True)
            for block in raw["blocks"]:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    y0 = min(span["bbox"][1] for span in spans)
                    y1 = max(span["bbox"][3] for span in spans)
                    if y0 < top_margin or y1 > page.rect.height - bottom_margin:
                        continue
                    pieces: list[str] = []
                    for span in spans:
                        chars = span.get("chars", [])
                        encoded = "".join(char["c"] for char in chars)
                        pieces.append(
                            self.decode_span(
                                encoded,
                                span["font"],
                                fonts,
                                page_number,
                                chars,
                                font_runs,
                            )
                        )
                    text = normalize_line("".join(pieces))
                    if text:
                        x0 = min(span["bbox"][0] for span in spans)
                        page_lines.append((y0, x0, text))
            page_lines.sort(key=lambda item: (round(item[0], 2), item[1]))
            output.extend(
                TextLine(text=text, page_number=page_number, y0=y0)
                for y0, _, text in page_lines
            )
        return output


def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ")
    return re.sub(r"[\t\f\v ]+", " ", text).strip()


def _label_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    key = " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    )
    return key.replace("ky hieu", "ki hieu")


def _match_label(text: str, label: str) -> str | None:
    escaped = re.escape(label.rstrip(":"))
    match = re.fullmatch(
        rf"{escaped}(?:\s*:\s*(.*)|\s+(.*)|\s*)", text
    )
    if match is None:
        # Some records abbreviate headings (for example "Kí hiệu" versus
        # "Kí hiệu VNCHN") or vary Vietnamese accents ("Ký" versus "Kí").
        # Accept that only for an explicit colon-delimited heading, never for
        # ordinary prose that merely begins with the same words.
        head, separator, remainder = text.partition(":")
        head_key = _label_key(head)
        label_key = _label_key(label.rstrip(":"))
        if separator and (
            head_key == label_key or label_key.startswith(f"{head_key} ")
        ):
            return remainder.strip()
        return None
    return next((group for group in match.groups() if group is not None), "")


def _identifier_values(value: str) -> list[str]:
    return re.findall(r"<\s*(\d+)\s*>?", value)


def _add_warning(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _parse_content(
    lines: list[TextLine],
    identifiers: list[str],
    config: ExtractConfig,
    record_number: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    marker_re = re.compile(config.marker_pattern)
    faces: dict[str | None, _FaceAccumulator] = {
        identifier: _FaceAccumulator(identifier) for identifier in identifiers
    }
    current_face: str | None = None
    current_section = config.content_start

    for line in lines:
        section = next(
            (
                label
                for label in config.content_sections
                if _match_label(line.text, label) == ""
            ),
            None,
        )
        if section is not None:
            current_section = section
            current_face = None
            continue

        marker = marker_re.fullmatch(line.text)
        remainder = ""
        if marker is not None:
            current_face = marker.group("id")
            remainder = marker.groupdict().get("rest", "").strip()
            if current_face not in faces:
                faces[current_face] = _FaceAccumulator(current_face)
                _add_warning(
                    warnings,
                    f"Văn bia số {record_number}: marker <{current_face}> "
                    "không có trong metadata",
                )
            if not remainder:
                continue

        if current_face not in faces:
            faces[current_face] = _FaceAccumulator(current_face)
        if current_face is None:
            _add_warning(
                warnings,
                f"Văn bia số {record_number}: có nội dung không thuộc marker mặt bia",
            )
        faces[current_face].add(current_section, remainder or line.text)

    for identifier in identifiers:
        if not faces[identifier].sections:
            _add_warning(
                warnings,
                f"Văn bia số {record_number}: không tìm thấy nội dung cho <{identifier}>",
            )

    result: list[dict[str, Any]] = []
    for face in faces.values():
        if not face.sections and face.identifier not in identifiers:
            continue
        result.append(
            {
                "ky_hieu": face.identifier,
                "chuyen_muc": [
                    {
                        "tieu_de": section.title,
                        "van_ban": "\n".join(section.lines).strip(),
                    }
                    for section in face.sections
                ],
            }
        )
    return result


def _parse_record(
    number: int,
    lines: list[TextLine],
    config: ExtractConfig,
    warnings: list[str],
) -> dict[str, Any]:
    values: dict[str, list[str]] = {spec.field: [] for spec in config.metadata}
    current_spec: MetadataSpec | None = None
    content_index: int | None = None

    for index, line in enumerate(lines):
        content_remainder = _match_label(line.text, config.content_start)
        if content_remainder is not None:
            content_index = index + 1
            if content_remainder:
                lines = lines[: index + 1] + [
                    TextLine(content_remainder, line.page_number, line.y0)
                ] + lines[index + 1 :]
            break
        matched_spec: MetadataSpec | None = None
        matched_value = ""
        for spec in sorted(config.metadata, key=lambda item: len(item.label), reverse=True):
            remainder = _match_label(line.text, spec.label)
            if remainder is not None:
                matched_spec = spec
                matched_value = remainder
                break
        if matched_spec is not None:
            current_spec = matched_spec
            if matched_value:
                values[current_spec.field].append(matched_value)
        elif current_spec is not None:
            values[current_spec.field].append(line.text)
        else:
            _add_warning(
                warnings,
                f"Văn bia số {number}: bỏ qua dòng trước metadata ở trang "
                f"{line.page_number}: {line.text!r}",
            )

    if content_index is None:
        raise ExtractionError(f"Văn bia số {number}: thiếu mốc {config.content_start!r}")

    record: dict[str, Any] = {"so_van_bia": number}
    identifiers: list[str] = []
    for spec in config.metadata:
        value = " ".join(values[spec.field]).strip()
        if spec.required and not value:
            raise ExtractionError(
                f"Văn bia số {number}: thiếu metadata bắt buộc {spec.label!r}"
            )
        if spec.type == "identifiers":
            parsed = _identifier_values(value)
            if spec.required and not parsed:
                raise ExtractionError(
                    f"Văn bia số {number}: không đọc được ký hiệu từ {value!r}"
                )
            record[spec.field] = parsed
            identifiers.extend(item for item in parsed if item not in identifiers)
        else:
            record[spec.field] = value

    content_lines = lines[content_index:]
    record["noi_dung"] = _parse_content(
        content_lines, identifiers, config, number, warnings
    )
    return record


def parse_records(
    lines: list[TextLine], config: ExtractConfig
) -> tuple[list[dict[str, Any]], list[str]]:
    title_re = re.compile(config.title_pattern)
    starts: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = title_re.fullmatch(line.text)
        if match is not None:
            starts.append((index, int(match.group("number"))))
    if not starts:
        raise ExtractionError("No inscription titles matched title_pattern")

    numbers = [number for _, number in starts]
    if len(numbers) != len(set(numbers)):
        raise ExtractionError(f"Duplicate inscription numbers: {numbers}")
    if config.require_consecutive_numbers:
        expected = list(range(numbers[0], numbers[0] + len(numbers)))
        if numbers != expected:
            raise ExtractionError(
                f"Inscription numbers are not consecutive: got {numbers}, expected {expected}"
            )
    if config.expected_record_count is not None and len(starts) != config.expected_record_count:
        raise ExtractionError(
            f"Expected {config.expected_record_count} records, found {len(starts)}"
        )

    warnings: list[str] = []
    records = []
    for position, (start, number) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        records.append(_parse_record(number, lines[start + 1 : end], config, warnings))
    return records, warnings


def _validate_json_value(value: Any, location: str = "record") -> None:
    if isinstance(value, str):
        for char in value:
            if char == "\ufffd" or (unicodedata.category(char) == "Cc" and char != "\n"):
                raise ExtractionError(
                    f"Invalid Unicode character U+{ord(char):04X} in {location}"
                )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_json_value(item, f"{location}.{key}")


def serialize_jsonl(records: list[dict[str, Any]]) -> str:
    for index, record in enumerate(records):
        if not record or next(reversed(record)) != "noi_dung":
            raise ExtractionError(f"Record {index} does not end with field 'noi_dung'")
        _validate_json_value(record, f"record[{index}]")
    return "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def extract_document(config: ExtractConfig) -> tuple[list[dict[str, Any]], list[str]]:
    if not config.input_pdf.is_file():
        raise ExtractionError(f"Input PDF does not exist: {config.input_pdf}")
    profile = load_glyph_profile(config.glyph_profile)
    try:
        document = pymupdf.open(config.input_pdf)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {config.input_pdf}: {exc}") from exc
    try:
        decoder = GlyphDecoder(document, profile, config.encoded_fonts)
        lines = decoder.extract_lines(config.top_margin, config.bottom_margin)
    finally:
        document.close()
    return parse_records(lines, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Vietnamese inscriptions from one configured PDF"
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        records, warnings = extract_document(config)
        payload = serialize_jsonl(records)
        atomic_write(config.output_jsonl, payload)
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(records)} records to {config.output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
