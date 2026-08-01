"""Binary-mask codec + PNG rendering for the Mask store (docs/data-model.md).

The stored blob is COCO-*uncompressed* RLE: alternating run lengths of 0s and 1s in
column-major (Fortran) order, serialized as compact JSON `{"size":[h,w],"counts":[...]}`.
This is dependency-free (no pycocotools) and round-trips a numpy boolean mask exactly.

`mask_png` renders a mask to a white RGBA PNG whose alpha *is* the mask, so the frontend
can tint it per-track (Pixi `tint`) without re-encoding.
"""

from __future__ import annotations

import io
import json

import numpy as np
from PIL import Image


def rle_encode(mask: np.ndarray) -> bytes:
    """(H, W) bool/0-1 array -> JSON RLE blob (column-major run lengths)."""
    h, w = mask.shape
    flat = np.asfortranarray(mask).astype(bool).ravel(order="F")
    # COCO convention: counts start with a 0-run. `prev` seeded False means a leading 1
    # emits counts[0]=0 automatically (the empty 0-run before it).
    counts: list[int] = []
    prev = False
    run = 0
    for v in flat:
        if bool(v) == prev:
            run += 1
        else:
            counts.append(run)
            prev = bool(v)
            run = 1
    counts.append(run)
    return json.dumps({"size": [h, w], "counts": counts}, separators=(",", ":")).encode()


def rle_decode(blob: bytes) -> np.ndarray:
    """JSON RLE blob -> (H, W) bool array."""
    obj = json.loads(blob)
    h, w = obj["size"]
    flat = np.zeros(h * w, dtype=bool)
    idx = 0
    val = False
    for run in obj["counts"]:
        if val and run:
            flat[idx:idx + run] = True
        idx += run
        val = not val
    return flat.reshape((h, w), order="F")


def mask_png(blob: bytes) -> bytes:
    """RLE blob -> white RGBA PNG with alpha = mask (for tinted overlay)."""
    m = rle_decode(blob)
    h, w = m.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = np.where(m, 255, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue()
