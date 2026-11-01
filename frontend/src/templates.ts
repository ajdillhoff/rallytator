// Normalized keypoint templates. Each entry is a [0,1]x[0,1] layout (x right, y down)
// in schema-point order (see schemas.ts). When a bounding box is drawn, the template is
// mapped into it so the user starts from a plausible pose and only nudges points.

import { LABEL_SCHEMAS } from "./schemas";
import type { Bbox, EditPoint, TrackType } from "./types";

type Norm = [number, number];

// COCO-17 canonical front-facing standing pose.
const PLAYER: Norm[] = [
  [0.50, 0.09], // nose
  [0.46, 0.07], // left_eye
  [0.54, 0.07], // right_eye
  [0.42, 0.09], // left_ear
  [0.58, 0.09], // right_ear
  [0.38, 0.20], // left_shoulder
  [0.62, 0.20], // right_shoulder
  [0.32, 0.35], // left_elbow
  [0.68, 0.35], // right_elbow
  [0.30, 0.50], // left_wrist
  [0.70, 0.50], // right_wrist
  [0.43, 0.55], // left_hip
  [0.57, 0.55], // right_hip
  [0.42, 0.75], // left_knee
  [0.58, 0.75], // right_knee
  [0.42, 0.97], // left_ankle
  [0.58, 0.97], // right_ankle
];

// Racquet held roughly vertical: shaft up the middle, face across the top.
const RACQUET: Norm[] = [
  [0.50, 0.95], // butt
  [0.50, 0.55], // throat
  [0.50, 0.05], // tip
  [0.25, 0.25], // head_left
  [0.75, 0.25], // head_right
];

// Court trapezoid (far baseline narrow/top, near baseline wide/bottom). Placeholder
// layout until the exact 17-ground-point convention is imported (docs/label-schemas.md).
const COURT_GROUND: Norm[] = [
  [0.35, 0.20], [0.50, 0.20], [0.65, 0.20],   // far baseline: L, C, R
  [0.28, 0.45], [0.50, 0.45], [0.72, 0.45],   // far service line: L, T, R
  [0.22, 0.65], [0.50, 0.65], [0.78, 0.65],   // near service line: L, T, R
  [0.15, 0.90], [0.50, 0.90], [0.85, 0.90],   // near baseline: L, C, R
  [0.25, 0.55], [0.75, 0.55],                 // net line x singles sidelines
  [0.20, 0.55], [0.80, 0.55],                 // net line x doubles sidelines
  [0.50, 0.55],                               // net line center (ground)
];
const COURT: Norm[] = [
  ...COURT_GROUND,
  [0.18, 0.48], // net_left (post top, off-plane)
  [0.50, 0.44], // net_center_top
  [0.82, 0.48], // net_right (post top, off-plane)
];

const TEMPLATES: Partial<Record<TrackType, Norm[]>> = {
  player: PLAYER,
  racquet: RACQUET,
  court: COURT,
};

/** Map a type's normalized template into `bbox`, yielding one EditPoint per schema point. */
export function applyTemplate(type: TrackType, bbox: Bbox): EditPoint[] {
  const [bx, by, bw, bh] = bbox;
  const tmpl = TEMPLATES[type];
  if (tmpl) {
    return tmpl.map(([nx, ny]) => ({ x: bx + nx * bw, y: by + ny * bh, status: "VISIBLE" }));
  }
  // Fallback: no template for this type — spread points evenly down the box center.
  const n = LABEL_SCHEMAS[type].points.length;
  return Array.from({ length: n }, (_, i) => ({
    x: bx + bw / 2,
    y: by + (bh * (i + 0.5)) / n,
    status: "VISIBLE" as const,
  }));
}
