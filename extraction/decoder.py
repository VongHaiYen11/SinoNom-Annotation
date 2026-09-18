"""PDF font inspection and deterministic CID glyph decoding."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

import pymupdf
from extraction.glyphs import embedded_glyphs, glyph_commands, signature
from extraction.models import DecodeStatistics, ExtractionError, TextCharacter, TextLine, TextSpan
from extraction.text import clean_extracted_text, normalize_line

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PageFont:
    xref: int
    extension: str
    font_type: str
    resource: str

    @property
    def is_cid_outline(self) -> bool:
        """True only for Type0 fonts whose CID can address an embedded outline."""
        return self.font_type == "Type0" and self.extension in {"cff", "cid", "ttf", "otf"}


@dataclass(frozen=True)
class _FontRun:
    font_name: str
    x: float
    y: float
    cids: tuple[int, ...]
    xref: int


def _font_basename(name: str) -> str:
    """Remove a PDF subset prefix and spaces from a font name."""
    return re.sub(r"^[A-Z]{6}\+", "", name).replace(" ", "")


class GlyphDecoder:
    """Decode CID subset fonts with a deterministic outline-signature profile."""

    def __init__(
        self,
        document: pymupdf.Document,
        profile: dict[str, dict[str, Any]],
        encoded_fonts: Iterable[str],
    ) -> None:
        self.document = document
        self.profile = profile
        self.encoded_fonts = tuple(encoded_fonts)
        self._font_maps: dict[int, dict[int, str]] = {}
        self._font_signatures: dict[int, dict[int, str]] = {}
        self._profile_misses: dict[tuple[int, str, int, int, str], int] = {}
        self._unsupported_font_xrefs: set[int] = set()
        self.statistics = DecodeStatistics()
        self._last_characters: tuple[TextCharacter, ...] = ()

    def _is_encoded(self, font_name: str) -> bool:
        """Return whether this span needs CID outline decoding."""
        return any(token in font_name for token in self.encoded_fonts)

    def _page_fonts(self, page: pymupdf.Page) -> dict[str, tuple[_PageFont, ...]]:
        result: dict[str, list[_PageFont]] = {}
        for row in page.get_fonts(full=True):
            xref, extension, font_type, basefont, resource = row[:5]
            normalized = _font_basename(basefont)
            result.setdefault(normalized, []).append(
                _PageFont(
                    xref=xref,
                    extension=extension.lower(),
                    font_type=font_type,
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
                if not font.is_cid_outline:
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
        """Map one embedded Type0 font's CID outlines through the profile."""
        result: dict[int, str] = {}
        signatures: dict[int, str] = {}
        _, extension, font_type, content = self.document.extract_font(xref)
        extension = extension.lower()
        source_glyphs = embedded_glyphs(self.document, xref)
        if extension in {"cff", "cid"}:
            candidates = (
                (int(match.group(1)), source_glyph.glyph, source_glyph.glyph_set)
                for source_glyph in source_glyphs
                if (match := re.fullmatch(r"cid(\d+)", source_glyph.name)) is not None
            )
        elif extension in {"ttf", "otf"} and font_type == "Type0" and content:
            # CIDFontType2 defaults to an identity CIDToGIDMap when that entry
            # is absent.  That is the common Type0 TrueType representation in
            # this corpus; non-identity maps remain explicit fallback cases.
            # A non-identity CIDToGIDMap must be applied before a TrueType
            # glyph order can be trusted.  Do not guess from rawdict Unicode.
            if "CIDToGIDMap" in self.document.xref_object(xref, compressed=True):
                self._unsupported_font_xrefs.add(xref)
                LOGGER.warning(
                    "xref=%d uses non-default CIDToGIDMap; retaining explicitly "
                    "marked fallback characters until this map is implemented", xref,
                )
                return result
            candidates = (
                (gid, source_glyph.glyph, source_glyph.glyph_set)
                for gid, source_glyph in enumerate(source_glyphs)
            )
        else:
            return result
        for cid, glyph, glyph_set in candidates:
            digest = signature(glyph_commands(glyph, glyph_set=glyph_set))
            signatures[cid] = digest
            if digest in self.profile:
                result[cid] = self.profile[digest]["char"]
        self._font_signatures[xref] = signatures
        return result

    def _record_profile_miss(
        self, page_number: int, font_name: str, xref: int, cid: int,
    ) -> None:
        """Aggregate encountered glyphs whose known signature is absent from profile."""
        digest = self._font_signatures.get(xref, {}).get(cid)
        if digest is None or digest in self.profile:
            return
        key = (page_number, font_name, xref, cid, digest)
        self._profile_misses[key] = self._profile_misses.get(key, 0) + 1

    def log_profile_misses(self) -> None:
        """Emit a concise, reviewable report of all missing profile entries."""
        for (page, font_name, xref, cid, digest), occurrences in sorted(
            self._profile_misses.items()
        ):
            LOGGER.warning(
                "Glyph profile miss: page=%d font=%r xref=%d CID=%d "
                "signature=%s occurrences=%d",
                page, font_name, xref, cid, digest, occurrences,
            )

    @staticmethod
    def _fallback_character(
        char: str,
        bbox: tuple[float, float, float, float],
        font_name: str,
        font_size: float,
        xref: int | None,
    ) -> TextCharacter:
        if clean_extracted_text(char):
            return TextCharacter(char, bbox, font_name, font_size, xref, "fallback")
        # Never silently delete a bad PDF character.  The visible placeholder
        # keeps positional evidence while the status makes it reviewable.
        return TextCharacter("□", bbox, font_name, font_size, xref, "unresolved")

    def _record_characters(self, characters: list[TextCharacter]) -> str:
        self._last_characters = tuple(characters)
        stats = getattr(self, "statistics", None)
        if stats is not None:
            stats.total_characters += len(characters)
            stats.profile_matched += sum(item.status == "matched" for item in characters)
            stats.fallback += sum(item.status == "fallback" for item in characters)
            stats.unresolved += sum(item.status == "unresolved" for item in characters)
        return "".join(item.text for item in characters)

    def _fallback_span(
        self, text: str, font_name: str, chars: list[dict[str, Any]] | None,
        font_size: float,
    ) -> str:
        if chars is None:
            # Compatibility for direct library callers of the historical API.
            return clean_extracted_text(text)
        return self._record_characters([
            self._fallback_character(
                char, tuple(info.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                font_name, font_size, None,
            )
            for char, info in zip(text, chars)
        ])

    def decode_span(
        self,
        text: str,
        font_name: str,
        page_fonts: dict[str, tuple[_PageFont, ...]],
        page_number: int,
        chars: list[dict[str, Any]] | None = None,
        font_runs: dict[tuple[str, float, float, int], list[_FontRun]] | None = None,
        font_size: float = 0.0,
    ) -> str:
        """Decode one raw PDF span while resolving subset-font ambiguity."""
        font_candidates = self._font_info(font_name, page_fonts)
        if not font_candidates:
            return self._fallback_span(text, font_name, chars, font_size)
        cid_candidates = tuple(font for font in font_candidates if font.is_cid_outline)
        if not cid_candidates:
            return self._fallback_span(text, font_name, chars, font_size)

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
        character_records: list[TextCharacter] = []
        for index, char in enumerate(text):
            cid = ord(char)
            char_info = chars[index] if chars is not None and index < len(chars) else {}
            bbox = tuple(char_info.get("bbox", (0.0, 0.0, 0.0, 0.0)))
            if chars is not None and chars[index].get("synthetic"):
                decoded.append(char)
                character_records.append(self._fallback_character(char, bbox, font_name, font_size, None))
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
                    value = next(iter(values))
                    decoded.append(value)
                    character_records.append(TextCharacter(value, bbox, font_name, font_size, possible[0], "matched"))
                    continue
                character_records.append(self._fallback_character(char, bbox, font_name, font_size, None))
                decoded.append(character_records[-1].text)
                continue
            font_map = self._font_maps[xref]
            if cid not in font_map:
                self._record_profile_miss(page_number, font_name, xref, cid)
                character_records.append(self._fallback_character(char, bbox, font_name, font_size, xref))
                decoded.append(character_records[-1].text)
                continue
            value = font_map[cid]
            decoded.append(value)
            character_records.append(TextCharacter(value, bbox, font_name, font_size, xref, "matched"))
        return self._record_characters(character_records) if character_records else clean_extracted_text("".join(decoded))

    def extract_lines(
        self,
        top_margin: float,
        bottom_margin: float,
        footnote_start_pattern: str | None = None,
        footnote_min_y: float = 0.0,
        footnote_max_font_size: float | None = None,
    ) -> list[TextLine]:
        """Extract decoded lines, optionally dropping footnotes at each page end.

        A footnote starts at the first line matching ``footnote_start_pattern``
        at or below ``footnote_min_y`` or rendered no larger than
        ``footnote_max_font_size``; that line and every later line on that page
        are excluded.  The guards prevent ordinary numbered body text from
        becoming a false footnote marker, while still handling image-only pages
        where a footnote begins above the usual bottom region.
        """
        output: list[TextLine] = []
        footnote_re = re.compile(footnote_start_pattern) if footnote_start_pattern else None
        for page_index, page in enumerate(self.document):
            page_number = page_index + 1
            fonts = self._page_fonts(page)
            font_runs = self._page_font_runs(page, fonts)
            page_lines: list[tuple[float, float, float, float, str, int, int, tuple[TextSpan, ...]]] = []
            raw = page.get_text("rawdict", sort=True)
            for block_number, block in enumerate(raw["blocks"]):
                for line_number, line in enumerate(block.get("lines", [])):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    y0 = min(span["bbox"][1] for span in spans)
                    y1 = max(span["bbox"][3] for span in spans)
                    if y0 < top_margin or y1 > page.rect.height - bottom_margin:
                        continue
                    pieces: list[str] = []
                    rebuilt_spans: list[TextSpan] = []
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
                                float(span["size"]),
                            )
                        )
                        rebuilt_spans.append(
                            TextSpan(
                                text=pieces[-1], bbox=tuple(span["bbox"]),
                                font_name=span["font"], font_size=float(span["size"]),
                                font_xref=(self._last_characters[0].font_xref if self._last_characters else None),
                                characters=self._last_characters,
                            )
                        )
                    text = normalize_line("".join(pieces))
                    if text:
                        x0 = min(span["bbox"][0] for span in spans)
                        font_size = max(float(span["size"]) for span in spans)
                        page_lines.append((y0, x0, y1, font_size, text, block_number, line_number, tuple(rebuilt_spans)))
            page_lines.sort(key=lambda item: (round(item[0], 2), item[1]))
            if footnote_re is not None:
                first_footnote = next(
                    (
                        index
                        for index, (y0, _, _, font_size, text, *_rest) in enumerate(page_lines)
                        if footnote_re.search(text) and (
                            y0 >= footnote_min_y
                            or (
                                footnote_max_font_size is not None
                                and font_size <= footnote_max_font_size
                            )
                        )
                    ),
                    None,
                )
                if first_footnote is not None:
                    page_lines = page_lines[:first_footnote]
            output.extend(
                TextLine(
                    text=text,
                    page_number=page_number,
                    y0=y0,
                    x0=x0,
                    y1=y1,
                    font_size=font_size,
                    block_number=block_number,
                    line_number=line_number,
                    spans=spans,
                )
                for y0, x0, y1, font_size, text, block_number, line_number, spans in page_lines
            )
        return output
