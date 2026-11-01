# ADR-0007: Object taxonomy, status labels, and identity operations

- **Status:** Accepted
- **Date:** 2026-08-02

## Context

Early RallyTator modeled every annotation as a **Track** (persistent identity) → per-Frame
**Detection**, with a 3-value **Visibility** (`visible`/`occluded`/`out-of-frame`) stored
per keypoint only. Three gaps surfaced in use:

1. Not every annotation is a multi-frame identity — some are **single-frame instances**
   (image-dataset work), though tracks dominate this project's video data.
2. Identities need **editing**: a tracker drifts or two subjects cross, so one labeled
   Track is really two (**split**); or SAM3 loses an object and a re-seed makes two Tracks
   that are one (**merge**). The DB primary key can't be the user-facing, editable id.
3. The 3-value Visibility has no **don't-care**: an occluded keypoint whose location the
   annotator cannot confidently place still gets supervised, polluting training.

## Decision

**An Object is a Track with a `kind`.** `kind ∈ {instance, track}`; an *instance* is an
Object whose geometry lives on a single Frame (one Detection). All Track → Detection
machinery — geometry, status, keypoints, masks, model-assist, export — is shared; only UI
affordances and export grouping differ. An image dataset is annotated as 1-Frame "videos".

- *Rejected:* a first-class Instance entity — duplicates the entire Detection/mask/export
  plumbing for a difference that is one boolean.

**Identity = immutable internal id + editable `label`.** The DB primary key never changes
(keeps Detection/Mask foreign keys intact); a `label`, **unique per Video**, is the
user-facing identity and the exported track id. Operations:

- **Split** at the current Frame: the active Track keeps `[…, F-1]`; its Detections from
  `[F, …]` move to a new Track (fresh id, next free label).
- **Merge** into a target Track: the source's Detections are re-parented to the target;
  on `(track, frame)` collisions the target's Detection wins.
- **Rename**: edit the label (uniqueness enforced per Video).

- *Rejected:* a mutable identity key — every rename/split rewrites foreign keys and risks
  collisions/orphans.

**Status replaces Visibility — 4 values, per bbox and per keypoint.** The canonical tokens
are `VISIBLE`, `OCCLUDED`, `IGNORE`, `OUT_OF_FRAME` (exact uppercase — a downstream dataset
contract). Semantics:

- **VISIBLE** — present and confidently located.
- **OCCLUDED** — hidden but a best-guess location is committed and **supervised**.
- **IGNORE** — in-frame and occluded, but the location is **not confidently known** →
  excluded from training/eval loss (the coordinate is a placeholder). The don't-care.
- **OUT_OF_FRAME** — outside the image; no reliable geometry.

Status is set on the **bbox** (object state on that Frame) and on **each keypoint**,
independent per joint, with two object-level overrides: bbox `OUT_OF_FRAME` hides the box
and all markers but keeps a **geometry-less Detection** (records genuine absence vs
not-yet-annotated); bbox `IGNORE` marks the whole Object don't-care. A Ball's single Point
carries an object-level status the same way.

Canvas: `VISIBLE` solid · `OCCLUDED` dimmed · `IGNORE` shown but visually flagged ·
`OUT_OF_FRAME` **hidden**. The quick keybind cycles only `VISIBLE → OCCLUDED → IGNORE`;
`OUT_OF_FRAME` is set deliberately from the status control. This semantic status is a
distinct axis from the editor-only **display show/hide** and **lock** aids, which persist.

- *Rejected:* keeping the 3-value Visibility — no way to exclude an unlocatable joint from
  loss, which is the whole point of annotating occlusion.

## Consequences

- Track gains `kind` + `label`; `geom` gains a bbox status; the per-keypoint third element
  becomes a Status token. Existing `visible/occluded/out-of-frame` map to the uppercase
  tokens. Schema change → recreate the dev DB (single-user local, no migration owed).
- Export emits the **label** as the track id and the Status tokens verbatim; grouping
  distinguishes `instance` from `track`.
- Split/merge are pure Detection re-parenting — no geometry recompute — so they stay cheap
  and reversible.
