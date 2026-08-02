// Typed client for the backend frame-delivery + annotation-store routes (main.py).
// Origin-relative; the Vite dev proxy (vite.config.ts) forwards to FastAPI.

import type { Detection, Geom, Source, Track, TrackType, VideoInfo } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const frameUrl = (index: number) => `/frame/${index}`;

export async function fetchFrameBitmap(index: number): Promise<ImageBitmap> {
  const res = await fetch(frameUrl(index), { cache: "no-store" });
  if (!res.ok) throw new Error(`frame ${index}: ${res.status}`);
  return createImageBitmap(await res.blob());
}

export const getVideoInfo = () => fetch("/video/info").then(json<VideoInfo>);

export const listTracks = (videoId: number) =>
  fetch(`/videos/${videoId}/tracks`).then(json<Track[]>);

export const createTrack = (videoId: number, type: TrackType) =>
  fetch(`/videos/${videoId}/tracks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ type }),
  }).then(json<Track>);

export const deleteTrack = (trackId: number) =>
  fetch(`/tracks/${trackId}`, { method: "DELETE" });

export const getFrameDetections = (videoId: number, frame: number) =>
  fetch(`/videos/${videoId}/frames/${frame}/detections`).then(json<Detection[]>);

export const upsertDetection = (
  trackId: number,
  frame: number,
  geom: Geom,
  source: Source = "human",
) =>
  fetch(`/tracks/${trackId}/detections/${frame}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ geom, source }),
  }).then(json<Detection>);

export const deleteDetection = (detectionId: number) =>
  fetch(`/detections/${detectionId}`, { method: "DELETE" });

export async function fetchMaskBitmap(detectionId: number): Promise<ImageBitmap> {
  const res = await fetch(`/detections/${detectionId}/mask.png`, { cache: "no-store" });
  if (!res.ok) throw new Error(`mask ${detectionId}: ${res.status}`);
  return createImageBitmap(await res.blob());
}

// ---- model assist (SAM3 / RFDETR) — see worker.py / jobs.py ---------------

export type RfdetrModel = "detect" | "segment" | "keypoints";
export type SegModel = "sam3" | "rfdetr";

const post = <T>(url: string) =>
  fetch(url, { method: "POST" }).then(json<T>);

/** RFDETR detect -> writes a bbox detection on (track, frame). */
export const runDetect = (trackId: number, frame: number) =>
  post<Detection>(`/tracks/${trackId}/detect?frame=${frame}`);

/** Segment via SAM3 (bbox prompt) or RFDETR; writes a mask (+bbox if missing). */
export const runSegment = (trackId: number, frame: number, model: SegModel) =>
  post<Detection>(`/tracks/${trackId}/segment?frame=${frame}&model=${model}`);

/** RFDETR pose -> writes COCO-17 keypoints (detect-first if no bbox). */
export const runKeypoints = (trackId: number, frame: number) =>
  post<Detection>(`/tracks/${trackId}/keypoints?frame=${frame}`);

export interface JobRef { job_id: string; }
export interface JobStatus {
  job_id: string;
  state: "queued" | "running" | "done" | "error";
  progress: number;   // 0..1
  detail?: string;
  error?: string;
}

/** SAM3 video track across [start,end]; returns a job id to poll/stream. */
export const startTrack = (trackId: number, start: number, end: number) =>
  fetch(`/tracks/${trackId}/track`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ start_frame: start, end_frame: end }),
  }).then(json<JobRef>);

/** Open a WebSocket for a track job's progress; falls back to GET polling on failure.
 * Always drives the job to a terminal state (done/error) so callers can clear busy UI. */
export function watchJob(jobId: string, onUpdate: (s: JobStatus) => void): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let stopped = false;
  let poll: number | undefined;
  const terminal = (s: JobStatus) => s.state === "done" || s.state === "error";
  const stop = () => { stopped = true; if (poll) { clearInterval(poll); poll = undefined; } };

  const startPoll = () => {
    if (poll || stopped) return;
    let fails = 0;
    poll = window.setInterval(async () => {
      const s = await fetch(`/jobs/${jobId}`).then(json<JobStatus>).catch(() => null);
      if (s) { fails = 0; onUpdate(s); if (terminal(s)) stop(); }
      else if (++fails >= 20) {  // ~10s of no contact — don't wedge the UI
        onUpdate({ job_id: jobId, state: "error", progress: 0, error: "lost contact with job" });
        stop();
      }
    }, 500);
  };

  try {
    const ws = new WebSocket(`${proto}://${location.host}/jobs/${jobId}/progress`);
    ws.onmessage = (e) => { const s = JSON.parse(e.data) as JobStatus; onUpdate(s); if (terminal(s)) stop(); };
    ws.onerror = () => startPoll();
    ws.onclose = () => { if (!stopped) startPoll(); };  // closed before terminal -> poll
    return () => { stop(); ws.close(); };
  } catch {
    startPoll();
    return stop;
  }
}
