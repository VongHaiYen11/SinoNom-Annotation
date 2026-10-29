# Development

This guide covers local setup, runtime inputs, tests, and common problems. All runtime dependencies are maintained in the root `requirements.txt`; external detection model assets are configured separately.

## Manual annotation environment

The shared `requirements.txt` targets Linux x86_64, Python 3.11, and CUDA 12.1. It includes Gradio, extraction, and detection dependencies. From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Provide an image directory and source JSON. Their paths are local to the machine running the server. Run manual annotation with a volume config for section headings and metadata fields:

```bash
python gradio/app.py --config helpers/configs/tap_1.json \
  --image-dir /path/to/images \
  --source-json /path/to/source.json \
  --output-dir /path/to/annotations \
  --skip-detection
```

The CLI options override the corresponding data paths from the config. Relative paths written in a config resolve from the config file's directory. See `python gradio/app.py --help` for all options, including port and model-path overrides.

The checked-in `helpers/configs/demo.json` expects local data under `input/demo/`; its input PDF and glyph profile are also external. Those files are not part of a clean checkout. Local `outputs/demo/` files are saved sample results and sidecars, not the missing image/source inputs. Adjust the config or pass CLI overrides before launching.

## Detection models

The shared installation above includes the PyTorch/MMCV stack. Model files must be supplied separately.
The app expects a damage-localization config/checkpoint and OCR executable under `text_detection/models/`. These external assets are not included in the repository. See the [AutoHDR model instructions](https://github.com/SCUT-DLVCLab/AutoHDR#-model-zoo) and use model files compatible with the pinned environment. The model paths can be overridden with `--vague-det-config`, `--vague-det-weights`, and `--ocr-det-executable`. Leave off `--skip-detection` to enable detection.

## PDF-to-JSON extraction

Extraction is a separate preprocessing command. It uses the PDF, reference fonts, and paths in the selected volume config; it does not start the annotation app.

```bash
python -m helpers.text_extraction.glyph_profile --config helpers/configs/tap_1.json
python -m helpers.text_extraction.main --config helpers/configs/tap_1.json
```

The root requirements include the extraction libraries. The generated JSON path is `paths.output_json`; review any generated `_invalid.json` report before using the source records in the app.

`helpers/image_extraction/extract_missing_images.py` reads the missing-ID input report from `helpers/image_extraction/copy_report.json` by default; use `--report` to select another input report. The generated extraction report is written under `--output-dir` as `extraction_report.json`.

## Tests

The Python suites use `unittest`:

```bash
python -m unittest discover -s helpers/tests -p 'test_*.py'
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s gradio/tests -p 'test_*.py'
```

The JavaScript browser-asset tests use Node.js built-ins:

```bash
for file in gradio/tests/*.js; do node "$file"; done
```

For browser interaction changes, launch the manual app with a small dataset and check the affected flow at desktop and narrow viewport sizes. Use the same image and source JSON when checking progress backup and restore.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The app cannot find an image or source JSON | Confirm the paths exist on the server machine. Config-relative paths are resolved from the config directory; CLI path options override them. |
| An image has no matching source record | Match each image stem to exactly one `noi_dung[].ky_hieu` value. |
| Detection is unavailable | Confirm the model config, checkpoint, OCR executable, and compatible Linux/CUDA environment. For manual work, use `--skip-detection`. |
| A character glyph is missing | Wait for font loading, retry failed fonts, or continue with the fonts already available. |
| Reload did not restore the draft | Same-tab recovery requires the same browser tab and a running server process. Use **Download Progress** for a portable snapshot. |
| Progress restore rejects a file | Restore against matching image names/dimensions, source content, and annotation configuration. The backup does not carry image binaries. |
| Export is missing editor history or preferences | Keep the per-image `.state` sidecars with saved results. The Download All archive contains result JSON, not editor sidecars. |
