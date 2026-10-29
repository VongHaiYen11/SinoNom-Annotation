# SinoNom Annotation Tool

![Python: ≥3.11](https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)
![Gradio: 6.28.0](https://img.shields.io/badge/Gradio-6.28.0-F97316)

Vietnamica Alignment is a desktop-oriented tool for verifying Hán–Nôm inscription text and annotating character locations in images. It combines PDF text extraction, optional character detection, manual alignment and review, then exports structured JSON.

## What it does

- Extracts structured records from PDFs with embedded glyph fonts.
- Lets reviewers verify source text and configured metadata.
- Supports automatic detection when its external models are installed, or manual box drawing and editing.
- Records reading order, character alignment, damage status, crop geometry, and source mismatches.
- Saves per-image results and exports completed work as a ZIP archive.

The app has four workflow steps: **Content Verification → Annotation Workspace → Crop → Review & Save**. See [the workflow guide](docs/workflow.md) for the controls, keyboard shortcuts, validation rules, and recovery behavior.

## Requirements

- Python 3.11 or newer.
- Image files and source JSON for the inscriptions you will annotate. Dataset inputs are not included in this repository.
- For automatic detection: the supported Linux x86_64/CUDA 12.1 environment and separately supplied detection model files. Manual annotation does not require those models.

## Quick start: manual annotation

Install the shared runtime from the root `requirements.txt`. Its pinned detection dependencies target Linux x86_64, Python 3.11, and CUDA 12.1; use an isolated environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the app with paths to your image directory, source JSON, and output directory. Use a volume config for its content headings and metadata fields; the command-line paths override the config's data paths.

```bash
python gradio/app.py --config helpers/configs/tap_1.json \
  --image-dir /path/to/images \
  --source-json /path/to/source.json \
  --output-dir /path/to/annotations \
  --skip-detection
```

Open the local URL printed in the terminal. `--skip-detection` disables the detection action; you can still draw and edit boxes manually. Use `--share` only when you need a public Gradio link.

`helpers/configs/demo.json` is a local demo setup, not a self-contained sample: it expects files under `input/demo/` and references an external PDF and glyph profile. Those inputs are intentionally not bundled. Supply the matching data or override the paths as shown above.

## Full detection setup

The shared installation above includes the detection dependencies.

Detection checkpoints and the OCR executable are external assets and are not included. See [Development](docs/development.md#detection-models) for their expected locations and CLI overrides. Start the app without `--skip-detection` to enable detection.

## Prepare source data

Image stems must match exactly one `noi_dung[].ky_hieu` value in the source JSON. Each record needs a `chuyen_muc` section whose `tieu_de` matches the configured `records.content.start_heading`. Keep the Vietnamese schema keys and section titles unchanged.

Minimal example for `12305.jpg`:

```json
[
  {
    "noi_dung": [
      {
        "ky_hieu": "12305",
        "chuyen_muc": [
          {"tieu_de": "Nguyên văn chữ Hán Nôm", "van_ban": "永樂"}
        ]
      }
    ]
  }
]
```

For PDF extraction, use the commands and configuration described in [Development](docs/development.md#pdf-to-json-extraction).

## Saved work and exports

Per-image annotations and `.state` sidecars are written under the configured output directory. The sidecars preserve editor state needed to reopen the work; keep them with the corresponding results. **Download All** exports completed results as `text_annotations.json`, `inscription_content.json`, and `source_mismatches.json` in a ZIP. It does not include editor sidecars. See [Export Format](docs/export-format.md) for schemas and merge guidance.

The same browser tab can recover in-progress edits after a reload while the app process is running. **Download Progress** creates a separate JSON backup for restoring work in another session or server. The backup does not contain image binaries; restore requires matching images, source content, and configuration. It is a snapshot, so download it again after further edits.

Font files load in the background. You can continue annotating while they load; if a font fails, the compact notice offers retry or lets you continue with available fonts.

## Repository map

| Path | Purpose |
| --- | --- |
| `helpers/configs/` | Volume and demo configuration |
| `input/`, `data/` | Local source datasets and glyph profiles (ignored by Git) |
| `outputs/` | Generated extraction, merged records, annotations, and reports (ignored by Git) |
| `fonts/` | Bundled reference and browser display fonts |
| `helpers/text_extraction/` | PDF glyph decoding and source JSON generation |
| `text_detection/` | Detection runtime, box fusion, and reading order |
| `gradio/annotation/` | Workflow rules, state, persistence, recovery, and exports |
| `gradio/ui/` | Gradio screen composition and browser assets |
| `gradio/crop/` | Crop interaction and export geometry |
| `helpers/analysis/` | Hán Việt frequency analysis and inscription decade charts |
| `helpers/records/` | Merge and validate source records; local review examples |
| `helpers/image_extraction/` | Extract inscription faces/images and store the input copy report |
| `helpers/misc/` | Standalone utilities without a shared topic, including the Kaggle downloader |
| `helpers/tests/`, `tests/`, `gradio/tests/` | Python and JavaScript tests |

Generated files use one `outputs/` directory:

- `outputs/extraction/`: PDF extraction JSON and validation reports (formerly `output/`).
- `outputs/merged_records/`: merged source records (formerly `merged_records/`).
- `outputs/annotations/`: default annotation results and `.state` sidecars.
- `outputs/demo/`: local demo annotation results and `.state` sidecars.
- `outputs/playwright/`: local browser captures.
- `outputs/reports/`, `outputs/han_viet_frequency/`, `outputs/inscription_decades/`: reports and analysis.

Preparation tools live in `helpers/`, grouped by topic as described below. Local review examples moved from `examples/` to `helpers/records/examples/`. Config paths are relative to `helpers/configs/`; the app defaults to `helpers/configs/tap_1.json`.

## Helper tools

```text
helpers/
├── configs/             # Volume and demo configuration
├── text_extraction/     # PDF decoding, glyph profiles, font inspection, batch extraction
├── image_extraction/    # Inscription images/faces and the input copy report
├── records/             # Record merging, validation, local examples/
├── analysis/            # Transcription frequency and decade charts
├── misc/                # Standalone dataset downloader
└── tests/               # Tests for preparation and analysis tools
```

Run preparation tools from the repository root:

```bash
python -m helpers.text_extraction.glyph_profile --config helpers/configs/tap_1.json
python -m helpers.text_extraction.main --config helpers/configs/tap_1.json
python helpers/text_extraction/extract_input_pdfs.py --only Tap-1
python helpers/text_extraction/list_pdf_fonts.py /path/to/document.pdf
python helpers/image_extraction/extract_missing_images.py --dry-run
python helpers/records/merge_record_files.py
python helpers/records/check_merged_records.py
python helpers/analysis/count_han_viet_frequency.py --top 20
python helpers/analysis/chart_inscription_decades.py --help
```

`helpers/image_extraction/copy_report.json` is the default input report for missing-image extraction; use `--report` to choose another report. `helpers/image_extraction/extract_33651_faces.py` handles the specific volume-4 face correction. The standalone downloader in `helpers/misc/download_dataset.py` requires `kagglehub`.

Paths inside configs resolve from the config file's directory. Bundled configs use `../../` to refer to repository-level inputs and fonts. Keep `.state` sidecars alongside saved annotation results. Local review examples under `helpers/records/examples/` and generated files under `outputs/` are ignored by Git.

```bash
python -m unittest discover -s helpers/tests -p 'test_*.py'
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s gradio/tests -p 'test_*.py'
```

## Project guides

- [Architecture](docs/architecture.md)
- [Annotation workflow](docs/workflow.md)
- [Development and troubleshooting](docs/development.md)

## Acknowledgments

[AutoHDR](https://github.com/SCUT-DLVCLab/AutoHDR) provides upstream character-localization and damage-detection components and a reading-order heuristic used by this project.
