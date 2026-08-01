# RallyTator frontend

Annotation canvas — React + PixiJS (WebGL), the planned stack from
[`../docs/adr/0001-server-browser-topology.md`](../docs/adr/0001-server-browser-topology.md).
Renders backend-delivered frames as a PixiJS sprite and draws / edits keypoint detections
over them, persisting through the annotation store (M2).

Run instructions (backend + frontend, dev server, keybinds) live in the
[root README](../README.md#running). The frontend is origin-relative; the Vite dev server
proxies frame-delivery + store routes to the FastAPI backend (default
`http://127.0.0.1:8099`, override `RALLYTATOR_BACKEND`).

## What it does (M3 — interactive annotation slice)

- **Frame render**: one PixiJS `world` container holds the frame sprite + overlay, scaled
  to fit — so all keypoint coordinates are native **video pixels**.
- **Overlay**: every Track's Detection on the current frame is drawn (points + per-type
  skeleton). The active Track shows a live, editable draft; occluded / out-of-frame points
  dim by visibility.
- **Edit loop**: click to place the next keypoint in schema order, drag to move, and each
  change `PUT`s the Detection to the store (`source: human`).

Label schemas (point order + skeleton) live in [`src/schemas.ts`](src/schemas.ts), mirroring
[`../docs/label-schemas.md`](../docs/label-schemas.md): player COCO-17 (+mask, M4), racquet
5-point, ball single point, court 20-point (ground ids still TODO — named generically).

Keybinds are documented in the [root README](../README.md#keys).

## Layout

- [`src/api.ts`](src/api.ts) — typed client for the backend routes.
- [`src/pixiStage.ts`](src/pixiStage.ts) — imperative PixiJS stage; reports pointer events
  in video-pixel coords, React owns all annotation state.
- [`src/App.tsx`](src/App.tsx) — state, keybinds, persistence, overlay render model.
- [`src/geom.ts`](src/geom.ts) — wire `geom` ⇄ editor `EditPoint[]`.

> Not yet verified in a browser end-to-end (build + module transform + full HTTP loop
> through the proxy are green); interactive canvas behavior needs a manual pass.
