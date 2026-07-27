"""SQLite schema + connection for the annotation store (ADR-0005, docs/data-model.md).

SQLite is the single source of truth; the export JSON is derived. This module owns the
DDL and hands back a configured connection. All access goes through `store.Store`.
"""

from __future__ import annotations

import sqlite3

# Schema mirrors docs/data-model.md. Kept as one string so `Store` can create it
# idempotently on open; migrations, if ever needed, layer on top of this baseline.
SCHEMA = """
CREATE TABLE IF NOT EXISTS Video (
  id        INTEGER PRIMARY KEY,
  path      TEXT NOT NULL,
  width     INTEGER NOT NULL,   -- coords are original-frame pixels
  height    INTEGER NOT NULL,
  fps       REAL,
  n_frames  INTEGER
);

CREATE TABLE IF NOT EXISTS Track (
  id        INTEGER PRIMARY KEY,
  video_id  INTEGER NOT NULL REFERENCES Video(id) ON DELETE CASCADE,
  type      TEXT NOT NULL CHECK (type IN ('player','racquet','ball','court')),
  annotator TEXT
);

CREATE TABLE IF NOT EXISTS Detection (
  id               INTEGER PRIMARY KEY,
  track_id         INTEGER NOT NULL REFERENCES Track(id) ON DELETE CASCADE,
  frame            INTEGER NOT NULL,   -- integer Frame index; the addressing unit
  geom             TEXT NOT NULL,      -- JSON: {"kpts":[[x,y,vis],...]} or {"pt":[x,y],"vis":...}
  flight_index     INTEGER,            -- Ball only: groups Detections into Flights
  source           TEXT NOT NULL CHECK (source IN ('yolo','sam3','cotracker','human')),
  edited           INTEGER NOT NULL DEFAULT 0,
  model_confidence REAL,
  model_geom       TEXT,               -- JSON snapshot of model's ORIGINAL geom, set on human edit
  UNIQUE(track_id, frame)
);

CREATE TABLE IF NOT EXISTS Mask (
  detection_id INTEGER PRIMARY KEY REFERENCES Detection(id) ON DELETE CASCADE,
  rle          BLOB NOT NULL,          -- COCO-style RLE, lossless, lazy-loaded
  height       INTEGER NOT NULL,
  width        INTEGER NOT NULL
);

-- read paths: "all detections in this frame" and "all tracks in this video"
CREATE INDEX IF NOT EXISTS idx_detection_frame ON Detection(frame);
CREATE INDEX IF NOT EXISTS idx_track_video ON Track(video_id);
"""


def connect(path: str) -> sqlite3.Connection:
    """Open a connection configured for the store: row dicts, FKs on, WAL."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn
