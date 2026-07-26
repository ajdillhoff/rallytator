"""RallyTator backend — frame-delivery slice (ADR-0001, ADR-0002).

Single-user local: opens one Video (env RALLYTATOR_VIDEO or POST /open) and serves exact
frames on demand. This slice exists to measure prefetched-frame scrub latency against the
<16 ms target banked in ADR-0002.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .video import VideoReader

app = FastAPI(title="RallyTator", version="0.1.0")

_STATIC = Path(__file__).resolve().parent.parent / "static"
_reader: VideoReader | None = None


def _open(path: str) -> VideoReader:
    global _reader
    if not Path(path).is_file():
        raise HTTPException(404, f"video not found: {path}")
    _reader = VideoReader(path)
    return _reader


@app.on_event("startup")
def _startup() -> None:
    env = os.environ.get("RALLYTATOR_VIDEO")
    if env and Path(env).is_file():
        _open(env)


@app.post("/open")
def open_video(path: str) -> dict:
    return _open(path).info()


@app.get("/video/info")
def video_info() -> dict:
    if _reader is None:
        raise HTTPException(409, "no video open — set RALLYTATOR_VIDEO or POST /open?path=...")
    return _reader.info()


@app.get("/frame/{index}")
def frame(index: int) -> Response:
    if _reader is None:
        raise HTTPException(409, "no video open")
    r = _reader.get(index)
    return Response(
        content=r.jpeg,
        media_type="image/jpeg",
        headers={
            "X-Frame-Index": str(r.index),
            "X-Cache": r.cache,
            "X-Decode-Ms": f"{r.decode_ms:.2f}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
