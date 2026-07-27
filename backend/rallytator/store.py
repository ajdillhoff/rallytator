"""Annotation store: CRUD over the SQLite schema (docs/data-model.md).

Thin data-access layer realizing Track -> Detection (+ Mask). Business rules that ADRs
describe -- anchor snapshots on human edit, Flight boundaries, propagation -- layer *on
top* of these primitives; this module just reads and writes rows. `geom`/`model_geom`
cross the boundary as Python objects and are JSON-encoded here.

One connection guarded by a lock: single-user local, so a global lock is simpler and
sufficient (ADR-0001). WAL is enabled for reader/writer overlap if that changes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from . import db


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def _detection_out(r: sqlite3.Row) -> dict:
    """Row -> API dict, parsing JSON columns back into objects."""
    d = dict(r)
    d["geom"] = json.loads(d["geom"])
    d["model_geom"] = json.loads(d["model_geom"]) if d["model_geom"] is not None else None
    d["edited"] = bool(d["edited"])
    return d


class Store:
    def __init__(self, path: str = "rallytator.db") -> None:
        self.path = path
        self._conn = db.connect(path)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- Video ------------------------------------------------------------

    def create_video(self, path: str, width: int, height: int,
                     fps: float | None, n_frames: int | None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO Video(path, width, height, fps, n_frames) VALUES (?,?,?,?,?)",
                (path, width, height, fps, n_frames),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_video(self, video_id: int) -> dict | None:
        with self._lock:
            return _row(self._conn.execute(
                "SELECT * FROM Video WHERE id=?", (video_id,)).fetchone())

    def get_video_by_path(self, path: str) -> dict | None:
        with self._lock:
            return _row(self._conn.execute(
                "SELECT * FROM Video WHERE path=? ORDER BY id DESC LIMIT 1",
                (path,)).fetchone())

    def list_videos(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in
                    self._conn.execute("SELECT * FROM Video ORDER BY id").fetchall()]

    # ---- Track ------------------------------------------------------------

    def create_track(self, video_id: int, type: str, annotator: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO Track(video_id, type, annotator) VALUES (?,?,?)",
                (video_id, type, annotator),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_tracks(self, video_id: int) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM Track WHERE video_id=? ORDER BY id", (video_id,)).fetchall()]

    def delete_track(self, track_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM Track WHERE id=?", (track_id,))
            self._conn.commit()

    # ---- Detection --------------------------------------------------------

    def upsert_detection(self, track_id: int, frame: int, geom: Any, source: str, *,
                        flight_index: int | None = None, edited: bool = False,
                        model_confidence: float | None = None,
                        model_geom: Any = None) -> int:
        """Insert or replace the Detection at (track_id, frame). Returns its id."""
        gj = json.dumps(geom)
        mgj = json.dumps(model_geom) if model_geom is not None else None
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO Detection
                    (track_id, frame, geom, flight_index, source, edited,
                     model_confidence, model_geom)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(track_id, frame) DO UPDATE SET
                    geom=excluded.geom,
                    flight_index=excluded.flight_index,
                    source=excluded.source,
                    edited=excluded.edited,
                    model_confidence=excluded.model_confidence,
                    model_geom=excluded.model_geom
                """,
                (track_id, frame, gj, flight_index, source, int(edited),
                 model_confidence, mgj),
            )
            self._conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = self._conn.execute(
                "SELECT id FROM Detection WHERE track_id=? AND frame=?",
                (track_id, frame)).fetchone()
            return int(row["id"])

    def get_detection(self, track_id: int, frame: int) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM Detection WHERE track_id=? AND frame=?",
                (track_id, frame)).fetchone()
        return _detection_out(r) if r is not None else None

    def track_detections(self, track_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM Detection WHERE track_id=? ORDER BY frame",
                (track_id,)).fetchall()
        return [_detection_out(r) for r in rows]

    def detections_in_frame(self, video_id: int, frame: int) -> list[dict]:
        """Every Detection at `frame` across the Video's Tracks -- the canvas read path."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT d.*, t.type AS track_type
                FROM Detection d JOIN Track t ON d.track_id = t.id
                WHERE t.video_id=? AND d.frame=?
                ORDER BY d.track_id
                """,
                (video_id, frame)).fetchall()
        out = []
        for r in rows:
            d = _detection_out(r)
            out.append(d)
        return out

    def delete_detection(self, detection_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM Detection WHERE id=?", (detection_id,))
            self._conn.commit()

    # ---- Mask -------------------------------------------------------------

    def set_mask(self, detection_id: int, rle: bytes, height: int, width: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO Mask(detection_id, rle, height, width) VALUES (?,?,?,?)
                ON CONFLICT(detection_id) DO UPDATE SET
                    rle=excluded.rle, height=excluded.height, width=excluded.width
                """,
                (detection_id, rle, height, width),
            )
            self._conn.commit()

    def get_mask(self, detection_id: int) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM Mask WHERE detection_id=?", (detection_id,)).fetchone()
        return _row(r)
