"""Can a video model tell this character's front from its back?

The failure this measures: a reference whose front and back views are the same
picture. H3 is image-to-video and reads the reference far more than the prompt
(``references/pitfalls.md#first-frame-dominates``), so if both look alike then
"pure rear view" produces a figure that turns around mid-clip, or a back-facing
direction that walks with its chest forward. Two views that differ only in a
little torso shading are, to the model, one view.

"I made the back different" is an opinion. This prints numbers:

    python check_facing.py views/                       # front vs back
    python check_facing.py views/ --json
    python check_facing.py templates/mannequin/ --strict

The primary metric is ``material_tv``: the total-variation distance between the
two views' **colour-area histograms**. Read it as "what share of the figure is a
different material". It is deliberately geometric-blind — a pixel-by-pixel
comparison was the first implementation and it lied in both directions: a
silhouette off by two pixels compared backdrop against wood along every edge and
reported 0.40 for a mannequin whose front and back were literally the same
drawing, while a real material swap that was slightly rotated reported less than
a shading change. Areas are immune to that: if two sides use the same colours in
the same proportions, they are the same picture no matter how the pixels line up.

Secondary metrics:

* ``silhouette_iou`` — how much the two outlines agree. High is *good*: the
  silhouette is what the character pass inherits, so the two sides should match
  in outline and differ in material. Low means they were not drawn as one body.
* ``profile_aspect`` — width/height of a side view. A true 90° profile is narrow
  (0.15–0.60). A side view that is 0.8 wide is three-quarter, and three-quarter
  references produce three-quarter animation.
* ``mirror_iou`` — left vs right; they should be mirror images.

Exit code is 0 for PASS, 1 for WEAK under --strict or for FAIL, so this can gate
a commit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prep_ref as pr          # noqa: E402  (fg_mask)

NORM_H = 300                   # height every view is measured at
NORM_W = 384                   # fixed canvas, so two views can be compared at all
# 32 merges anti-aliasing and shading noise into one bin without merging pale
# wood with dark leather. Measured on the two bundled mannequins: the old
# (front and back are the same drawing) scores 0.05 at 32 and 0.10 at 16 — the
# finer bin was measuring dithering, not material.
Q = 32

# Measured: the old bundled mannequin (front and back the same drawing) 0.05;
# the current one (leather back panel + stained nape) 0.44. The bands sit in the
# gap so "nearly the same" fails instead of passing.
PASS_TV = 0.22
WEAK_TV = 0.10


# --------------------------------------------------------------------------

def _load(path: str) -> dict:
    im = Image.open(path)
    m = pr.fg_mask(im)
    if not m.any():
        return {"path": path, "empty": True}
    ys, xs = np.nonzero(m)
    x0, y0 = int(xs.min()), int(ys.min())
    x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
    rgb = np.asarray(im.convert("RGB"))[y0:y1, x0:x1]
    return {"path": path, "empty": False, "rgb": rgb, "mask": m[y0:y1, x0:x1],
            "w": x1 - x0, "h": y1 - y0}


def _erode(m: np.ndarray, r: int = 1) -> np.ndarray:
    out = m.copy()
    h, w = m.shape
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            sh = np.zeros_like(m)
            xs0, xs1 = max(0, dx), min(w, w + dx)
            ys0, ys1 = max(0, dy), min(h, h + dy)
            sh[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
            out &= sh
    return out


def _norm(v: dict, flip: bool = False) -> dict:
    """Scale every view to the same figure height and centre it, so silhouette
    IoU compares shapes and not file sizes. Aspect is *not* forced, or a
    character who is genuinely wider from the front would lose IoU points for
    being drawn correctly."""
    rgb, mask = v["rgb"], v["mask"]
    if flip:
        rgb = rgb[:, ::-1]
        mask = mask[:, ::-1]
    s = min(NORM_H / v["h"], NORM_W / v["w"])
    nw, nh = max(1, int(round(v["w"] * s))), max(1, int(round(v["h"] * s)))
    m_img = Image.fromarray((mask * 255).astype(np.uint8), "L").resize((nw, nh),
                                                                     Image.NEAREST)
    rgb_img = Image.fromarray(rgb, "RGB").resize((nw, nh), Image.NEAREST)
    out_mask = np.zeros((NORM_H, NORM_W), dtype=bool)
    out_rgb = np.zeros((NORM_H, NORM_W, 3), dtype=np.uint8)
    ox, oy = (NORM_W - nw) // 2, (NORM_H - nh) // 2
    out_mask[oy:oy + nh, ox:ox + nw] = np.asarray(m_img) > 127
    out_rgb[oy:oy + nh, ox:ox + nw] = np.asarray(rgb_img)
    return {"rgb": out_rgb, "mask": out_mask}


def _region(mask: np.ndarray, y0: float, y1: float) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return mask
    top, bot = int(ys.min()), int(ys.max()) + 1
    h = bot - top
    out = np.zeros_like(mask)
    top_i, bot_i = int(top + y0 * h), int(top + y1 * h)
    out[top_i:bot_i] = True
    return out & mask


def _histogram(mask: np.ndarray, rgb: np.ndarray) -> dict:
    """Quantised colour -> area share, over the figure's interior."""
    m = _erode(mask, 1)
    px = rgb[m]
    if not len(px):
        return {}
    key = (px // Q) * Q + Q // 2
    keys, counts = np.unique(key.reshape(-1, 3), axis=0, return_counts=True)
    return {tuple(int(c) for c in k): float(n) / len(px)
            for k, n in zip(keys, counts)}


def _material_tv(a: dict, b: dict, ra=None, rb=None) -> dict:
    """Total variation between two colour-area histograms: the share of the
    figure that has to change material to turn one view into the other."""
    ha = _histogram(a["mask"] & ra if ra is not None else a["mask"], a["rgb"])
    hb = _histogram(b["mask"] & rb if rb is not None else b["mask"], b["rgb"])
    if not ha or not hb:
        return {"material_tv": 0.0, "front_top": None, "back_top": None,
                "separation": None}
    keys = set(ha) | set(hb)
    tv = 0.5 * sum(abs(ha.get(k, 0.0) - hb.get(k, 0.0)) for k in keys)
    fa = max(ha.items(), key=lambda kv: kv[1])
    fb = max(hb.items(), key=lambda kv: kv[1])
    sep = float(np.abs(np.array(fa[0], dtype=np.int16)
                       - np.array(fb[0], dtype=np.int16)).sum())
    return {"material_tv": round(float(tv), 3),
            "front_top": fa[0] + (round(fa[1], 3),),
            "back_top": fb[0] + (round(fb[1], 3),),
            "separation": round(sep, 1)}


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    u = int((a | b).sum())
    return round(float((a & b).sum() / u), 3) if u else 0.0


def _verdict(tv: float) -> str:
    if tv >= PASS_TV:
        return "PASS"
    if tv >= WEAK_TV:
        return "WEAK"
    return "FAIL"


def audit(views_dir: str) -> dict:
    names = ("front", "back", "left", "right")
    have = {n: os.path.join(views_dir, f"{n}.png") for n in names
            if os.path.exists(os.path.join(views_dir, f"{n}.png"))}
    if "front" not in have or "back" not in have:
        raise SystemExit(f"need front.png and back.png in {views_dir} "
                         f"(found: {', '.join(sorted(have)) or 'nothing'})")

    loaded = {n: _load(p) for n, p in have.items()}
    empty = [n for n, v in loaded.items() if v.get("empty")]
    if empty:
        raise SystemExit(f"no foreground in {', '.join(empty)} — check the images")

    front, back = loaded["front"], loaded["back"]
    res = {
        "views_dir": os.path.abspath(views_dir),
        "whole": _material_tv(front, back),
        # the torso is where a change has to be to survive motion; the head is
        # what a viewer (and an encoder) checks first
        "torso": _material_tv(front, back, _region(front["mask"], 0.24, 0.54),
                              _region(back["mask"], 0.24, 0.54)),
        "head": _material_tv(front, back, _region(front["mask"], 0.00, 0.22),
                             _region(back["mask"], 0.00, 0.22)),
        "silhouette_iou": _iou(_norm(front)["mask"], _norm(back, flip=True)["mask"]),
    }
    # Any single strongly-cued region is enough for the model — a stained nape, a
    # leather back panel, a cape. The TV already prices in how much area the cue
    # covers, so a marker on one fingertip cannot carry the score.
    res["score"] = max(res["whole"]["material_tv"], res["torso"]["material_tv"],
                       res["head"]["material_tv"])
    res["verdict"] = _verdict(res["score"])

    prof = {}
    for n in ("left", "right"):
        if n in loaded:
            prof[n] = {"aspect": round(loaded[n]["w"] / loaded[n]["h"], 3)}
    if "left" in loaded and "right" in loaded:
        prof["mirror_iou"] = _iou(_norm(loaded["left"])["mask"],
                                  _norm(loaded["right"], flip=True)["mask"])
    res["profile"] = prof

    notes = []
    tv = res["score"]
    if res["verdict"] == "FAIL":
        notes.append(f"front and back are the same picture to a video model "
                     f"(material_tv {tv:.2f}) — this is the failure that produces "
                     f"a figure which turns around mid-clip or walks backwards "
                     f"facing forward. Fix the reference, not the prompt: give "
                     f"one side a different material (back panel, lacing, stained "
                     f"nape, buckled front) and keep the outline identical.")
    elif res["verdict"] == "WEAK":
        notes.append(f"the two sides differ, but only a little (material_tv "
                     f"{tv:.2f}) — expect the model to lose the facing on some "
                     f"frames. Push the change onto the torso, where it is "
                     f"visible in every frame.")
    if res["torso"]["material_tv"] < 0.12:
        notes.append(f"the torso is nearly unchanged (material_tv "
                     f"{res['torso']['material_tv']:.2f}) — a marker that only "
                     f"exists on a limb is hidden for most of a walk cycle.")
    if res["silhouette_iou"] < 0.85:
        notes.append(f"silhouettes disagree (IoU {res['silhouette_iou']}) — the "
                     f"front and back were not drawn as one body, so the "
                     f"character pass inherits two different characters.")
    for n in ("left", "right"):
        if n in prof and prof[n]["aspect"] > 0.62:
            notes.append(f"{n} is {prof[n]['aspect']} wide — that is a "
                         f"three-quarter view, not a profile. Re-cut the view.")
    if "mirror_iou" in prof and prof["mirror_iou"] < 0.90:
        notes.append(f"left and right are not mirrors (IoU {prof['mirror_iou']}) "
                     f"— render one side and mirror it (mirror.py).")
    res["notes"] = notes
    return res


# --------------------------------------------------------------------------

def render_report(res: dict) -> str:
    out = [f"facing audit  {res['views_dir']}",
           f"  verdict       {res['verdict']}   (score {res['score']:.3f})"]
    for label in ("whole", "torso", "head"):
        m = res[label]
        out.append(f"  {label:12s} material_tv {m['material_tv']:.3f}   "
                   f"front {m['front_top']}  back {m['back_top']}   "
                   f"sep {m['separation']}")
    out.append(f"  silhouette    IoU {res['silhouette_iou']}")
    p = res.get("profile") or {}
    for n in ("left", "right"):
        if n in p:
            out.append(f"  {n:12s} aspect {p[n]['aspect']}")
    if "mirror_iou" in p:
        out.append(f"  mirror        IoU {p['mirror_iou']}")
    if res["notes"]:
        out.append("")
        for n in res["notes"]:
            out.append(f"  ! {n}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="is the front of this reference distinguishable from its back?")
    ap.add_argument("views", help="folder with front.png / back.png "
                                  "(and optionally left.png / right.png)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="treat WEAK as a failure too")
    a = ap.parse_args(argv)

    res = audit(a.views)
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        print(render_report(res))

    v = res["verdict"]
    if v == "PASS":
        return 0
    if v == "WEAK" and not a.strict:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
