# Label Schemas

Concrete geometry for each **Track** type's **Detections**. The *why* behind these
choices is in [ADR-0004](adr/0004-label-schemas.md); the vocabulary is in
[`../CONTEXT.md`](../CONTEXT.md).

Every keypoint carries a **Visibility** value: `visible` / `occluded` / `out-of-frame`.

---

## Court — 20 keypoints

17 on the ground plane (line intersections) + 3 net points off the plane at known
heights. The off-plane points make calibration **full 3D**, not just a planar homography
(see [ADR-0004](adr/0004-label-schemas.md)).

### Ground plane (17)

> **TODO: import the exact 17-point definition from the existing setup.** Do not invent
> these — they must match the annotator's established convention and the downstream
> calibration's expected ordering/ids. The standard tennis-CV 14-point set (4 doubles
> corners, 4 singles corners, 4 service-line×singles-sideline, 2 T's) is a *subset*; the
> remaining 3 (likely baseline center marks and/or net-line×sideline points) come from
> the existing setup.

### Net (3) — off ground plane, known heights

| id | point | height |
|----|-------|--------|
| net_post_left  | left net-post top | standard post height |
| net_post_right | right net-post top | standard post height |
| net_center_top | top of net at center strap | standard center-net height |

Known heights + ground points → solve camera pose/height → metric ball height, true net
clearance, 3D-accurate metrics.

---

## Player — COCO-17 keypoints + SAM3 mask

A Player Detection carries **both** geometries.

### Keypoints (COCO-17)

`nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder,
left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee,
right_knee, left_ankle, right_ankle`

- Chosen for stock **YOLO-pose** auto-init and because pose feeds downstream Action
  inference. Feet keypoints deliberately excluded — sub-pixel unreliable at broadcast
  distance (see [ADR-0004](adr/0004-label-schemas.md)).

### Mask (SAM3)

- Standard on **every** Player Detection; cheap via SAM3 human segmentation.
- Primary source of **ground-contact** (mask lowest-point → court plane) — the reliable
  substitute for unplaceable far-player feet.
- Encoding: **TODO** (RLE vs polygon) — pending the storage-format branch.

---

## Racquet — 5 keypoints

`butt` (grip end), `throat` (handle–head junction), `tip` (top of hoop),
`head_left`, `head_right` (hoop widest points).

- `butt → tip` gives the long axis / swing arc; `head_left/right` give racquet-face
  orientation (contact normal).
- Side points are the most distance/blur-sensitive — mark `occluded`/`out-of-frame` via
  Visibility rather than guessing.
- Racquet is an **auxiliary** Track (not a driver of the primary Action inference, which
  uses pose + court + ball).

---

## Ball — 1 point

A single 2D point. Present only while the ball is **Ballistic** (in flight). Carries
Visibility (`visible` / `occluded` / `out-of-frame`) so brief mid-flight occlusions stay
on the trajectory. See [`../CONTEXT.md`](../CONTEXT.md).
