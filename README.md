# SinoNom Annotation

Tools for extracting inscription text from PDFs and annotating Hán/Nôm characters in images. The Gradio app lets you verify source text, edit character boxes, arrange reading order, and export annotations. It reads source JSON; it does not extract text directly from PDFs.

## Prepare your data

- **Images:** A flat folder of inscription images. Each filename stem must be unique and match exactly one `ky_hieu` in the source JSON (for example, `12305.jpg` matches `"ky_hieu": "12305"`).
- **Source JSON:** Extracted or reviewed inscription records containing `noi_dung`, face identifiers (`ky_hieu`), and `chuyen_muc` sections with `tieu_de` and `van_ban`. Each image needs one original Hán/Nôm text section, normally `Nguyên văn chữ Hán Nôm`.
- **Document config:** Start from [configs/tap_1.json](configs/tap_1.json). Set `paths.output_json` (source JSON), `gradio.image_dir`, and `gradio.output_dir`, and adjust content headings for your document. Paths inside the config are relative to the config file.
- **For PDF extraction:** Prepare the source PDF, matching Unicode reference fonts in `fonts/`, and config settings for PDF paths, glyph profile, page filtering, record headings, and face markers.
- **For automatic detection:** Prepare the model assets listed below. Manual annotation can run without them.

## Install and run

Run commands from the repository root using Python 3.11.

For manual annotation:

```bash
python -m pip install -r gradio/requirements.txt
python gradio/app.py --config configs/tap_1.json --skip-detection
```

For the complete extraction and detection runtime (Linux x86_64, CUDA 12.1):

```bash
python -m pip install -r requirements.txt
python gradio/app.py --config configs/tap_1.json
```

The app uses `configs/tap_1.json` by default. Override data paths when needed:

```bash
python gradio/app.py --config configs/tap_1.json --skip-detection \
  --image-dir /path/to/images \
  --source-json /path/to/source.json \
  --output-dir /path/to/annotations
```

Open the local URL printed in the terminal. Gradio selects an available port automatically; use `--port 7861` to choose one. For remote access, add `--server-name 0.0.0.0 --share`. Run `python gradio/app.py --help` for all options.

## Gradio workflow

1. **Image:** Select an image and click **Start Verification**.
2. **Content:** Check and correct the available source sections. The original Hán/Nôm text supplies the character sequence.
3. **Bounding Boxes & Sort:** Run detection or draw/edit boxes manually. Use **Sort Boxes** for all or selected boxes, or assign order numbers manually. Before continuing, every box needs a unique order from `1` to `n`.
4. **Status & Order:** Review `intact`/`damaged` status, mark damaged characters as unknown when needed, arrange character cards to match numbered boxes, and flag suspicious content.
5. **Crop:** Adjust the crop frame. Crops longer than 4096 pixels are scaled down proportionally at export.
6. **Review:** Inspect the image and JSON, then click **Save Annotation**.

If box and character counts differ, confirm **Missing Content** (more boxes) or **Extra Content** (more characters). Missing content uses `MISS` cards; extra characters are exported as excluded characters. Choose **Other** with a note for an issue that cannot be mapped; this goes directly to Review.

**Next** validates each stage and keeps edits in the current session. **Save Annotation** writes results to the output folder; the source JSON stays unchanged. Use **History** to find completed and unfinished images.

After saving, **Download All** creates `annotations.zip` in the output folder and downloads it. Depending on the saved records, it contains:

| File | Contents |
| --- | --- |
| `text_annotations.json` | Character boxes, statuses, character assignments, and crop information |
| `inscription_content.json` | Verified content for each saved image |
| `source_mismatches.json` | Confirmed source issues and missing/extra character mappings |
| `suspicious_details.json` | Suspicious Box IDs and notes |

Unsaved drafts are excluded from the archive.

## PDF extraction commands

List the PDF's embedded fonts, then place matching Unicode reference-font files in `fonts/`:

```bash
python helpers/list_pdf_fonts.py /path/to/document.pdf
```

Reference fonts must match the embedded family/style metadata. Configure the PDF and output paths in your document config, then run:

```bash
python -m text_extraction.font_discovery --config configs/tap_1.json
python -m text_extraction.glyph_profile --config configs/tap_1.json
python -m text_extraction.main --config configs/tap_1.json
```

Font discovery updates `encoded_fonts`; profile generation and extraction also perform this step automatically. Reuse the glyph profile for the same PDF/font set. Extraction writes valid records to the configured output JSON and records needing review to `<output-stem>_invalid.json`.

To extract every PDF directly inside `input/` using its matching `configs/tap_N.json`:

```bash
python scripts/extract_input_pdfs.py
```

Add `--only Tap-3` to select a filename fragment. The summary is written to `output/extraction_summary.txt`.

To merge valid extraction records with `manual-review` and `tag-corrected` records from `examples/` and `output/`, then check image/source matching:

```bash
python scripts/merge_record_files.py
python scripts/check_merged_records.py --image-dir /path/to/images
```

Merged files go to `merged_records/`. For duplicate face IDs, manual review takes priority over tag corrections, then valid extraction. Use the relevant merged file as Gradio's `--source-json`.

## Detection and sorting

Automatic detection requires these external assets:

```text
text_detection/models/
├── ckpts/
│   ├── damage_detect.py
│   └── damage_detect.pth
└── dists/det_model/det_model
```

Use a matching DINO config/checkpoint and an OCR executable compatible with your host. On Linux, make the executable runnable:

```bash
chmod +x text_detection/models/dists/det_model/det_model
```

Run detection independently for one image:

```bash
python -m text_detection /path/to/image.jpg --output output/detection.json
```

Character detection, DINO damaged-character detection, and the reading-order sorting process are based on [AutoHDR](https://github.com/SCUT-DLVCLab/AutoHDR). Refer to that repository for the original models and sorting approach. Detection locates boxes; characters are assigned from the verified source text in Gradio. Review the proposed boxes and order before saving.

This project's fusion adds one rule to AutoHDR: when a small damage box is contained in a larger OCR box with at least 80% smaller-box coverage and IoU below 0.5, the larger OCR box is retained as `damaged`. This avoids duplicate boxes for the same character.
