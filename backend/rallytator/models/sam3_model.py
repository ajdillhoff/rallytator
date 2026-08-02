"""SAM3 wrapper (Meta SAM3 via `transformers`): box-prompted image segmentation +
box-prompted video tracking.

`facebook/sam3` is a composite (`Sam3VideoModel`) whose nested `tracker_config`
(`sam3_tracker_video`) is the SAM2-lineage *geometry* tracker we want. Both the
`Sam3TrackerVideoModel` weights and the `Sam3TrackerVideoProcessor` load directly from that
repo. Verified against transformers 5.14 on GPU: a box prompt yields a per-frame mask via
the streaming session API.

One model serves both ops: `segment` runs a one-frame session, `track` a multi-frame one.
Weights are GATED — accept the license at https://huggingface.co/facebook/sam3 and
authenticate (`hf auth login` or `HF_TOKEN`). Override the repo via `RALLYTATOR_SAM_CKPT`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

import numpy as np

from .base import Bbox

CKPT = os.environ.get("RALLYTATOR_SAM_CKPT", "facebook/sam3")


def _xyxy(b: Bbox) -> list[float]:
    x, y, w, h = b
    return [float(x), float(y), float(x + w), float(y + h)]


def _to_bool(mask) -> np.ndarray:
    """post_process_masks item (num_obj,1,H,W) -> a single (H,W) bool mask."""
    arr = mask.detach().cpu().numpy() if hasattr(mask, "detach") else np.asarray(mask)
    while arr.ndim > 2:      # drop object / channel axes
        arr = arr[0]
    return arr.astype(bool)


class SAM3:
    """Box-prompted SAM3 tracker — segment one frame or propagate across a span."""

    def __init__(self) -> None:
        import torch
        from transformers import Sam3TrackerVideoModel, Sam3TrackerVideoProcessor
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = Sam3TrackerVideoModel.from_pretrained(CKPT).to(self.device).eval()
        self.proc = Sam3TrackerVideoProcessor.from_pretrained(CKPT)

    def _run(self, video: np.ndarray, box: Bbox,
             progress: Callable[[float, str], None] | None) -> list[tuple[int, np.ndarray]]:
        import torch
        h, w = int(video.shape[1]), int(video.shape[2])
        session = self.proc.init_video_session(
            video=video, inference_device=self.device, dtype=torch.float32)
        self.proc.add_inputs_to_inference_session(
            inference_session=session, frame_idx=0, obj_ids=1, input_boxes=[[_xyxy(box)]])
        out: list[tuple[int, np.ndarray]] = []
        total = len(video)
        with torch.inference_mode():
            for k, o in enumerate(self.model.propagate_in_video_iterator(session, start_frame_idx=0)):
                mask = self.proc.post_process_masks([o.pred_masks], [(h, w)])[0]
                out.append((int(o.frame_idx), _to_bool(mask)))
                if progress is not None:
                    progress((k + 1) / total, f"frame {o.frame_idx}")
        return out

    # ---- Segmenter -------------------------------------------------------
    def segment(self, image: np.ndarray, box: Bbox) -> np.ndarray:
        return self._run(np.stack([image]), box, None)[0][1]

    # ---- Tracker ---------------------------------------------------------
    def track(
        self,
        frames: Iterable[tuple[int, np.ndarray]],
        box: Bbox,
        progress: Callable[[float, str], None],
    ) -> Iterable[tuple[int, np.ndarray]]:
        frames = list(frames)
        idxs = [i for i, _ in frames]
        video = np.stack([f for _, f in frames])
        # propagate_in_video_iterator yields session-relative indices (0..T-1); remap.
        return [(idxs[rel], m) for rel, m in self._run(video, box, progress)]
