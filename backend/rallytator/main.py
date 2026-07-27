"""RallyTator backend — frame-delivery slice (ADR-0001, ADR-0002).

Single-user local: opens one Video (env RALLYTATOR_VIDEO or POST /open) and serves exact
frames on demand. This slice exists to measure prefetched-frame scrub latency against the
<16 ms target banked in ADR-0002.
"""

from __future__ import annotations

import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .store import Store
from .video import VideoReader

_STATIC = Path(__file__).resolve().parent.parent / "static"
_DB_PATH = os.environ.get("RALLYTATOR_DB", "rallytator.db")

_reader: VideoReader | None = None
_video_id: int | None = None
_store: Store | None = None


def store() -> Store:
    if _store is None:
        raise HTTPException(503, "store not initialized")
    return _store


def _open(path: str) -> dict:
    """Open the video for frame delivery and ensure it has a Video row. Returns info+id."""
    global _reader, _video_id
    if not Path(path).is_file():
        raise HTTPException(404, f"video not found: {path}")
    _reader = VideoReader(path)
    info = _reader.info()
    row = store().get_video_by_path(path)
    if row is None:
        _video_id = store().create_video(
            path, info["width"], info["height"], info["fps"], info["n_frames"])
    else:
        _video_id = int(row["id"])
    return {**info, "video_id": _video_id}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    if _store is None:                 # tests may inject a store before startup
        _store = Store(_DB_PATH)
    env = os.environ.get("RALLYTATOR_VIDEO")
    if env and Path(env).is_file():
        _open(env)
    yield
    if _store is not None:
        _store.close()


app = FastAPI(title="RallyTator", version="0.1.0", lifespan=lifespan)


@app.post("/open")
def open_video(path: str) -> dict:
    return _open(path)


@app.get("/video/info")
def video_info() -> dict:
    if _reader is None:
        raise HTTPException(409, "no video open — set RALLYTATOR_VIDEO or POST /open?path=...")
    return {**_reader.info(), "video_id": _video_id}


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


# ---- annotation store (ADR-0005, docs/data-model.md) ----------------------

TrackType = Literal["player", "racquet", "ball", "court"]
Source = Literal["yolo", "sam3", "cotracker", "human"]


class TrackIn(BaseModel):
    type: TrackType
    annotator: str | None = None


class DetectionIn(BaseModel):
    geom: Any                       # {"kpts":[[x,y,vis],...]} or {"pt":[x,y],"vis":...}
    source: Source
    flight_index: int | None = None
    edited: bool = False
    model_confidence: float | None = None
    model_geom: Any = None


class MaskIn(BaseModel):
    rle: str                        # base64-encoded RLE blob
    height: int
    width: int


@app.get("/videos")
def list_videos() -> list[dict]:
    return store().list_videos()


@app.get("/videos/{video_id}")
def get_video(video_id: int) -> dict:
    v = store().get_video(video_id)
    if v is None:
        raise HTTPException(404, f"no video {video_id}")
    return v


@app.get("/videos/{video_id}/tracks")
def list_tracks(video_id: int) -> list[dict]:
    return store().list_tracks(video_id)


@app.post("/videos/{video_id}/tracks", status_code=201)
def create_track(video_id: int, body: TrackIn) -> dict:
    if store().get_video(video_id) is None:
        raise HTTPException(404, f"no video {video_id}")
    tid = store().create_track(video_id, body.type, body.annotator)
    return {"id": tid, "video_id": video_id, "type": body.type, "annotator": body.annotator}


@app.delete("/tracks/{track_id}", status_code=204)
def delete_track(track_id: int) -> Response:
    store().delete_track(track_id)
    return Response(status_code=204)


@app.get("/tracks/{track_id}/detections")
def track_detections(track_id: int) -> list[dict]:
    return store().track_detections(track_id)


@app.put("/tracks/{track_id}/detections/{frame}")
def upsert_detection(track_id: int, frame: int, body: DetectionIn) -> dict:
    did = store().upsert_detection(
        track_id, frame, body.geom, body.source,
        flight_index=body.flight_index, edited=body.edited,
        model_confidence=body.model_confidence, model_geom=body.model_geom)
    return store().get_detection(track_id, frame) | {"id": did}


@app.get("/tracks/{track_id}/detections/{frame}")
def get_detection(track_id: int, frame: int) -> dict:
    d = store().get_detection(track_id, frame)
    if d is None:
        raise HTTPException(404, f"no detection at track {track_id} frame {frame}")
    return d


@app.delete("/detections/{detection_id}", status_code=204)
def delete_detection(detection_id: int) -> Response:
    store().delete_detection(detection_id)
    return Response(status_code=204)


@app.get("/videos/{video_id}/frames/{frame}/detections")
def frame_detections(video_id: int, frame: int) -> list[dict]:
    """Every Detection at this frame across the video's tracks — the canvas read path."""
    return store().detections_in_frame(video_id, frame)


@app.put("/detections/{detection_id}/mask", status_code=204)
def set_mask(detection_id: int, body: MaskIn) -> Response:
    try:
        rle = base64.b64decode(body.rle, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(400, "rle is not valid base64")
    store().set_mask(detection_id, rle, body.height, body.width)
    return Response(status_code=204)


@app.get("/detections/{detection_id}/mask")
def get_mask(detection_id: int) -> dict:
    m = store().get_mask(detection_id)
    if m is None:
        raise HTTPException(404, f"no mask for detection {detection_id}")
    return {"detection_id": m["detection_id"], "height": m["height"],
            "width": m["width"], "rle": base64.b64encode(m["rle"]).decode()}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
