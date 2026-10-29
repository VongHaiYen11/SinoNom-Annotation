# SinoNom Annotation Tool

![Python: ≥3.11](https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)
![Gradio: 6.28.0](https://img.shields.io/badge/Gradio-6.28.0-F97316)

## Introduction

Vietnamica Alignment is a semi-automated tool for annotating Hán–Nôm inscriptions. It combines structured text extraction from PDFs with character-level alignment to inscription images and manual verification through a Gradio interface.

Reviewers can correct source content, character locations, reading order, and damage labels before exporting structured JSON. The resulting annotations can support downstream research on inscription text, character recognition, and document damage.

## Key Features

- **PDF text extraction:** Decode embedded glyphs and generate structured inscription records.
- **Character detection and box editing:** Detect character regions or draw and adjust bounding boxes manually.
- **Text alignment and reading order:** Assign characters to boxes and correct box order and text sequence.
- **Damage annotation:** Label characters as intact or damaged, with light, medium, or severe damage levels and character flags.
- **Source verification:** Review text and metadata, and record missing text, extra text, or other source mismatches.
- **Crop metadata:** Define the crop region recorded in export geometry.
- **JSON export:** Download saved annotations, verified content, and source mismatches in one ZIP archive.

## Repository Structure

```text
configs/          # Per-volume settings
fonts/            # Reference and display fonts
text_extraction/  # PDF decoding and structured record extraction
text_detection/   # Detection, box fusion, and reading order
gradio/           # Annotation UI, validation, and export
scripts/          # Batch extraction, record processing, and analysis
helpers/          # Data preparation and inspection utilities
tests/            # Tests; UI tests also live in gradio/tests/
```

Input PDFs, inscription images, source JSON, matching reference fonts, and pretrained model assets may need to be provided separately.

## Annotation Workflow

1. **Image:** Select an inscription image and start verification.
2. **Content:** Review and correct the source text and configured metadata.
3. **Bounding Boxes & Sort:** Detect characters or draw boxes manually, then assign their order.
4. **Status & Order:** Check character assignments, reorder text, and set intact/damaged status, damage levels, and flags.
5. **Crop:** Adjust the crop region used in export metadata.
6. **Review:** Inspect the final image and JSON, then save the annotation.

**Download All** exports saved results as a ZIP archive.

Font preparation displays downloaded MB and byte percentages for each bundled font and the combined download. A font becomes ready only after the browser parses it. Unknown totals display received MB without a percentage. After five minutes, choose **Tiếp tục chờ** to wait another five minutes (retrying failed fonts), or **Làm việc với font đã có** to continue with available fonts while downloads finish in the background. Some characters may remain unavailable until their font is ready. Finished downloads with errors offer **Thử lại font lỗi** immediately. Font preparation has its own dialog and does not dismiss annotation task loading, reload the page, or restart the server.

To verify font preparation locally, run `node gradio/tests/test_font_loader.js`. For browser acceptance, use network throttling with a cold cache: check per-font and total progress, leave a request pending for five minutes, test both choices and keyboard focus, then restore the connection and confirm glyphs update automatically. Block a font request to check immediate retry once the other requests finish. Repeat with a warm cache and confirm each font has only one request and annotation loading is unaffected.

## Getting Started

### Prerequisites

| Mode | Runtime | Dependencies |
| --- | --- | --- |
| Full detection | Linux x86_64, Python 3.11, CUDA 12.1-compatible environment | `requirements.txt` |
| Manual annotation | Python ≥ 3.11; launch with `--skip-detection` | `gradio/requirements.txt` |

The full runtime requirements are pinned for Kaggle Linux/CUDA and are not intended as a general macOS/CPU installation.

### Installation

Clone the repository:

```bash
git clone https://github.com/VongHaiYen11/SinoNom-Annotation.git
cd SinoNom-Annotation
```

For the full detection runtime:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For manual annotation, use a Python ≥ 3.11 interpreter:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gradio/requirements.txt
```

### Model Setup

For the full detection runtime, download the **Damage Localization Model** and **OCR Model** linked in the [AutoHDR Model Zoo](https://github.com/SCUT-DLVCLab/AutoHDR#-model-zoo). Extract and arrange the required files as follows:

```text
text_detection/models/
├── ckpts/
│   ├── damage_detect.py       # Matching DINO configuration
│   └── damage_detect.pth      # Damage-localization checkpoint
└── dists/det_model/
    └── det_model             # OCR executable; retain accompanying resources
```

Rename downloaded files as needed or supply `--vague-det-config`, `--vague-det-weights`, and `--ocr-det-executable`. The config must match the checkpoint, and the executable must support the host platform. Upstream environment instructions differ from this repo's pinned requirements; keep the environments separate. Qwen/DiffHDR restoration models are not required for this workflow.

```bash
chmod +x text_detection/models/dists/det_model/det_model
```

### Prepare Input Data

Place images and source JSON in a folder such as `input/data-student/student_001/`. Image stems must be unique and match exactly one `noi_dung[].ky_hieu`. Minimal source JSON for `12305.jpg`:

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

Keep the Vietnamese JSON keys and section labels shown above: they are part of the configured input schema. Each face requires exactly one section matching `records.content.start_heading`. Records may come from multiple volumes; `source_file` does not control image matching. CLI inputs are server-local paths, not remote data URLs.

### Run the Application

```bash
python gradio/app.py --config configs/tap_1.json \
  --image-dir input/data-student/student_001 \
  --source-json input/data-student/student_001/student_001.json \
  --output-dir annotations/student_001
```

Open the URL printed in the terminal. Add `--skip-detection` for manual boxes or `--share` for a public Gradio link. Results are saved under `annotations/student_001`; **Download All** creates `annotations.zip`. Download saved results before ending a Kaggle session.

Reloading the same browser tab automatically restores the current image, workflow step, and unfinished edits, including labels that have not been applied and content still being typed. Recovery uses browser session storage and application memory; keep the Gradio process running in the Kaggle session. Closing the tab, restarting the application, or ending the Kaggle session is outside this recovery guarantee. **Save Annotation** still writes the final annotation, and **Download All** includes saved results only. The recovery message above the workspace reports when browser storage is unavailable.

### Unified Annotation Workspace

The interface uses four steps after selecting an image: **Content Verification → Annotation Workspace → Crop → Review & Save**. Reference content, image geometry, reading order, and box status are edited together in the workspace; matching character/box counts are not required to start.

- The reference sidebar has an icon-only open/close control. Its width, scroll position, and selection are restored in the same tab. Selecting content preserves image zoom; use **Focus** to center a selected box.
- Right-click a character or use its **⋯** menu to insert literal **MISS** entries before/after it, **Exclude from Alignment**, or **Include in Alignment**. Excluded entries stay visible in place and do not consume an effective sequence number.
- **Draw Box** or **Alt + drag** adds a box; drag a box to move it or use its corner handles to resize. **Shift + click** selects multiple boxes; **Delete** removes selected boxes. **Space + drag** pans, and **Ctrl + wheel** zooms. Enter a character/box number and press **Enter** to navigate.
- Reading order is independent of permanent box identity. Changing order 65 to 180 inserts the box at 180 and shifts the intervening orders. Adding a box uses the established spatial sorter to suggest an insertion without reordering the other boxes.
- Position-based suggestions update automatically. **Confirm Alignment**, **Confirm & Next**, or the explicit batch controls confirm pairs. Confirmed relationships retain their IDs after content/order edits; conflicts require resolution. **Use Suggested Alignment** checks one-to-one assignment before replacing a confirmation. **Remove Confirmation** releases a conflicting relationship.
- Status and damage levels remain attached to boxes. Suggestions do not change them. Explicit confirmation applies the existing mandatory `□`, `@`, and `MISS` rules after showing any required flag changes. Every damaged box needs level 1, 2, or 3.
- **Continue** requires nonempty boxes, unique contiguous reading orders `1..N`, valid statuses, and complete confirmed one-to-one alignments. **Cannot Continue** lists issues and offers **Download Issues (.txt)**, generated from the same validation results.
- **Undo/Redo** (Ctrl/Cmd+Z / Ctrl/Cmd+Shift+Z) covers content corrections, geometry edits, reading order, and confirmations. Up to 50 recent editor states are kept, with a size budget for long inscriptions. Detection replaces boxes and starts a new box-edit history.

Saved `.state` sidecars preserve editor IDs, content corrections in their original positions, confirmations, history, and preferences. Keep these sidecars with per-image output to reopen the complete editor state. The downloadable ZIP retains the same three result files and does not include editor metadata. Source JSON is never rewritten.

## JSON Output

`annotations.zip` contains `text_annotations.json`, `inscription_content.json`, and `source_mismatches.json`. Each file contains a **top-level JSON array of objects** with zero, one, or multiple records. Each record represents one inscription image or face, identified by `image`. Empty categories are `[]`. Match records by `image`, not by array position. The examples below use illustrative 1000 × 1000 images.

### `text_annotations.json`

Character assignments, bounding boxes, damage labels, and geometry for images saved as normal annotations.

<details>
<summary><code>text_annotations.json</code> — Example</summary>

```json
[
  {
    "image": "12305.jpg",
    "bounding_boxes": {
      "1": {
        "bbox": [100, 100, 150, 150],
        "status": "intact",
        "damage_level": null,
        "unknown": false,
        "unavailable_font": false,
        "expert_prediction": false,
        "suspicious": false
      }
    },
    "annotations": {"1": "永"},
    "image_resize": {
      "source_size": [1000, 1000],
      "output_size": [1000, 1000],
      "scale_x": 1.0,
      "scale_y": 1.0
    },
    "crop": {
      "top_left": [0, 0],
      "top_right": [1000, 0],
      "bottom_right": [1000, 1000],
      "bottom_left": [0, 1000]
    }
  },
  {
    "image": "12306.jpg",
    "bounding_boxes": {
      "1": {
        "bbox": [100, 100, 150, 150],
        "status": "damaged",
        "damage_level": 2,
        "unknown": false,
        "unavailable_font": false,
        "expert_prediction": false,
        "suspicious": false
      }
    },
    "annotations": {"1": "樂"},
    "image_resize": {
      "source_size": [1000, 1000],
      "output_size": [1000, 1000],
      "scale_x": 1.0,
      "scale_y": 1.0
    },
    "crop": {
      "top_left": [0, 0],
      "top_right": [1000, 0],
      "bottom_right": [1000, 1000],
      "bottom_left": [0, 1000]
    }
  }
]
```

</details>

| Field | Meaning |
| --- | --- |
| `image` | Image filename; identifies the face within the dataset. |
| `bounding_boxes` | Map of box IDs, starting at `"1"` for each image. |
| `bounding_boxes[id].bbox` | `[x1, y1, x2, y2]` in original-image pixels. |
| `bounding_boxes[id].status` | `intact` or `damaged`. |
| `bounding_boxes[id].damage_level` | `1` light, `2` medium, `3` severe; `null` for intact. Required for damaged boxes when applying or confirming status. |
| `bounding_boxes[id].unknown` | Unidentified damaged character; cannot coexist with the other character flags. |
| `bounding_boxes[id].unavailable_font` | Character marked as unavailable in the font. |
| `bounding_boxes[id].expert_prediction` | Character interpretation marked as an expert prediction. |
| `bounding_boxes[id].suspicious` | Character assignment flagged for review. |
| `annotations` | Box ID → assigned grapheme. |
| `image_resize` | Original/output `[width, height]` in `source_size`/`output_size`, plus `scale_x` and `scale_y`. |
| `crop` | `top_left`, `top_right`, `bottom_right`, `bottom_left` in resized-image coordinates. Metadata only; no cropped image is exported. |

### `inscription_content.json`

Verified source content and configured metadata saved from the Content stage.

<details>
<summary><code>inscription_content.json</code> — Example</summary>

```json
[
  {
    "image": "12305.jpg",
    "inscription_code": "12305",
    "content": {
      "Tên bia": "Example inscription",
      "Địa điểm": "Example location",
      "Niên đại": "1700",
      "Nguyên văn chữ Hán Nôm": "永",
      "Phiên âm Hán Việt": "Vĩnh",
      "Toát yếu": null
    }
  },
  {
    "image": "12306.jpg",
    "inscription_code": "12306",
    "content": {
      "Tên bia": "Example inscription",
      "Địa điểm": "Example location",
      "Niên đại": "1700",
      "Nguyên văn chữ Hán Nôm": "樂",
      "Phiên âm Hán Việt": "Lạc",
      "Toát yếu": null
    }
  }
]
```

</details>

| Field | Meaning |
| --- | --- |
| `image` | Image filename; identifies the face within the dataset. |
| `inscription_code` | Face identifier matching the image stem. |
| `content` | Configured section labels mapped to verified text or `null` when unavailable; punctuation and line breaks are preserved. |
| `content` keys | With the default configuration: `Tên bia` (title), `Địa điểm` (location), `Niên đại` (date), `Nguyên văn chữ Hán Nôm` (original text), `Phiên âm Hán Việt` (transcription), `Toát yếu` (summary). Metadata keys are omitted when disabled. |

### `source_mismatches.json`

Images saved with missing source text (`missing_text`), extra source text (`extra_text`), or another source mismatch (`other`). Fields depend on the mismatch type.

<details>
<summary><code>source_mismatches.json</code> — Example</summary>

```json
[
  {
    "image": "12307.jpg",
    "inscription_code": "12307",
    "source_text": "永",
    "source_character_count": 1,
    "bounding_box_count": 2,
    "issue_type": ["missing_text"],
    "note": "The image has two characters, but the source contains only one.",
    "bounding_boxes": {
      "1": {
        "bbox": [100, 100, 150, 150],
        "status": "intact",
        "damage_level": null,
        "unknown": false,
        "unavailable_font": false,
        "expert_prediction": false,
        "suspicious": false
      },
      "2": {
        "bbox": [100, 160, 150, 210],
        "status": "intact",
        "damage_level": null,
        "unknown": false,
        "unavailable_font": false,
        "expert_prediction": false,
        "suspicious": false
      }
    },
    "annotations": {"1": "永", "2": "MISS"},
    "image_resize": {
      "source_size": [1000, 1000],
      "output_size": [1000, 1000],
      "scale_x": 1.0,
      "scale_y": 1.0
    },
    "crop": {
      "top_left": [0, 0],
      "top_right": [1000, 0],
      "bottom_right": [1000, 1000],
      "bottom_left": [0, 1000]
    }
  },
  {
    "image": "12308.jpg",
    "inscription_code": "12308",
    "source_text": "永樂",
    "source_character_count": 2,
    "bounding_box_count": 1,
    "issue_type": ["extra_text"],
    "note": "The source character 樂 has no corresponding box.",
    "bounding_boxes": {
      "1": {
        "bbox": [100, 100, 150, 150],
        "status": "intact",
        "damage_level": null,
        "unknown": false,
        "unavailable_font": false,
        "expert_prediction": false,
        "suspicious": false
      }
    },
    "annotations": {"1": "永"},
    "text_sequence": ["永", "樂"],
    "excluded_characters": ["樂"],
    "image_resize": {
      "source_size": [1000, 1000],
      "output_size": [1000, 1000],
      "scale_x": 1.0,
      "scale_y": 1.0
    },
    "crop": {
      "top_left": [0, 0],
      "top_right": [1000, 0],
      "bottom_right": [1000, 1000],
      "bottom_left": [0, 1000]
    }
  },
  {
    "image": "12309.jpg",
    "inscription_code": "12309",
    "issue_type": ["other"],
    "note": "The image does not match the source; review is required.",
    "bounding_boxes": {
      "1": {
        "bbox": [100, 100, 150, 150]
      }
    }
  }
]
```

</details>

| Field | Meaning |
| --- | --- |
| `image` | Image filename; identifies the face within the dataset. |
| `inscription_code` | Face identifier matching the image stem. |
| `issue_type` | `missing_text`, `extra_text`, or `other` as a single-item array; simultaneous corrections use `["missing_text", "extra_text"]`. |
| `note` | Reviewer explanation; required and nonempty for `other`. |
| `source_text` | Source text used for alignment; present for missing/extra text. |
| `source_character_count`, `bounding_box_count` | Normalized source character count and number of boxes; present for missing/extra text. |
| `bounding_boxes` | Same box fields as normal annotations for missing/extra text; only `bbox` for `other`. |
| `annotations` | Assignments for missing/extra text; `MISS` marks boxes without source characters. Absent for `other`. |
| `text_sequence`, `excluded_characters` | Extra-text and mixed records: annotation values in box order followed by the excluded source characters. The editor retains excluded characters in place; this suffix is an export convention. |
| `image_resize`, `crop` | Same geometry as normal annotations for missing/extra text; absent for `other`. |

When combining downloads, merge arrays from files with the same name and keep the latest record per `image`. An image should appear in either normal annotations or source mismatches according to its latest saved state; merge content independently.

For mixed corrections, source and box counts may be equal. Validation checks that the non-MISS annotations plus excluded characters account for the normalized source characters. A count difference alone does not identify which correction is needed. Consumers that previously assumed a single `issue_type` must accept both values for mixed records; the JSON fields and archive filenames are unchanged.

## PDF-to-JSON Extraction

PDF extraction is an optional preprocessing stage that generates source JSON from inscription PDFs. Run it separately when source JSON is not already available; it does not launch Gradio.

Provide the PDF and matching reference fonts, then edit the appropriate volume config (for example, `configs/tap_1.json`):

| Config field | Purpose |
| --- | --- |
| `input_pdf_path` | Source PDF path. |
| `paths.glyph_profile` | Glyph profile to generate and reuse. |
| `paths.output_json` | Extracted record destination. |
| `encoded_fonts` | Reference fonts used to decode embedded glyphs. |
| `page_filter`, `records` | Margins, footnotes, record boundaries, metadata, and content headings. |

Config paths resolve relative to the config file. Install extraction dependencies if not already available:

```bash
python -m pip install fonttools==4.65.0 pymupdf==1.28.2 numpy==1.26.4
python -m text_extraction.glyph_profile --config configs/tap_1.json
python -m text_extraction.main --config configs/tap_1.json
```

Records are written to `paths.output_json`; structural review items go to `<output-stem>_invalid.json`. Pass the resulting source JSON to Gradio with `--source-json`.

## References and Acknowledgments

[AutoHDR — Reviving Cultural Heritage: A Novel Approach for Comprehensive Historical Document Restoration](https://github.com/SCUT-DLVCLab/AutoHDR) supplies the upstream character-localization and damage-detection models and reading-order heuristic reused here. Vietnamica Alignment integrates these components with its PDF extraction, manual verification workflow, and annotation exports.

## Development Notes

> [!NOTE]
> Parts of the Gradio interface were developed with AI-assisted coding tools. The current implementation prioritizes annotation functionality and has not undergone a comprehensive architectural refactoring. Review the code and tests before adapting it for production use.
