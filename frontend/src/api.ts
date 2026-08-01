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
