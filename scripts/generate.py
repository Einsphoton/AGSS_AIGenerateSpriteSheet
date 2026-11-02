"""Generate one animation in every requested view, from a description.

This is the orchestration layer: it builds the four prompts, submits them to
ComfyUI with the *same* seed and length (that is what makes the views line up
later), waits, and drops renumbered frames plus a manifest into the project.

    # four views of a walk, 56 frames, one seed
    python generate.py --views views/ --out frames/walk --action walk \
        --subject "a chibi knight with a red plume" --frames 56

    # side view only, custom action
    python generate.py --views views/ --out frames/slash --action custom \
        --describe "a fast horizontal slash from right to left, the torso \
rotating into it, then a short recovery" --views-wanted right

    # is the server there at all?
    python generate.py --health

The clips themselves do not stay in the frame folders. Each batch of views gets
one version number and its mp4s are moved to ``<project>/videos/`` as
``<action>_v<NN>_<view>.mp4`` (see videos.py). That folder is the thing you hand
to the studio with ``?videos=`` — "load the clip" and "load the frames" are
different entry points, and only one of them is easy to find again.

Design note: all four views are submitted in ONE batch with the same seed.
Sequential single-view runs drift apart because H3 picks its own tempo each
time; sharing the seed and the beat wording is the only thing that keeps the
stride counts close (measured: 33% spread with mixed seeds, 9% with shared).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h3client as h3
import make_prompt as mp
import videos as vv


def view_image(views_dir: str, view: str) -> str | None:
    """Find the reference PNG for a view. 'left' is allowed to fall back to
    'right' — they are mirror images and generating both is wasted compute."""
    for name in (view, "right" if view == "left" else view):
        p = os.path.join(views_dir, f"{name}.png")
        if os.path.exists(p):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", help="folder with front.png/back.png/right.png")
    ap.add_argument("--out", required=False, help="output folder for frames")
    ap.add_argument("--views-wanted", default="front,back,right",
                    help="which views to render (default front,back,right; "
                         "left is mirrored from right by mirror.py)")
    ap.add_argument("--action", default="walk")
    ap.add_argument("--subject", default="")
    ap.add_argument("--subject-file")
    ap.add_argument("--describe", help="custom beat text")
    ap.add_argument("--extra", help="extra sentence appended to every prompt")
    ap.add_argument("--limits", help="comma list of parts allowed to move")
    ap.add_argument("--frames", type=int, default=56)
    ap.add_argument("--size", type=int, default=768)
    ap.add_argument("--seed", type=int, default=808080)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--no-turbo", action="store_true")
    ap.add_argument("--server", default=h3.DEFAULT_SERVER)
    ap.add_argument("--videos", help="folder for the versioned source clips "
                                    "(default: <project>/videos, i.e. sibling of "
                                    "the folder holding --out)")
    ap.add_argument("--no-archive", action="store_true",
                    help="leave the mp4s next to the frames instead of videos/")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--dry", action="store_true", help="write prompts, do not submit")
    ap.add_argument("--timeout", type=float, default=3600)
    args = ap.parse_args()

    if args.health:
        st = h3.health(args.server)
        print(json.dumps(st, indent=1, ensure_ascii=False))
        return 0 if st.get("ok") else 1

    if not args.views or not args.out:
        ap.error("--views and --out are required")

    subject = args.subject
    if args.subject_file:
        with open(args.subject_file, encoding="utf-8") as f:
            subject = f.read().strip()
    if not subject:
        subject = "the character shown in the reference"

    frames = h3.snap_length(args.frames)
    if frames != args.frames:
        print(f"note: H3 needs length % 17 == 5, snapped {args.frames} -> {frames}")
    seconds = frames / 24.0

    wanted = [v.strip() for v in args.views_wanted.split(",") if v.strip()]
    os.makedirs(args.out, exist_ok=True)

    jobs = []
    for v in wanted:
        img = view_image(args.views, v)
        if not img:
            print(f"skip {v}: no reference png in {args.views}")
            continue
        prompt = mp.build_prompt(
            v, args.action, subject, seconds,
            describe=args.describe,
            limits=[s.strip() for s in args.limits.split(",")] if args.limits else None,
            extra=args.extra,
        )
        pfile = os.path.join(args.out, f"prompt_{v}.txt")
        with open(pfile, "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
        jobs.append((v, img, prompt))
        print(f"prompt {v:6s} {len(prompt):5d} chars -> {pfile}")

    if not jobs:
        raise SystemExit("nothing to render")
    if args.dry:
        print("\n--dry: prompts written, nothing submitted")
        return 0

    # stage all references first, then submit, then wait — one batch, one seed
    staged, ids = [], []
    for v, img, prompt in jobs:
        name = h3.stage(img, args.server, name=f"ref_{v}.png")
        graph = h3.build(
            prompt, name, width=args.size, height=args.size, length=frames,
            seed=args.seed, steps=args.steps, turbo=not args.no_turbo,
            filename_prefix=f"sprite/{os.path.basename(args.out)}_{v}",
        )
        pid = h3.submit(graph, args.server)
        ids.append((v, pid))
        staged.append((v, img))
        print(f"queued {v:6s} {pid}   seed {args.seed}  frames {frames}")

    manifest = {"action": args.action, "frames": frames, "seed": args.seed,
                "size": args.size, "views": {}, "prompts": {}, "videos": {}}
    vdir = None if args.no_archive else vv.videos_dir(args.out, args.videos)
    version = vv.next_version(vdir) if vdir else None
    clips: dict[str, str] = {}
    rc = 0
    for v, pid in ids:
        print(f"\n-- waiting {v} ({pid})", flush=True)
        try:
            entry = h3.wait(pid, args.server, timeout=args.timeout)
        except SystemExit as e:
            print(f"{v}: {e}")
            rc = 1
            continue
        status = (entry.get("status") or {}).get("status_str", "?")
        d = os.path.join(args.out, v)
        n, video = h3.collect(entry, d, args.server, stem="frame")
        manifest["views"][v] = {"status": status, "count": n,
                                "dir": os.path.relpath(d, args.out),
                                "video": os.path.basename(video) if video else None}
        manifest["prompts"][v] = os.path.basename(os.path.join(args.out, f"prompt_{v}.txt"))
        if video:
            clips[v] = video
        print(f"{v:6s} {status}  frames={n}  -> {d}")
        if not n:
            rc = 1

    if vdir and clips:
        entry = vv.archive(vdir, args.action, version, clips,
                           {"frames": frames, "seed": args.seed, "size": args.size,
                            "views": sorted(clips),
                            "frames_dir": os.path.relpath(os.path.abspath(args.out),
                                                          os.path.dirname(vdir))})
        manifest["videos"] = {"dir": os.path.relpath(vdir, os.path.dirname(vdir)),
                              "version": version, "files": entry["files"],
                              "index": os.path.basename(entry["_index"])}
        print(f"\nvideo  : {vdir}")
        for k, name in entry["files"].items():
            print(f"  v{version:02d} {k:6s} {name}")
        print("         (Sprite Sheet Studio: ?videos=/videos, then pick the version)")

    mf = os.path.join(args.out, "manifest.json")
    with open(mf, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print(f"\nmanifest -> {mf}")
    print("next: mirror the side view, then open the studio on this folder")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())