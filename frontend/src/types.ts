// Wire types shared with the backend store (docs/data-model.md).

export type TrackType = "player" | "racquet" | "ball" | "court";
export type Source = "yolo" | "sam3" | "cotracker" | "human";
export type Visibility = "visible" | "occluded" | "out-of-frame";

// geom crosses the wire as one of two shapes (docs/data-model.md §geom JSON):
export interface PoseGeom {
  kpts: [number, number, Visibility][]; // player / racquet / court
}
export interface PointGeom {
  pt: [number, number]; // ball
  vis: Visibility;
}
export type Geom = PoseGeom | PointGeom;

export interface VideoInfo {
  path: string;
  width: number;
  height: number;
  fps: number;
  n_frames: number;
  video_id: number | null;
}

export interface Track {
  id: number;
  video_id: number;
  type: TrackType;
  annotator: string | null;
}

export interface Detection {
  id: number;
  track_id: number;
  frame: number;
  geom: Geom;
  flight_index: number | null;
  source: Source;
  edited: boolean;
  model_confidence: number | null;
  model_geom: Geom | null;
  track_type?: TrackType; // present on the frame read path
}

// Internal editor representation: an ordered list of points, one per schema keypoint.
export interface EditPoint {
  x: number;
  y: number;
  vis: Visibility;
}
