# ADR-0003: Domain model — identity spine and three surprising choices

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

RallyTator annotates tennis video to feed RallyLens and a custom TrackNetV4 ball
tracker. The README named Tasks (Pose / Point / Actions) but no *ontology* — nothing
about identity across Frames, multiple balls, racquet ownership, or where Actions come
from. This ADR records the domain model, and in particular three decisions a future
reader would otherwise find surprising. The full glossary lives in
[`CONTEXT.md`](../../CONTEXT.md).

## Decision

**Identity spine.** A **Track** is a persistent subject identity within a Video and owns
per-Frame **Detections** (the standard MOT decomposition). Track types: Player, Racquet,
Ball, Court. Player count is not hardcoded (N Player Tracks). Court is **static-hold** —
annotated once, holding across Frames until camera drift forces a new Detection.

Three non-obvious choices, each a real trade-off:

### 1. Racquet is a standalone Track — no link to a Player

A Racquet Track carries no `held_by` reference. "Whose racquet" is resolved downstream by
spatial proximity if needed.

- *Why:* keeps the tool out of relationship-maintenance; racquets track independently.
- *Cost:* when two racquets cross near the net, nothing in-tool disambiguates ownership —
  downstream must infer it. Accepted.

### 2. Balls are labeled only while Ballistic; multiple balls, no primary

A ball is labeled only *in flight* (**Ballistic**); labeling ends once it rolls, stops,
leaves Frame, or bounces twice without being hit. Multiple Ball Tracks may coexist (ball
machine, adjacent court) and **none is marked primary** — every ballistic ball is labeled
equally.

- *Why:* matches the annotator's ballistic-only strategy and TrackNetV4's preference for
  the actively-moving ball; a uniform "label every ballistic ball" rule removes an
  error-prone "which is the rally ball?" judgment at annotation time.
- *Cost:* downstream must select the rally ball among several Tracks. Accepted.

### 3. Actions are derived, not a primary Task

Actions (strokes) are **inferred downstream** from Pose + Court + Ball. RallyTator does
not annotate them from scratch; it provides a **review/correct** layer over inferred
results to build train/eval ground-truth. Recorded Actions attach to a Player Track and
carry a Frame span plus a distinguished **contact** Frame.

- *Why:* the pipeline extracts primitives first, then infers events; hand-labeling every
  stroke would duplicate that inference.
- *Cost:* the README's original "Actions" Task was demoted (README updated accordingly).
  Accepted. *(Contradicted the README as written; reconciled here.)*

## Alternatives considered

- **Racquet linked to Player** (`held_by`): preserves ownership in-tool but conflates two
  rigid bodies and adds a relationship to maintain. Rejected.
- **Single Ball Track / primary-ball flag**: cleaner single target for TrackNetV4 but
  forces a rally-ball judgment mid-machine-feed and discards stray-ball data. Rejected.
- **Actions as a full manual Task** (per original README): most complete labels but
  duplicates downstream inference and is the heaviest effort. Rejected.

## Consequences

- Propagation and analytics have a stable identity spine (Track → Detections).
- Annotation effort concentrates on the substrate (Pose, Ball); Actions are cheap review.
- Downstream (RallyLens, TrackNetV4) inherits two responsibilities by design: racquet
  ownership and rally-ball selection.
- **Open, deferred:** exact label schemas — Player/Racquet/Court keypoint sets — with the
  Court landmark set gated by downstream homography calibration needs.
