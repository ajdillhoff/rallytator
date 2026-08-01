// Convert between wire `geom` (docs/data-model.md) and the editor's Draft.
// Ball is a single {pt,vis}; everything else is {kpts:[[x,y,vis],...]} with an
// optional enclosing {bbox:[x,y,w,h]}.

import type { Draft, EditPoint, Geom, TrackType } from "./types";

export function geomToDraft(geom: Geom): Draft {
  if ("pt" in geom) {
    return { bbox: null, points: [{ x: geom.pt[0], y: geom.pt[1], vis: geom.vis }] };
  }
  return {
    bbox: geom.bbox ?? null,
    points: geom.kpts.map(([x, y, vis]) => ({ x, y, vis })),
  };
}

export function draftToGeom(type: TrackType, draft: Draft): Geom {
  if (type === "ball") {
    const p = draft.points[0] ?? { x: 0, y: 0, vis: "visible" as const };
    return { pt: [p.x, p.y], vis: p.vis };
  }
  const kpts = draft.points.map((p) => [p.x, p.y, p.vis] as [number, number, EditPoint["vis"]]);
  return draft.bbox ? { bbox: draft.bbox, kpts } : { kpts };
}
