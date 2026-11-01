// Wire types shared with the backend store (docs/data-model.md).

export type TrackType = "player" | "racquet" | "ball" | "court";
export type Source = "yolo" | "sam3" | "rfdetr" | "cotracker" | "human";
export type ObjectKind = "instance" | "track";

// Status (ADR-0007): observability + trainability of geometry on a Frame. Canonical
// uppercase tokens — a downstream dataset contract. Replaces the old 3-value Visibility.
export type Status = "VISIBLE" | "OCCLUDED" | "IGNORE" | "OUT_OF_FRAME";

// A bounding box in video-pixel coords: [x, y, width, height] (top-left origin).
export type Bbox = [number, number, number, number];

// geom crosses the wire as one of two shapes (docs/data-model.md §geom JSON):
export interface PoseGeom {
  bbox?: Bbox;                      // optional enclosing box for player/racquet/court
  bbox_status?: Status;             // object-level status for the box (default VISIBLE)
  kpts: [number, number, Status][]; // player / racquet / court
}
export interface PointGeom {
  pt: [number, number]; // ball
  status: Status;
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
  kind: ObjectKind;     // instance (single frame) | track (persistent identity)
  label: string;        // editable, unique-per-video user-facing id (ADR-0007)
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
  has_mask?: boolean;     // present on the frame read path
}

// Internal editor representation: an ordered list of points, one per schema keypoint.
export interface EditPoint {
  x: number;
  y: number;
  status: Status;
}

// The active-track working state: the (optional) box + its status, plus one point per
// schema keypoint.
export interface Draft {
  bbox: Bbox | null;
  bboxStatus: Status;
  points: EditPoint[];
}

export const emptyDraft = (): Draft => ({ bbox: null, bboxStatus: "VISIBLE", points: [] });
