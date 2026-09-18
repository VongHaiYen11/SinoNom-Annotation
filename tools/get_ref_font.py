from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont


REFERENCE_DIR = Path("/Users/v.h.yen/Documents/Code_2026/text-restoration /SinoNom/Data Annotation/Vietnamica-Alignment/fonts/reference")
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}


def get_names(font: TTFont, name_id: int) -> list[str]:
    names = set()

    for record in font["name"].names:
        if record.nameID == name_id:
            try:
                names.add(record.toUnicode())
            except Exception:
                pass

    return sorted(names)


def inspect_font(path: Path, font: TTFont, index: int | None = None) -> None:
    prefix = f"[{index}] " if index is not None else ""

    print("=" * 70)
    print(f"File:         {path.name}")
    print(f"Font:         {prefix}")
    print(f"Family:       {get_names(font, 1)}")
    print(f"Subfamily:    {get_names(font, 2)}")
    print(f"Full name:    {get_names(font, 4)}")
    print(f"PostScript:   {get_names(font, 6)}")
    print(f"UnitsPerEm:   {font['head'].unitsPerEm}")
    print(f"Glyph count:  {len(font.getGlyphOrder())}")
    print(f"Cmap count:   {len(font.getBestCmap() or {})}")


def inspect_file(path: Path) -> None:
    with path.open("rb") as file:
        is_collection = file.read(4) == b"ttcf"

    if is_collection:
        fonts = TTCollection(path).fonts

        for index, font in enumerate(fonts):
            inspect_font(path, font, index)
    else:
        font = TTFont(path)
        inspect_font(path, font)


def main() -> None:
    for path in sorted(
        REFERENCE_DIR.iterdir(),
        key=lambda path: path.name.casefold(),
    ):
        if path.suffix.lower() not in FONT_EXTENSIONS:
            continue

        try:
            inspect_file(path)
        except Exception as error:
            print("=" * 70)
            print(f"File:  {path.name}")
            print(f"ERROR: {error}")


if __name__ == "__main__":
    main()

