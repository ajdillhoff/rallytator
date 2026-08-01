// Label schemas (docs/label-schemas.md). Point order is significant — geom stores
// keypoints in exactly this order. Edges are index pairs for skeleton rendering.

import type { TrackType } from "./types";

export interface LabelSchema {
  type: TrackType;
  points: string[];
  edges: [number, number][];
  color: number; // overlay tint
  hasMask: boolean;
}

// COCO-17 (player). Standard keypoint order + skeleton.
const COCO_POINTS = [
  "nose", "left_eye", "right_eye", "left_ear", "right_ear",
  "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
  "left_wrist", "right_wrist", "left_hip", "right_hip",
  "left_knee", "right_knee", "left_ankle", "right_ankle",
];
const COCO_EDGES: [number, number][] = [
  [15, 13], [13, 11], [16, 14], [14, 12], [11, 12], [5, 11], [6, 12],
  [5, 6], [5, 7], [6, 8], [7, 9], [8, 10], [1, 2], [0, 1], [0, 2],
  [1, 3], [2, 4], [3, 5], [4, 6],
];

// Racquet 5-point (+face): shaft butt→throat→tip, face across the head.
const RACQUET_POINTS = ["butt", "throat", "tip", "head_left", "head_right"];
const RACQUET_EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [2, 4], [3, 4],
];

// Court 20-point: 17 ground + 3 net (left post, center-top, right post).
// TODO: exact ground-point ids depend on importing the existing setup
// (docs/label-schemas.md). Named generically until then; no line topology yet.
const COURT_POINTS = [
  ...Array.from({ length: 17 }, (_, i) => `ground_${i}`),
  "net_left", "net_center_top", "net_right",
];

export const LABEL_SCHEMAS: Record<TrackType, LabelSchema> = {
  player: { type: "player", points: COCO_POINTS, edges: COCO_EDGES, color: 0x4fc3f7, hasMask: true },
  racquet: { type: "racquet", points: RACQUET_POINTS, edges: RACQUET_EDGES, color: 0xffb74d, hasMask: false },
  ball: { type: "ball", points: ["center"], edges: [], color: 0xff5252, hasMask: false },
  court: { type: "court", points: COURT_POINTS, edges: [], color: 0x81c784, hasMask: false },
};

export const TRACK_TYPES: TrackType[] = ["player", "racquet", "ball", "court"];
