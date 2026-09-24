# AutoHDR Stage 1: text and damage localization

`text_detection` is an optional, image-level AutoHDR adapter. It does not
recognize the character inside a box or alter the source image. Its inference
responsibilities are:

1. Detect ordinary character boxes with the OCR detector.
2. Detect damaged-character boxes with the DINO detector.
3. Remove an OCR box whose IoU with any damage box is at least `0.5`.
4. Apply the vendored layout-aware reading-order heuristic to the fused boxes.

The Python inference API returns a `Stage1Result` containing integer `xyxy`
boxes in these fields:
`ocr_boxes`, `damage_boxes`, `normal_boxes`, `fused_boxes`, and
`ordered_boxes`. `normal_boxes` is the OCR subset left after fusion;
`fused_boxes` is damage boxes followed by normal boxes.

This package is independent of `text_extraction`: installing or importing the
PDF extraction workflow does not load the ML stack.

## Install and model runtime

Install the optional common runtime from the repository root:

```bash
uv sync --extra text-detection
```

The DINO configuration and checkpoint are external model assets, as is the OCR
detector executable. The DINO configuration determines the compatible
MMDetection/MMCV/MMEngine versions, so that MMLab stack is deliberately not
pinned in this repository. Install the versions required by the supplied
`damage_detect.py` before running Stage 1; otherwise the run stops with a
missing `mmdet` error.

As a starting point, MMDetection recommends installing MMEngine, MMCV, and
MMDetection with MIM. Do this in the project environment only after selecting
versions compatible with the external DINO config and the local Torch/CUDA
build:

```bash
uv pip install openmim
uv run mim install mmengine
uv run mim install "mmcv>=2.0.0"
uv run mim install mmdet
```

Use model assets from a trusted AutoHDR release and record their release,
platform, and checksums with the experiment that uses them. The OCR executable
must be compatible with the host OS and CPU/GPU environment.

```text
text_detection/
├── models/
│   ├── ckpts/
│   │   ├── damage_detect.py
│   │   └── damage_detect.pth
│   └── dists/
│       └── det_model/det_model
├── runtime/       # vendored detector and reading-order support code
└── work/          # ignored, generated inverted OCR inputs
```

Model files and generated work images are intentionally ignored by Git.

## Run

From the repository root, pass exactly one input image. By default the command
writes a JSON file beside it using the same stem:

```bash
uv run python -m text_detection path/to/input.png
```

To choose the destination explicitly:

```bash
uv run python -m text_detection path/to/input.png \
  --output output/input.json
```

`text_detection.main.main()` is the canonical entry point used by both
commands. Pass `--help` to see model paths and detector thresholds:

```bash
uv run python -m text_detection --help
```

## JSON output

Bounding-box IDs are stable, one-based IDs assigned from `fused_boxes` (damage
boxes first, then retained intact OCR boxes). `reading_order` is the ordered
list of those IDs, so it remains meaningful even when spatial order differs
from detector order.

```json
{
  "image": "bia_001.jpg",
  "bounding_boxes": {
    "1": {
      "bbox": [120, 450, 180, 520],
      "status": "damaged"
    },
    "2": {
      "bbox": [120, 350, 180, 420],
      "status": "intact"
    }
  },
  "reading_order": [2, 1]
}
```

`bbox` uses `[x1, y1, x2, y2]`. `status` is either `intact` or `damaged`.

For code use, pass an object with the same attributes exposed by the CLI
options:

```python
from types import SimpleNamespace

from text_detection import run_stage1

options = SimpleNamespace(
    vague_det_config="text_detection/models/ckpts/damage_detect.py",
    vague_det_weights="text_detection/models/ckpts/damage_detect.pth",
    ocr_det_executable="text_detection/models/dists/det_model/det_model",
    det_batch_size=1,
    img_size=2048,
    conf_thres=0.45,
    iou_thres=0.2,
)
result = run_stage1("page.png", options)
for box in result.ordered_boxes:
    print(box)
```

To serialize an already computed result without invoking the CLI, use
`build_detection_document()` and `write_detection_json()` from
`text_detection.main`.

`iter_stage1()` exposes the progress phases `loading_models`, `preprocessing`,
`detecting`, `fusing`, and `reading_order` for callers that need progress
updates.
