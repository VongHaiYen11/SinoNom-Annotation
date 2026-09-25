# SinoNom Annotation

Tools for extracting structured Vietnamese inscription content from PDF files and annotating Hán/Nôm characters in images.

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](requirements.txt)
[![Gradio 6.28](https://img.shields.io/badge/Gradio-6.28-FF7C00)](gradio/requirements.txt)
[![Output JSON](https://img.shields.io/badge/output-UTF--8_JSON-EA580C)](#outputs)

[Tiếng Việt](README.vi.md)

## Components

| Component | Purpose |
| --- | --- |
| `text_extraction/` | Decodes embedded Type0 CID glyphs and converts PDF content into structured JSON. |
| `text_detection/` | Detects intact and damaged character boxes and proposes an initial reading order. It does not recognize characters. |
| `gradio/` | Seven-step interface for content verification, box editing, status, reading order, crop and review. |

The Gradio app consumes extraction JSON. It does not extract text directly from a PDF.

## Installation

The complete runtime targets Linux x86_64, Python 3.11 and CUDA 12.1:

```bash
python -m pip install -r requirements.txt
```

This installs PDF extraction, Gradio, PyTorch, MMCV and MMDetection. The Torch/MMCV versions are intentionally pinned together. A clean environment is recommended.

For the UI without detection models:

```bash
python -m pip install -r gradio/requirements.txt
```

## PDF text extraction

Extraction is config-driven. [`configs/tap_1.json`](configs/tap_1.json) is the reference configuration and defines:

- source PDF, glyph profile and output paths;
- page margins and footnote filtering;
- record titles and metadata fields;
- face-marker syntax;
- allowed content sections.

Build the glyph profile, then extract the PDF:

```bash
python -m text_extraction.glyph_profile \
  --config configs/tap_1.json

python -m text_extraction.main \
  --config configs/tap_1.json
```

Both commands discover compatible embedded/reference fonts and refresh `encoded_fonts`. Paths inside a config are resolved relative to that config file.

The primary output is a UTF-8 JSON array:

```json
[
  {
    "so_van_bia": 1,
    "ten_bia": "[Vô đề]",
    "ky_hieu_vnchn": ["12305"],
    "noi_dung": [
      {
        "ky_hieu": "12305",
        "chuyen_muc": [
          {
            "tieu_de": "Nguyên văn chữ Hán Nôm",
            "van_ban": "永寺樂"
          }
        ]
      }
    ]
  }
]
```

Extraction also creates `<output-stem>_invalid.json` containing malformed records, parser warnings and sequence errors. Records flagged for review are excluded from the primary JSON.

## Detection models

Place external model assets at the default paths:

```text
text_detection/models/
├── ckpts/
│   ├── damage_detect.py
│   └── damage_detect.pth
└── dists/
    └── det_model/
        └── det_model
```

Make the OCR executable runnable on Linux:

```bash
chmod +x text_detection/models/dists/det_model/det_model
```

With this layout, Gradio needs no model-path arguments. The packaged OCR subprocess is quiet by default, including PyInstaller `PyiFrozenFinder` output. Use `--show-detection-logs` only for startup debugging.

Run detection for one image independently:

```bash
python -m text_detection path/to/image.jpg \
  --output output/detection.json
```

See [`text_detection/README.md`](text_detection/README.md) for model compatibility and runtime details.

## Gradio annotation app

Image files must be directly inside one flat folder. Each filename stem must match one `ky_hieu` in the source JSON and must be unique.

```bash
python gradio/app.py \
  --image-dir /path/to/images \
  --source-json /path/to/extracted-source.json \
  --output-dir /path/to/annotations
```

To review the UI or annotate manually without loading detection models:

```bash
python gradio/app.py \
  --image-dir /path/to/images \
  --source-json /path/to/extracted-source.json \
  --output-dir /path/to/annotations \
  --skip-detection
```

Open `http://127.0.0.1:7860`. For a remote environment:

```text
--server-name 0.0.0.0 --share
```

### Workflow

1. **Image** — select an image from the configured folder.
2. **Content** — verify and save the five configured sections: original Hán/Nôm, Sino-Vietnamese transcription, translation, summary and notes.
3. **Bounding Boxes** — detect, add, move, resize or delete boxes with stable IDs.
4. **Status** — mark every character as `intact` or `damaged`.
5. **Reading Order** — reorder stable box IDs without changing their character mapping.
6. **Crop** — set an independent rectangular crop using original-image coordinates.
7. **Review** — inspect the final table/text/JSON and save the image object.

The Python state is authoritative. JavaScript only reports UI actions. Any content or box change invalidates dependent alignment and reading-order confirmation. Annotation can continue only when normalized character count equals box count.

### Saving

- **Save content** updates the source JSON and adds/updates that image in the internal content registry. It does not download a file.
- **Save image** on Review commits bounding boxes, annotations, reading order and crop for that image.
- **Save all** downloads:
  - `annotations.json` for images committed with **Save image**;
  - `content.json` for images committed with **Save content**.

Drafts are never included until their corresponding Save action is used.

## Outputs

```text
annotations/
├── 12305.json          # boxes, statuses, annotations, reading order and crop
└── .state/
    ├── 12305.json      # stable-ID and validation metadata
    └── content.json    # internal Save-all content registry
```

All JSON is written as UTF-8 with readable Unicode. Per-image annotation writes are atomic.

## Repository layout

```text
configs/                 Document-specific extraction rules
fonts/                   Unicode reference fonts and Hán/Nôm UI fonts
text_extraction/         PDF decoding, glyph profiles and record parsing
text_detection/          OCR/damage localization and reading-order proposal
gradio/                  Annotation application and UI assets
requirements.txt         Complete Python 3.11/CUDA 12.1 runtime
```

## Known limitations

- Glyph profiling supports Type0 `cff`, `cid`, `ttf` and `otf` resources using two-byte `Identity-H`/`Identity-V` CIDs.
- Type1/simple fonts, unsupported CMaps and non-identity Type0 `CIDToGIDMap` cases are not decoded.
- The glyph raster matcher has no confidence threshold; generated profiles require review.
- Content-stream parsing supports the expected `Tf`/`Tj`/`TJ` patterns, not every valid PDF construction.
- Detection requires external model files compatible with the pinned MMDetection runtime.
