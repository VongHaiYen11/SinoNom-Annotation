"""Convert ordered extracted lines into inscription records and warnings."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from extraction.models import ExtractConfig, ExtractionError, MetadataSpec, TextLine


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

def _label_key(text: str) -> str:
    """Create an accent-insensitive key for tolerant heading matching."""
    decomposed = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    key = " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    )
    return key.replace("ky hieu", "ki hieu")


def _match_label(text: str, label: str) -> str | None:
    """Match a heading and return its optional inline remainder."""
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


def _marker_list(identifiers: list[str]) -> str:
    return " ".join(f"<{identifier}>" for identifier in identifiers) or "(trống)"


def _parse_content(
    lines: list[TextLine],
    identifiers: list[str],
    config: ExtractConfig,
    record_number: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Assign content lines to sections and face markers, retaining ambiguity."""
    marker_re = re.compile(config.marker_pattern)
    faces: dict[str | None, _FaceAccumulator] = {
        identifier: _FaceAccumulator(identifier) for identifier in identifiers
    }
    current_face: str | None = None
    current_section = config.content_start
    unmarked_content: dict[str, list[TextLine]] = {}

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
                    f"Văn bia số {record_number}: marker <{current_face}> không có "
                    "trong metadata (danh sách marker metadata: "
                    f"{_marker_list(identifiers)}) ở trang {line.page_number}, "
                    f"dòng: {line.text!r}",
                )
            if not remainder:
                continue

        if current_face not in faces:
            faces[current_face] = _FaceAccumulator(current_face)
        if current_face is None:
            unmarked_content.setdefault(current_section, []).append(line)
        faces[current_face].add(current_section, remainder or line.text)

    for section, section_lines in unmarked_content.items():
        pages = sorted({line.page_number for line in section_lines})
        page_description = str(pages[0]) if len(pages) == 1 else ", ".join(map(str, pages))
        content = "\n".join(line.text for line in section_lines)
        _add_warning(
            warnings,
            f"Văn bia số {record_number}: có nội dung không thuộc marker mặt bia "
            f"ở trang {page_description}, chuyên mục {section!r}. Nguyên nhân: "
            "chưa gặp marker <...> sau tiêu đề chuyên mục hoặc marker bị thiếu/vỡ "
            f"khi trích xuất PDF. Nội dung chưa gán: {content!r}",
        )

    for identifier in identifiers:
        if not faces[identifier].sections:
            _add_warning(
                warnings,
                f"Văn bia số {record_number}: metadata khai báo marker <{identifier}> "
                "nhưng không có dòng nội dung nào được gán cho marker này "
                f"(danh sách marker metadata: {_marker_list(identifiers)}).",
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
    """Build one inscription record from lines between two title headings."""
    values: dict[str, list[str]] = {spec.field: [] for spec in config.metadata}
    current_spec: MetadataSpec | None = None
    content_index: int | None = None

    for index, line in enumerate(lines):
        content_remainder = _match_label(line.text, config.content_start)
        if content_remainder is not None:
            content_index = index + 1
            if content_remainder:
                lines = lines[: index + 1] + [
                    TextLine(
                        content_remainder,
                        line.page_number,
                        line.y0,
                        line.x0,
                        line.y1,
                        line.font_size,
                    )
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


def _record_starts(lines: list[TextLine], config: ExtractConfig) -> list[tuple[int, int]]:
    """Find record heading positions without deciding whether their sequence is valid."""
    title_re = re.compile(config.title_pattern)
    starts: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = title_re.fullmatch(line.text)
        if match is not None:
            starts.append((index, int(match.group("number"))))
    if not starts:
        raise ExtractionError("No inscription titles matched title_pattern")
    return starts


def _sequence_errors(starts: list[tuple[int, int]], config: ExtractConfig) -> list[str]:
    """Return global title/record-count violations while preserving recoverable records."""
    numbers = [number for _, number in starts]
    errors: list[str] = []
    if len(numbers) != len(set(numbers)):
        errors.append(f"Duplicate inscription numbers: {numbers}")
    if config.require_consecutive_numbers:
        expected = list(range(numbers[0], numbers[0] + len(numbers)))
        if numbers != expected:
            errors.append(
                f"Inscription numbers are not consecutive: got {numbers}, expected {expected}"
            )
    if config.expected_record_count is not None and len(starts) != config.expected_record_count:
        errors.append(f"Expected {config.expected_record_count} records, found {len(starts)}")
    return errors


def _issue(
    number: int | None,
    record_lines: list[TextLine],
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reviewable JSON item for one malformed or warned record."""
    item: dict[str, Any] = {
        "so_van_bia": number,
        "trang": sorted({line.page_number for line in record_lines}),
        "loi": errors or [],
        "canh_bao": warnings or [],
    }
    if record is not None:
        item["van_bia"] = record
    else:
        item["du_lieu_nguon"] = [line.text for line in record_lines]
    return item


def parse_records_with_issues(
    lines: list[TextLine], config: ExtractConfig
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Parse every possible record and collect malformed data for JSON review.

    A bad metadata block no longer prevents later inscriptions from being
    extracted.  Structural warnings remain in the normal warning list and are
    also attached to the matching record in ``issues``.
    """
    try:
        starts = _record_starts(lines, config)
    except ExtractionError as exc:
        return [], [], [_issue(None, lines, errors=[str(exc)])]

    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    sequence_errors = _sequence_errors(starts, config)
    if sequence_errors:
        issues.append(_issue(None, [], errors=sequence_errors))
    records: list[dict[str, Any]] = []
    for position, (start, number) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        record_lines = lines[start : end]
        local_warnings: list[str] = []
        try:
            record = _parse_record(number, lines[start + 1 : end], config, local_warnings)
        except ExtractionError as exc:
            issues.append(_issue(number, record_lines, errors=[str(exc)]))
            continue
        records.append(record)
        warnings.extend(item for item in local_warnings if item not in warnings)
        if local_warnings:
            issues.append(_issue(number, record_lines, warnings=local_warnings, record=record))
    return records, warnings, issues


def parse_records(
    lines: list[TextLine], config: ExtractConfig
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split records strictly, retaining the original API for library callers."""
    records, warnings, issues = parse_records_with_issues(lines, config)
    errors = [error for issue in issues for error in issue["loi"]]
    if errors:
        raise ExtractionError(errors[0])
    return records, warnings
