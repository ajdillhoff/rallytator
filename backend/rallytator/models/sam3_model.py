"""SAM3 wrappers: box-prompted image segmentation + box-prompted video tracking.

Prefers a `sam3` install; falls back to `sam2` (same box-prompt image predictor +
`build_sam2_video_predictor` propagation) behind the identical interface, so downstream
code (worker/API) is backend-agnostic. Weights + torch come from the optional `models`
dependency group; imports are lazy so the base install and CPU tests stay clean.

`_load_backend()` returns a small adapter exposing `image_predictor()` and
`video_predictor()`. Concrete call signatures follow the current SAM2 API; if a real
`sam3` package ships a different surface, adapt it *here* only.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

import numpy as np

from .base import Bbox

# Weights checkpoint + config are environment-overridable so a user can point at whatever
# they downloaded without code changes.
SAM_CKPT = os.environ.get("RALLYTATOR_SAM_CKPT", "")
SAM_CFG = os.environ.get("RALLYTATOR_SAM_CFG", "")


def _xywh_to_xyxy(b: Bbox) -> np.ndarray:
    x, y, w, h = b
    return np.array([x, y, x + w, y + h], dtype=np.float32)


def _load_backend():
    """Return (kind, module-ish) for the best available SAM backend."""
    try:
        import sam3  # type: ignore  # noqa: F401
        return "sam3"
    except ImportError:
        try:
            import sam2  # type: ignore  # noqa: F401
            return "sam2"
        except ImportError as e:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "no SAM backend installed — `uv sync --group models` and set "
                "RALLYTATOR_SAM_CKPT / RALLYTATOR_SAM_CFG"
            ) from e


class SAMSegmenter:
    """Box-prompted single-image segmentation."""

    def __init__(self) -> None:
        self.kind = _load_backend()
        self._predictor = self._build_image_predictor()

    def _build_image_predictor(self):
        if self.kind == "sam3":  # pragma: no cover - env-dependent
            from sam3 import SAM3ImagePredictor  # type: ignore
            return SAM3ImagePredictor.from_pretrained(SAM_CKPT or "facebook/sam3")
        from sam2.build_sam import build_sam2  # type: ignore
        from sam2.sam2_image_predictor import SAM2ImagePredictor  # type: ignore
        return SAM2ImagePredictor(build_sam2(SAM_CFG, SAM_CKPT))

    def segment(self, image: np.ndarray, box: Bbox) -> np.ndarray:
        self._predictor.set_image(image)
        masks, scores, _ = self._predictor.predict(
            box=_xywh_to_xyxy(box)[None, :], multimask_output=False)
        m = masks[int(np.argmax(scores))] if masks.ndim == 4 else masks[0]
        return np.asarray(m, dtype=bool)


class SAMTracker:
    """Box-prompted mask propagation across a frame span."""

    def __init__(self) -> None:
        self.kind = _load_backend()
        self._predictor = self._build_video_predictor()

    def _build_video_predictor(self):
        if self.kind == "sam3":  # pragma: no cover - env-dependent
            from sam3 import build_sam3_video_predictor  # type: ignore
            return build_sam3_video_predictor(SAM_CKPT or "facebook/sam3")
        from sam2.build_sam import build_sam2_video_predictor  # type: ignore
        return build_sam2_video_predictor(SAM_CFG, SAM_CKPT)

    def track(
        self,
        frames: Iterable[tuple[int, np.ndarray]],
        box: Bbox,
        progress: Callable[[float, str], None],
    ) -> Iterable[tuple[int, np.ndarray]]:  # pragma: no cover - GPU path
        frames = list(frames)
        images = np.stack([f for _, f in frames])          # [T, H, W, 3]
        idxs = [i for i, _ in frames]
        state = self._predictor.init_state_from_frames(images)
        self._predictor.add_new_points_or_box(
            state, frame_idx=0, obj_id=1, box=_xywh_to_xyxy(box))
        out: list[tuple[int, np.ndarray]] = []
        total = len(frames)
        for rel, _obj_ids, mask_logits in self._predictor.propagate_in_video(state):
            mask = (mask_logits[0] > 0).cpu().numpy().astype(bool).squeeze()
            out.append((idxs[rel], mask))
            progress((rel + 1) / total, f"frame {idxs[rel]}")
        return out
