# ADR-0004: Label schemas — 3D court, mask-not-feet, 5-point racquet

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

Each Track type needs a fixed keypoint/geometry schema. Changing a schema later
invalidates existing annotations, so these are hard-to-reverse. Two forces dominate the
choices: **broadcast distance/resolution** (far players and thin racquets are sub-pixel
in places) and **downstream calibration** (a fixed camera whose view is calibrated from
Court keypoints). Concrete point lists live in
[`../label-schemas.md`](../label-schemas.md).

## Decision

**Court — 20 keypoints, 3 off-plane.** 17 ground-plane line intersections plus 3 net
points (left post top, right post top, center-net top). The net points sit off the
ground plane at *standard, known heights*.

- *Why:* off-plane points at known heights upgrade calibration from a planar homography
  to a **full 3D** solve (camera pose + height), enabling metric ball height and true net
  clearance. An over-determined ground set stays robust to occluded intersections.
- *Cost / alternative:* the common 14-point planar set is simpler but yields only a plane
  homography and weaker 3D metrics. Rejected in favour of the existing 20-point setup.

**Player — COCO-17 keypoints + standard SAM3 mask (no feet keypoints).** Every Player
Detection carries both.

- *Why:* foot keypoints (toes/heels) are sub-pixel unreliable on the far player at
  broadcast distance, so a Halpe-26-style foot schema is a false economy. Instead, a SAM3
  human mask — cheap, since SAM3 segments people well — supplies **ground contact** via
  its lowest point projected to the court plane. COCO-17 keeps stock YOLO-pose auto-init
  and feeds Action inference.
- *Cost:* a Player Detection now carries two geometries (keypoints + mask) to store,
  render (WebGL — see [ADR-0001](0001-server-browser-topology.md)), correct, and export.
  Accepted.

**Racquet — 5 keypoints (butt, throat, tip, head-left, head-right).**

- *Why:* butt→tip gives the swing axis; the two head points add racquet-face orientation
  (contact normal) for spin/contact geometry.
- *Cost / alternative:* the 3-point "stick" is more robust at distance/blur but discards
  face orientation. The 5-point set was chosen despite the side points being the most
  distance-sensitive; Visibility flags mark them unreliable rather than fabricating them.
  A SAM3 mask on the thin, motion-blurred racquet was rejected as too noisy.

## Consequences

- Calibration is 3D-capable; Player ground-contact is mask-derived, not foot-keypoint-
  derived; racquet carries orientation at the cost of two fragile side points.
- Masks become a first-class geometry (Player, and any future masked Track), feeding the
  storage-format and rendering work.
- **Open / deferred:** the exact 17 ground-plane Court points must be **imported from the
  existing setup**, not invented (marked TODO in the schema doc). Mask encoding (RLE vs
  polygon) is deferred to the storage-format branch.
