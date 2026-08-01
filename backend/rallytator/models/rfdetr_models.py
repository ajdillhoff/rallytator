"""RFDETR wrappers: detect (RFDETRLarge), segment (RFDETRSegLarge), pose
(RFDETRKeypointPreview).

Lazy `rfdetr` / `supervision` imports (installed via the optional `models` dependency
group). The concrete `.predict(...)` attribute names follow the current Roboflow RFDETR /
supervision API; if the installed versions differ, adjust *here* only — the Protocols in
base.py are the stable contract. `COCO_PERSON` is the class id RFDETR emits for a person.
"""

from __future__ import annotations

import numpy as np

from .base import Bbox, Keypoint

COCO_PERSON = 0
CONF_KPT = 0.3  # keypoint-confidence threshold below which a joint is marked out-of-frame


def _xyxy_to_xywh(b: np.ndarray) -> Bbox:
    x1, y1, x2, y2 = (float(v) for v in b)
    return (x1, y1, x2 - x1, y2 - y1)


def _iou(a: np.ndarray, box: Bbox) -> float:
    bx, by, bw, bh = box
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = bx, by, bx + bw, by + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + bw * bh - inter
    return inter / ua if ua > 0 else 0.0


def _pick(xyxy: np.ndarray, conf: np.ndarray, prompt: Bbox | None) -> int:
    """Pick the prompt-overlapping box (if a prompt is given) else the most confident."""
    if len(xyxy) == 0:
        raise RuntimeError("model returned no detections")
    if prompt is not None:
        return int(np.argmax([_iou(b, prompt) for b in xyxy]))
    return int(np.argmax(conf))


class RFDETRDetector:
    def __init__(self) -> None:
        from rfdetr import RFDETRLarge
        self.model = RFDETRLarge()

    def detect(self, image: np.ndarray, prompt: Bbox | None) -> tuple[Bbox, float]:
        d = self.model.predict(image, threshold=0.4)
        person = d[d.class_id == COCO_PERSON] if d.class_id is not None else d
        i = _pick(person.xyxy, person.confidence, prompt)
        return _xyxy_to_xywh(person.xyxy[i]), float(person.confidence[i])


class RFDETRSegmenter:
    def __init__(self) -> None:
        from rfdetr import RFDETRSegLarge
        self.model = RFDETRSegLarge()

    def segment(self, image: np.ndarray, box: Bbox) -> np.ndarray:
        d = self.model.predict(image, threshold=0.4)
        person = d[d.class_id == COCO_PERSON] if d.class_id is not None else d
        i = _pick(person.xyxy, person.confidence, box)
        if person.mask is None:
            raise RuntimeError("RFDETRSegLarge returned no masks")
        return np.asarray(person.mask[i], dtype=bool)


class RFDETRPose:
    def __init__(self) -> None:
        from rfdetr import RFDETRKeypointPreview
        self.model = RFDETRKeypointPreview()

    def keypoints(self, image: np.ndarray, box: Bbox | None) -> tuple[list[Keypoint], Bbox]:
        d = self.model.predict(image, threshold=0.4)
        i = _pick(d.xyxy, d.confidence, box)
        kp = d.keypoints  # supervision KeyPoints: .xy [N,K,2], .confidence [N,K]
        xy = np.asarray(kp.xy[i])
        kc = np.asarray(kp.confidence[i]) if kp.confidence is not None else np.ones(len(xy))
        kpts: list[Keypoint] = [
            [float(x), float(y), "visible" if c >= CONF_KPT else "out-of-frame"]
            for (x, y), c in zip(xy, kc)
        ]
        return kpts, _xyxy_to_xywh(d.xyxy[i])
