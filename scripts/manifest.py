"""Write a manifest.json next to a folder of frames.

The studio reads `manifest.json` to know the frame order, so this is what
bridges "a folder of PNGs" and "a loadable sequence". It also renumbers files
if H3's SaveImage counter left you with 057..112.

    python manifest.py frames/walk/right
    python manifest.py frames/walk --dirs right,left --out frames/walk/manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil


IMG = (".png", ".jpg", ".jpeg", ".webp")


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def renumber(folder: str, stem: str | None = None) -> list[str]:
    """Rename frames to <stem>_001.._NNN if they are not already 1..N."""
    files = sorted((f for f in os.listdir(folder) if f.lower().endswith(IMG)), key=natural_key)
    if not files:
        return []
    if not stem:
        stem = re.sub(r"[_-]?\d+$", "", os.path.splitext(files[0])[0]) or "frame"

    want = [f"{stem}_{i:03d}.png" for i in range(1, len(files) + 1)]
    if files == want:
        return files

    tmp = os.path.join(folder, "_renumber_tmp")
    os.makedirs(tmp, exist_ok=True)
    for i, f in enumerate(files, 1):
        shutil.move(os.path.join(folder, f), os.path.join(tmp, f"{stem}_{i:03d}.png"))
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and f.lower().endswith(IMG):
            os.remove(p)
    for f in os.listdir(tmp):
        shutil.move(os.path.join(tmp, f), os.path.join(folder, f))
    os.rmdir(tmp)
    print(f"renumbered {len(files)} frames in {folder} -> {stem}_001.._{len(files):03d}.png")
    return want


def write_manifest(folder: str, out: str | None = None) -> str:
    frames = renumber(folder)
    if not frames:
        raise SystemExit(f"no images in {folder}")
    mm = {"dir": os.path.basename(os.path.normpath(folder)),
          "count": len(frames), "frames": frames}
    out = out or os.path.join(folder, "manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(mm, f, indent=1, ensure_ascii=False)
    print(f"{out}  {len(frames)} frames")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--dirs", help="comma list of subfolders (one per view)")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.dirs:
        report = {}
        for d in [x.strip() for x in args.dirs.split(",") if x.strip()]:
            sub = os.path.join(args.folder, d)
            if not os.path.isdir(sub):
                print(f"skip {d}: not a folder")
                continue
            write_manifest(sub)
            report[d] = sum(1 for f in os.listdir(sub) if f.lower().endswith(IMG))
        out = args.out or os.path.join(args.folder, "views.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
        print(f"{out}  -> {report}")
    else:
        write_manifest(args.folder, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())