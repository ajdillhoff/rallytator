"""RallyTator backend — frame-delivery slice (ADR-0001, ADR-0002).

Single-user local: opens one Video (env RALLYTATOR_VIDEO or POST /open) and serves exact
frames on demand. This slice exists to measure prefetched-frame scrub latency against the
<16 ms target banked in ADR-0002.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import masks
from .jobs import JobManager, LocalRunner
from .store import Store
from .video import VideoReader

_STATIC = Path(__file__).resolve().parent.parent / "static"
_DB_PATH = os.environ.get("RALLYTATOR_DB", "rallytator.db")

_reader: VideoReader | None = None
_video_id: int | None = None
_store: Store | None = None
_jobs_mgr: JobManager | None = None
# Test hook: set to run jobs inline with a fake Registry (no subprocess/GPU).
_local_runner: LocalRunner | None = None


def store() -> Store:
    if _store is None:
        raise HTTPException(503, "store not initialized")
    return _store


def jobs() -> JobManager:
    if _jobs_mgr is None:
        raise HTTPException(503, "job manager not initialized")
    return _jobs_mgr


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
    global _store, _jobs_mgr
    if _store is None:                 # tests may inject a store before startup
        _store = Store(_DB_PATH)
    if _jobs_mgr is None:              # tests may inject a manager + local runner
        _jobs_mgr = JobManager()
        _jobs_mgr.start(asyncio.get_running_loop(), local_runner=_local_runner)
    env = os.environ.get("RALLYTATOR_VIDEO")
    if env and Path(env).is_file():
        _open(env)
    yield
    if _jobs_mgr is not None:
        _jobs_mgr.stop()
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
Source = Literal["yolo", "sam3", "rfdetr", "cotracker", "human"]


ObjectKind = Literal["instance", "track"]


class TrackIn(BaseModel):
    type: TrackType
    kind: ObjectKind = "track"
    label: str | None = None          # omitted -> store assigns the next free label
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
    try:
        tid = store().create_track(video_id, body.type, body.kind, body.label, body.annotator)
    except sqlite3.IntegrityError as e:  # duplicate label (UNIQUE(video_id, label))
        raise HTTPException(409, f"could not create track: {e}")
    return store().get_track(tid)


@app.delete("/tracks/{track_id}", status_code=204)
def delete_track(track_id: int) -> Response:
    store().delete_track(track_id)
    return Response(status_code=204)


class RenameIn(BaseModel):
    label: str


@app.patch("/tracks/{track_id}")
def rename_track(track_id: int, body: RenameIn) -> dict:
    if store().get_track(track_id) is None:
        raise HTTPException(404, f"no track {track_id}")
    try:
        store().rename_track(track_id, body.label)
    except sqlite3.IntegrityError as e:
        raise HTTPException(409, f"label already in use: {e}")
    return store().get_track(track_id)


@app.post("/tracks/{track_id}/split", status_code=201)
def split_track(track_id: int, frame: int) -> dict:
    """Split at `frame`: original keeps [..,frame-1], a new track gets [frame,..]."""
    if store().get_track(track_id) is None:
        raise HTTPException(404, f"no track {track_id}")
    try:
        new_id = store().split_track(track_id, frame)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return store().get_track(new_id)


@app.post("/tracks/{src_id}/merge")
def merge_tracks(src_id: int, into: int) -> dict:
    """Merge `src` into `into`; destination wins on frame collisions, src is deleted."""
    src, dst = store().get_track(src_id), store().get_track(into)
    if src is None or dst is None:
        raise HTTPException(404, "track not found")
    if src_id == into:
        raise HTTPException(400, "cannot merge a track into itself")
    if src["video_id"] != dst["video_id"] or src["type"] != dst["type"]:
        raise HTTPException(400, "tracks must share a video and type to merge")
    store().merge_tracks(src_id, into)
    return store().get_track(into)


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


@app.get("/detections/{detection_id}/mask.png")
def get_mask_png(detection_id: int) -> Response:
    """Mask as a white RGBA PNG (alpha = mask) for tinted canvas overlay."""
    m = store().get_mask(detection_id)
    if m is None:
        raise HTTPException(404, f"no mask for detection {detection_id}")
    return Response(content=masks.mask_png(m["rle"]), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


# ---- model assist (SAM3 / RFDETR) — worker.py, jobs.py, ADR-0001 ----------

SegModel = Literal["sam3", "rfdetr"]


class TrackJobIn(BaseModel):
    start_frame: int
    end_frame: int


def _track_video_path(track_id: int) -> tuple[dict, str]:
    """Resolve a track to (track_row, video_path); 404 if either is missing."""
    tr = store().get_track(track_id)
    if tr is None:
        raise HTTPException(404, f"no track {track_id}")
    v = store().get_video(tr["video_id"])
    if v is None:
        raise HTTPException(404, f"track {track_id} has no video")
    return tr, v["path"]


def _prompt_bbox(track_id: int, frame: int) -> list | None:
    """The bbox already annotated on this (track, frame), if any — the model prompt."""
    d = store().get_detection(track_id, frame)
    if d and isinstance(d.get("geom"), dict):
        b = d["geom"].get("bbox")
        return list(b) if b else None
    return None


def _write_geom(track_id: int, frame: int, *, bbox: list | None = None,
                kpts: list | None = None, source: str) -> int:
    """Merge model geometry into the (track, frame) detection, preserving what it doesn't
    set. Never clobbers a human anchor (edited=1)."""
    existing = store().get_detection(track_id, frame)
    if existing and existing.get("edited"):
        return int(existing["id"])
    geom = dict(existing["geom"]) if existing and isinstance(existing.get("geom"), dict) else {}
    geom.setdefault("kpts", [])
    if bbox is not None:
        geom["bbox"] = bbox
    if kpts is not None:
        geom["kpts"] = kpts
    return store().upsert_detection(track_id, frame, geom, source)


@app.post("/tracks/{track_id}/detect")
async def detect(track_id: int, frame: int) -> dict:
    _, path = _track_video_path(track_id)
    jid = jobs().submit("detect", video_path=path, frame=frame, bbox=_prompt_bbox(track_id, frame))
    try:
        res = await jobs().await_result(jid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    _write_geom(track_id, frame, bbox=res["bbox"], source="rfdetr")
    return store().get_detection(track_id, frame)


@app.post("/tracks/{track_id}/segment")
async def segment(track_id: int, frame: int, model: SegModel = "sam3") -> dict:
    _, path = _track_video_path(track_id)
    prompt = _prompt_bbox(track_id, frame)
    if model == "sam3" and prompt is None:
        raise HTTPException(400, "SAM3 auto-segment needs a bounding box on this frame")
    jid = jobs().submit("segment", video_path=path, frame=frame, bbox=prompt, model=model)
    try:
        res = await jobs().await_result(jid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    did = _write_geom(track_id, frame, bbox=res["bbox"], source=model)
    store().set_mask(did, res["mask_rle"], res["height"], res["width"])
    return store().get_detection(track_id, frame)


@app.post("/tracks/{track_id}/keypoints")
async def keypoints(track_id: int, frame: int) -> dict:
    _, path = _track_video_path(track_id)
    jid = jobs().submit("keypoints", video_path=path, frame=frame, bbox=_prompt_bbox(track_id, frame))
    try:
        res = await jobs().await_result(jid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    _write_geom(track_id, frame, bbox=res["bbox"], kpts=res["kpts"], source="rfdetr")
    return store().get_detection(track_id, frame)


@app.post("/tracks/{track_id}/track")
async def track_span(track_id: int, body: TrackJobIn) -> dict:
    _, path = _track_video_path(track_id)
    prompt = _prompt_bbox(track_id, body.start_frame)
    if prompt is None:
        raise HTTPException(400, "SAM3 track needs a bounding box on the start frame")
    jid = jobs().submit("track", video_path=path, bbox=prompt,
                        start=body.start_frame, end=body.end_frame)

    async def _persist() -> None:
        try:
            res = await jobs().await_result(jid)
        except RuntimeError:
            return  # error surfaced via job status / WS
        for fr in res["frames"]:
            did = _write_geom(track_id, fr["frame"], bbox=fr["bbox"], source="sam3")
            store().set_mask(did, fr["mask_rle"], fr["height"], fr["width"])

    asyncio.create_task(_persist())
    return {"job_id": jid}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    st = jobs().status(job_id)
    if st is None:
        raise HTTPException(404, f"no job {job_id}")
    return st


@app.websocket("/jobs/{job_id}/progress")
async def job_progress(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    q = jobs().subscribe(job_id)
    try:
        while True:
            st = await q.get()
            await ws.send_json(st)
            if st.get("state") in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        jobs().unsubscribe(job_id, q)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
