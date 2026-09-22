# AutoHDR Character Detection

Standalone inference-only extraction of AutoHDR's character-level text detector.
It extracts the released AutoHDR character-detection path: inverted input by
default, the original single-image rectangular letterbox geometry, RGB/NCHW
conversion, normalization, YOLOv7 NMS, coordinate rescaling, and AutoHDR's
coordinate-only reading-order heuristic.

The detector input is a single batched RGB image (`1×3×H×W`). Internal model
feature-channel widths (for example, 64 or 256) are handled inside the released
executable and are not configurable by this package.

It does **not** include recognition, DINO damage localization, Qwen/VLCP,
DiffHDR, training, datasets, evaluation, or experiment/logging code.

## Dependencies

`torch`, `torchvision`, `numpy`, `opencv-python`, and `shapely`, plus the
released AutoHDR detector executable (normally `dist/det_model/det_model`).
The executable is external to this repository and must be compatible with the
host platform.

## Use

```python
from character_detection import CharacterDetector

with CharacterDetector('dist/det_model/det_model') as detector:
    result = detector.detect('page.jpg', reading_order=True)

for item in result.detections:
    print(item.confidence, item.corners)
```

`corners` is `(top-left, top-right, bottom-right, bottom-left)` in original
image pixels. Set `reading_order=False` to return detector/NMS order.
