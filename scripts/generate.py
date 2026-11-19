"""Generate one animation in every requested view, from a description.

This is the orchestration layer: it prepares the reference images, builds the
prompts, submits them to ComfyUI with the *same* seed and length (that is what
makes the views line up later), waits, checks the frames, and drops renumbered
frames plus a manifest into the project.

    # four views of a walk, 56 frames, one seed
    python generate.py --views views/ --out frames/walk --action walk \\
        --subject "a chibi knight with a red plume" --frames 56

    # the normal path: every shared parameter comes from the storyboard
    python generate.py --views views/ --out frames/walk \\
        --storyboard beats/walk.storyboard.json

    # side view only, custom action, beats kept in a file
    python generate.py --views views/ --out frames/slash --action attack \\
        --describe-file beats/slash.txt --views-wanted right

    # is the server there at all?
    python generate.py --health

`--storyboard` is the recommended entry point: seed, frames, key, coverage,
limits, subject, views and the beats all come from that one file, so no flag can
drift between the front, back and side passes. Flags still win when passed
explicitly — that is for experiments, and the run prints which of the two a value
came from.

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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h3client as h3
import make_prompt as mp
import prep_ref as pr
import storyboard as sb
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


def parse_anchors(specs: list[str] | None, views: list[str]) -> dict[str, str]:
    """`--anchor back=the tall red cape and the silver clasp` — the visible
    evidence for one view, when the character's own markers are the thing that
    makes the facing unambiguous. A bare string applies to every rendered view
    when only one view is being rendered; otherwise it is ignored with a note,
    because the same sentence on a front and a back prompt is a contradiction."""
    out: dict[str, str] = {}
    if not specs:
        return out
    for spec in specs:
        if "=" in spec:
            v, text = spec.split("=", 1)
            v = v.strip().lower()
            if v in ("left", "right", "front", "back"):
                out[v] = text.strip()
                continue
        if len(views) == 1:
            out[views[0]] = spec.strip()
        else:
            print(f"note: --anchor '{spec[:40]}…' has no view prefix — pass "
                  f"--anchor back=… / --anchor front=…", file=sys.stderr)
    return out


def cross_view_notes(results: dict) -> tuple[list[str], list[str]]:
    """Do the directions agree that this is the same character at the same size?

    Rhythm cannot be measured from a still — that is the storyboard's job (same
    beats, same seed, same frames). What *can* be measured is the thing a
    drifting batch gets wrong first: each view ends up at a different scale,
    because H3 framed the figure differently per call. Then the sprite sheet
    pops when the character turns, and it looks like a design error rather than
    a pipeline one.

    Returns (fails, notes). A fail is a disagreement big enough that the frames
    cannot be packed at one cell size without rescaling.
    """
    fails: list[str] = []
    notes: list[str] = []
    rows = {v: r for v, r in (results or {}).items() if r and not r.get("error")}
    if len(rows) < 2:
        return fails, notes

    heights = {v: r["height_median"] for v, r in rows.items() if r.get("height_median")}
    counts = {v: r["frames"] for v, r in rows.items() if r.get("frames")}
    if heights:
        lo, hi = min(heights.values()), max(heights.values())
        spread = (hi - lo) / lo if lo else 0.0
        detail = "  ".join(f"{v} {h}px" for v, h in sorted(heights.items()))
        if spread > 0.18:
            fails.append(f"views disagree on the character's size by "
                         f"{spread * 100:.0f}% ({detail}) — the four directions "
                         f"cannot share one cell size; re-render, do not rescale")
        elif spread > 0.08:
            notes.append(f"view scale spread {spread * 100:.0f}% ({detail}) — "
                         f"small, but check the turn for a pop")
    if counts and len(set(counts.values())) > 1:
        notes.append("frame counts differ per view "
                     f"({', '.join(f'{v} {n}' for v, n in counts.items())}) — the "
                     f"views cannot share one timeline; one render was short")
    return fails, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", help="folder with front.png/back.png/right.png")
    ap.add_argument("--out", required=False, help="output folder for frames")
    ap.add_argument("--storyboard", help="beats/<action>.storyboard.json — the one "
                                        "file every view reads its beats, seed, "
                                        "frames, key, coverage and limits from")
    ap.add_argument("--views-wanted",
                    help="which views to render (default: the board's views, or "
                         "front,back,right; left is mirrored from right by mirror.py)")
    ap.add_argument("--action")
    ap.add_argument("--subject", default="")
    ap.add_argument("--subject-file")
    ap.add_argument("--describe", help="custom beat text")
    ap.add_argument("--describe-file", help="read the beat text from a file — "
                                          "same file in both passes of a proxy run")
    ap.add_argument("--extra", help="extra sentence appended to every prompt")
    ap.add_argument("--anchor", action="append",
                    help="view=text: what the camera can see in that view, in "
                         "plain nouns (default depends on the view). Repeat for "
                         "several views. See references/facing.md")
    ap.add_argument("--no-facing-check", action="store_true",
                    help="skip the front/back distinguishability audit")
    ap.add_argument("--limits", help="comma list of parts allowed to move")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--size", type=int, default=768)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--key", default=os.environ.get("SPRITE_KEY_HEX"),
                    help="auto (default) | green | magenta | cyan | #RRGGBB")
    ap.add_argument("--coverage",
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

    # ---- the storyboard, if there is one ----------------------------------
    # It is validated before anything is spent: a board with a beat at 2.9s in
    # a 2.3s clip, or with two actions in one beat, is a whole batch of renders
    # that cannot come out right.
    board = None
    if args.storyboard:
        board = sb.load(args.storyboard)
        err, warn = sb.check(board)
        for w in warn:
            print(f"board    warn  {w}")
        if err:
            print("board    FAIL")
            for e in err:
                print(f"         - {e}")
            raise SystemExit(f"fix {args.storyboard} first "
                             f"(python scripts/storyboard.py check {args.storyboard})")

    # ---- one value per question: flag > board > default --------------------
    # The precedence is printed below, because "why is this run using 73 frames"
    # is the question that costs fifteen minutes when the answer is a stale flag.
    def pick(flag, field, default):
        if flag not in (None, ""):
            return flag, "flag"
        if board is not None and board.get(field) not in (None, ""):
            return board[field], "board"
        return default, "default"

    action, action_src = pick(args.action, "action", "walk")
    frames_raw, frames_src = pick(args.frames, "frames", 56)
    seed, seed_src = pick(args.seed, "seed", 808080)
    key_req, key_src = pick(args.key, "key", "auto")
    cov_req, cov_src = pick(args.coverage, "coverage", "auto")

    subject = args.subject
    if args.subject_file:
        with open(args.subject_file, encoding="utf-8") as f:
            subject = f.read().strip()
    if not subject and board is not None:
        subject = board.get("subject") or ""
    if not subject:
        subject = "the character shown in the reference"

    describe = args.describe
    if args.describe_file:
        with open(args.describe_file, encoding="utf-8") as f:
            # Collapse the hard wraps. A beat file is wrapped for humans, but it
            # is pasted into a single-line prompt, and a raw newline there is a
            # segment break the encoder never asked for.
            describe = re.sub(r"\s+", " ", f.read()).strip()
    if board is not None and describe:
        print("note: --describe is ignored — the storyboard owns the beats. Edit "
              "the board instead, so every view keeps reading the same sentences.")
        describe = None

    limits = args.limits or (",".join(board.get("limits") or []) if board else None)

    frames = h3.snap_length(int(frames_raw))
    if frames != int(frames_raw):
        print(f"note: H3 needs length % 17 == 5, snapped {frames_raw} -> {frames}")
    seconds = frames / 24.0

    if args.views_wanted:
        wanted = [v.strip() for v in args.views_wanted.split(",") if v.strip()]
    elif board is not None:
        wanted = list(board["views"])
    else:
        wanted = ["front", "back", "right"]

    if board is not None:
        print(f"board    {args.storyboard}  {len(board['beats'])} beats  "
              f"{frames}f @ 24fps = {seconds:.2f}s")
        print(f"         action {action} ({action_src}) · seed {seed} ({seed_src}) · "
              f"frames {frames} ({frames_src})")
        print(f"         key {key_req} ({key_src}) · coverage {cov_req} ({cov_src})")
        print(f"         views {','.join(wanted)} · limits {limits or '—'} "
              f"· subject from {'flag' if args.subject else 'board'}")
        print("         (these are the same for every view — that is the point)")

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
                        None if str(key_req).lower() == "auto" else key_req)
    key_rgb = tuple(key["chosen"]["rgb"])
    key_hex = key["chosen"]["hex"]
    key_name = KEY_WORDS.get(key["chosen"]["name"], key["chosen"]["name"])
    print(f"key      {key_name} {key_hex}   "
          f"({key['chosen']['clash'] * 100:.2f}% of the character matches it)")
    if key["warn"]:
        print(f"WARN     {key['warn']}")

    # ---- facing: is the back view actually a back view? -------------------
    # Runs before anything is submitted, because a reference whose front and
    # back are the same picture costs a whole render per view to discover. See
    # references/facing.md — the fix is the reference, not the prompt.
    if not args.no_facing_check:
        pair = {v: os.path.join(args.views, f"{v}.png") for v in ("front", "back")}
        if all(os.path.exists(p) for p in pair.values()):
            try:
                import check_facing as cf
                aud = cf.audit(args.views)
                print(f"facing   {aud['verdict']}  material_tv {aud['score']:.2f}  "
                      f"(torso {aud['torso']['material_tv']:.2f}, "
                      f"head {aud['head']['material_tv']:.2f})")
                for n in aud["notes"]:
                    print(f"WARN     {n}")
            except SystemExit as e:
                print(f"facing   skipped: {e}")
        else:
            print("facing   skipped: needs both front.png and back.png")

    # ---- framing: pad so a sword cannot leave the frame --------------------
    cov = cov_req
    if str(cov) == "auto":
        cov = (pr.COVERAGE_ARC if str(action).lower() in pr.ARC_ACTIONS
               else pr.COVERAGE_DEFAULT)
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
    # Anchors come from the board first (per-view evidence is part of the
    # script), and a --anchor on the command line overrides that view.
    anchors = {}
    if board is not None:
        for v, spec in board["views"].items():
            if (spec or {}).get("anchor"):
                anchors[v] = spec["anchor"]
    anchors.update(parse_anchors(args.anchor, list(sources)))
    for v, text in anchors.items():
        print(f"anchor {v:6s} {text}")
    jobs = []
    for v in sources:
        prompt = mp.build_prompt(
            v, action, subject, seconds,
            describe=describe,
            limits=[s.strip() for s in limits.split(",")] if limits else None,
            extra=args.extra, key_name=key_name, key_hex=key_hex, coverage=cov,
            anchor=anchors.get(v), board=board,
        )
        pfile = os.path.join(args.out, f"prompt_{v}.txt")
        with open(pfile, "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
        jobs.append((v, refs[v], prompt))
        print(f"prompt {v:6s} {len(prompt):5d} chars -> {pfile}")

    # The exact board this run used, next to the frames: a render is only
    # reproducible if the beats that drove it travel with it.
    if board is not None:
        snap = {k: v for k, v in board.items() if not k.startswith("_")}
        snap["rendered_at"] = sb._now()
        snap["render"] = {"frames": frames, "seed": seed, "key": key_hex,
                          "coverage": cov, "size": args.size,
                          "views": sorted(sources), "limits": limits}
        with open(os.path.join(args.out, "storyboard.json"), "w",
                  encoding="utf-8") as f:
            json.dump(snap, f, indent=1, ensure_ascii=False)
        print(f"board    snapshot -> {os.path.join(args.out, 'storyboard.json')}")

    if args.dry:
        print("\n--dry: prompts and references written, nothing submitted")
        return 0

    # stage all references first, then submit, then wait — one batch, one seed
    ids = []
    for v, img, prompt in jobs:
        pid_name = h3.stage(img, args.server, name=f"ref_{v}.png")
        graph = h3.build(
            prompt, pid_name, width=args.size, height=args.size, length=frames,
            seed=seed, steps=args.steps, turbo=not args.no_turbo,
            filename_prefix=f"sprite/{os.path.basename(args.out)}_{v}",
        )
        pid = h3.submit(graph, args.server)
        ids.append((v, pid))
        print(f"queued {v:6s} {pid}   seed {seed}  frames {frames}  "
              f"ref {pid_name}")
    print("         (the reference each job reads is printed above — if the "
          "frames show the wrong character, compare that file first)")

    manifest = {"action": action, "frames": frames, "seed": seed,
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

    # What each view's clip ended up being called, for the record in the board:
    # the archived name (`walk_v01_front.mp4`) once videos/ has taken it, the raw
    # ComfyUI name only when archiving is off.
    archived: dict[str, str] = {v: os.path.basename(p) for v, p in clips.items()}
    if vdir and clips:
        entry = vv.archive(vdir, action, version, clips,
                           {"frames": frames, "seed": seed, "size": args.size,
                            "views": sorted(clips),
                            "frames_dir": os.path.relpath(os.path.abspath(args.out),
                                                          os.path.dirname(vdir))})
        archived = dict(entry["files"])
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
    verdict = "unknown"
    if not args.no_qc:
        import qc
        print("\n== frame check ==")
        notes: list[str] = []
        results: dict = {}
        try:
            results, hard, notes = qc.report_frames(args.out, key_rgb,
                                                    sorted(clips) or wanted)
        except SystemExit as e:
            print(f"  skipped: {e}")
            hard = []

        # The per-view gate above says whether each clip is usable. This one
        # says whether the set of clips is one character — the difference that
        # turns four renders into a sprite sheet.
        strip_fails, strip_notes = cross_view_notes(results)
        hard += strip_fails
        notes += strip_notes
        if strip_fails or strip_notes:
            print("\n== 方向一致性 / cross-view ==")
            for h in strip_fails:
                print(f"  FAIL  {h}")
            for n in strip_notes:
                print(f"  note  {n}")
        else:
            print("  cross-view: same scale in every direction")

        if hard:
            verdict = "fail"
            print("\n  Fix before picking frames:")
            for h in hard:
                print(f"  - {h}")
            print("  Clipping → re-run with a smaller --coverage (0.42) into a "
                  "fresh --out. H3 inherits the reference framing; it does not "
                  "invent margin.")
            print("  A re-render is 2–4 min per view; picking around a broken "
                  "clip costs an hour.")
        else:
            verdict = "warn" if notes else "pass"
            print("  clean: nothing clipped, no empty or black frames, "
                  "backdrop is one flat colour")

    # ---- fold the result back into the board ------------------------------
    # The board is the project record: which version came from which seed and
    # coverage, and what the gate said. A re-run is then a diff, not a memory
    # test — and it is the first thing to read when a direction looks off.
    if board is not None and version:
        sb.add_render(board, version, archived,
                      qc=verdict, coverage=round(cov, 3), key=key_hex, seed=seed,
                      note=f"frames_dir {os.path.relpath(os.path.abspath(args.out), os.getcwd())}")
        sb.save(board, args.storyboard)
        print(f"board    recorded v{version:02d} ({verdict}) -> {args.storyboard}")

    print("\nnext: put the clips on screen, then mirror the side view "
          "(mirror.py), then open the studio — the user picks the frames, "
          "not this script.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
