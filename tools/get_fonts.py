import os
import re

import pymupdf


def normalize_font_name(font_name):
    """Remove the six-character subset prefix from a font name."""
    return re.sub(r"^[A-Z]{6}\+", "", font_name)


def extract_font_info(pdf_path):
    """Extract unique normalized font names and their types from a PDF."""
    doc = pymupdf.open(pdf_path)
    fonts = {}

    for page in doc:
        for font in page.get_fonts(full=True):
            font_name = normalize_font_name(font[3])
            font_type = font[2]

            fonts.setdefault(font_name, set()).add(font_type)

    doc.close()
    return fonts


def process_input(input_folder, output_folder):
    """Process all PDF files in the input folder."""
    if not os.path.isdir(input_folder):
        print(f"[!] Input folder does not exist: {input_folder}")
        return

    os.makedirs(output_folder, exist_ok=True)

    pdf_files = [
        os.path.join(input_folder, f)
        for f in os.listdir(input_folder)
        if f.lower().endswith(".pdf")
    ]

    if not pdf_files:
        print("[!] No PDF files found in the input folder.")
        return

    for pdf_path in sorted(pdf_files):
        pdf_name = os.path.basename(pdf_path)
        base_name = os.path.splitext(pdf_name)[0]

        print(f"[*] Processing: {pdf_name}...")

        fonts = extract_font_info(pdf_path)

        pdf_output_folder = os.path.join(
            output_folder,
            base_name,
        )
        os.makedirs(pdf_output_folder, exist_ok=True)

        fonts_txt_path = os.path.join(
            pdf_output_folder,
            "fonts.txt",
        )

        with open(
            fonts_txt_path,
            "w",
            encoding="utf-8",
        ) as f:
            for font_name in sorted(fonts):
                font_types = ", ".join(
                    sorted(fonts[font_name])
                )
                f.write(
                    f"{font_name}\t{font_types}\n"
                )

        print(f"[✓] Found {len(fonts)} unique fonts.")
        print(f"[✓] Saved: {fonts_txt_path}")


if __name__ == "__main__":
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(tools_dir)

    input_folder = os.path.join(project_dir, "input")
    output_folder = os.path.join(project_dir, "output")

    process_input(input_folder, output_folder)