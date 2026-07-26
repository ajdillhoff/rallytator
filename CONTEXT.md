# RallyTator — Context

Glossary of the ubiquitous language for RallyTator. Terms only — no implementation
detail, no spec. When code or docs name a concept below, use *this* word for it.

Architectural decisions live in [`docs/adr/`](docs/adr/).

---

## Annotation

A human- or model-produced label attached to the content of a **Video**. Concretely,
almost every Annotation is a **Detection** (per-Frame geometry) belonging to a **Track**.
Every Annotation carries an **Annotator** — nullable today, but always present so
provenance survives a future multi-annotator world.

## Annotator

The agent that produced an Annotation — a person or a **Model**. Single-user today, so
the field is usually implicit, but it is a first-class concept.

## Video

The primary unit of source material. Annotation is **frame-accurate**: a Video is
addressed by integer **Frame** index, never by wall-clock time (timestamps drift).

## Frame

A single decoded image at an integer index within a Video — the atomic temporal unit of
annotation. Frame delivery is server-authoritative (see
[ADR-0002](docs/adr/0002-server-side-frame-delivery.md)); the browser never guesses which
Frame it has.

## Track

A **persistent subject identity within a single Video** — the identity spine. "Player A"
in Frame 10 and Frame 500 are the same Track. A Track owns an ordered set of
**Detections**, one per annotated Frame. Track types:

- **Player** — a person on court (Pose). As many Player Tracks as there are players
  (2 singles, 4 doubles); the tool does not hardcode a count.
- **Racquet** — a racquet (Pose). **Standalone**: *not* linked to a Player. Whose racquet
  it is, if needed, is resolved downstream (e.g. spatial proximity). See
  [ADR-0003](docs/adr/0003-domain-model.md).
- **Ball** — a ball (Point). Multiple Ball Tracks may coexist (ball machine, adjacent
  court). Labeled **only while Ballistic** (see below); no primary/rally distinction is
  made in-tool.
- **Court** — the court (Pose / keypoints). Modeled **static-hold**: annotated once, its
  Detection holds across all Frames until re-annotated (camera is fixed but can drift
  from wind/vibration). Court keypoints must be rich enough for downstream homography
  calibration.

## Detection

The geometry of one Track on one Frame — a keypoint skeleton (Pose), a 2D point (Point),
and/or a **mask**, whatever the Track's Task requires. A Player Detection carries *both*
COCO-17 keypoints and a SAM3 mask. A Detection belongs to exactly one Track and one Frame.
Exact per-type point sets live in [`docs/label-schemas.md`](docs/label-schemas.md).

## Ballistic

The state of a **Ball** that is *in flight* — the only state in which a Ball is labeled.
A ball stops being Ballistic (and labeling ends) once it is rolling, stopped, has left
the Frame, or has **bounced twice without being hit again**. The labeled extent of a Ball
Track is therefore its **flight** span(s). Downstream ball tracking (a custom TrackNetV4)
favors the actively-moving ball, which this policy directly serves.

## Flight

The **labeled extent of a Ball Track while Ballistic** — one contiguous in-flight arc. A
Flight ends when the ball becomes non-ballistic (rolls, stops, leaves the Frame, or
bounces twice without being hit). A Ball Track may contain several Flights (hit → land →
hit again); a Flight is the natural unit for the downstream (TrackNetV4) ball export. See
[`docs/data-model.md`](docs/data-model.md).

## Visibility

The observability of a Detection's subject on a Frame: **visible** (has geometry),
**occluded** (briefly hidden but still present — e.g. a Ballistic ball behind a player;
position optional/estimated), or **out-of-frame**. Distinguishes genuine absence from
"not yet annotated" (which is the *absence of a Detection*).

## Task

A category of annotation work. RallyTator's **primary** Tasks produce the *substrate*:

- **Pose** — keypoint skeletons for Player, Racquet, Court.
- **Point** — a single 2D location, used for the Ball.

**Action is not a primary Task** — see below.

## Action

A stroke label (Forehand/Backhand Swing, Forehand/Backhand Volley, Serve, Lob) on a
**Player** Track. Actions are **derived**, not hand-annotated from scratch: a downstream
pipeline infers them from Pose + Court + Ball. RallyTator's role is a **review/correct**
layer — surface inferred Actions so a human can verify and fix them, producing train/eval
ground-truth. When an Action is recorded its shape is a Frame **span** (start, end) with a
distinguished **contact** Frame (racquet–ball impact). See
[ADR-0003](docs/adr/0003-domain-model.md).

## Model

An open-source assist Model that produces or propagates Detections — currently YOLO
(detection), SAM3 (segmentation masks), CoTracker (point tracking). Models are the
automated half of RallyTator's *semi-automated* workflow.

## Propagation

Extending a Track's geometry across Frames by running a Model (content-aware) between
**Anchors**. The primary gap-fill; linear interpolation is an explicit cheaper option for
near-static spans. Propagation is **on-demand** (region-by-region, no batch pass) and
never overwrites an Anchor. See [ADR-0006](docs/adr/0006-automation-workflow.md).

## Anchor

A human-edited (`edited=1`) Detection. It is **locked** — Propagation treats it as a fixed
endpoint and never overwrites it — so re-propagation only ever improves a Track. Editing a
Detection snapshots the Model's original geometry (`model_geom`) for later measurement.

## Job

A unit of Model work (e.g. a CoTracker propagation across a Frame span) run on the warm
**Worker** and reported back with progress. Long-running and GPU-bound.

## Worker

The single persistent subprocess that holds Models warm on the GPU and executes Jobs from
a queue. Serializes GPU access; isolates Model crashes from the API. See
[ADR-0001](docs/adr/0001-server-browser-topology.md).

---

*This file is a glossary and nothing else. Add a term the moment it is resolved; keep
implementation choices in ADRs.*
