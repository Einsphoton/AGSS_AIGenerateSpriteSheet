"""Split a character reference sheet into per-view PNGs.

Handles the two layouts people actually have:

  * **grid**   — 4 isolated figures on a plain background, one per cell
                 (2x2 strip, 1x4 row, 4x1 column)
  * **single** — one figure per file already (you pass them separately)

The point is not to be clever about art direction; it is to get four clean
PNGs with *the same* transparent bounds so the downstream chroma-key / sizing
steps have something predictable to work with.

Auto-detection is on connected components of "not background". Background is
whatever colour the corners are. If auto-detect gets it wrong, pass --boxes
explicitly:

    python split_views.py sheet.png --out views/
    python split_views.py sheet.png --out views/ --auto-threshold 0.02
    python split_views.py sheet.png --out views/ --boxes 0,0,256,300 256,0,512,300 ...

Output names come from --names (default front,back,left,right) in left-to-right,
top-to-bottom order of the detected boxes.
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage


# --------------------------------------------------------------------------

def bg_colour(im: Image.Image) -> np.ndarray:
    """Most common corner colour — good enough for a flat backdrop."""
    a = np.asarray(im.convert("RGB"))
    h, w = a.shape[:2]
    k = max(2, min(h, w) // 40)
    corners = np.concatenate([
        a[:k, :k].reshape(-1, 3), a[:k, -k:].reshape(-1, 3),
        a[-k:, :k].reshape(-1, 3), a[-k:, -k:].reshape(-1, 3),
    ])
    # median is robust against one dirty corner
    return np.median(corners, axis=0)


def fg_mask(im: Image.Image, tol: int = 28) -> np.ndarray:
    a = np.asarray(im.convert("RGB")).astype(int)
    bg = bg_colour(im)
    return (np.abs(a - bg).sum(2) > tol * 3)


def find_boxes(im: Image.Image, tol: int = 28, min_area_frac: float = 0.004,
               merge: int = 9) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of the separate figures, reading order."""
    m = fg_mask(im, tol)
    H, W = m.shape
    min_area = max(64, int(min_area_frac * H * W))

    # close small gaps so one figure doesn't split into head/body/sword
    m2 = ndimage.binary_closing(m, np.ones((merge, merge)))
    lab, n = ndimage.label(m2, np.ones((3, 3)))

    boxes = []
    for k in range(1, n + 1):
        sel = lab == k
        if int(sel.sum()) < min_area:
            continue
        ys, xs = np.nonzero(sel)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))

    # reading order: group into rows by y-centre, then left-to-right
    if not boxes:
        return []
    boxes.sort(key=lambda b: (b[1] + b[3]) / 2)
    row_h = np.median([b[3] - b[1] for b in boxes])
    rows: list[list[tuple[int, int, int, int]]] = []
    for b in boxes:
        cy = (b[1] + b[3]) / 2
        if rows and abs(((rows[-1][0][1] + rows[-1][0][3]) / 2) - cy) < row_h * 0.6:
            rows[-1].append(b)
        else:
            rows.append([b])
    ordered = []
    for r in rows:
        r.sort(key=lambda b: b[0])
        ordered.extend(r)
    return ordered


def key_background(im: Image.Image, crop: tuple[int, int, int, int],
                   tol: int = 28, pad: int = 4) -> Image.Image:
    """Crop one figure and make the backdrop transparent."""
    a = np.asarray(im.convert("RGB")).astype(int)
    bg = bg_colour(im)
    x0, y0, x1, y1 = crop
    sub = a[y0:y1, x0:x1]
    alpha = (np.abs(sub - bg).sum(2) > tol * 3).astype(np.uint8) * 255
    rgba = np.dstack([sub, alpha]).astype(np.uint8)
    out = Image.fromarray(rgba, "RGBA")

    bb = out.getbbox()
    if bb:
        out = out.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(out.width, bb[2] + pad), min(out.height, bb[3] + pad)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--out", default="views")
    ap.add_argument("--names", default="front,back,left,right")
    ap.add_argument("--tol", type=int, default=28, help="background tolerance")
    ap.add_argument("--min-area", type=float, default=0.004,
                    help="ignore blobs smaller than this fraction of the image")
    ap.add_argument("--merge", type=int, default=9,
                    help="close gaps up to this many px when grouping one figure")
    ap.add_argument("--boxes", nargs="+", default=None,
                    help="explicit boxes as x0,y0,x1,y1 (skips detection)")
    ap.add_argument("--keep-bg", action="store_true",
                    help="keep the opaque backdrop (needed by chroma-key H3)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    im = Image.open(args.sheet).convert("RGB")
    names = [n.strip() for n in args.names.split(",") if n.strip()]

    if args.boxes:
        boxes = [tuple(int(v) for v in b.split(",")) for b in args.boxes]
    else:
        boxes = find_boxes(im, args.tol, args.min_area, args.merge)

    if not boxes:
        raise SystemExit("no figures found — try a lower --tol or pass --boxes")
    if len(boxes) != len(names):
        print(f"warning: found {len(boxes)} figures but got {len(names)} names; "
              f"using {min(len(boxes), len(names))}")

    report = []
    for name, box in zip(names, boxes):
        if args.keep_bg:
            out = im.crop(box)
        else:
            out = key_background(im, box, args.tol)
        path = os.path.join(args.out, f"{name}.png")
        out.save(path)
        report.append({"name": name, "path": path, "box": list(box),
                       "size": list(out.size)})
        print(f"{name:8s} box={box}  -> {out.size[0]}x{out.size[1]}  {path}")

    with open(os.path.join(args.out, "views.json"), "w", encoding="utf-8") as f:
        json.dump({"source": args.sheet, "views": report}, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())