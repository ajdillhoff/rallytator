# RallyTator backend

Frame-delivery slice (see [`../docs/adr/0001-server-browser-topology.md`](../docs/adr/0001-server-browser-topology.md),
[`0002`](../docs/adr/0002-server-side-frame-delivery.md)). FastAPI serves exact frames on
demand; a single worker thread owns the PyAV container, prefetches a forward window, and
caches encoded JPEGs in an LRU.

## Run

```bash
uv sync
RALLYTATOR_VIDEO=/path/to/video.mp4 uv run uvicorn rallytator.main:app --port 8099
# open http://127.0.0.1:8099  — scrubber + latency HUD, with sequential/random benchmarks
```

Or open a video at runtime: `POST /open?path=/abs/path.mp4`.

Endpoints: `GET /video/info`, `GET /frame/{index}` (JPEG + `X-Cache` / `X-Decode-Ms`
headers), `GET /` (scrubber UI).

## Annotation store (ADR-0005, [`../docs/data-model.md`](../docs/data-model.md))

SQLite is the single source of truth (`RALLYTATOR_DB`, default `rallytator.db`). Opening a
video registers a `Video` row and returns its `video_id`; annotations hang off it as
`Track → Detection (+ Mask)`. `db.py` owns the schema, `store.py` the CRUD, `main.py` the
REST surface. Geometry crosses the wire as JSON objects (`{"kpts":[[x,y,vis],...]}` for
poses, `{"pt":[x,y],"vis":...}` for the ball point); masks as base64 RLE.

| method | route | purpose |
|--------|-------|---------|
| `GET` | `/videos`, `/videos/{id}` | list / fetch videos |
| `GET`/`POST` | `/videos/{id}/tracks` | list / create a Track (`player\|racquet\|ball\|court`) |
| `DELETE` | `/tracks/{id}` | delete Track (cascades to Detections + Masks) |
| `PUT` | `/tracks/{tid}/detections/{frame}` | upsert the Detection at (track, frame) |
| `GET`/`DELETE` | `/tracks/{tid}/detections/{frame}`, `/detections/{id}` | fetch / delete |
| `GET` | `/tracks/{tid}/detections` | a Track's Detections, ordered by frame |
| `GET` | `/videos/{id}/frames/{frame}/detections` | **canvas read path** — all Detections in a frame |
| `PUT`/`GET` | `/detections/{id}/mask` | set / get RLE mask (base64) |

Upsert is keyed on `UNIQUE(track_id, frame)`: re-`PUT`ting a human edit over a model
Detection replaces the row (pass `edited: true` + `model_geom` to snapshot the original —
anchor logic layers on top later, per ADR-0006).

## Tests

```bash
uv run pytest          # store CRUD + invariants, API smoke (no video needed)
```

## Measured — scrub latency vs the <16ms target (ADR-0002)

1080p / 30fps synthetic clip (600 frames, 1s GOP), localhost HTTP:

| case | median | p95 |
|------|--------|-----|
| prefetched (cache hit) | **2.4 ms** | 11.8 ms |
| cold random seek (miss) | 20.2 ms | 22.7 ms |

**Prefetch hides decode** (hits ≪ 16 ms); cold seeks exceed target, confirming prefetch is
required, not optional. Caveats: synthetic content decodes cheaper than real tennis
footage; under a zero-delay request loop the prefetcher kept ~48% ahead — realistic
rAF-paced scrubbing (~16ms/frame) leaves more room. Next: bench on real footage, tune
prefetch window / JPEG quality, consider WebP + HTTP keep-alive.
