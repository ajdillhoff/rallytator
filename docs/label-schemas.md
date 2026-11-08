# Label Schemas

Concrete geometry for each **Track** type's **Detections**. The *why* behind these
choices is in [ADR-0004](adr/0004-label-schemas.md); the vocabulary is in
[`../CONTEXT.md`](../CONTEXT.md).

Every keypoint (and the bbox) carries a **Status** value: `VISIBLE` / `OCCLUDED` /
`IGNORE` / `OUT_OF_FRAME` (ADR-0007). `IGNORE` = in-frame, occluded, and not confidently
locatable → excluded from training loss.

---

## Court — 20 keypoints

17 on the ground plane (line intersections) + 3 net points off the plane at known
heights. The off-plane points make calibration **full 3D**, not just a planar homography
(see [ADR-0004](adr/0004-label-schemas.md)).

### Ground plane (17)

Canonical definition is `CourtKeypoint` in `rallylens/core/geometry.py`. World frame:
origin at net-line center, +x right doubles sideline, +y far baseline, +z up. Units: metres.

| id | name | x (m) | y (m) |
|----|------|-------|-------|
| 0 | far_left_doubles | −5.485 | +11.885 |
| 1 | far_left_singles | −4.115 | +11.885 |
| 2 | far_right_singles | +4.115 | +11.885 |
| 3 | far_right_doubles | +5.485 | +11.885 |
| 4 | far_left_service | −4.115 | +6.400 |
| 5 | far_service_t | 0.000 | +6.400 |
| 6 | far_right_service | +4.115 | +6.400 |
| 7 | net_left_post | −5.485 | 0.000 |
| 8 | net_right_post | +5.485 | 0.000 |
| 9 | near_left_service | −4.115 | −6.400 |
| 10 | near_service_t | 0.000 | −6.400 |
| 11 | near_right_service | +4.115 | −6.400 |
| 12 | near_left_doubles | −5.485 | −11.885 |
| 13 | near_left_singles | −4.115 | −11.885 |
| 14 | near_right_singles | +4.115 | −11.885 |
| 15 | near_right_doubles | +5.485 | −11.885 |
| 16 | net_center_base | 0.000 | 0.000 |

IDs 7/8 are the **ground-level bases** of the net posts (z=0). IDs 0–6 and 9–15 are
the standard 14 line intersections. ID 16 is the center-strap base, needed for the P
(full projection) solve together with net-top ID 19.

### Net (3) — off ground plane, known heights

Canonical definition is `NetTop` in `rallylens/core/geometry.py`.

| id | name | x (m) | z (m) |
|----|------|-------|-------|
| 17 | net_left_post_top | −5.485 | +1.070 |
| 18 | net_right_post_top | +5.485 | +1.070 |
| 19 | net_center_strap_top | 0.000 | +0.914 |

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
