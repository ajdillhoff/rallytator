"""Model-assist package: interfaces + a warm registry (ADR-0001).

Public surface is `base` (interfaces + Registry); concrete backends (RFDETR, SAM3/SAM2)
are imported lazily by the Registry so importing this package pulls in no torch.
"""

from .base import Bbox, Detector, PoseEstimator, Registry, Segmenter, Tracker

__all__ = ["Bbox", "Detector", "PoseEstimator", "Registry", "Segmenter", "Tracker"]
