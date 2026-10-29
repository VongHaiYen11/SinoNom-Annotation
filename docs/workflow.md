# Annotation workflow

The starting screen lets you choose an image. After **Start Verification**, the workflow has four steps: **Content Verification**, **Annotation Workspace**, **Crop**, and **Review & Save**. Use **Back** and **Continue** to move between steps.

## 1. Content Verification

Choose a section and review its text. The field labels and surrounding controls are in English; option titles come directly from the volume configuration and remain unchanged, including Vietnamese titles such as `Tên bia` and `Nguyên văn chữ Hán Nôm`.

Edit the selected text and choose **Apply to Draft** to apply the change to this image's working draft. **Undo Content** reverses the last content correction. The **Content JSON** disclosure shows the structured content preview. This step does not rewrite the source JSON.

## 2. Annotation Workspace

The workspace keeps the character list, image canvas, and selected-box controls together.

### Image and box editing

- Select a character from **Reference Content** to inspect its suggested or confirmed box relationship.
- Choose **Draw Box** or hold **Alt** while dragging over the image to create a box. Drag a box to move it; drag a corner handle to resize it.
- Hold **Space** and drag to pan. Scroll the image viewport to move around an image larger than the viewport. **Ctrl/Command + scroll** zooms around the pointer. **Fit** scales the full image into the viewport; **Width** fits the image to the viewport width.
- Use the character and box number fields to jump to an item. **Focus** centers the selected box. **Shift + click** selects multiple boxes; **Delete** removes the selected boxes.
- Use **Undo** and **Redo** or Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z to reverse recent workspace edits.

### Alignment and character handling

Suggested relationships can change when content or reading order changes. Choose **Confirm Alignment** to retain a relationship. A conflicting relationship can expose **Use Suggested Alignment** and **Remove Confirmation** for resolving it. Batch confirmation actions are grouped in the workspace footer.

Use a character's **⋯** menu or its context menu to insert a literal `MISS` entry, exclude an entry from alignment, or include it again. Excluded entries remain visible in their source position and are left out of the effective alignment sequence.

Status and damage labels belong to boxes. Confirming an alignment does not silently change an existing status. Damaged boxes require damage level 1, 2, or 3. The required handling for `□`, `@`, and `MISS` is shown before a confirmation that needs a flag change.

**Continue** validates the workspace before moving on. It checks that boxes and reading orders are usable, statuses are valid, and confirmed alignments are complete and one-to-one. When validation fails, the issue list describes what needs attention and can be downloaded as a text report.

## 3. Crop

Drag the crop frame or its corners to set crop geometry. **Suggest position** creates a crop that includes the bounding boxes. The crop is metadata for export; the source image is not overwritten. The viewer supports zoom and scrolling when the image exceeds its viewport.

## 4. Review & Save

Review the image and result JSON. **Save Annotation** writes the completed per-image result and editor sidecar to the configured output directory. **Download All** is available from the application header when saved results exist; it packages the completed JSON exports, not editor sidecars.

## Recovery

- Reloading the same browser tab can restore in-progress work while the server process remains running. This recovery is tied to that tab and process.
- **Download Progress** saves a portable, versioned JSON snapshot. On another session, choose **Restore from Progress File**, review the import summary, and confirm with **Restore Progress**. Canceling the preview does not apply the restore.
- The backup does not contain image files. The target server needs matching image names and dimensions, source content, and relevant configuration. Download a new backup after making additional edits.

See [Development](development.md) for how to launch the app and prepare its inputs.
