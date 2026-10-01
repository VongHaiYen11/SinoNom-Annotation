# Bounding-box and reading-order state audit

## State flow before the refactor

| Action | Read | Write | Python | Rerender / persist |
|---|---|---|---|---|
| Detection / reopen | workflow `regions` | workflow `regions` then component props | yes | initializes editor |
| Select / multi-select / sweep | `localBoxes` + `selectedIds` | `selectedIds` | no | local render |
| Add | `localBoxes` | `localBoxes` + SVG node | no | local render |
| Delete | `localBoxes` | `localBoxes` + SVG removal | no | local render |
| Move / resize | `localBoxes` | box `bbox` + SVG | no | local render |
| Count validation | `localBoxes` | DOM summary | no | local render |
| Manual order | `localBoxes` | box `order` | no | local render |
| Sort | frontend bbox subset | **also mutated workflow regions and initialized alignment** | yes | full component rerender |
| Apply | `localBoxes` through custom action **and** SVG/sidebar through a second Gradio click callback | workflow regions | **twice** | full rerender |
| Next | hidden bridge, SVG snapshot, and sidebar coordinates | workflow regions | yes | navigates |

The principal competing states were `localBoxes`, SVG geometry, the hidden bridge,
sidebar coordinate values, workflow `regions`, and materialized
`bounding_boxes`. Apply had two handlers. Empty frontend snapshots fell back to
backend regions, which could resurrect every deleted box. Sorting changed backend
state despite being presented as a calculation.

## State flow after the refactor

- Detection and reopen initialize `localBoxes` from component props.
- Selection remains a separate `Set` and only references IDs in `localBoxes`.
- Add, delete, geometry, metadata, manual order, count validation, and rendering
  operate on `localBoxes`.
- The hidden bridge serializes the complete box objects. DOM inspection is only
  a compatibility fallback when the bridge has no snapshot.
- Sort sends current IDs and coordinates to Python's spatial algorithm. The UI
  adapter returns ordered IDs without mutating workflow state.
- Apply has one handler and sends one complete snapshot.
- Next reads the same complete snapshot; sidebar coordinates are not overlaid as
  a second source.
- Python replacement semantics are `regions := frontend snapshot`, including an
  empty snapshot. Missing backend IDs are never merged or restored.
- Incomplete orders are retained as draft metadata. A complete unique `1..N`
  order is required before alignment/navigation can succeed.

Diagnostic logs report action counts and IDs in the browser, plus sort and
commit counts in Python. Count invariants are asserted at frontend hydration and
after local mutations.
