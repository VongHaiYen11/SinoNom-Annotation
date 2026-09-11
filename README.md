# Vietnamica-Alignment
Align Vietnamica Inscription with annotated texts.

## 1. Setup

1. Clone the repository
2. Install `uv`
3. Create the locked environment:

```bash
uv sync --frozen
```

## 2. Commands

### 2.1. Extract PDFs

These PDFs use embedded CID fonts without reliable Unicode maps. Extraction is
therefore split into two deterministic stages: build a glyph profile once from
legally obtained reference fonts, then reuse that profile for every extraction.
OCR is not used.

Generate the profile for the sample volume:

```bash
uv run python tools/build_glyph_profiles.py \
  --pdf input/Tap-1_Bia-Hau-the-ki-XVII_760-trang.pdf \
  --nomna fonts/reference/NomNaTong.ttf \
  --palatino fonts/reference/Palatino-Regular.ttf \
  --palatino-bold fonts/reference/Palatino-Bold.ttf \
  --palatino-italic fonts/reference/Palatino-Italic.ttf \
  --palatino-bold-italic fonts/reference/Palatino-BoldItalic.ttf \
  --pmingliu fonts/reference/PMingLiU-ExtB.ttc \
  --output data/glyph_profiles/tap_1.json
```

`--pmingliu` is optional. It is only needed when that font occurs in the target
content. Reference fonts are stored locally under `fonts/reference/` and are
intentionally ignored by Git because some of them have restricted licenses.

Extract the configured PDF:

```bash
uv run python extract_pdf.py --config configs/tap_1.json
```

Paths inside a config are resolved relative to the config file. Use one config
per PDF; metadata labels and their stable JSON field names are declared in the
`metadata` list. The command writes UTF-8 JSONL atomically and reports structural
warnings on stderr.

### 2.2. Tests

```bash
uv run python -m unittest discover -s tests -v
```

The sample integration test runs when both the ignored input PDF and generated
glyph profile are present; otherwise it is skipped.
