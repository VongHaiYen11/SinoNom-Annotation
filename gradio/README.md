# Vietnamica Gradio annotation

A seven-step image annotation workflow using centralized Python state. The UI uses the dark/orange design from `image-annotation-tool-design/`; no Next.js installation is required. Source text comes from existing extraction JSON, while optional detection uses `text_detection`.

## Installation

Python 3.11+, from the repository root:

```bash
pip install -r gradio/requirements.txt
```

For UI, PDF extraction and detection on Kaggle Linux x86_64 with Python 3.11:

```bash
python -m pip install -r requirements-detection.txt
```

That file includes the UI dependencies and uses Torch 2.1.0/cu121 and MMCV 2.1.0. Do not additionally install `.[text-detection]`, which requires newer Torch. Model weights and the OCR executable must be supplied separately. See `../text_detection/README.md` for compatible detection dependencies. UI and state tests do not require the ML runtime.

For the existing virtual environment:

```bash
uv pip install --python .venv/bin/python -r gradio/requirements.txt
```

## Run

```bash
python gradio/app.py \
  --image-dir /absolute/path/images \
  --source-json /absolute/path/source.json \
  --output-dir /absolute/path/annotations \
  --skip-detection
```

Open `http://127.0.0.1:7860`; use `--port 7870` to change the port. `--skip-detection` disables automatic and manual model execution. Existing annotations still load, and boxes can be drawn manually. All workflow validation remains active. The separate screen-preview mode has been removed.

To enable detection, omit `--skip-detection` and supply:

```text
--vague-det-config /absolute/path/damage_detect.py
--vague-det-weights /absolute/path/damage_detect.pth
--ocr-det-executable /absolute/path/det_model
```

The packaged OCR subprocess output is hidden by default, so PyInstaller import
debug lines do not flood Kaggle logs. Add `--show-detection-logs` temporarily
when diagnosing an executable that fails to start.

Alternatively, run `python app.py` from `gradio/`. Defaults are relative to the working directory: `data/images`, `data/source_json/source.json`, `data/annotations`. Missing inputs display an error; restart with correct paths.

The image folder is flat. Image stems must match source `ky_hieu` exactly, such as `12305.jpg`. Duplicate stems are rejected to prevent output collisions. Images are selected from the folder, not uploaded.

## Content and source schema

The adapter supports the repository's extraction format:

```json
[{"so_van_bia":1,"noi_dung":[{"ky_hieu":"12305","chuyen_muc":[{"tieu_de":"Nguyên văn chữ Hán Nôm","van_ban":"永寺樂"}]}]}]
```

The editor exposes only the existing `van_ban` values of these sections for the selected image's face:

| Source title | UI label |
| --- | --- |
| Nguyên văn chữ Hán Nôm | Original Hán/Nôm text |
| Phiên âm Hán Việt | Sino-Vietnamese transcription |
| Dịch nghĩa | Translation |
| Toát yếu | Summary |
| Chú thích | Notes |

Source text, titles, metadata, other sections and other faces remain in their original language and format. Missing sections are not invented. Annotation uses only the original Hán/Nôm text. Missing or ambiguous image codes/annotation sections are errors. Additional schemas require an adapter in `annotation/text_extraction.py`.

## Workflow

1. **Image:** choose an image and select **Open image**. Saved annotations load automatically; session drafts are retained per image.
2. **Content:** edit a section, select **Apply content**, then **Save content** to update the source JSON and verify the text. **Undo changes** returns to the latest saved content; **Restore original content** restores the initial snapshot into the draft and requires Save to persist.
3. **Bounding Boxes:** draw, move or resize boxes; edit coordinates or delete by stable ID. Detection runs on first entry unless disabled. Replacing existing boxes through detection requires its confirmation checkbox.
4. **Status:** select a box on the image or in the left table, choose intact/damaged, and update. Intact boxes are green; damaged boxes are red, including selected boxes. Character text and alignment cards are hidden on this screen. Count mismatches block entry; temporary alignment is performed internally.
5. **Reading Order:** drag character cards or apply a JSON list of box IDs. Reordering changes only the sequence, never the ID-to-character mapping.
6. **Crop:** move/resize the rectangular frame or apply coordinates. Crop remains independent of annotation coordinates and is included when saving the image.
7. **Review:** inspect the image, table, final text, reading order and complete JSON. **Save image** writes one object containing annotation and crop.

Back/Next retain the same state and enforce validation. **Reset draft** reloads the selected image from disk. Browser reload starts a new session; unsaved drafts are lost. There is no automatic file save.

Canvas zoom and Fit image affect display only. Coordinate controls and the reading-order field provide alternatives to dragging. The workspace stretches with the control panel and keeps navigation at its bottom. Shared CSS classes (`section`, `field-group`, `button-group`, `panel`) use consistent spacing across all steps.

## Fonts

The font selector supports NomNaTong, DengXian and PMingLiU. Local font files under `fonts/` are served directly, including PMingLiU-ExtB for extended characters. Missing glyphs fall back to the other fonts. Font selection changes rendering only; text, counts and annotations remain unchanged. PDF extraction's `encoded_fonts` configuration is unaffected.

## Saving and downloading

```text
annotations/
├── 12305.json          # One object: image, bounding_boxes, reading_order, annotations, crop
└── .state/
    ├── 12305.json      # Temporary order, next ID and source/document hashes
    └── content.json    # Internal Save-all registry; not a user download
```

Crop contains `top_left`, `top_right`, `bottom_right`, `bottom_left` in original image coordinates. If no crop was changed, it covers the full image. Existing separate `crops/<stem>.json` files remain readable; an embedded crop takes precedence. The application does not crop the image file itself.

**Save content** adds or updates that image's object in the internal Save-all registry. It does not trigger a download and does not create a separate content file per image. The object contains `image`, `inscription_code`, and a stable `content` mapping for Original Hán/Nôm text, Sino-Vietnamese transcription, Translation, Summary and Notes. A missing optional source section is represented as `null`; content is never invented. Draft edits do not update the registry until **Save content** is pressed again.

**Save all** in the header downloads up to two aggregate files:

- `annotations.json` contains only images previously committed with **Save image** on Review.
- `content.json` contains only images previously committed with **Save content** in Content Verification.

Unsaved images and in-memory draft changes are excluded. Each object reflects its last explicit save. If only one data type has saved records, only its file is downloaded; if neither has records, the app displays an error. Downloading does not modify per-image files or draft state.

JSON uses UTF-8 with readable Unicode. Individual files are written atomically. State sidecars are trusted only when hashes match. When source content changes, verification and dependent confirmations must be repeated. Legacy files without sidecars can be exported after structural and source-character validation, but cannot prove their original source-text ordering.

Source updates compare the record baseline under a process lock to prevent concurrent sessions overwriting source edits. This MVP assumes one server process. Individual annotation files use last-save-wins; avoid concurrent edits of the same image.

## State architecture

- `box_id` is identity; `bbox` is location; `status` is condition.
- `annotations[str(box_id)]` holds character content; `reading_order` holds IDs.
- One `gr.State` holds active state and per-image drafts. JavaScript sends actions; Python validates and returns the authoritative snapshot.
- Temporary order is independent of reading order. Deleted IDs are never reused within state; saved sidecars retain the ID high-water mark.
- Text changes invalidate alignment/status/order even when character count stays equal. Box edits invalidate dependent verification. Matching counts permit alignment from current temporary order, followed by status/order confirmation.
- Status edits preserve identity, coordinates, annotation and order. Crop edits preserve annotation data.
- Mutation callbacks are serialized. Canvas/card events carry image and revision so stale events are rejected.

Raw extraction → draft → Save source → verified content → annotation text → count validation → temporary alignment.

Normalization uses NFC, removes whitespace and Unicode punctuation (category P), and preserves meaningful letters/symbols, including text inside parentheses. Grapheme counting uses `regex` `\X`, so combining marks and variation selectors are not separate characters. Original source text keeps punctuation. Counting and mapping share the rules in `text_alignment.py`.

## Tests

```bash
python -m unittest discover -s gradio/tests -v
```

Tests use temporary images/source files and mock detection, without models or changes to real data. They cover state invariants, callbacks, count changes, source conflicts, combined crop persistence and folder export. See `examples/bia_001.json` for an output object.

## Modules

`app.py` builds components and callbacks. `annotation/` handles state, workflow, extraction, boxes, status, order, alignment and persistence/export. `ui/presentation.py` and `ui/assets/workbench.css` define layout; `ui/editor.py` and editor assets implement SVG interactions. `crop/crop.py` handles crop validation independently. Do not add `gradio/__init__.py`, which would shadow the installed Gradio library.
