# ADR-0006: Automation workflow — anchor-based, propagation-primary, on-demand

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

RallyTator is *semi-automated*: models (YOLO, SAM3, CoTracker) propose geometry, a human
corrects it. The value — and the "fast, keybind-driven" goal — hinges on how that loop is
structured: how re-propagation treats human work, what fills the gaps, how Ball Flights
are bounded, and how much is auto-populated up front. Terms in
[`../CONTEXT.md`](../CONTEXT.md); provenance fields in
[ADR-0005](0005-data-storage.md).

## Decision

**Human edits are anchors; propagation is protected against them.** An edited (`edited=1`)
Detection is locked. Propagation only writes/overwrites model-sourced, un-edited Frames
and uses anchors as fixed endpoints. Re-propagation is therefore *monotonic* — it can only
improve, never destroy a correction.

- *Rejected:* clobber-all-in-range (destroys corrections, kills trust); prompt-on-conflict
  (modal spam that breaks the keybind flow).

**Model propagation is the primary gap-fill; interpolation is an explicit option.** The
model fills Frames between anchors using pixels (content-aware), because the subjects move
non-linearly (ballistic ball, rotational pose) where geometric interpolation is wrong. A
linear-interpolation fill is offered explicitly for near-static spans to avoid firing the
GPU needlessly.

- *Rejected:* interpolation-primary (wrong under fast motion, needs many anchors);
  model-only (wastes GPU on trivially static spans).

**Ball Flight boundaries are marked manually (in/out).** The annotator sets Flight start
and end Frames by eye, then seeds points and propagates within.

- *Why:* model-proposed boundaries need a ball detector — the very thing (TrackNetV4)
  being trained downstream — so bootstrapping from it is circular; deriving from Actions
  fails too (Actions are downstream-inferred, unavailable at annotation time).
- *Enhancement (deferred):* an auto-stop assist that extends a Flight until the tracker
  loses ballistic motion.

**Initial pass is on-demand only — no batch import pass.** The human seeds each Track and
propagates region-by-region.

- *Why (chosen by the owner):* tightest identity control, minimal wasted compute, and only
  the footage that matters (rallies, not warm-up) gets annotated.
- *Rejected/deferred:* hybrid (batch-draft always-present Players + on-demand rest) and
  batch-everything (identity mess, stray-ball noise, GPU on episodic subjects). A batch
  player-draft could return later as an opt-in accelerator.

## The loop

seed a Track → propagate across a region (warm Worker + WebSocket progress,
[ADR-0001](0001-server-browser-topology.md)) → scrub, drop corrected **anchors** (each
snapshotting the model's original `model_geom`, [ADR-0005](0005-data-storage.md)) →
re-propagate between anchors. Ball: mark Flight in/out, seed points, propagate within.

## Consequences

- The loop is trust-preserving (monotonic re-propagation) and control-first (on-demand),
  at the cost of manual Track seeding on every Video.
- Correction effort concentrates where models are weak; provenance snapshots turn that
  effort into an active-learning corpus.
- **Measurement (required — "nothing is proven without measurement"):** propagation Job
  latency per N Frames, and end-to-end **Frames-annotated-per-hour**. These substantiate
  (or refute) the "fast and user-friendly" claim; without them it is unproven.
