"""Frame-accurate, on-demand video frame delivery (ADR-0002).

A single worker thread owns the PyAV container (PyAV containers are not thread-safe) and
services two kinds of work:

  * on-demand frame requests (highest priority), and
  * a forward prefetch window that fills the LRU ahead of the scrub head.

Frames are addressed by integer index. Seeking jumps to the nearest preceding keyframe and
decodes forward to the exact frame; sequential access reuses the live decoder so scrubbing
forward costs one decode per frame, not one seek per frame.
"""

from __future__ import annotations

import io
import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass

import av


@dataclass
class FrameResult:
    jpeg: bytes
    index: int
    cache: str          # "hit" | "miss"
    decode_ms: float    # decode + encode time on the worker (0.0 for a cache hit)


class VideoReader:
    def __init__(self, path: str, *, cache_size: int = 512, prefetch: int = 24,
                 jpeg_quality: int = 80) -> None:
        self.path = path
        self._cache_size = cache_size
        self._prefetch = prefetch
        self._quality = jpeg_quality

        self._container = av.open(path)
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        self._time_base = self._stream.time_base
        avg = self._stream.average_rate
        self.fps = float(avg) if avg else 30.0
        # frames may be 0 for some containers; fall back to duration * rate
        n = self._stream.frames
        if not n and self._stream.duration:
            n = int(float(self._stream.duration * self._time_base) * self.fps)
        self.n_frames = int(n) or 0
        self.width = self._stream.codec_context.width
        self.height = self._stream.codec_context.height

        self._cache: "OrderedDict[int, bytes]" = OrderedDict()
        self._lock = threading.Lock()
        self._reqs: "queue.Queue[tuple[int, Future]]" = queue.Queue()
        self._prefetch_next = 0            # next index the prefetcher will try
        self._decoder = None               # live decode generator
        self._expected = None              # index the live decoder will yield next

        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---- public API -------------------------------------------------------

    def info(self) -> dict:
        return {
            "path": self.path, "width": self.width, "height": self.height,
            "fps": self.fps, "n_frames": self.n_frames,
        }

    def get(self, index: int) -> FrameResult:
        index = max(0, min(index, (self.n_frames - 1) if self.n_frames else index))
        with self._lock:
            hit = self._cache.get(index)
            if hit is not None:
                self._cache.move_to_end(index)
                self._prefetch_next = index + 1
                return FrameResult(hit, index, "hit", 0.0)
        fut: Future = Future()
        self._reqs.put((index, fut))
        return fut.result()

    # ---- worker -----------------------------------------------------------

    def _run(self) -> None:
        while True:
            try:
                index, fut = self._reqs.get(timeout=0.005)
            except queue.Empty:
                self._prefetch_step()
                continue
            try:
                with self._lock:
                    cached = self._cache.get(index)
                if cached is not None:
                    fut.set_result(FrameResult(cached, index, "hit", 0.0))
                else:
                    jpeg, ms = self._decode_encode(index)
                    self._store(index, jpeg)
                    fut.set_result(FrameResult(jpeg, index, "miss", ms))
                self._prefetch_next = index + 1
            except Exception as exc:  # surface decode errors to the request
                fut.set_exception(exc)

    def _prefetch_step(self) -> None:
        if self.n_frames and self._prefetch_next >= self.n_frames:
            return
        target = self._prefetch_next
        with self._lock:
            ahead = sum(1 for i in range(self._prefetch_next, self._prefetch_next + self._prefetch)
                        if i in self._cache)
            if target in self._cache:
                self._prefetch_next += 1
                return
        if ahead >= self._prefetch:
            return
        try:
            jpeg, _ = self._decode_encode(target)
            self._store(target, jpeg)
            self._prefetch_next = target + 1
        except Exception:
            self._prefetch_next = target + 1  # skip a bad frame, keep the window moving

    # ---- decode -----------------------------------------------------------

    def _decode_encode(self, index: int) -> tuple[bytes, float]:
        t0 = time.perf_counter()
        frame = self._decode_index(index)
        img = frame.to_image()
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self._quality)
        return buf.getvalue(), (time.perf_counter() - t0) * 1000.0

    def _decode_index(self, index: int):
        # Fast path: the live decoder is already positioned at `index`.
        if self._decoder is not None and self._expected == index:
            return self._advance_to(index)
        # Seek to the nearest keyframe at/just before the target, then decode forward.
        target_pts = int(index / self.fps / self._time_base)
        self._container.seek(target_pts, stream=self._stream, backward=True, any_frame=False)
        self._decoder = self._container.decode(self._stream)
        self._expected = None
        return self._advance_to(index)

    def _advance_to(self, index: int):
        for frame in self._decoder:
            if frame.pts is None:
                continue
            idx = round(float(frame.pts * self._time_base) * self.fps)
            self._expected = idx + 1
            if idx >= index:
                return frame
        raise RuntimeError(f"reached EOF before frame {index}")

    def _store(self, index: int, jpeg: bytes) -> None:
        with self._lock:
            self._cache[index] = jpeg
            self._cache.move_to_end(index)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
