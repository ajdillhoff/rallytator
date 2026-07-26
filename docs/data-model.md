# Data Model

The SQLite store realizing **Track → Detection** (see [`../CONTEXT.md`](../CONTEXT.md)),
and the single-JSON export contract. Rationale is in [ADR-0005](adr/0005-data-storage.md).

SQLite is the **single source of truth**; the export JSON is a derived artifact.

---

## Tables (sketch)

```sql
Video(
  id            INTEGER PRIMARY KEY,
  path          TEXT NOT NULL,
  width         INTEGER NOT NULL,     -- coords are original-frame pixels
  height        INTEGER NOT NULL,
  fps           REAL,
  n_frames      INTEGER
);

Track(
  id            INTEGER PRIMARY KEY,
  video_id      INTEGER NOT NULL REFERENCES Video(id),
  type          TEXT NOT NULL,        -- 'player' | 'racquet' | 'ball' | 'court'
  annotator     TEXT                  -- nullable; provenance for a future multi-user world
);

Detection(
  id              INTEGER PRIMARY KEY,
  track_id        INTEGER NOT NULL REFERENCES Track(id),
  frame           INTEGER NOT NULL,   -- integer Frame index; the addressing unit
  geom            TEXT NOT NULL,      -- JSON: keypoints[] + per-point visibility, or point
  flight_index    INTEGER,            -- Ball only: which Flight of this Ball Track (see below)
  source          TEXT NOT NULL,      -- 'yolo' | 'sam3' | 'cotracker' | 'human'
  edited          INTEGER NOT NULL DEFAULT 0,
  model_confidence REAL,
  model_geom      TEXT,               -- JSON snapshot of the model's ORIGINAL geom, set on human edit
  UNIQUE(track_id, frame)
);

Mask(
  detection_id  INTEGER PRIMARY KEY REFERENCES Detection(id),  -- 1:1, Player Detections
  rle           BLOB NOT NULL,        -- COCO-style RLE, lossless, lazy-loaded
  height        INTEGER NOT NULL,
  width         INTEGER NOT NULL
);
```

### `geom` JSON

- **Pose** (player/racquet/court): `{ "kpts": [[x,y,vis], ...] }` in schema order
  (see [`label-schemas.md`](label-schemas.md)); `vis` ∈ `visible|occluded|out-of-frame`.
- **Point** (ball): `{ "pt": [x,y], "vis": "visible" }`.

### Flight (Ball only)

The **labeled extent of a Ball Track while Ballistic** (see `CONTEXT.md`). Boundaries:
ball becomes non-ballistic (rolls, stops, leaves Frame, or bounces twice without being
hit). A Ball Track may have several Flights (hit → land → hit again); `flight_index`
groups a Ball Track's Detections into distinct Flights, which is also the natural unit for
the TrackNet export.

---

## Export — single custom JSON (per Video)

One document per Video is the RallyLens / TrackNetV4 contract. Consumers extract the parts
they need (TrackNet → ball flights; RallyLens → poses + court calibration). SQLite schema
is free to evolve behind this boundary.

```jsonc
{
  "video": { "path": "...", "width": 1920, "height": 1080, "fps": 30, "n_frames": 9000 },
  "court": {                          // static-hold; keypoints for 3D calibration
    "keypoints": { "<id>": [x, y, vis], ... },   // 17 ground + 3 net (known heights)
    "held_from_frame": 0
  },
  "tracks": [
    {
      "id": 1, "type": "player",
      "detections": [
        { "frame": 320,
          "kpts": [[x,y,"visible"], ...],   // COCO-17
          "mask_rle": "...",                // RLE string
          "source": "human", "edited": true }
      ]
    },
    {
      "id": 7, "type": "ball",
      "flights": [                          // grouped by flight_index
        { "index": 0,
          "points": [ { "frame": 331, "pt": [x,y], "vis": "visible" }, ... ] }
      ]
    }
    // racquet tracks: 5-kpt detections, same shape as player minus mask
  ]
}
```

> Field layout is a **sketch**, not frozen — exact keys firm up when the export is built.
> Court's exact 17 ground-point ids depend on the **TODO: import from existing setup**
> (see [`label-schemas.md`](label-schemas.md)).
