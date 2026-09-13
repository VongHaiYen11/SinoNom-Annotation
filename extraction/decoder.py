"""PDF font inspection and deterministic CID glyph decoding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

import pymupdf

from extract_support import ExtractionError, TextLine, clean_extracted_text, normalize_line
from tools.build_glyph_profiles import cff_top, glyph_commands, signature


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
            # Fonts such as TimesNewRoman use PyMuPDF's normal decoding, but
            # an unknown glyph may still arrive as U+0001 or another control.
            return clean_extracted_text(text)
        font_candidates = self._font_info(font_name, page_fonts)
        if not font_candidates:
            raise ExtractionError(
                f"Cannot resolve embedded font {font_name!r} on page {page_number}"
            )
        cid_candidates = tuple(font for font in font_candidates if font.is_cid_cff)
        if not cid_candidates:
            return clean_extracted_text(text)

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
        return clean_extracted_text("".join(decoded))

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
