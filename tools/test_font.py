from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


font_paths = [
    "fonts/reference/NomNaTong.ttf",
    "fonts/reference/PMingLiU-ExtB.ttf",
]

codepoints = [
    174818,
    150112,
    156005,
    173993,
    165307,
    176337,
    131636,
    173983,
    131566,
    140750,
    176409,
]

output_dir = Path("./unsupported_fonts")
output_dir.mkdir(parents=True, exist_ok=True)


# Load tất cả font trước
fonts = []

for font_path in font_paths:
    path = Path(font_path)

    if not path.exists():
        print(f"Không tìm thấy font: {font_path}")
        continue

    font = TTFont(font_path)
    cmap = font.getBestCmap()
    pil_font = ImageFont.truetype(font_path, 200)

    fonts.append(
        {
            "path": path,
            "name": path.stem,
            "font": font,
            "cmap": cmap,
            "pil_font": pil_font,
        }
    )


for codepoint in codepoints:
    print()
    print("=" * 60)
    print(f"U+{codepoint:04X}")

    found = False
    char = chr(codepoint)

    for item in fonts:
        font_name = item["name"]
        cmap = item["cmap"]
        pil_font = item["pil_font"]

        glyph_name = cmap.get(codepoint)

        if glyph_name is None:
            print(f"  {font_name}: không tìm thấy")
            continue

        found = True

        print(
            f"  {font_name}: "
            f"U+{codepoint:04X} -> {glyph_name} -> {char}"
        )

        # Tạo thư mục riêng cho từng font
        font_output_dir = output_dir / font_name
        font_output_dir.mkdir(parents=True, exist_ok=True)

        img = Image.new("RGB", (300, 300), "white")
        draw = ImageDraw.Draw(img)

        draw.text(
            (50, 30),
            char,
            font=pil_font,
            fill="black",
        )

        output_path = (
            font_output_dir / f"U+{codepoint:04X}.png"
        )

        img.save(output_path)

        print(f"    Đã lưu: {output_path}")

    if not found:
        print(
            f"  ❌ Không font nào có "
            f"U+{codepoint:04X}"
        )
