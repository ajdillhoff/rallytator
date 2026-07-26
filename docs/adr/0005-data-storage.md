# ADR-0005: Data storage — JSON-geometry rows, RLE-in-DB, model snapshots, single-JSON export

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

[ADR-0001](0001-server-browser-topology.md) fixed **SQLite** as the single-user-local
store. This ADR records how the domain model (Track → Detection, keypoints, masks,
visibility, ballistic flights — see [`../CONTEXT.md`](../CONTEXT.md)) is persisted and
exported. Concrete tables are in [`../data-model.md`](../data-model.md). Coordinates are
stored in **original-frame pixel** space; the Frame index is the addressing unit.

## Decision

**Detection geometry as JSON, not normalized keypoint rows.** Tables Video, Track,
Detection; geometry lives in a `geom` JSON column.

- *Why:* the access pattern is per-Detection editing and per-Track propagation — never
  per-keypoint SQL. Normalizing 17–20 keypoints × Detections × Frames explodes to hundreds
  of thousands of rows per clip for no benefit; `json1` still extracts fields when needed.

**Masks as COCO RLE in a separate `Mask` table, in the DB.**

- *Why:* RLE is a few KB and lossless; keeping it in SQLite preserves the single-file,
  transactional, no-file-sync virtue. A separate 1:1 table keeps the fat blob out of the
  hot Detection row and allows lazy loading per rendered Frame.
- *Rejected:* polygon (lossy on irregular SAM silhouettes; imprecise ground-contact),
  PNG-files-on-disk (thousands of files, DB no longer source of truth).

**Provenance = light fields + a model-original snapshot.** `source`, `edited`,
`model_confidence`, plus `model_geom` — a snapshot of the model's original prediction,
captured when a human corrects a Detection.

- *Why:* the workflow is semi-automated; without the original prediction you can only
  measure correction *rate*, not *magnitude*. The snapshot enables keypoint-error / mask-
  IoU measurement, per-Task model precision, and active-learning target mining — directly
  serving the "nothing is proven without measurement" standard.
- *Rejected:* minimal flags (loses the original geometry), full event-sourcing (audit/undo
  are not worth the schema+query weight for a single-user tool).

**Export = a single custom JSON document per Video.** SQLite stays the source of truth;
the JSON is a derived interchange artifact and is the RallyLens / TrackNetV4 contract.

- *Why (chosen by the owner):* one contract to define; each consumer extracts the parts it
  needs (TrackNet → ball flights, RallyLens → poses + court calibration).
- *Trade-off accepted:* no COCO-tooling reuse and one document shape serves two very
  different consumers, versus the per-consumer-views alternative (COCO + trajectory files +
  calibration export) that was **not** chosen.

## Consequences

- Internal schema is free to evolve behind the export boundary.
- Model-vs-human is measurable per Detection, with error magnitude recoverable from
  `model_geom` — the foundation for a future active-learning loop.
- `flight_index` on Ball Detections groups a Ball Track into Flights, the natural TrackNet
  export unit.
- **Deferred:** exact export field layout, mask `Mask.rle` byte format specifics, and the
  Court 17-ground-point ids (TODO-import) firm up when the export/serializer is built.
