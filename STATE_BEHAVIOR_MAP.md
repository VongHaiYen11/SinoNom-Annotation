# Annotation UI state and behavior map

This is the characterization baseline for any structural refactor of the Gradio annotation UI. It records current behavior, including awkward or duplicated behavior; it is not a redesign proposal. No implementation code has been moved as part of this pass.

## Evidence and confidence

Primary sources inspected: `gradio/app.py` (`create_app`, `render`, `run`, `next_step`, `commit_frontend_*`, `commit_statuses`, `on_action`); `gradio/ui/editor.py` (`snapshot`, `source_text`); `gradio/ui/assets/editor.js` (local state, DOM event handlers, snapshot bridge, render rehydration); `gradio/annotation/state.py`; `workflow.py`; `bbox.py`; `status.py`; `reading_order.py`; and `gradio/tests/test_ui.py`, `test_annotation.py`, `test_export.py`.

The Python unit suite characterizes many workflow/data contracts. A substantial part of `test_ui.py` checks source strings and markup rather than running a browser. Pointer, drag, pan, zoom, rerender timing, and live DOM snapshot behavior therefore need a manual browser pass before and after any extraction. The details below have high confidence where directly expressed in code; anything explicitly called unsafe must be characterized further before moving its implementation.

## State ownership and lifecycle

### Authoritative state by layer

| State | Current authority | Initialization and mutation | Persistence / rerender |
|---|---|---|---|
| Active workflow/image | Python `gr.State` object `ctx['active']`; created by `new_state()` and `Workflow.open_image()` | `Workflow.apply()` actions return a state snapshot; `run()` installs it in session state. Open and Reset replace it. | Most actions call `render()` and return the complete output vector; selected action families use `gr.skip()` for unaffected outputs. This is session state, not durable storage. |
| Content being edited in Step 2 | Browser `content-draft-bridge` while typing; Python `draft_content` after `commit_frontend_content()` | JS-only `field.change` copies bridge value into the field editor; `apply_field` updates bridge/preview in browser only. Save Content and Next validate/commit bridge values to Python. | Save Content persists both source JSON and output content document and verifies it. Next also saves content as part of the step transition. |
| Step 3 boxes, selection, geometry, status, order draft | JS `localBoxes` object and `selectedIds`/`activeBoxId` while interacting. Backend `regions` becomes authoritative only at explicit snapshot commits. | JS initializes from `props.value.boxes`, then mutates local objects from pointer/control actions. `syncExternalControls()` serializes the whole local collection. `commit_frontend_boxes()` sends the serialized collection to `Workflow.apply('commit_boxes')`. | Browser-only edits redraw DOM immediately. Apply boundaries include Confirm/Clear Mismatch, Sort Boxes, Delete, and Next. Complete order values may materialize Python alignment during `sync_draft_boxes`. |
| Step 4 character assignment | JS chip DOM and `localTextSequence`/token IDs while dragging; Python `text_sequence`, `text_token_ids`, `annotations` after Apply Changes or Next | Chips first render from Python snapshot; a `MutationObserver` waits until expected token IDs exist before drag is enabled and DOM order is read back. Pointer drag reorders DOM and browser-local arrays. | Apply Changes calls Python `reorder_text` and `statuses`, then rerenders. Next repeats those commits before validation/advance. No annotation JSON is written here. |
| Status, unknown and suspicious flags | JS canvas/DOM and local collections during direct manipulation; Python `regions`/`bounding_boxes` and token IDs after snapshot boundary | Status and unknown controls mutate local box metadata. Suspicious flag mutates token-ID set and chip classes. Python has both per-region status and aligned public-box copies; `confirm_status()` synchronizes at transition. | Status is committed on Apply Changes and Next. Suspicious tokens are committed with text sequence (or alone if no sequence change). Durable files are written only on Review Save. |
| Step 6 crop | JS local `localBoxes.crop` and SVG/coordinate UI during direct interaction; Python `crop` after crop action or Next | SVG pointer edits and coordinate fields update browser state. Apply crop invokes Python `crop`; Next snapshots the current crop then invokes `crop` before transition. | Crop edits mark `crop_saved=False` but do not write a crop file until Review Save; `save_crop` exists but is not the normal UI Next path. |
| Review and persisted annotations | Python active state builds preview; files under output directory are durable authority after Save | Review snapshot is rendered from state after prior step validations. `save` writes normal annotation or mismatch, suspicious details, metadata hashes, and crop. | Save returns a fresh image-selection state and removes that image from `ctx['drafts']`. Download All archives already persisted files; it does not snapshot current unsaved browser state. |
| Zoom/pan, selection focus, pointer gesture | Browser DOM/JS only | `editor.js` owns transform and pointer state. No Python event for zoom/pan. | A DOM replacement can reset view-local state. This lifecycle must be browser-tested; do not infer persistence across rerender. |

`ctx['drafts']` is populated when switching away from an open image, but `open_image()` intentionally reloads persisted data rather than using that draft. The dictionary is used for within-session bookkeeping/cleanup, not restoration on reopening. Back does not reopen an image; it changes `current_step` in the active Python state.

### Render and identity contracts

`render(ctx)` passes Python values into `snapshot(s)`, which creates SVG and chip markup plus JS props (`revision`, `image`, `step`, `boxes`, selection, validation, alignment IDs, text and suspicious flags). `editor.js` clones the incoming boxes for its local collection. On a same image/step context, it preserves the old `localBoxes` object across a rerender, but rehydrates selection from props and chip sequence/suspicious IDs from the props/DOM path. On context change it initializes from new props. IDs are opaque region UUIDs in Step 3 and public numeric string IDs after alignment. Temporary frontend-added box IDs are `box_new_N`; Python preserves these IDs when committed.

`revision` is incremented for workflow actions and included in event payloads for frontend actions. Stale image/revision payloads are rejected. A render is not a generic reset: some action outputs are skipped, JS preserves local box objects under a same-context rerender, and some handler state (notably active pointer drag) is explicitly cleaned up on rerender. These are behavior contracts, not opportunities to normalize state.

## Stage and navigation contracts

| Stage | State and behavior | Next / Back / return behavior |
|---|---|---|
| 1. Image selection | Python starts with empty `new_state()`. Opening validates selected path, loads source and existing annotation/mismatch/crop/suspicious data, and starts at Step 2. Existing public box IDs are hydrated into new region UUIDs while preserving mapping. | Open always reloads persisted files. Selecting/reopening does not recover unsaved `ctx['drafts']`. |
| 2. Content | Browser bridge owns keystrokes and per-field draft changes until commit. Python `draft_content` changes on save/Next; content verification and annotation text are Python state. | Save Content persists source JSON and content document and verifies content; Next commits bridge then runs `save_content`, and advances to Step 3. Back only changes step to 1. Returning with Back then Next uses the still-active state. Content edits that change normalized text invalidate alignment mappings. |
| 3. Bounding Boxes | `localBoxes` is authoritative during editing. It includes bbox, status/unknown, optional order, and local IDs. DOM is a projection, not a state source, except the snapshot bridge reads order chips for live character order. Pointer operations update JS objects and redraw SVG. Python `regions` is synchronized from a complete replacement snapshot, with missing IDs deleted. | Next commits boxes and optional live coordinate values, can record mismatch from supplied controls, then validates count/alignment and advances to Step 4 or Step 7 for `other`. Run Detection is a Python call replacing all regions; on entry from Step 2 it may run automatically. Back to Step 2 retains active workflow state; returning Next reuses existing boxes. |
| 4. Reading Order / Character Alignment | Box status, unknown, suspicious token set, token identity and chip sequence are local while editing. DOM chip order is read only after expected alignment token IDs appear. Python `annotations` are keyed by spatial Box ID; text token IDs preserve identity when repeated characters are dragged. | Apply Changes commits current text/token order and statuses to Python and rerenders on Step 4. Next does the same commits, validates reading order/status, then advances to Step 6. Back to Step 3 retains the active Python alignment/regions, while frontend rehydrates from props; changing boxes can invalidate and clear alignment. |
| 5. Status (legacy workflow state) | `Workflow.apply` supports Step 5 status handling and Next validation, though current `render()` exposes the sidebar status group and canvas status behavior on Step 4 and navigation from Step 4 goes directly to Step 6. | This is not reached through the current normal Next route. Treat any extraction of Step 5 code as unsafe until the discrepancy between legacy workflow support and rendered UI is separately characterized. |
| 6. Crop | Browser canvas handles crop drag/resize and zoom/pan; coordinate input can override the snapshot. Python validates crop bounds and stores crop in active state. | Apply crop calls Python `crop` but does not persist. Next commits sidebar coordinates if present, else frontend crop snapshot, then advances to Step 7. Back returns to Step 4. |
| 7. Review | Python renders final result and JSON previews, including persisted collection previews plus the current in-memory document. Other-mismatch review intentionally has no character mapping. | Save Annotation is the durable write point, then resets active state to Step 1. Back for `other` mismatch returns to Step 3; otherwise normal Back decrements to Step 6. |

## Major interaction traces

### Bounding Box editing, selection, add/delete, move/resize

`pointerdown`/`pointermove`/`pointerup` in `editor.js` mutate `localBoxes` and `selectedIds` directly. Click selects one; modifier click toggles membership; marquee drag selects multiple; Alt/Option drag creates a temporary-ID region; drag moves selected boxes; handles resize a single selection. Step 3 coordinate inputs mutate the active local box and redraw. DOM SVG geometry is regenerated from local objects. No Python call occurs for these gestures. Add/Delete buttons update the frontend immediately; delete also has a Python callback that commits current full snapshot before applying deletion. Next and mismatch confirmation serialize the entire authoritative local collection to avoid resurrecting deleted/stale backend regions.

Invariants: preserve ID strings and insertion/order behavior; preserve complete replacement semantics; never rebuild local boxes from stale `regions` during a same-context rerender; keep status/unknown/order metadata attached to each box; maintain selection separately from box identity; and retain the exact local snapshot bridge precedence over stale Gradio textbox input.

### Zoom and pan

Toolbar buttons and pointer/wheel handlers mutate `imageTransform` and SVG/viewport styles in JS. They do not call Gradio or persist. Viewport measurement and resize setup depend on rendered DOM dimensions. Browser regression is required for fit sizing, min/max zoom, panning bounds, rerender and image changes.

### Run Detection

Explicit Run Detection asks browser `window.confirm` if Python currently has regions. On acceptance it calls Python `Workflow.apply('detect')`; detector output IDs are discarded and new UUIDs are created, then alignment state is invalidated and a full render follows. On Step 2 Next to Step 3, `next_with_progress` yields a pending result and then runs detection if no detection was previously loaded and detection is enabled. Detection failure leaves the workflow on Step 3 with an error message. `--skip-detection` disables the button and automatic call. It is unsafe to extract detection trigger logic separately from Next sequencing without preserving the generator/yield behavior and concurrency limit.

### Apply Changes

The Step 4 button runs `apply_reading_order`: parse frontend snapshot, call `reorder_text` when sequence is available (or commit suspicious IDs alone), commit statuses, then render Python state. It does not call file persistence. Reorder preserves token IDs for duplicate characters and recomputes box-to-character assignments; statuses are synchronized from region state into aligned bounding boxes.

### Next

Next is a multi-boundary commit. A JS preprocessor captures the current live board into `selection_bridge`, preferring `board.dataset.localBoxesSnapshot` over the potentially stale textbox value and reading chip order/token/suspicious markers from DOM. Python then commits content on Step 2; complete boxes plus coordinates on Step 3; mismatch details when needed; status plus character sequence/token identity on Step 4; or crop coordinates on Step 6. `Workflow.apply('next')` validates and changes `current_step`, then `render()` refreshes relevant components. Automatic detection runs only after this first yielded transition result. Ordering of commits and Gradio concurrency (`annotation-actions`, limit 1) are behaviorally significant.

### Status, unknown, suspicious and manual reading order

Status/unknown controls are browser-local during Step 4 interaction; the bridge serializes every box. Python conversion maps public Box IDs back to region UUIDs. Unknown is allowed only with damaged status, and missing-character boxes cannot be unknown. Suspicious applies to token identity, not character value or box ID, and is disabled for excluded/missing chips. Manual order input only writes `localBoxes[activeBoxId].order`; duplicate orders are rejected/cleared in the browser. Sort Boxes sends current frontend geometry to a Python spatial-order calculator, returns calculated IDs via a transient board snapshot, and JS assigns order values locally. Clear Order changes local order values after confirmation. Python alignment is materialized only when the full order is exactly 1..N in `sync_draft_boxes` or on Sort Boxes; final Next requires valid mapping and coordinate-slot order.

### Character alignment and drag/drop

Initial chips are server-rendered with distinct token IDs, including repeated identical characters. Browser waits for the expected token IDs to be present via a `MutationObserver`; pointer handlers are enabled only after alignment readiness. Pointer capture and document-level capture-phase listeners are scoped to one pointer ID. Drag cleanup also runs on cancellation, lost capture, and rerender. Successful drop updates DOM sequence and token order, then updates local arrays/snapshot. Preserve listener registration/removal timing, chip object identity during gesture, MutationObserver behavior, and animation cleanup.

### Restoration and navigation

`Workflow.open_image()` reloads normal/mismatch annotation, crop, metadata hash sidecar, and suspicious detail files. Existing annotations may be exactly restored after content save only when metadata fingerprints match; source mismatch variants have special hydration behavior. New internal region UUIDs map to preserved public Box IDs. Return via Back operates on active session state; it does not reload files. Reset All restores the server-start byte snapshot transactionally, then reopens the image. Save Annotation writes durable files and returns to selection; Download All archives durable output only.

## State invariants to preserve

1. Browser `localBoxes` is the live authority during direct box interaction. Snapshot commit uses replacement semantics so removed frontend boxes stay removed.
2. Box UUID/temp ID/public Box ID mapping is stage-specific and must not be regenerated casually. Public ID mapping is tied to spatial alignment; token IDs are separately preserved across duplicate-character chip reorder.
3. Local selection is interaction state; re-render selection rules differ by context. Multi-selection and active box must not be collapsed without characterization.
4. Local snapshot stored on `.workbench-board.dataset.localBoxesSnapshot` wins over bridge input because Gradio may lag a browser event.
5. Box status, unknown flag, order and geometry travel together through box snapshots. Damaged/unknown and MISS constraints are enforced at different layers.
6. `textSequence`, `tokenOrder`, and `suspiciousTokenIds` are separate dimensions. Character equality alone cannot reconstruct token identity.
7. Source mismatch confirmation is bound to exact text and box counts; box count changes invalidate confirmation. `other` has a distinct Step 7 path and no annotation mapping.
8. Python `regions` (editable UUID keyed records), `bounding_boxes` (public ID keyed records), `annotations`, and frontend `localBoxes` are related but not interchangeable sources. Workflow explicitly synchronizes between them at boundaries.
9. Step 4 Apply is in-memory workflow commit; Step 7 Save is durable annotation persistence. Crop persistence is also deferred until Review Save in the current UI path.
10. Same-image/same-step render can preserve the existing local box collection; image/step context changes initialize from props. DOM-specific observers, pointer capture and animation state require explicit cleanup behavior.
11. `revision` and image identity protect event payloads from stale actions; action ordering/concurrency must remain stable.
12. Opening an image reads durable state, while Back retains active state. `ctx['drafts']` currently does not change this distinction.

## Known complexity to preserve and track separately

- Step 5 workflow/status actions remain in `Workflow` despite the normal UI path moving from Step 4 to Step 6. Do not remove or relocate until callers and persisted compatibility are understood.
- Status exists in editable `regions` and aligned `bounding_boxes`; synchronization occurs in explicit functions and at transitions. This duplication is intentional in current workflow behavior.
- `editor.js` contains browser state, bridge serialization, direct DOM rendering, and lifecycle listeners in one file. Extraction boundaries should follow complete lifecycle units rather than apparent helper similarity.
- `snapshot()` returns and mutates `calc_sorted_box_ids` by popping it from the state argument; its caller currently passes snapshots/transient state in relevant paths. Characterize object identity and call-site ownership before extracting this behavior.
- Existing `test_ui.py` has source-string assertions for intricate behavior. They help detect accidental deletion but do not prove browser event order or synchronization. Do not silently replace/remove them during extraction.
- `ctx['drafts']` stores prior active image states but opening explicitly reloads durable state. This may look redundant; preserve unless a separately approved behavior change says otherwise.

## Incremental migration plan

No extraction should start until its characterization check is in place. Each step must be independently runnable and reversible.

| Step | Smallest candidate unit and proposed ownership | State read / mutated | Events and Python ↔ JS boundary | Persistence and expected behavior | Checks and rollback boundary |
|---|---|---|---|---|---|
| 0. Baseline characterization (required first) | Add Python workflow tests for exact state transitions/persistence and a manual browser checklist; no code movement. | All state described above. | Exercise existing handlers unchanged. | Record outputs and files for each key action. | Existing unit suite plus new targeted tests; save baseline fixtures/results. No rollback needed. |
| 1. Pure rendering helpers | Move a self-contained markup helper from `ui/editor.py` only after inspecting references; keep `snapshot()` in place initially. Old owner: `ui/editor.py`; new owner: a rendering helper module. | Reads Python snapshot only; must not mutate it or change returned markup/props. | No events or Python/JS synchronization changes. | No persistence impact; exact same markup/props. | Snapshot golden/structural tests for each step and duplicate token IDs. Roll back only helper/import change. |
| 2. Python input decoding/validation helpers | Move pure `frontend_*` parsers from `app.py` only if signatures and raised Gradio errors stay identical. Old owner: `create_app` closures; new owner: a small adapter module. | Reads bridge strings; no workflow state mutation. | Called by existing callbacks; boundary unchanged. | None. | Parser tests for malformed/absent fields, ID shapes, snapshot precedence handled outside this step. Roll back adapter import. |
| 3. Step 2 content bridge | Extract JS-only content field bridge after browser characterization. Old owner: inline `app.py` JS strings; new owner: asset/module still invoked from same Gradio event. | Reads/writes browser content draft bridge and field display; Python mutation remains Save Content/Next. | `field.change` and `apply_field`; no new backend call. | Save timing unchanged. | Manual content edit, section switch, Apply Field, Save Content, Next, validation failure, Back. Rollback JS reference only. |
| 4. Step 3 box gesture lifecycle | Extract one coherent group (selection/marquee OR move/resize, not both) while keeping `localBoxes`, IDs, bridge function and event targets in same runtime scope. Old owner: `editor.js`; new owner: imported/module factory only if it preserves one shared object identity. | `localBoxes`, `selectedIds`, `activeBoxId`, SVG geometry. | Pointer listeners remain browser-only; Next and mismatch snapshot boundary unchanged. | None until explicit commit. | Manual pointer/multi-select/coordinates/rerender; compare serialized bridge before/after. Roll back that handler group. |
| 5. Step 3 add/delete/detection/sort | Migrate individually after Step 4. Old owner: JS handlers plus existing Python callback; new owner: feature module only, same bridge and Gradio callbacks. | Complete box collection, order, selection; detection mutates Python regions; sorting result returns to JS. | Preserve custom `board.action`, button event, generator timing, confirmation modal and concurrency. | Detection replaces in-memory boxes; no file write. | Manual add/delete stale-backend protection, Run Detection confirm/cancel/auto/failure, sort all/selected. Rollback each action independently. |
| 6. Step 4 alignment/status controls | Extract chip drag lifecycle separately from status/suspicious behavior. Old owner: `editor.js`; new owner: separate runtime module with shared local state references. | DOM chip identity/order, `localTextSequence`, `localTokenOrder`, suspicious set, local box status. | Apply/Next bridge and Python commits unchanged. | Apply remains memory-only; Save remains Step 7. | Manual repeated characters, excluded/MISS tokens, pointer cancel/lost capture/rerender, status/unknown/suspicious and Apply/Next parity. Rollback per feature. |
| 7. Step 6 crop/pan/zoom | Extract crop gesture separately from generic viewport transform. Old owner: `editor.js`; new owner: canvas interaction module. | `localBoxes.crop`, image transform, SVG/viewport dimensions. | Apply Crop and Next continue current Python callbacks. | Crop persistence stays Review Save. | Manual crop bounds, coordinate override, Back/Next, resize/zoom/pan; compare bridge and persisted output. Rollback per gesture family. |
| 8. Python workflow action modules | Only after all UI boundaries are characterized, move pure action families from `Workflow.apply`; preserve exact input/output state shapes and copy behavior. Old owner: `workflow.py`; new owner: action module called synchronously by `Workflow`. | Python state branches and object identity/copy semantics. | Gradio callback/event graph unchanged. | Same writes and timing. | Workflow tests including `is`/copy expectations where relevant, exact files/hashes, all stage transitions. Roll back one action family at a time. |

For every step, compare the full bridge JSON, active Python state fields, rendered props/DOM, persisted output files, and visible workflow result for the same interaction sequence. If any source of truth, timing, identity, or event lifecycle is uncertain, mark that candidate unsafe and do not proceed until the contract is characterized.

## Manual regression checklist before/after stateful extraction

Use one image with normal matching counts, one with missing text, one with extra text, one `other` mismatch, and one restored annotation with repeated characters.

1. Open image with saved normal and mismatch annotation; compare IDs, geometry, status, text, crop and suspicious flags.
2. Step 2 edit multiple sections, switch sections, Save change, Save Content, Next, Back, and return; verify source/content files and unsaved bridge behavior.
3. Step 3 select, toggle multi-select, marquee, add, delete, move, resize, coordinate edit, zoom/pan; trigger a harmless rerender and verify no deleted boxes return, IDs/order/selection follow current contract, and no duplicate listeners appear.
4. Confirm mismatch, change count to invalidate, clear mismatch, confirm again; verify exact source/count binding and manual order availability.
5. Run Detection cancel/confirm, automatic-on-entry, disabled detection and failure; compare boxes and validation state.
6. Sort all and selected boxes, manually assign/clear order, create duplicates/missing numbers; verify sort order, modal range and validation timing.
7. Step 4 drag repeated identical characters, cancel/lost pointer capture, reorder suspicious token, change status/unknown, Apply Changes, Next, Back to Step 3 and return; compare token IDs, annotations, status and bridge snapshot.
8. Step 6 resize crop, enter coordinates, Apply crop, zoom/pan, Back/Next; ensure persisted crop changes only when Review Save occurs.
9. Review normal/mismatch output, Save Annotation, reopen, Reset All, Download All; compare exact durable JSON and archive contents.

