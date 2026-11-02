"""Bake an exported sprite sheet into preview GIFs.

The studio exports PNG + atlas JSON; this turns them into animated GIFs you can
send to someone without a server. Re-run it after every re-export — the GIF is a
static artifact and will otherwise lag behind the sheet.

    python bake_gifs.py sheet.png
    python bake_gifs.py sheet.png --atlas sheet.json --fps 12 --out demo/
"""

from __future__ import annotations

import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

BG = (13, 17, 23, 255)
INK = (140, 152, 170, 255)
RULE = (32, 40, 52, 255)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

CN = {"front": "前", "back": "后", "left": "左", "right": "右"}


def font(size: int):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def read_atlas(sheet: str, atlas: str | None) -> dict:
    if atlas is None:
        cand = os.path.splitext(sheet)[0] + "_atlas.json"
        atlas = cand if os.path.exists(cand) else None
    if atlas and os.path.exists(atlas):
        with open(atlas, encoding="utf-8") as f:
            meta = json.load(f)["meta"]
        return {
            "cw": meta["cellWidth"], "ch": meta["cellHeight"],
            "n": meta["columns"], "rows": meta["rows"],
            "dirs": meta.get("directions") or ["front", "back", "left", "right"],
        }
    im = Image.open(sheet)
    n = 12 if im.width % 12 == 0 else 8
    return {"cw": im.width // n, "ch": im.height // 4, "n": n, "rows": 4,
            "dirs": ["front", "back", "left", "right"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--atlas")
    ap.add_argument("--out", default=".")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--scale", type=float, default=0.75, help="strip GIF scale")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sheet = Image.open(args.sheet).convert("RGBA")
    m = read_atlas(args.sheet, args.atlas)
    CW, CH, N, ROWS = m["cw"], m["ch"], m["n"], m["rows"]
    dur = max(20, round(1000 / max(1, args.fps)))
    stem = os.path.splitext(os.path.basename(args.sheet))[0]

    def cell(i: int, r: int) -> Image.Image:
        return sheet.crop((i * CW, r * CH, (i + 1) * CW, (r + 1) * CH))

    # ---- all views in one strip ----
    cw, ch = int(CW * args.scale), int(CH * args.scale)
    band = 26
    f = font(14)
    frames = []
    for i in range(N):
        img = Image.new("RGBA", (cw * ROWS, ch + band), BG)
        for r in range(ROWS):
            c = cell(i, r).resize((cw, ch), Image.NEAREST)
            img.paste(c, (r * cw, band), c)
        d = ImageDraw.Draw(img)
        for r in range(ROWS):
            tag = m["dirs"][r] if r < len(m["dirs"]) else str(r)
            d.text((r * cw + 10, 5), f"{CN.get(tag, tag)} {tag.upper()}", font=f, fill=INK)
            if r:
                d.line([(r * cw, 4), (r * cw, ch + band - 4)], fill=RULE)
        d.line([(0, band - 1), (cw * ROWS, band - 1)], fill=RULE)
        frames.append(img)

    out = os.path.join(args.out, f"{stem}_strip.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=dur, loop=0, disposal=2, optimize=True)
    print(f"{out}  {frames[0].size[0]}x{frames[0].size[1]}  {N}f  "
          f"{os.path.getsize(out) // 1024}KB")

    # ---- one GIF per view ----
    for r in range(ROWS):
        name = m["dirs"][r] if r < len(m["dirs"]) else f"row{r}"
        fr = [cell(i, r) for i in range(N)]
        out = os.path.join(args.out, f"{stem}_{name}.gif")
        fr[0].save(out, save_all=True, append_images=fr[1:],
                   duration=dur, loop=0, disposal=2, optimize=True)
        print(f"{out}  {fr[0].size[0]}x{fr[0].size[1]}  {N}f  "
              f"{os.path.getsize(out) // 1024}KB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())