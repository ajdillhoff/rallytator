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
