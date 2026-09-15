from pathlib import Path
import pymupdf


PDF_PATH = Path(
    "../Vietnamica-Alignment/input/Tap-1_Bia-Hau-the-ki-XVII_760-trang.pdf"
)


def inspect_fonts(pdf_path: Path) -> None:
    document = pymupdf.open(pdf_path)

    try:
        fonts_by_type = {
            "cid": set(),
            "ttf": set(),
        }

        for page in document:
            for font in page.get_fonts(full=True):
                extension = font[1].lower()
                basefont = font[3]

                if extension in fonts_by_type:
                    fonts_by_type[extension].add(basefont)

        print("=== CID fonts ===")
        for font_name in sorted(fonts_by_type["cid"]):
            print(font_name)

        print("\n=== TTF fonts ===")
        for font_name in sorted(fonts_by_type["ttf"]):
            print(font_name)

    finally:
        document.close()


if __name__ == "__main__":
    inspect_fonts(PDF_PATH)