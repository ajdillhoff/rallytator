"""Unit tests for the model-assist compute layer — no GPU, no subprocess.

Covers the mask RLE codec and `worker.process_job` driven by a fake Registry with
in-memory frames, exercising every op's result shape.
"""

from __future__ import annotations

import numpy as np

from rallytator import masks
from rallytator.worker import process_job


def test_rle_roundtrip_and_png():
    m = np.zeros((6, 8), dtype=bool)
    m[1:4, 2:5] = True
    blob = masks.rle_encode(m)
    assert np.array_equal(masks.rle_decode(blob), m)
    png = masks.mask_png(blob)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature


def test_rle_roundtrip_leading_one():
    m = np.ones((4, 4), dtype=bool)          # first pixel set -> leading empty 0-run
    assert np.array_equal(masks.rle_decode(masks.rle_encode(m)), m)


# ---- fakes ---------------------------------------------------------------

class _Det:
    def detect(self, image, prompt):
        return (10.0, 20.0, 30.0, 40.0), 0.9


class _Seg:
    def segment(self, image, box):
        m = np.zeros((8, 8), dtype=bool)
        m[2:5, 2:5] = True
        return m


class _Pose:
    def keypoints(self, image, box):
        return [[float(i), float(i), "visible"] for i in range(17)], (5.0, 5.0, 10.0, 10.0)


class _Trk:
    def track(self, frames, box, progress):
        frames = list(frames)
        out = []
        for k, (idx, _img) in enumerate(frames):
            m = np.zeros((8, 8), dtype=bool)
            m[1:3, 1:3] = True
            out.append((idx, m))
            progress((k + 1) / len(frames), f"f{idx}")
        return out


class FakeRegistry:
    def rfdetr_detector(self): return _Det()
    def rfdetr_segmenter(self): return _Seg()
    def rfdetr_pose(self): return _Pose()
    def sam_segmenter(self): return _Seg()
    def sam_tracker(self): return _Trk()


def _read_frame(path, index):
    return np.zeros((8, 8, 3), dtype=np.uint8)


def _read_span(path, start, end):
    return [(i, np.zeros((8, 8, 3), dtype=np.uint8)) for i in range(start, end + 1)]


def _run(job):
    events = []
    res = process_job(job, FakeRegistry(), lambda p, d: events.append((p, d)),
                      _read_frame, _read_span)
    return res, events


def test_process_detect():
    res, _ = _run({"op": "detect", "video_path": "x", "frame": 3, "bbox": None})
    assert res["kind"] == "detect" and res["bbox"] == [10.0, 20.0, 30.0, 40.0]


def test_process_segment_sam_requires_box():
    import pytest
    with pytest.raises(ValueError):
        _run({"op": "segment", "video_path": "x", "frame": 0, "bbox": None, "model": "sam3"})


def test_process_segment_rfdetr_derives_bbox():
    res, _ = _run({"op": "segment", "video_path": "x", "frame": 0, "bbox": None, "model": "rfdetr"})
    assert res["kind"] == "segment" and res["bbox"] == [2.0, 2.0, 3.0, 3.0]  # tight from mask
    assert np.array_equal(masks.rle_decode(res["mask_rle"])[2:5, 2:5], np.ones((3, 3), bool))


def test_process_keypoints():
    res, _ = _run({"op": "keypoints", "video_path": "x", "frame": 0, "bbox": [1, 2, 3, 4]})
    assert res["kind"] == "keypoints" and len(res["kpts"]) == 17 and res["bbox"] == [1, 2, 3, 4]


def test_process_track_emits_progress():
    res, events = _run({"op": "track", "video_path": "x", "bbox": [0, 0, 4, 4],
                        "start": 5, "end": 8})
    assert res["kind"] == "track" and [f["frame"] for f in res["frames"]] == [5, 6, 7, 8]
    assert events[-1][0] == 1.0  # progress reaches 100%
