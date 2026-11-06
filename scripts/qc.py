"""Quality gate: look at the pixels before spending an hour picking frames.

Two modes, used at two different moments:

    # before a render — is the reference framed loosely enough, and does the
    # key colour already exist in the costume?
    python qc.py views views/

    # after a render — did the sword leave the frame, did the body zoom, did a
    # black frame sneak in, is the backdrop actually one flat colour?
    python qc.py frames frames/slash --key '#FF00FF' --action attack

Exit code 1 means "do not pick frames yet": at least one hard failure. The
hints printed next to each failure are the actual fix, not a shrug — a render
with 9/39 frames clipping the blade is re-rendered with a tighter coverage, not
salvaged by hand.

Why bother: every one of these checks corresponds to a wasted render in the
past. The expensive mistake is not a bad clip, it is picking 12 frames out of a
clip whose last third has no sword in it.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prep_ref as pr

VIEWS = ("front", "back", "left", "right")

# a frame "touches the edge" when this many foreground pixels sit within
# EDGE_BAND px of the border — a single stray pixel is noise, a sword is not
EDGE_BAND = 2
EDGE_MIN_PX = 24


def _np():
    return pr._np()


def key_rgb(key: str) -> tuple[int, int, int]:
    k = (key or "auto").strip().lower()
    for name, rgb, hexv in (pr.KEY_GREEN, pr.KEY_MAGENTA, pr.KEY_CYAN):
        if k in (name, hexv.lower()):
            return rgb
    if k.startswith("#") and len(k) == 7:
        return tuple(int(k[i:i + 2], 16) for i in (1, 3, 5))
    return pr.KEY_GREEN[1]


def _fg(im, key: tuple[int, int, int], tol: int = 54):
    """Foreground = pixels meaningfully away from the key colour."""
    np = _np()
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    return np.abs(a - np.array(key, dtype=np.int16)).sum(2) > tol * 3


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------

def _longest_run(line) -> int:
    """Longest unbroken stretch of foreground along one border line.

    A count of stray pixels cries wolf — video compression leaves specks on the
    edge of a clean frame. A sword that leaves the frame leaves a *run*, tens of
    pixels long, and that is what this measures.
    """
    best = cur = 0
    for v in line:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return float(xs[len(xs) // 2])


def check_view(frame_dir: str, key: tuple[int, int, int]) -> dict:
    from PIL import Image

    np = _np()
    files = sorted(glob.glob(os.path.join(frame_dir, "*.png")))
    if not files:
        return {"dir": frame_dir, "frames": 0, "error": "no frames",
                "hard": ["no frames"], "warn": []}

    edge_hits: list[tuple[str, int]] = []
    heights: list[int] = []
    widths: list[int] = []
    corner_purity: list[float] = []
    empty: list[str] = []
    dark: list[str] = []

    for p in files:
        im = Image.open(p)
        m = _fg(im, key)
        ys, xs = np.nonzero(m)
        name = os.path.basename(p)
        if len(ys) < 40:
            empty.append(name)
            continue
        heights.append(int(ys.max() - ys.min() + 1))
        widths.append(int(xs.max() - xs.min() + 1))

        H, W = m.shape
        run = max(_longest_run(m[0]), _longest_run(m[-1]),
                  _longest_run(m[:, 0]), _longest_run(m[:, -1]))
        if run >= max(8, int(0.015 * min(H, W))):
            edge_hits.append((name, int(run)))

        if float(np.asarray(im.convert("RGB")).mean()) < 24:
            dark.append(name)

        # backdrop as seen from the corners — a ground plane or a re-keyed
        # mismatch shows up there first, and the figure rarely reaches all four
        b = max(8, int(0.12 * min(H, W)))
        boxes = [(slice(0, b), slice(0, b)), (slice(0, b), slice(W - b, W)),
                 (slice(H - b, H), slice(0, b)), (slice(H - b, H), slice(W - b, W))]
        corner_purity.append(_median([1.0 - float(m[s].mean()) for s in boxes]))

    med_h = int(_median(heights))
    spread = (max(heights) - min(heights)) / med_h if med_h else 0.0
    purity = _median(corner_purity)
    ratio = len(edge_hits) / max(1, len(files))

    hard: list[str] = []
    warn: list[str] = []
    if len(edge_hits) >= max(2, int(0.10 * len(files))):
        hard.append(f"{len(edge_hits)}/{len(files)} frames clipped at the border "
                    f"(longest run {max(r for _, r in edge_hits)} px)")
    elif edge_hits:
        warn.append(f"{len(edge_hits)}/{len(files)} frames touch the border "
                    f"(a blade tip is cut — usually fine, but check)")
    if empty:
        hard.append(f"{len(empty)} empty frames ({', '.join(empty[:4])})")
    if dark:
        hard.append(f"{len(dark)} black frames ({', '.join(dark[:4])}) — the "
                    f"reference had alpha and was echoed on black")
    # bbox height is *not* a zoom measurement: a sword raised overhead or a
    # blade swept low changes it by 30% with a perfectly locked camera. Report
    # it as a number and let the clip answer the question.
    if spread > 0.30:
        warn.append(f"body height swings {spread * 100:.0f}% — weapons overhead "
                    f"can do that on their own; if the torso visibly zooms in the "
                    f"clip, shorten the clip and re-render")
    if purity < 0.50:
        hard.append(f"backdrop is not one flat colour (corner purity "
                    f"{purity * 100:.0f}%) — wrong key colour, or a ground plane")
    elif purity < 0.75:
        warn.append(f"backdrop mostly flat (corner purity {purity * 100:.0f}%) — "
                    f"expect some fringe when keying")

    return {
        "dir": frame_dir, "frames": len(files),
        "edge": [n for n, _ in edge_hits], "edge_ratio": ratio,
        "height_min": min(heights) if heights else 0,
        "height_max": max(heights) if heights else 0,
        "height_median": med_h, "height_spread": spread,
        "width_median": int(_median(widths)),
        "empty": empty, "dark": dark, "key_purity": purity,
        "hard": hard, "warn": warn,
    }


def report_frames(frames_dir: str, key: tuple[int, int, int],
                  views: list[str]) -> tuple[dict, list[str], list[str]]:
    dirs = []
    for v in views:
        d = os.path.join(frames_dir, v)
        if os.path.isdir(d) and glob.glob(os.path.join(d, "*.png")):
            dirs.append((v, d))
    if not dirs and glob.glob(os.path.join(frames_dir, "*.png")):
        dirs = [(os.path.basename(os.path.abspath(frames_dir)), frames_dir)]
    if not dirs:
        raise SystemExit(f"no frames under {frames_dir}")

    results, hard, warn = {}, [], []
    for v, d in dirs:
        r = check_view(d, key)
        results[v] = r
        print(f"\n{v}")
        if r.get("error"):
            print(f"  {r['error']}")
            hard.append(f"{v}: {r['error']}")
            continue
        print(f"  frames        {r['frames']}")
        print(f"  body height   {r['height_min']}–{r['height_max']} px "
              f"(median {r['height_median']}, swing {r['height_spread'] * 100:.0f}%)")
        print(f"  backdrop      {r['key_purity'] * 100:.0f}% flat at the corners")
        print(f"  border        {'clean' if not r['edge'] else str(len(r['edge'])) + ' frames touch it'}")
        for msg in r["hard"]:
            print(f"  FAIL          {msg}")
            hard.append(f"{v}: {msg}")
        for msg in r["warn"]:
            print(f"  note          {msg}")
            warn.append(f"{v}: {msg}")
    return results, hard, warn


# --------------------------------------------------------------------------
# views
# --------------------------------------------------------------------------

def report_views(views_dir: str, key: tuple[int, int, int]) -> tuple[dict, list[str]]:
    paths = {v: os.path.join(views_dir, f"{v}.png") for v in VIEWS}
    paths = {v: p for v, p in paths.items() if os.path.exists(p)}
    if not paths:
        raise SystemExit(f"no front/back/left/right png in {views_dir}")
    out, hard = {}, []
    for v, p in paths.items():
        a = pr.analyse(p)
        out[v] = a
        if a["empty"]:
            print(f"{v:6s} EMPTY")
            hard.append(f"{v}: empty reference")
            continue
        clash = pr.clash_fraction(p, key)
        print(f"{v:6s} {a['w']}x{a['h']} in {a['size'][0]}x{a['size'][1]}  "
              f"coverage {a['coverage']}%  margins {a['margin_pct']}  "
              f"key clash {clash * 100:.2f}%")
        if a.get("tight"):
            hard.append(f"{v}: reference fills its own canvas "
                        f"(coverage {a['coverage']}%, margins {a['margin_pct']})")
        if clash > 0.005:
            hard.append(f"{v}: {clash * 100:.1f}% of the character matches the key")
    return out, hard


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="pixel quality gate")
    ap.add_argument("mode", choices=["views", "frames"])
    ap.add_argument("dir")
    ap.add_argument("--key", default="auto", help="auto | green | magenta | #RRGGBB")
    ap.add_argument("--views", default=",".join(VIEWS), help="comma list (frames mode)")
    ap.add_argument("--action", default="", help="only used in the printed hints")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    key = key_rgb(a.key)
    if a.key == "auto":
        found = [os.path.join(a.dir, f"{v}.png") for v in VIEWS]
        found = [p for p in found if os.path.exists(p)]
        if found:
            key = pr.choose_key(found)["chosen"]["rgb"]

    stage_word = "rendering" if a.mode == "views" else "picking frames"
    if a.mode == "views":
        res, hard = report_views(a.dir, key)
        hints = {
            "fills its own canvas":
                "the render inherits that crop, so a sword that sweeps outward "
                "leaves the frame — run scripts/prep_ref.py (or just generate.py, "
                "which now preps automatically) to pad onto a wider canvas",
            "matches the key":
                "pick another key colour (--key magenta / #00FFFF); a green "
                "costume under a green key gets eaten",
        }
    else:
        res, hard, warn = report_frames(a.dir, key, [v.strip() for v in a.views.split(",") if v.strip()])
        hints = {
            "clipped at the border":
                "re-render with a smaller --coverage (0.42) — H3 inherits the "
                "reference padding, it does not invent margin",
            "black frames":
                "the reference PNG had alpha; prep_ref.py composites it onto the "
                "key colour so frame 1 is not black",
            "camera is not locked":
                "camera was not locked — add 'the camera is locked off' beats or "
                "lower the frame count",
            "backdrop is not one flat colour":
                "check the key colour against the clip; the studio can re-key, "
                "but a ground plane cannot be removed",
        }

    if a.json:
        print(json.dumps({"key": list(key), "results": res,
                          "failures": hard, "notes": warn if a.mode == "frames" else []},
                         indent=1, ensure_ascii=False))

    if hard:
        print(f"\nFAIL — fix these before {stage_word}:")
        seen = set()
        for h in hard:
            print(f"  - {h}")
            for k, hint in hints.items():
                if k in h and k not in seen:
                    print(f"    -> {hint}")
                    seen.add(k)
        return 1
    print("\nPASS" + (f" (with {len(warn)} note(s))" if a.mode == "frames" and warn else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
