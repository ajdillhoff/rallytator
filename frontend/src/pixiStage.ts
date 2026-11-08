// Imperative PixiJS (v8) stage. React owns annotation state; this renders it and reports
// pointer events back in *video-pixel* coordinates. A single `world` container holds the
// frame sprite, a mask layer, and the vector overlay, transformed by a persistent
// view (scale + position) that supports zoom-to-cursor and drag-to-pan. All keypoint /
// bbox coords are video pixels; markers are drawn at a constant *screen* size.

import { Application, Container, type FederatedPointerEvent, Graphics, Sprite, Texture } from "pixi.js";
import type { Bbox, EditPoint, Status } from "./types";

export interface RenderItem {
  points: EditPoint[];
  pointVisible?: boolean[];   // per-point display flag (default all true)
  edges: [number, number][];
  color: number;
  active: boolean;
  bbox?: Bbox | null;         // drawn (with resize handles when active) if present
  bboxStatus?: Status;        // styles the box (IGNORE = amber, OCCLUDED = dim)
}

const IGNORE_COLOR = 0xffc107;  // amber — the flagged / excluded-from-loss style

export interface MaskItem {
  id: number;                 // detection id (texture cache key)
  bitmap: ImageBitmap;        // full-frame mask, video resolution
  color: number;
  alpha: number;
}

export type Hit =
  | { kind: "point"; index: number }
  | { kind: "handle"; corner: number }; // 0=TL 1=TR 2=BR 3=BL

export interface PointerInfo {
  x: number;  // video-pixel coords
  y: number;
  sx: number; // screen coords (for panning)
  sy: number;
  hit: Hit | null;
}

type PointerCb = (p: PointerInfo) => void;

// Keypoints are drawn by *shape* per status (always full opacity, except OUT_OF_FRAME which
// is hidden): VISIBLE = filled dot, OCCLUDED = open ring, IGNORE = cross.
const HIT_RADIUS_SCREEN = 10;
const HANDLE_RADIUS_SCREEN = 7;
const MIN_SCALE = 0.05;
const MAX_SCALE = 40;

export class PixiStage {
  readonly app = new Application();
  private world = new Container();
  private sprite = new Sprite();
  private maskLayer = new Container();
  private overlay = new Graphics();
  private videoW = 1;
  private videoH = 1;

  // Persistent view transform (video -> screen): screen = video * scale + (posX, posY).
  private scale = 1;
  private posX = 0;
  private posY = 0;
  private haveView = false;

  private activePoints: EditPoint[] = [];
  private activeVisible: boolean[] = [];
  private activeBbox: Bbox | null = null;
  private maskTex = new Map<number, { tex: Texture; sprite: Sprite }>();

  private ro?: ResizeObserver;
  private inited = false;
  private killed = false;

  onPointerDown: PointerCb = () => {};
  onPointerMove: PointerCb = () => {};
  onPointerUp: PointerCb = () => {};

  async init(parent: HTMLElement): Promise<void> {
    await this.app.init({ background: 0x0a0a0a, antialias: true, resizeTo: parent });
    if (this.killed) return; // destroyed before init resolved (StrictMode double-mount)
    this.inited = true;
    parent.appendChild(this.app.canvas);
    this.world.addChild(this.sprite, this.maskLayer, this.overlay);
    this.app.stage.addChild(this.world);

    this.app.stage.eventMode = "static";
    this.app.stage.hitArea = this.app.screen;
    const at = (e: FederatedPointerEvent) => this.info(e.global);
    this.app.stage.on("pointerdown", (e) => this.onPointerDown(at(e)));
    this.app.stage.on("pointermove", (e) => this.onPointerMove(at(e)));
    this.app.stage.on("pointerup", (e) => this.onPointerUp(at(e)));
    this.app.stage.on("pointerupoutside", (e) => this.onPointerUp(at(e)));

    // Zoom-to-cursor is fully owned by the stage; React never sees the wheel.
    this.app.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = this.app.canvas.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * 0.0015);
      this.zoomAt(e.clientX - rect.left, e.clientY - rect.top, factor);
    }, { passive: false });

    this.ro = new ResizeObserver(() => this.resetView());
    this.ro.observe(parent);
  }

  destroy(): void {
    this.killed = true;
    if (!this.inited) return; // init hasn't resolved; init() will bail on `killed`
    this.ro?.disconnect();
    for (const { tex } of this.maskTex.values()) tex.destroy(true);
    this.app.destroy(true, { children: true, texture: true });
  }

  setFrame(bitmap: ImageBitmap): void {
    const old = this.sprite.texture;
    const dimsChanged = bitmap.width !== this.videoW || bitmap.height !== this.videoH;
    this.videoW = bitmap.width;
    this.videoH = bitmap.height;
    this.sprite.texture = Texture.from(bitmap);
    if (old && old !== Texture.EMPTY) old.destroy(true);
    // Only (re)fit when the video geometry changes or we have no view yet; scrubbing
    // frames must preserve the annotator's current zoom/pan.
    if (dimsChanged || !this.haveView) this.resetView();
    else this.apply();
  }

  // ---- view transform ------------------------------------------------------

  private resetView(): void {
    const { width, height } = this.app.screen;
    const s = Math.min(width / this.videoW, height / this.videoH) || 1;
    this.scale = s;
    this.posX = (width - this.videoW * s) / 2;
    this.posY = (height - this.videoH * s) / 2;
    this.haveView = true;
    this.apply();
  }

  private apply(): void {
    this.world.scale.set(this.scale);
    this.world.position.set(this.posX, this.posY);
    this.draw();
  }

  zoomAt(sx: number, sy: number, factor: number): void {
    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale * factor));
    const f = next / this.scale;
    // Keep the video point under (sx, sy) fixed: p' = c - f*(c - p).
    this.posX = sx - f * (sx - this.posX);
    this.posY = sy - f * (sy - this.posY);
    this.scale = next;
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.posX += dx;
    this.posY += dy;
    this.apply();
  }

  private info(global: { x: number; y: number }): PointerInfo {
    const local = this.world.toLocal(global);
    let hit: Hit | null = null;

    // Keypoints first (they sit inside the box), then bbox corner handles.
    const rp = HIT_RADIUS_SCREEN / this.scale;
    let best = rp * rp;
    this.activePoints.forEach((p, i) => {
      if (this.activeVisible[i] === false) return;
      const d = (p.x - local.x) ** 2 + (p.y - local.y) ** 2;
      if (d <= best) { best = d; hit = { kind: "point", index: i }; }
    });

    if (hit === null && this.activeBbox) {
      const rh = HANDLE_RADIUS_SCREEN / this.scale;
      const corners = this.bboxCorners(this.activeBbox);
      let hb = rh * rh;
      corners.forEach(([cx, cy], c) => {
        const d = (cx - local.x) ** 2 + (cy - local.y) ** 2;
        if (d <= hb) { hb = d; hit = { kind: "handle", corner: c }; }
      });
    }
    return { x: local.x, y: local.y, sx: global.x, sy: global.y, hit };
  }

  private bboxCorners([x, y, w, h]: Bbox): [number, number][] {
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
  }

  // ---- masks ---------------------------------------------------------------

  /** Reconcile the mask sprite pool with the given set (keyed by detection id). */
  setMasks(masks: MaskItem[]): void {
    const keep = new Set(masks.map((m) => m.id));
    for (const [id, entry] of this.maskTex) {
      if (!keep.has(id)) {
        entry.sprite.destroy();
        entry.tex.destroy(true);
        this.maskTex.delete(id);
      }
    }
    for (const m of masks) {
      let entry = this.maskTex.get(m.id);
      if (!entry) {
        const tex = Texture.from(m.bitmap);
        const sprite = new Sprite(tex);
        this.maskLayer.addChild(sprite);
        entry = { tex, sprite };
        this.maskTex.set(m.id, entry);
      }
      entry.sprite.tint = m.color;
      entry.sprite.alpha = m.alpha;
    }
  }

  // ---- overlay -------------------------------------------------------------

  render(items: RenderItem[], selected: number | null): void {
    const active = items.find((it) => it.active);
    this.activePoints = active?.points ?? [];
    this.activeVisible = active?.pointVisible ?? this.activePoints.map(() => true);
    this.activeBbox = active?.bbox ?? null;
    this.pending = { items, selected };
    this.draw();
  }

  private pending: { items: RenderItem[]; selected: number | null } = { items: [], selected: null };

  private draw(): void {
    const { items, selected } = this.pending;
    const g = this.overlay;
    g.clear();

    for (const item of items) {
      const vis = item.pointVisible;
      // A keypoint renders unless display-hidden (👁) or semantically OUT_OF_FRAME.
      const shown = (i: number) =>
        (vis === undefined || vis[i] !== false) && item.points[i]?.status !== "OUT_OF_FRAME";

      // bounding box
      if (item.bbox) {
        const [x, y, w, h] = item.bbox;
        const st = item.bboxStatus ?? "VISIBLE";
        const boxColor = st === "IGNORE" ? IGNORE_COLOR : item.color;
        const boxAlpha = st === "OCCLUDED"
          ? (item.active ? 0.5 : 0.25)
          : (item.active ? 0.9 : 0.4);
        g.rect(x, y, w, h).stroke({
          width: (item.active ? 1.5 : 1) / this.scale,
          color: boxColor,
          alpha: boxAlpha,
        });
        if (item.active) {
          const rh = HANDLE_RADIUS_SCREEN / this.scale;
          for (const [cx, cy] of this.bboxCorners(item.bbox)) {
            g.rect(cx - rh, cy - rh, rh * 2, rh * 2)
              .fill({ color: 0x000000, alpha: 0.6 })
              .stroke({ width: 1.5 / this.scale, color: item.color });
          }
        }
      }

      // skeleton edges (skip any edge with a hidden endpoint)
      for (const [a, b] of item.edges) {
        if (!shown(a) || !shown(b)) continue;
        const pa = item.points[a];
        const pb = item.points[b];
        if (!pa || !pb) continue;
        g.moveTo(pa.x, pa.y).lineTo(pb.x, pb.y);
      }
      g.stroke({
        width: (item.active ? 2 : 1.25) / this.scale,
        color: item.color,
        alpha: item.active ? 0.9 : 0.5,
      });

      // keypoints (constant screen size); shape encodes status
      const r = (item.active ? 6 : 4) / this.scale;
      const sw = (item.active ? 2.5 : 2) / this.scale;
      item.points.forEach((p, i) => {
        if (!shown(i)) return;
        const isSel = item.active && i === selected;
        const col = isSel ? 0xffffff : item.color;
        const rr = isSel ? r + 1.5 / this.scale : r;
        if (p.status === "IGNORE") {
          g.moveTo(p.x - rr, p.y - rr).lineTo(p.x + rr, p.y + rr)
           .moveTo(p.x - rr, p.y + rr).lineTo(p.x + rr, p.y - rr)
           .stroke({ width: sw, color: col });                       // cross
        } else if (p.status === "OCCLUDED") {
          g.circle(p.x, p.y, rr).stroke({ width: sw, color: col });  // open ring
        } else {
          g.circle(p.x, p.y, rr).fill({ color: col });               // filled dot (VISIBLE)
        }
        if (isSel) g.circle(p.x, p.y, rr + 1 / this.scale).stroke({ width: 1 / this.scale, color: item.color });
      });
    }
  }
}
