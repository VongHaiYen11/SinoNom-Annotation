# AutoHDR Stage 1 checkpoints

Place these files here before running `python -m text_detection`:

- `damage_detect.py` - MMDetection DINO configuration.
- `damage_detect.pth` - DINO damage-localization checkpoint.

The files are intentionally not versioned because the checkpoint is large and
the model assets are distributed separately by AutoHDR. `damage_detect.py`
also determines the compatible MMDetection/MMCV/MMEngine versions; keep the
configuration and checkpoint from the same release.
