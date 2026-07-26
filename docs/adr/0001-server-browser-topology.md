# ADR-0001: Python backend + browser frontend, run locally

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

RallyTator is a frame-accurate video annotation tool for tennis (feeding RallyLens).
Its automated half relies on Python/PyTorch, GPU-bound models (YOLO, SAM3, CoTracker),
which must run in a process with GPU access. The human half needs a fast annotation
UI: a dense canvas, frame-accurate scrubbing, and heavy keybinds.

The tool is, for now, a **single-user local** research tool — one annotator, on the
machine with the GPU, no auth.

## Decision

Split into a **Python (FastAPI) backend** that owns models + data, and a **browser
frontend** (React + PixiJS/WebGL) that is the annotation UI. Run locally: the "server"
is a localhost convenience, not a shared service.

GPU inference does **not** run inline in the request path. A single persistent **worker
subprocess** holds models warm and executes queued **Jobs**; FastAPI enqueues work and
streams progress/results over WebSocket. One GPU → one serialized worker.

Persistence is **SQLite** (single-file, transactional, queryable) — sufficient and
ideal for single-user local.

## Alternatives considered

- **Native Python desktop (PySide/Qt), models in-process.** Zero IPC and inline torch
  calls, but building a dense, ergonomic annotation canvas in Qt is materially more
  work and the UX lags the browser. Rejected: UI ergonomics are the product.
- **Desktop shell + Python sidecar (Tauri/Electron).** Best-of-both UX + native models,
  but two runtimes to package and an IPC bridge to maintain. Rejected as premature
  weight for a single-user local tool.
- **In-process threadpool for inference.** Simplest, but an OOM/crash takes down the
  API and pre/post-processing contends on the GIL. Rejected for the warm-worker model.
- **Celery/RQ + Redis.** Durable and scalable, but an external broker is overkill for
  one local user. Rejected.

## Consequences

- Best-in-class annotation ergonomics; models run native on GPU; API stays responsive
  during long propagation Jobs.
- **Cost:** a client/server split to build, frame serving over HTTP (see
  [ADR-0002](0002-server-side-frame-delivery.md)), and a job/progress protocol.
- Multi-user is **not** built, but not precluded: the **Annotator** field exists
  (nullable) so provenance survives if a second annotator is added later. Real auth /
  concurrency would be a new ADR.
- Reversible-ish: swapping to a desktop shell later reuses the same React UI and
  FastAPI, but is a significant migration — hence this record.
