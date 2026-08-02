"""Model interfaces + a lazy warm registry (ADR-0001).

The worker (worker.py) owns one Registry and holds concrete models warm on the GPU. Each
concrete model lives behind a narrow Protocol so the backing package (RFDETR; SAM3 with a
SAM2 fallback) can swap without touching the worker or the API. Nothing here imports torch
— concrete builders import lazily so the base install stays light and CPU-only tests can
monkeypatch a fake Registry.

Coordinates are video pixels; a Bbox is (x, y, w, h). Masks are (H, W) boolean arrays.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np

Bbox = tuple[float, float, float, float]
# COCO-17 keypoint as [x, y, visibility-string].
Keypoint = list[object]


class Detector(Protocol):
    def detect(self, image: np.ndarray, prompt: Bbox | None) -> tuple[Bbox, float]: ...


class Segmenter(Protocol):
    def segment(self, image: np.ndarray, box: Bbox) -> np.ndarray: ...


class PoseEstimator(Protocol):
    def keypoints(self, image: np.ndarray, box: Bbox | None) -> tuple[list[Keypoint], Bbox]: ...


class Tracker(Protocol):
    def track(
        self,
        frames: Iterable[tuple[int, np.ndarray]],
        box: Bbox,
        progress: Callable[[float, str], None],
    ) -> Iterable[tuple[int, np.ndarray]]: ...


class Registry:
    """Lazily builds + caches one instance of each concrete model, warm for reuse."""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}

    def _get(self, key: str, build: Callable[[], object]) -> object:
        inst = self._cache.get(key)
        if inst is None:
            inst = build()
            self._cache[key] = inst
        return inst

    def rfdetr_detector(self) -> Detector:
        from .rfdetr_models import RFDETRDetector
        return self._get("rf_detect", RFDETRDetector)  # type: ignore[return-value]

    def rfdetr_segmenter(self) -> Segmenter:
        from .rfdetr_models import RFDETRSegmenter
        return self._get("rf_seg", RFDETRSegmenter)  # type: ignore[return-value]

    def rfdetr_pose(self) -> PoseEstimator:
        from .rfdetr_models import RFDETRPose
        return self._get("rf_pose", RFDETRPose)  # type: ignore[return-value]

    def _sam3(self) -> object:
        from .sam3_model import SAM3
        return self._get("sam3", SAM3)

    def sam_segmenter(self) -> Segmenter:
        return self._sam3()  # type: ignore[return-value]

    def sam_tracker(self) -> Tracker:
        return self._sam3()  # type: ignore[return-value]
