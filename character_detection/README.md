# AutoHDR Character Detection

Standalone inference-only extraction of AutoHDR's character-level text detector.
It retains the paper's YOLOv7 detection path: inverted input by default,
letterbox, RGB/CHW conversion, normalization, original NMS, and coordinate
rescaling. It also retains AutoHDR's coordinate-only reading-order heuristic.

It does **not** include recognition, DINO damage localization, Qwen/VLCP,
DiffHDR, training, datasets, evaluation, or experiment/logging code.

## Dependencies

`torch`, `torchvision`, `numpy`, `opencv-python`, and `shapely`, plus the
released AutoHDR detector executable (normally placed at
`character_detection/models/det_model`).
The executable is external to this repository and must be compatible with the
host platform.

For a standalone pip environment, install the local dependency list:

```bash
pip install -r character_detection/requirements.txt
```

## Use

```python
from character_detection import CharacterDetector

with CharacterDetector('character_detection/models/det_model') as detector:
    result = detector.detect('page.jpg', reading_order=True)

for item in result.detections:
    print(item.confidence, item.corners)
```

`corners` is `(top-left, top-right, bottom-right, bottom-left)` in original
image pixels. Set `reading_order=False` to return detector/NMS order.
