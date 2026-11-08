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

// Court 20-point: 17 ground-plane (CourtKeypoint enum) + 3 net-top (NetTop enum).
// Order is canonical — matches rallylens/core/geometry.py IDs 0-19.
const COURT_POINTS = [
  // Ground plane (IDs 0-16, CourtKeypoint)
  "far_left_doubles",    // 0  (−5.485, +11.885, 0)
  "far_left_singles",    // 1  (−4.115, +11.885, 0)
  "far_right_singles",   // 2  (+4.115, +11.885, 0)
  "far_right_doubles",   // 3  (+5.485, +11.885, 0)
  "far_left_service",    // 4  (−4.115,  +6.400, 0)
  "far_service_t",       // 5  (  0.000,  +6.400, 0)
  "far_right_service",   // 6  (+4.115,  +6.400, 0)
  "net_left_post",       // 7  (−5.485,   0.000, 0)
  "net_right_post",      // 8  (+5.485,   0.000, 0)
  "near_left_service",   // 9  (−4.115,  −6.400, 0)
  "near_service_t",      // 10 (  0.000,  −6.400, 0)
  "near_right_service",  // 11 (+4.115,  −6.400, 0)
  "near_left_doubles",   // 12 (−5.485, −11.885, 0)
  "near_left_singles",   // 13 (−4.115, −11.885, 0)
  "near_right_singles",  // 14 (+4.115, −11.885, 0)
  "near_right_doubles",  // 15 (+5.485, −11.885, 0)
  "net_center_base",     // 16 (  0.000,   0.000, 0)
  // Off-plane net tops (IDs 17-19, NetTop)
  "net_left_post_top",      // 17 (−5.485, 0, +1.07)
  "net_right_post_top",     // 18 (+5.485, 0, +1.07)
  "net_center_strap_top",   // 19 (  0.000, 0, +0.914)
];

export const LABEL_SCHEMAS: Record<TrackType, LabelSchema> = {
  player: { type: "player", points: COCO_POINTS, edges: COCO_EDGES, color: 0x4fc3f7, hasMask: true },
  racquet: { type: "racquet", points: RACQUET_POINTS, edges: RACQUET_EDGES, color: 0xffb74d, hasMask: false },
  ball: { type: "ball", points: ["center"], edges: [], color: 0xff5252, hasMask: false },
  court: { type: "court", points: COURT_POINTS, edges: [], color: 0x81c784, hasMask: false },
};

export const TRACK_TYPES: TrackType[] = ["player", "racquet", "ball", "court"];
