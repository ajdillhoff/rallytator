# ADR-0002: Server-side, on-demand frame delivery

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

Tennis annotation is **frame-accurate**: ball position per Frame, and Action start/end
Frames, must land on the exact integer Frame the user intends. The browser's native
`<video>` element seeks to keyframes and its timestamp math is fuzzy — "go to Frame
1043" is not reliable. The [backend](0001-server-browser-topology.md) already has a
Python decoder with frame-exact random access.

## Decision

The **backend owns decoding**. The browser requests a Frame by integer index
(`GET /frame/{n}`); the backend seeks and decodes that exact Frame and returns it as an
image. The browser never guesses a Frame from time.

To hide decode latency during scrubbing, the backend/frontend maintain a **prefetch
window** (±N Frames around the current index) and an **LRU cache** of decoded Frames.

## Alternatives considered

- **Pre-extract every Frame to JPEG on import.** Trivially frame-accurate and fast to
  serve, but costs GBs per Video and a preprocessing pass before annotation can start.
  Rejected as the default; viable fallback if on-demand random-access decode proves too
  slow.
- **In-browser decode (WebCodecs / `<video>`).** Smooth playback, low server load, but
  frame-exact seeking is fragile/complex and puts demux+decode logic in JS. Rejected:
  correctness over playback smoothness.

## Consequences

- Frame accuracy is correct **by construction** — the unit of addressing is the integer
  Frame index, end to end.
- **Cost / risk:** scrub latency depends on decode + serve speed and on prefetch tuning.
  This is the make-or-break metric for the choice.
- **Measurement (required before we trust this):** prefetched-Frame scrub latency,
  **target < 16 ms**; size the prefetch window to keep decode off the interactive path.
  Bench decode-library options (decord / PyAV / OpenCV) against this target.
