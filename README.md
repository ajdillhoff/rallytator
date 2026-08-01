# RallyTator
RallyTator is a fast and user-friendly annotation tool primarily used for annotating objects in videos for RallyLens, a Tennis analytics platform. Annotations are semi-automated through the aid of open-source models (YOLO, SAM3, CoTracker, etc.). Efficient keybinds make annotating much easier and streamline the user's workflow.

# Tasks

RallyTator's primary job is to produce the annotation *substrate* — the per-frame
geometry a downstream pipeline consumes:

- Pose (Player, Racquet, Court)
- Point (Ball) — labeled only while *ballistic* (in flight)

**Actions** (Forehand Swing, Backhand Swing, Forehand Volley, Backhand Volley, Serve,
Lob) are **derived**, not annotated from scratch: a downstream pipeline infers them from
pose + court + ball. RallyTator supports *reviewing and correcting* inferred Actions to
build train/eval ground-truth. See [CONTEXT.md](CONTEXT.md) and
[docs/adr/](docs/adr/) for the domain model and decisions.

# Primary Data
First-class support for video and frame-by-frame annotation.

# Running

Two processes: a Python/FastAPI **backend** (frame delivery + annotation store) and a
React/PixiJS **frontend** (the annotation canvas). Prerequisites: [uv](https://docs.astral.sh/uv/)
and Node ≥ 20.

## Backend (`backend/`)

FastAPI serves exact frames on demand and owns the SQLite annotation store
([ADR-0001](docs/adr/0001-server-browser-topology.md),
[ADR-0002](docs/adr/0002-server-side-frame-delivery.md),
[ADR-0005](docs/adr/0005-data-storage.md)).

```bash
cd backend
uv sync
RALLYTATOR_VIDEO=/path/to/clip.mp4 uv run uvicorn rallytator.main:app --port 8099
# http://127.0.0.1:8099 — scrubber + latency HUD; open another video with POST /open?path=...
```

Environment:
- `RALLYTATOR_VIDEO` — video opened on startup (else `POST /open?path=/abs/path.mp4`).
- `RALLYTATOR_DB` — SQLite path (default `rallytator.db`; single source of truth).

Run the tests (store CRUD + API, no video needed):

```bash
cd backend && uv run pytest
```

## Frontend (`frontend/`)

React + PixiJS annotation canvas. Origin-relative; the Vite dev server proxies the frame +
store routes to the backend (default `http://127.0.0.1:8099`, override `RALLYTATOR_BACKEND`).
Start the backend first, then:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # tsc typecheck + production bundle to dist/
```

### Keys

| key | action |
|-----|--------|
| `←` / `→` | step frame ±1 (`shift` = ±10) |
| `n` | new Track of the current *new-type* |
| `1`–`4` | set new-type (player / racquet / ball / court) |
| `Tab` | cycle the active Track |
| click / drag | place / move a keypoint |
| `v` | cycle selected point visibility (visible → occluded → out-of-frame) |
| `Backspace` | undo last placed point |
| `d` | delete active Track (cascades) |
| `Esc` | deselect |