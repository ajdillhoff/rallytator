// Bidirectional frame cache. Holds compressed JPEG blobs in an LRU window around the play
// head (ahead *and* behind, since annotators step both directions) and decodes a fresh
// ImageBitmap on demand — decode is ~1-2 ms, so a cached blob makes stepping either way
// feel instant, while caching blobs (not decoded bitmaps) keeps memory ~80x smaller and
// sidesteps ImageBitmap/Pixi-texture lifetime coupling. Backs both stepping and playback.

export class FrameCache {
  private blobs = new Map<number, Blob>();            // insertion order = LRU order
  private inflight = new Map<number, Promise<Blob>>();

  constructor(private cap = 400) {}

  private touch(i: number): void {
    const b = this.blobs.get(i)!;
    this.blobs.delete(i);
    this.blobs.set(i, b);
  }

  private fetchBlob(i: number): Promise<Blob> {
    const cached = this.blobs.get(i);
    if (cached) { this.touch(i); return Promise.resolve(cached); }
    let p = this.inflight.get(i);
    if (!p) {
      p = fetch(`/frame/${i}`).then((r) => {
        if (!r.ok) throw new Error(`frame ${i}: ${r.status}`);
        return r.blob();
      });
      this.inflight.set(i, p);
      p.then((b) => { this.inflight.delete(i); this.blobs.set(i, b); this.evict(); })
       .catch(() => this.inflight.delete(i));
    }
    return p;
  }

  /** Decoded bitmap for frame `i` (fetches + caches the blob first if needed). */
  async get(i: number): Promise<ImageBitmap> {
    return createImageBitmap(await this.fetchBlob(i));
  }

  /** True if the blob is already resident (decode would be instant — no network). */
  hasBlob(i: number): boolean {
    return this.blobs.has(i);
  }

  /** Warm the window [center-behind, center+ahead] (forward-biased for playback). */
  prefetch(center: number, ahead: number, behind: number, max: number): void {
    for (let i = center - behind; i <= center + ahead; i++) {
      if (i < 0 || i > max || this.blobs.has(i) || this.inflight.has(i)) continue;
      void this.fetchBlob(i).catch(() => {});
    }
  }

  private evict(): void {
    while (this.blobs.size > this.cap) {
      const oldest = this.blobs.keys().next().value as number;
      this.blobs.delete(oldest);
    }
  }
}
