"""RFDETR wrappers: detect (RFDETRLarge), segment (RFDETRSegLarge), pose
(RFDETRKeypointPreview).

Verified against rfdetr 1.9 / supervision 0.29 (RTX GPU):
- `model.predict(rgb_ndarray, threshold=...)` returns a supervision `Detections`
  (detect/seg) or `KeyPoints` (pose).
- `Detections`: `.xyxy (N,4)`, `.confidence (N,)`, `.class_id (N,)`, `.mask (N,H,W) bool`.
  Person is class id **1** (rfdetr uses 1-indexed COCO; id 0 is unused / background).
- `KeyPoints`: `.xy (N,17,2)`, `.visible (N,17)`, `.keypoint_confidence (N,17)`,
  `.detection_confidence (N,)` — note there is **no** `.xyxy`, so a pose instance's box is
  derived from its keypoints.
Adjust here only if versions change; base.py Protocols are the stable contract.
"""

from __future__ import annotations

import numpy as np

from .base import Bbox, Keypoint

COCO_PERSON = 1
CONF_KPT = 0.3  # keypoint-confidence below which a joint is marked not-visible


def _xyxy_to_xywh(b: np.ndarray) -> Bbox:
    x1, y1, x2, y2 = (float(v) for v in b)
    return (x1, y1, x2 - x1, y2 - y1)


def _iou(a, box: Bbox) -> float:
    """IoU of an xyxy box `a` against an xywh prompt `box`."""
    bx, by, bw, bh = box
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = bx, by, bx + bw, by + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + bw * bh - inter
    return inter / ua if ua > 0 else 0.0


def _pick(xyxy, score, prompt: Bbox | None) -> int:
    """Index of the prompt-overlapping box (if prompted) else the most confident one."""
    if len(xyxy) == 0:
        raise RuntimeError("model returned no detections")
    if prompt is not None:
        return int(np.argmax([_iou(b, prompt) for b in xyxy]))
    return int(np.argmax(score))


def _persons(d):
    """Filter a Detections to the person class (falls back to all if class_id absent)."""
    if getattr(d, "class_id", None) is not None:
        p = d[d.class_id == COCO_PERSON]
        if len(p.xyxy):
            return p
    return d


class RFDETRDetector:
    def __init__(self) -> None:
        from rfdetr import RFDETRLarge
        self.model = RFDETRLarge()

    def detect(self, image: np.ndarray, prompt: Bbox | None) -> tuple[Bbox, float]:
        d = _persons(self.model.predict(image, threshold=0.4))
        i = _pick(d.xyxy, d.confidence, prompt)
        return _xyxy_to_xywh(d.xyxy[i]), float(d.confidence[i])


class RFDETRSegmenter:
    def __init__(self) -> None:
        from rfdetr import RFDETRSegLarge
        self.model = RFDETRSegLarge()

    def segment(self, image: np.ndarray, box: Bbox | None) -> np.ndarray:
        d = _persons(self.model.predict(image, threshold=0.4))
        if getattr(d, "mask", None) is None:
            raise RuntimeError("RFDETRSegLarge returned no masks")
        i = _pick(d.xyxy, d.confidence, box)
        return np.asarray(d.mask[i], dtype=bool)


class RFDETRPose:
    def __init__(self) -> None:
        from rfdetr import RFDETRKeypointPreview
        self.model = RFDETRKeypointPreview()

    def keypoints(self, image: np.ndarray, box: Bbox | None) -> tuple[list[Keypoint], Bbox]:
        kp = self.model.predict(image, threshold=0.4)   # supervision KeyPoints
        xy = np.asarray(kp.xy)                            # (N, 17, 2)
        if len(xy) == 0:
            raise RuntimeError("pose model returned no detections")
        conf = np.asarray(kp.keypoint_confidence)        # (N, 17)
        vis = np.asarray(kp.visible) if kp.visible is not None else conf >= CONF_KPT
        # KeyPoints has no boxes; derive a per-instance box from visible joints to pick.
        boxes = np.array([_kp_box(xy[n], vis[n]) for n in range(len(xy))])
        det_conf = (np.asarray(kp.detection_confidence)
                    if kp.detection_confidence is not None else conf.mean(axis=1))
        i = _pick(boxes, det_conf, box)
        kpts: list[Keypoint] = [
            [float(x), float(y), "visible" if (v and c >= CONF_KPT) else "out-of-frame"]
            for (x, y), v, c in zip(xy[i], vis[i], conf[i])
        ]
        return kpts, tuple(box) if box is not None else _xyxy_to_xywh_arr(boxes[i])


def _kp_box(xy: np.ndarray, vis: np.ndarray) -> np.ndarray:
    """xyxy tight box around the visible keypoints (all points if none visible)."""
    pts = xy[vis.astype(bool)] if vis.any() else xy
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    return np.array([x1, y1, x2, y2], dtype=float)


def _xyxy_to_xywh_arr(b: np.ndarray) -> Bbox:
    return _xyxy_to_xywh(b)
