# Export Format

This guide describes the JSON files included in the annotation export archive.

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
