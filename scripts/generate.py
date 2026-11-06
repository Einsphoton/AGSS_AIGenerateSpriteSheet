"""Generate one animation in every requested view, from a description.

This is the orchestration layer: it prepares the reference images, builds the
prompts, submits them to ComfyUI with the *same* seed and length (that is what
makes the views line up later), waits, checks the frames, and drops renumbered
frames plus a manifest into the project.

    # four views of a walk, 56 frames, one seed
    python generate.py --views views/ --out frames/walk --action walk \
        --subject "a chibi knight with a red plume" --frames 56

    # side view only, custom action, beats kept in a file
    python generate.py --views views/ --out frames/slash --action attack \
        --describe-file beats/slash.txt --views-wanted right

    # is the server there at all?
    python generate.py --health

Three things happen before anything is submitted, because all three cost a full
render when skipped:

* **The key colour is chosen from the reference**, not from a habit. A green
  armoured character shot against chroma green loses its armour to the key.
* **The reference is padded onto a square key-coloured canvas** (prep_ref.py).
  H3 inherits the reference's framing, so a reference that fills the canvas
  produces a clip where the sword leaves the frame and comes back as a stump.
  The same step removes the transparent-PNG "black first frame".
* **The actual bytes sent are written to `<out>/_ref/`** and printed, so "which
  image did it use?" never has to be answered by inference later.

The clips themselves do not stay in the frame folders. Each batch of views gets
one version number and its mp4s are moved to ``<project>/videos/`` as
``<action>_v<NN>_<view>.mp4`` (see videos.py).

Design note: all four views are submitted in ONE batch with the same seed.
Sequential single-view runs drift apart because H3 picks its own tempo each
time; sharing the seed and the beat wording is the only thing that keeps the
stride counts close (measured: 33% spread with mixed seeds, 9% with shared).
For a two-pass (mannequin → character) run, the seed and the beat text must be
identical in both passes for the same reason — see references/proxy-pass.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h3client as h3
import make_prompt as mp
import prep_ref as pr
import videos as vv

KEY_WORDS = {"green": "chroma green", "magenta": "magenta", "cyan": "cyan"}


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
    ap.add_argument("--describe-file", help="read the beat text from a file — "
                                          "same file in both passes of a proxy run")
    ap.add_argument("--extra", help="extra sentence appended to every prompt")
    ap.add_argument("--limits", help="comma list of parts allowed to move")
    ap.add_argument("--frames", type=int, default=56)
    ap.add_argument("--size", type=int, default=768)
    ap.add_argument("--seed", type=int, default=808080)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--key", default=os.environ.get("SPRITE_KEY_HEX", "auto"),
                    help="auto (default) | green | magenta | cyan | #RRGGBB")
    ap.add_argument("--coverage", default="auto",
                    help="figure size on the square reference canvas "
                         "(auto: 0.48 for attack/cast/throw, 0.58 otherwise)")
    ap.add_argument("--no-prep", action="store_true",
                    help="send the reference as-is (no padding, no key composite)")
    ap.add_argument("--staged-dir", help="where to write the prepared references "
                                        "(default <out>/_ref)")
    ap.add_argument("--no-qc", action="store_true", help="skip the frame check")
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

    describe = args.describe
    if args.describe_file:
        with open(args.describe_file, encoding="utf-8") as f:
            describe = f.read().strip()

    frames = h3.snap_length(args.frames)
    if frames != args.frames:
        print(f"note: H3 needs length % 17 == 5, snapped {args.frames} -> {frames}")
    seconds = frames / 24.0

    wanted = [v.strip() for v in args.views_wanted.split(",") if v.strip()]
    os.makedirs(args.out, exist_ok=True)

    sources: dict[str, str] = {}
    for v in wanted:
        img = view_image(args.views, v)
        if not img:
            print(f"skip {v}: no reference png in {args.views}")
            continue
        sources[v] = img
    if not sources:
        raise SystemExit("nothing to render")

    # ---- key colour: chosen from the reference, not from a habit -----------
    key = pr.choose_key(list(sources.values()),
                        None if str(args.key).lower() == "auto" else args.key)
    key_rgb = tuple(key["chosen"]["rgb"])
    key_hex = key["chosen"]["hex"]
    key_name = KEY_WORDS.get(key["chosen"]["name"], key["chosen"]["name"])
    print(f"key      {key_name} {key_hex}   "
          f"({key['chosen']['clash'] * 100:.2f}% of the character matches it)")
    if key["warn"]:
        print(f"WARN     {key['warn']}")

    # ---- framing: pad so a sword cannot leave the frame --------------------
    cov = args.coverage
    if cov == "auto":
        cov = pr.COVERAGE_ARC if args.action.lower() in pr.ARC_ACTIONS else pr.COVERAGE_DEFAULT
    else:
        cov = float(cov)

    staged_dir = args.staged_dir or os.path.join(args.out, "_ref")
    if args.no_prep:
        refs = dict(sources)
        print(f"prep     skipped (--no-prep) — H3 receives the reference as-is; "
              f"a figure touching the canvas edge will be cropped in the clip")
    else:
        res = pr.prep_set(sources, staged_dir, key_rgb, cov)
        refs = {v: i["staged"] for v, i in res["views"].items() if i.get("staged")}
        print(f"prep     {res['side']}x{res['side']} canvas, figure at "
              f"{cov * 100:.0f}%, margins ≈{(1 - cov) * 50:.0f}% per side -> {staged_dir}")
        for v, i in res["views"].items():
            if i.get("staged"):
                print(f"         {v:6s} {i['w']}x{i['h']}  "
                      f"margin {i['staged_margin_px']} px")
        if res["warning"]:
            print(f"         note: {res['warning']}")

    # ---- prompts ----------------------------------------------------------
    jobs = []
    for v in sources:
        prompt = mp.build_prompt(
            v, args.action, subject, seconds,
            describe=describe,
            limits=[s.strip() for s in args.limits.split(",")] if args.limits else None,
            extra=args.extra, key_name=key_name, key_hex=key_hex, coverage=cov,
        )
        pfile = os.path.join(args.out, f"prompt_{v}.txt")
        with open(pfile, "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
        jobs.append((v, refs[v], prompt))
        print(f"prompt {v:6s} {len(prompt):5d} chars -> {pfile}")

    if args.dry:
        print("\n--dry: prompts and references written, nothing submitted")
        return 0

    # stage all references first, then submit, then wait — one batch, one seed
    ids = []
    for v, img, prompt in jobs:
        pid_name = h3.stage(img, args.server, name=f"ref_{v}.png")
        graph = h3.build(
            prompt, pid_name, width=args.size, height=args.size, length=frames,
            seed=args.seed, steps=args.steps, turbo=not args.no_turbo,
            filename_prefix=f"sprite/{os.path.basename(args.out)}_{v}",
        )
        pid = h3.submit(graph, args.server)
        ids.append((v, pid))
        print(f"queued {v:6s} {pid}   seed {args.seed}  frames {frames}  "
              f"ref {pid_name}")
    print("         (the reference each job reads is printed above — if the "
          "frames show the wrong character, compare that file first)")

    manifest = {"action": args.action, "frames": frames, "seed": args.seed,
                "size": args.size, "key": key_hex, "coverage": cov,
                "views": {}, "prompts": {}, "videos": {}}
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

    # ---- gate: look before picking ---------------------------------------
    if not args.no_qc:
        import qc
        print("\n== frame check ==")
        try:
            _, hard, _notes = qc.report_frames(args.out, key_rgb,
                                               sorted(clips) or wanted)
        except SystemExit as e:
            print(f"  skipped: {e}")
            hard = []
        if hard:
            print("\n  Fix before picking frames:")
            for h in hard:
                print(f"  - {h}")
            print("  Clipping: re-run with a smaller --coverage (0.42). H3 "
                  "inherits the reference framing — it does not invent margin.")
            print("  A re-render is 2–4 min per view; picking around a broken "
                  "clip costs an hour.")
        else:
            print("  clean: nothing clipped, no empty or black frames, "
                  "backdrop is one flat colour")

    print("\nnext: put the clips on screen, then mirror the side view "
          "(mirror.py), then open the studio — the user picks the frames, "
          "not this script.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
