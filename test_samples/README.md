# Manual test samples

Keep the three inputs for one page together in `sample_001/`:

- The original image (`.jpg` or `.png`).
- The detection JSON containing bounding boxes.
- The text annotation JSON to compare or align with those boxes.

Suggested layout (existing filenames may be kept):

```text
test_samples/
  sample_001/
    original.jpg
    detection.json
    character_annotations.json
```

Use inputs for the same page and the original image dimensions used for
detection. Keep JSON contents unchanged so their schemas can be inspected.
If annotations cover multiple pages, keep that file intact and identify the
page corresponding to the image.

For another sample, create `sample_002/`, and so on. This directory is a
manual input location; it does not automatically run inference or import
the files into the annotation app.
