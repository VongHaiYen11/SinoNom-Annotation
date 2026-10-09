# Vietnamica Alignment

An interactive extraction and annotation workflow for Hán/Nôm inscriptions. Recover structured text from PDFs, localize characters in inscription images, and verify character-level alignments through a Gradio interface.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Gradio](https://img.shields.io/badge/Gradio-6.28.0-F97316?style=flat-square)
![PyMuPDF](https://img.shields.io/badge/PDF-PyMuPDF-2563EB?style=flat-square)
![PyTorch](https://img.shields.io/badge/Detection-PyTorch-EE4C2C?style=flat-square&logo=pytorch&logoColor=white)

## Overview

Vietnamica Alignment connects document text extraction with image-based inscription annotation. Document-specific configurations define how PDF text is decoded and parsed. The annotation interface pairs each image with its source record and guides reviewers through content, geometry, character status, reading order, and crop verification.

Automation proposes text records, character boxes, damage labels, and spatial order. Reviewers correct these proposals and explicitly confirm source discrepancies before exporting annotations.

> [!NOTE]
> The Gradio application reads source JSON; PDF extraction runs separately. Detection supplies character locations and damage proposals. Character labels come from verified source text, not OCR recognition.

## Key features

- **Configurable PDF extraction:** embedded-font decoding, reusable glyph profiles, margin and footnote filtering, and structured inscription records.
- **Optional assisted detection:** OCR character localization, DINO damage detection, box fusion, and heuristic reading order.
- **Interactive verification:** edit boxes, correct source sections, reorder character cards, and review intact or damaged status.
- **Explicit uncertainty:** unknown flags for damaged characters, suspicious-content flags, and confirmed missing or extra source characters.
- **Structured exports:** per-image JSON, verified content, discrepancy records, crop/resize metadata, and a consolidated ZIP archive.
- **Record preparation:** batch extraction, priority-based record merging, and image/source compatibility checks.

## Workflow

```text
PDF + reference fonts + document config
                  │
           Glyph profile → Text extraction → Source JSON
                                                  │
Inscription images ────────────────────────────────┤
                                                  ▼
                                Gradio verification
                          Content → Boxes → Status & Order
                                  → Crop → Review → Save
                                                  │
                                  Per-image JSON + ZIP export
```

Reviewed source JSON can enter the workflow directly. Manual annotation runs without detector models or the ML stack.

## Repository structure

```text
Vietnamica-Alignment/
├── configs/                 # Per-volume extraction and annotation settings
├── fonts/                   # Reference fonts and Hán/Nôm display fonts
├── text_extraction/         # Font discovery, glyph decoding, and record parsing
├── text_detection/          # Localization, fusion, and reading order
│   ├── runtime/             # OCR executable adapter and layout heuristic
│   ├── models/              # External detector assets
│   └── work/                # Generated preprocessing images
├── gradio/
│   ├── app.py               # Annotation application entry point
│   ├── annotation/          # Workflow, validation, persistence, and export
│   ├── crop/                # Crop geometry and resize metadata
│   ├── ui/                  # Interface components, JavaScript, and CSS
│   ├── tests/               # Annotation, export, and UI callback tests
│   └── requirements.txt     # Manual annotation dependencies
├── scripts/                 # Batch extraction and record preparation
├── helpers/                 # PDF font inspection
├── tests/                   # Extraction and detection tests
├── pyproject.toml           # Base dependencies and optional detection extra
├── requirements.txt         # Full Linux / CUDA runtime
└── uv.lock                  # Lockfile for the pyproject environment
```

`input/`, `data/`, `examples/`, `output/`, and `merged_records/` are local input or generated-data directories excluded from version control. Supply your own PDFs, images, and source records.

## Installation

Run commands from the repository root in an isolated environment.

### Manual annotation

The project declares Python **3.11 or later**. The checked-in `.python-version` selects **3.12**; use **3.11** for the pinned CUDA runtime below.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gradio/requirements.txt
```

Gradio, Pillow, and `regex` are sufficient for annotation with `--skip-detection`.

### PDF extraction only

Install the base dependencies declared in `pyproject.toml`, plus NumPy for glyph-profile generation. NumPy is included in the full requirements but absent from the base project dependencies.

```bash
python -m pip install fonttools==4.65.0 pymupdf==1.28.2 numpy==1.26.4
```

### Full extraction and detection runtime

Use a separate **Python 3.11, Linux x86_64** environment for the supplied CUDA 12.1 requirements:

```bash
python -m pip install -r requirements.txt
```

The file pins PyTorch `2.1.0+cu121`, torchvision `0.16.0+cu121`, MMCV `2.1.0`, MMEngine `0.10.5`, and MMDetection `3.3.0`, alongside extraction and annotation dependencies.

> [!IMPORTANT]
> The root requirements target the Kaggle Linux/CUDA environment documented in the file. They are not a portable macOS or CPU installation recipe. The optional `text-detection` extra in `pyproject.toml` specifies a different Torch range and omits MMDetection/MMCV; it does not provide the complete pinned runtime. Detector assets must be supplied separately.

## Usage

### Configure and launch the annotation application

Start with [configs/tap_1.json](configs/tap_1.json) or the matching volume configuration.

| Setting | Purpose |
| --- | --- |
| `paths.output_json` | Source inscription JSON |
| `gradio.image_dir` | Flat folder of inscription images |
| `gradio.output_dir` | Saved annotations and export archive |
| `records.content.start_heading` | Section supplying the Hán/Nôm character sequence |
| `records.content.section_headings` | Sections shown for content verification |
| `gradio.show_metadata_fields` | Whether configured string metadata is editable |

Configuration paths resolve relative to the configuration file. CLI path overrides resolve from the working directory. The application still reads its configuration when all data paths are overridden.

```bash
python gradio/app.py --config configs/tap_1.json --skip-detection
```

Override data locations as needed:

```bash
python gradio/app.py --config configs/tap_1.json --skip-detection \
  --image-dir /path/to/images \
  --source-json /path/to/source.json \
  --output-dir /path/to/annotations
```

With the detection runtime and assets installed, omit `--skip-detection`:

```bash
python gradio/app.py --config configs/tap_1.json
```

Open the local URL printed in the terminal. The default host is `127.0.0.1`; Gradio selects an available port. Use `--port 7861` for a fixed port, `--server-name 0.0.0.0` to bind all interfaces, or `--share` to create a public Gradio link. Run `python gradio/app.py --help` for all options.

### Verify an inscription

1. **Image:** select an image and click **Start Verification**.
2. **Content:** correct the configured source sections. The original Hán/Nôm section supplies the character sequence.
3. **Bounding Boxes & Sort:** run detection or draw/edit boxes manually. Sort all or selected boxes, or assign order numbers. Every box needs a unique order from `1` to `n` before continuing.
4. **Status & Order:** review `intact`/`damaged` labels, flag unknown damaged characters, reorder character cards to match boxes, and mark suspicious content.
5. **Crop:** adjust the crop frame. Export metadata scales crops whose longest side exceeds 4096 pixels.
6. **Review:** inspect the image and JSON, then click **Save Annotation**.

If counts differ, confirm **Missing Content** for more boxes than characters or **Extra Content** for more characters than boxes. Missing content uses `MISS` cards; extra characters are retained as excluded characters. **Other**, with a required note, records an unmappable issue and proceeds directly to Review.

**Next** validates stage transitions and retains edits in the current session. **Save Annotation** persists annotations and verified content without modifying the source JSON. **History** lists completed and unfinished images; saved annotations can be reopened. **Download All** exports saved records only, excluding unsaved drafts.

### Extract source text from a PDF

Configure `input_pdf_path`, `paths.glyph_profile`, and `paths.output_json`. Adjust page filters, metadata labels, section headings, and face-marker patterns for the document.

Inspect embedded fonts and supply matching Unicode reference fonts in `fonts/`:

```bash
python helpers/list_pdf_fonts.py /path/to/document.pdf
python -m text_extraction.font_discovery --config configs/tap_1.json
python -m text_extraction.glyph_profile --config configs/tap_1.json
python -m text_extraction.main --config configs/tap_1.json
```

Font discovery matches embedded family/style metadata and updates `encoded_fonts` in the configuration. Profile generation and extraction also run discovery automatically. Build the profile before extraction; reuse it for the corresponding PDF/font set.

Extraction writes valid records to `paths.output_json` and format-review items to `<output-stem>_invalid.json`. Structural validation does not establish transcription accuracy.

<details>
<summary>Batch extraction and record preparation</summary>

Process PDFs directly inside `input/`, named with a `Tap-N` prefix and matched to `configs/tap_N.json`:

```bash
python scripts/extract_input_pdfs.py
python scripts/extract_input_pdfs.py --only Tap-3
```

The batch runner reuses existing nonempty glyph profiles or builds missing ones, then writes `output/extraction_summary.txt`.

Merge recognized volume files from `examples/` and `output/`, then check source compatibility:

```bash
python scripts/merge_record_files.py
python scripts/check_merged_records.py --image-dir /path/to/images
```

Recognized sources include bare volume filenames such as `Tap-1_Bia-Hau.json` and matching `_valid.json`, `_tag-corrected.json`, or `_manual-review.json` files. Duplicate face IDs resolve by priority: **manual review → tag corrections → valid extraction**. Filenames such as `tap_1.json` do not match the merge script's volume naming convention.

Both default input directories must exist. Merged records go to `merged_records/`; use the appropriate file as the app's `--source-json`. Pass `--image-dir` to the merge command to filter out faces without matching images.

</details>

## Input format

Images must occupy a flat folder with unique filename stems. Supported extensions are `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.webp`, and `.bmp`. Each stem must identify exactly one face through `ky_hieu`: `12305.jpg` corresponds to `"ky_hieu": "12305"`. Exact matching is attempted first, followed by a numeric leading-zero fallback.

Source JSON is a UTF-8 array of inscription records. A minimal example for the default configuration is:

```json
[
  {
    "noi_dung": [
      {
        "ky_hieu": "12305",
        "chuyen_muc": [
          {
            "tieu_de": "Nguyên văn chữ Hán Nôm",
            "van_ban": "永樂"
          }
        ]
      }
    ]
  }
]
```

Each matching face needs exactly one text section whose `tieu_de` equals `records.content.start_heading`. That heading must also appear in `section_headings`. Additional metadata, transcription, and summary sections may be included.

Alignment applies NFC normalization, removes whitespace and Unicode punctuation, then segments extended grapheme clusters using `regex`. Box counts follow this normalized sequence rather than raw string length.

## Output format

A normal saved annotation has this shape. This illustrative example uses an unscaled 1000 × 1000 image:

```json
{
  "image": "12305.jpg",
  "bounding_boxes": {
    "1": {"bbox": [120, 350, 180, 420], "status": "intact", "unknown": false, "unavailable_font": false, "expert_prediction": false, "suspicious": true},
    "2": {"bbox": [120, 450, 180, 520], "status": "damaged", "unknown": true, "unavailable_font": false, "expert_prediction": false, "suspicious": false}
  },
  "annotations": {"1": "永", "2": "樂"},
  "image_resize": {
    "source_size": [1000, 1000],
    "output_size": [1000, 1000],
    "scale_x": 1.0,
    "scale_y": 1.0
  },
  "crop": {
    "top_left": [100, 200],
    "top_right": [900, 200],
    "bottom_right": [900, 900],
    "bottom_left": [100, 900]
  }
}
```

| Field | Meaning |
| --- | --- |
| `bounding_boxes` | Contiguous string IDs `"1"` through `"n"`, ordered for character assignment |
| `bbox` | `[x1, y1, x2, y2]` in original-image pixel coordinates |
| `status` / `unknown` | Physical condition and an independent unknown flag for damaged characters |
| `unavailable_font` / `expert_prediction` / `suspicious` | Required per-box boolean flags; suspicious can combine with font/expert flags but cannot combine with unknown |
| `annotations` | One normalized character per box; `MISS` denotes missing source content in mismatch records |
| `image_resize` | Source/output dimensions and scale factors |
| `crop` | Four corners in resized-image coordinates |
| `issue_type` | Source mismatch type only: missing_text, extra_text, or other; absent from normal annotations |

> [!IMPORTANT]
> Boxes remain in original-image coordinates; crop corners refer to `image_resize.output_size`. Apply the scale factors when combining these geometries. Export stores JSON metadata, not cropped image files.

Normal annotations are saved as `<output-dir>/<image-stem>.json`. Confirmed discrepancies go to `source_mismatches/<image-stem>.json`. Missing/extra records include source counts and mappings; **Other** uses a minimal issue document with a note and box coordinates. Internal `.state/` files retain verified content and consistency metadata for reopening and export.

**Download All** creates `<output-dir>/annotations.zip` with the applicable documents:

| Archive member | Contents |
| --- | --- |
| `text_annotations.json` | Array of normal saved annotations |
| `inscription_content.json` | Array of verified per-image content documents |
| `source_mismatches.json` | Array of confirmed discrepancy records |

All three files are included; empty categories contain `[]`. Suspicious is saved directly on each bounding box and does not create a source mismatch or a separate file. Reordering character cards keeps the flag on its box; reopening an annotation restores it from the saved JSON. Missing/extra records retain the flag on their annotated boxes. Annotation files must contain the current flags; the former suspicious sidecar format is not migrated or loaded. The standalone detection CLI returns `image`, `bounding_boxes`, and a separate `reading_order` list; this is an intermediate result, not a completed annotation document.

## Architecture

| Component | Responsibility |
| --- | --- |
| `text_extraction` | Discover fonts, match embedded glyph outlines to Unicode, decode PDF lines, and parse configured record boundaries and sections |
| `text_detection` | Invert images, run OCR localization and DINO inference, fuse boxes, and propose reading order |
| `gradio/annotation` | Maintain verification state, validate geometry and alignment, track discrepancies, and atomically persist JSON |
| `gradio/ui` | Synchronize interactive SVG editing and character cards with Python workflow state |
| `gradio/crop` | Validate crop rectangles and compute export resize geometry |

Glyph profiles use exact outline signatures when available and rasterized nearest-reference matching otherwise. Accuracy depends on suitable reference fonts. Reading order is heuristic and requires review, particularly for irregular layouts.

Fusion retains a larger OCR box as `damaged` when a smaller damage box is contained with at least 80% smaller-box coverage and IoU below 0.5, reducing duplicate character boxes.

## Detection models

Supply these external assets; checkpoints and executables are excluded from version control:

```text
text_detection/models/
├── ckpts/
│   ├── damage_detect.py       # DINO / MMDetection configuration
│   └── damage_detect.pth      # Matching checkpoint
└── dists/det_model/det_model  # Packaged OCR detector executable
```

The configuration/checkpoint must match, and the executable must be compatible with the host. On Linux:

```bash
chmod +x text_detection/models/dists/det_model/det_model
python -m text_detection /path/to/image.jpg --output output/detection.json
```

Both entry points accept `--vague-det-config`, `--vague-det-weights`, and `--ocr-det-executable` for alternative asset paths. DINO selects CUDA when PyTorch reports it available, otherwise CPU; this does not establish CPU compatibility for the external executable or pinned installation.

## Development

The repository uses `unittest` for extraction, detection adapters, annotation validation, exports, and Gradio callbacks. With extraction and manual annotation dependencies installed:

```bash
python -m unittest discover -s tests
python -m unittest discover -s gradio/tests
```

Detection tests include mocked model outputs and adapters. Passing them does not validate real checkpoint inference or the packaged executable.

## Acknowledgements

Character localization, DINO damaged-character detection, and the reading-order heuristic are based on [AutoHDR](https://github.com/SCUT-DLVCLab/AutoHDR). Consult the upstream project for the original models and approach. This repository integrates those stages with PDF extraction and human verification, including the additional containment rule described above.

## License

No repository-level license file is currently included. Review applicable permissions for the code, bundled fonts, source documents, and external model assets before reuse or redistribution.
