// Convert between wire `geom` (docs/data-model.md) and the editor's Draft.
// Ball is a single {pt,status}; everything else is {kpts:[[x,y,status],...]} with an
// optional enclosing {bbox:[x,y,w,h], bbox_status}.

import type { Draft, Geom, Status, TrackType } from "./types";

export function geomToDraft(geom: Geom): Draft {
  if ("pt" in geom) {
    return {
      bbox: null,
      bboxStatus: "VISIBLE",
      points: [{ x: geom.pt[0], y: geom.pt[1], status: geom.status }],
    };
  }
  return {
    bbox: geom.bbox ?? null,
    bboxStatus: geom.bbox_status ?? "VISIBLE",
    points: geom.kpts.map(([x, y, status]) => ({ x, y, status })),
  };
}

export function draftToGeom(type: TrackType, draft: Draft): Geom {
  if (type === "ball") {
    const p = draft.points[0] ?? { x: 0, y: 0, status: "VISIBLE" as const };
    return { pt: [p.x, p.y], status: p.status };
  }
  const kpts = draft.points.map((p) => [p.x, p.y, p.status] as [number, number, Status]);
  return draft.bbox
    ? { bbox: draft.bbox, bbox_status: draft.bboxStatus, kpts }
    : { kpts };
}
