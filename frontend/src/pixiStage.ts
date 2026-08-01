// Imperative PixiJS (v8) stage. React owns annotation state; this renders it and reports
// pointer events back in *video-pixel* coordinates. A single `world` container holds the
// frame sprite and the overlay, scaled to fit — so all keypoint coords are video pixels.

import { Application, Container, type FederatedPointerEvent, Graphics, Sprite, Texture } from "pixi.js";
import type { EditPoint } from "./types";

export interface RenderItem {
  points: EditPoint[];
  edges: [number, number][];
  color: number;
  active: boolean;
}

export interface PointerInfo {
  x: number; // video pixel coords
  y: number;
  hit: number | null; // index of active-item point under cursor, if any
}

type PointerCb = (p: PointerInfo) => void;

const VIS_ALPHA = { visible: 1, occluded: 0.45, "out-of-frame": 0.2 } as const;
const HIT_RADIUS_SCREEN = 10;

export class PixiStage {
  readonly app = new Application();
  private world = new Container();
  private sprite = new Sprite();
  private overlay = new Graphics();
  private videoW = 1;
  private videoH = 1;
  private activePoints: EditPoint[] = [];
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
    this.world.addChild(this.sprite, this.overlay);
    this.app.stage.addChild(this.world);

    this.app.stage.eventMode = "static";
    this.app.stage.hitArea = this.app.screen;
    const at = (e: FederatedPointerEvent) => this.info(e.global);
    this.app.stage.on("pointerdown", (e) => this.onPointerDown(at(e)));
    this.app.stage.on("pointermove", (e) => this.onPointerMove(at(e)));
    this.app.stage.on("pointerup", (e) => this.onPointerUp(at(e)));
    this.app.stage.on("pointerupoutside", (e) => this.onPointerUp(at(e)));

    this.ro = new ResizeObserver(() => this.fit());
    this.ro.observe(parent);
  }

  destroy(): void {
    this.killed = true;
    if (!this.inited) return; // init hasn't resolved; init() will bail on `killed`
    this.ro?.disconnect();
    this.app.destroy(true, { children: true, texture: true });
  }

  setFrame(bitmap: ImageBitmap): void {
    const old = this.sprite.texture;
    this.videoW = bitmap.width;
    this.videoH = bitmap.height;
    this.sprite.texture = Texture.from(bitmap);
    if (old && old !== Texture.EMPTY) old.destroy(true);
    this.fit();
  }

  private fit(): void {
    const { width, height } = this.app.screen;
    const scale = Math.min(width / this.videoW, height / this.videoH) || 1;
    this.world.scale.set(scale);
    this.world.position.set(
      (width - this.videoW * scale) / 2,
      (height - this.videoH * scale) / 2,
    );
  }

  private info(global: { x: number; y: number }): PointerInfo {
    const local = this.world.toLocal(global);
    const r = HIT_RADIUS_SCREEN / (this.world.scale.x || 1);
    let hit: number | null = null;
    let best = r * r;
    this.activePoints.forEach((p, i) => {
      const d = (p.x - local.x) ** 2 + (p.y - local.y) ** 2;
      if (d <= best) {
        best = d;
        hit = i;
      }
    });
    return { x: local.x, y: local.y, hit };
  }

  render(items: RenderItem[], selected: number | null): void {
    const active = items.find((it) => it.active);
    this.activePoints = active?.points ?? [];
    const g = this.overlay;
    g.clear();

    for (const item of items) {
      const r = item.active ? 5 : 3.5;
      for (const [a, b] of item.edges) {
        const pa = item.points[a];
        const pb = item.points[b];
        if (!pa || !pb) continue;
        g.moveTo(pa.x, pa.y).lineTo(pb.x, pb.y);
      }
      g.stroke({ width: item.active ? 2.5 : 1.5, color: item.color, alpha: item.active ? 0.9 : 0.5 });

      item.points.forEach((p, i) => {
        const isSel = item.active && i === selected;
        g.circle(p.x, p.y, isSel ? r + 2 : r);
        g.fill({ color: isSel ? 0xffffff : item.color, alpha: VIS_ALPHA[p.vis] });
        if (isSel) g.circle(p.x, p.y, r + 2).stroke({ width: 2, color: item.color });
      });
    }
  }
}
