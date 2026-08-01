// Convert between wire `geom` (docs/data-model.md) and the editor's flat EditPoint[].
// Ball is a single {pt,vis}; everything else is {kpts:[[x,y,vis],...]}.

import type { EditPoint, Geom, TrackType } from "./types";

export function geomToPoints(geom: Geom): EditPoint[] {
  if ("pt" in geom) {
    return [{ x: geom.pt[0], y: geom.pt[1], vis: geom.vis }];
  }
  return geom.kpts.map(([x, y, vis]) => ({ x, y, vis }));
}

export function pointsToGeom(type: TrackType, points: EditPoint[]): Geom {
  if (type === "ball") {
    const p = points[0] ?? { x: 0, y: 0, vis: "visible" as const };
    return { pt: [p.x, p.y], vis: p.vis };
  }
  return { kpts: points.map((p) => [p.x, p.y, p.vis]) };
}
