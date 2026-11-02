"""Mirror a frame sequence horizontally — how you get the 'left' view for free.

Render only the right-facing profile, then mirror it. The two directions then
share *every* pixel of jitter, so they can never desync. Generating both sides
independently costs a full render and still leaves a 1-frame phase difference.

    python mirror.py frames/walk/right frames/walk/left
    python mirror.py in/ out/ --suffix .png
"""

from __future__ import annotations

import argparse
import os

from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--suffix", default=".png")
    ap.add_argument("--ext", default=".png", help="output extension")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.src) if f.lower().endswith(args.suffix))
    if not files:
        raise SystemExit(f"no *{args.suffix} in {args.src}")
    os.makedirs(args.dst, exist_ok=True)

    for f in files:
        im = Image.open(os.path.join(args.src, f)).transpose(Image.FLIP_LEFT_RIGHT)
        stem = os.path.splitext(f)[0]
        im.save(os.path.join(args.dst, stem + args.ext))

    print(f"{args.src} -> {args.dst}  {len(files)} frames mirrored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())