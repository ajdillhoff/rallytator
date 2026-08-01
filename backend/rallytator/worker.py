"""Warm model worker (ADR-0001): one persistent subprocess holds models on the GPU and
serializes access. It is *pure compute* — it never touches SQLite. Jobs arrive as plain
dicts on an input queue; progress + results go back on an output queue. The API process
(jobs.py) owns the DB and writes results.

`process_job` is separated from the multiprocessing plumbing so it can be unit-tested with
a fake Registry and in-memory frames — no subprocess, no GPU.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np

from .masks import rle_encode
from .models import Registry

# A job dict: {id, op, video_path, frame?, bbox?, model?, start?, end?}. `bbox` is
# (x,y,w,h) in video pixels or None. Results are dicts carrying an RLE mask blob (bytes).
Job = dict
Emit = Callable[[float, str], None]


def _mask_bbox(mask: np.ndarray) -> tuple[float, float, float, float]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return (0.0, 0.0, 0.0, 0.0)
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def _mask_result(mask: np.ndarray, bbox) -> dict:
    h, w = mask.shape
    return {"mask_rle": rle_encode(mask), "height": h, "width": w, "bbox": list(bbox)}


def process_job(
    job: Job,
    registry: Registry,
    emit: Emit,
    read_frame: Callable[[str, int], np.ndarray],
    read_span: Callable[[str, int, int], Iterable[tuple[int, np.ndarray]]],
) -> dict:
    """Run one job to completion; return its result dict. Raises on model failure."""
    op = job["op"]
    path = job["video_path"]
    bbox = tuple(job["bbox"]) if job.get("bbox") else None

    if op == "detect":
        img = read_frame(path, job["frame"])
        box, conf = registry.rfdetr_detector().detect(img, bbox)
        return {"kind": "detect", "bbox": list(box), "confidence": conf}

    if op == "segment":
        img = read_frame(path, job["frame"])
        model = job.get("model", "sam3")
        if model == "rfdetr":
            mask = registry.rfdetr_segmenter().segment(img, bbox)  # bbox optional (self-detects)
        else:
            if bbox is None:
                raise ValueError("SAM3 auto-segment requires a bounding box prompt")
            mask = registry.sam_segmenter().segment(img, bbox)
        out_bbox = bbox if bbox is not None else _mask_bbox(mask)
        return {"kind": "segment", **_mask_result(mask, out_bbox)}

    if op == "keypoints":
        img = read_frame(path, job["frame"])
        kpts, box = registry.rfdetr_pose().keypoints(img, bbox)
        return {"kind": "keypoints", "kpts": kpts, "bbox": list(bbox or box)}

    if op == "track":
        if bbox is None:
            raise ValueError("SAM3 track requires a bounding box on the start frame")
        start, end = job["start"], job["end"]
        frames = read_span(path, start, end)
        results = registry.sam_tracker().track(frames, bbox, emit)
        return {"kind": "track", "frames": [
            {"frame": idx, **_mask_result(m, _mask_bbox(m))} for idx, m in results
        ]}

    raise ValueError(f"unknown op: {op}")


# ---- frame decoding (own av container; independent of the API's VideoReader) ----------

def read_frame(path: str, index: int) -> np.ndarray:
    import av
    with av.open(path) as c:
        st = c.streams.video[0]
        st.thread_type = "AUTO"
        fps = float(st.average_rate or 30)
        tb = st.time_base
        c.seek(int(index / fps / tb), stream=st, backward=True, any_frame=False)
        for f in c.decode(st):
            if f.pts is None:
                continue
            if round(float(f.pts * tb) * fps) >= index:
                return f.to_ndarray(format="rgb24")
    raise RuntimeError(f"reached EOF before frame {index}")


def read_span(path: str, start: int, end: int):
    import av
    with av.open(path) as c:
        st = c.streams.video[0]
        st.thread_type = "AUTO"
        fps = float(st.average_rate or 30)
        tb = st.time_base
        c.seek(int(start / fps / tb), stream=st, backward=True, any_frame=False)
        for f in c.decode(st):
            if f.pts is None:
                continue
            idx = round(float(f.pts * tb) * fps)
            if idx < start:
                continue
            if idx > end:
                break
            yield idx, f.to_ndarray(format="rgb24")


# ---- multiprocessing loop -------------------------------------------------------------

def run_worker(in_q, out_q) -> None:  # pragma: no cover - runs in a subprocess
    """Drain jobs forever; emit progress/result/error dicts keyed by job id."""
    registry = Registry()
    while True:
        job = in_q.get()
        if job is None:  # shutdown sentinel
            return
        jid = job["id"]

        def emit(progress: float, detail: str, _jid=jid) -> None:
            out_q.put({"id": _jid, "type": "progress", "progress": progress, "detail": detail})

        try:
            result = process_job(job, registry, emit, read_frame, read_span)
            out_q.put({"id": jid, "type": "result", "data": result})
        except Exception as exc:  # noqa: BLE001 - worker error boundary -> reported as job error
            out_q.put({"id": jid, "type": "error", "error": f"{type(exc).__name__}: {exc}"})
