"""Prepare reference views so H3 has room to swing.

Two failures this file exists to prevent, both seen in real runs:

1. **Cropped weapon / cropped feet.** H3 reads the first frame far more than the
   prompt (see references/pitfalls.md#first-frame-dominates). If the reference
   fills the canvas edge to edge, the render inherits that crop — and the moment
   a sword sweeps outward it leaves the frame and comes back as a stump. A
   reference with 20–30% empty margin on every side gives the arc somewhere to go.

2. **A black first frame.** H3 echoes the reference as frame 1. A transparent
   PNG pasted onto a black canvas gives one black frame at the head of every
   clip. Compositing onto the key colour before upload removes it.

So every reference goes through here first: foreground bbox, then a *square*
canvas of the key colour (square because the render is 768×768 — matching the
aspect removes one more thing H3 can drift), figure scaled to a fixed fraction
of the canvas, centred.

    python prep_ref.py views/ --out views_staged --key auto --action attack

The same scale denominator is used for every view, so a narrow side view stays
narrow instead of being blown up to match the front view.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

KEY_GREEN = ("green", (35, 233, 20), "#23E914")     # chroma green, make_prompt default
KEY_MAGENTA = ("magenta", (255, 0, 255), "#FF00FF")
KEY_CYAN = ("cyan", (0, 255, 255), "#00FFFF")

# Actions whose silhouette throws a weapon (or a limb) far outside the standing
# bbox. They get a smaller figure so the arc has room.
ARC_ACTIONS = {"attack", "slash", "cast", "throw", "punch", "kick"}
# How much of the square canvas the figure may occupy (longest dimension).
COVERAGE_DEFAULT = 0.58
COVERAGE_ARC = 0.48


# --------------------------------------------------------------------------

def _load(path: str):
    from PIL import Image
    return Image.open(path)


def _np():
    import numpy as np
    return np


def border_rgb(im) -> tuple[int, int, int]:
    """Median colour of the outermost 2 px — i.e. whatever the backdrop is."""
    np = _np()
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    band = np.concatenate([
        a[:2].reshape(-1, 3), a[-2:].reshape(-1, 3),
        a[:, :2].reshape(-1, 3), a[:, -2:].reshape(-1, 3),
    ])
    med = np.median(band, axis=0)
    return tuple(int(v) for v in med)


def fg_mask(im, tol: int = 36):
    """Boolean mask of the character: alpha when the PNG has it, else
    'not the border colour'."""
    np = _np()
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        alpha = np.asarray(rgba)[:, :, 3]
        if (alpha < 250).any():
            return alpha > 8
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    bg = np.array(border_rgb(im), dtype=np.int16)
    return np.abs(a - bg).sum(2) > tol * 3


def analyse(path: str) -> dict:
    im = _load(path)
    m = fg_mask(im)
    np = _np()
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return {"path": path, "size": im.size, "empty": True,
                "bbox": None, "w": 0, "h": 0, "bg": border_rgb(im)}
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    w, h = x1 - x0, y1 - y0
    W, H = im.size
    return {
        "path": path, "size": (W, H), "mode": im.mode, "empty": False,
        "bbox": (x0, y0, x1, y1), "w": w, "h": h,
        "margin_px": (x0, y0, W - x1, H - y1),
        "margin_pct": (round(100 * x0 / W, 1), round(100 * y0 / H, 1),
                       round(100 * (W - x1) / W, 1), round(100 * (H - y1) / H, 1)),
        "coverage": round(100 * max(w, h) / max(W, H), 1),
        "touches_edge": bool(x0 <= 1 or y0 <= 1 or x1 >= W - 1 or y1 >= H - 1),
        # 98% coverage is not "a bit tight" — it is the whole canvas, and H3
        # will reproduce that crop. Anything under ~2% margin gets called out.
        "tight": bool(min(x0 / W, y0 / H, (W - x1) / W, (H - y1) / H) < 0.02),
        "bg": border_rgb(im),
    }


def clash_fraction(path: str, key_rgb: tuple[int, int, int], tol: int = 42) -> float:
    """Share of the *character* that sits within `tol` of the key colour.

    Above ~0.005 the key will start eating the costume — this is why a green
    armoured character must never be shot against chroma green.
    """
    np = _np()
    im = _load(path)
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    m = fg_mask(im)
    near = np.abs(a - np.array(key_rgb, dtype=np.int16)).sum(2) <= tol * 3
    total = int(m.sum())
    return 0.0 if not total else float((near & m).sum() / total)


def choose_key(paths: list[str], preferred: str | None = None) -> dict:
    """Pick the chroma colour that exists least in the character.

    `preferred` is whatever the user asked for ('green' / 'magenta' / '#RRGGBB').
    Without one, green wins unless the character is green, in which case magenta.
    """
    cands = []
    for name, rgb, hexv in (KEY_GREEN, KEY_MAGENTA, KEY_CYAN):
        worst = max((clash_fraction(p, rgb) for p in paths), default=0.0)
        cands.append({"name": name, "rgb": rgb, "hex": hexv, "clash": worst})

    warn = None
    if preferred:
        pref = preferred.strip().lower()
        match = next((c for c in cands if pref in (c["name"], c["hex"].lower())), None)
        if match is None and pref.startswith("#") and len(pref) == 7:
            rgb = tuple(int(pref[i:i + 2], 16) for i in (1, 3, 5))
            match = {"name": pref, "rgb": rgb, "hex": pref,
                     "clash": max((clash_fraction(p, rgb) for p in paths), default=0.0)}
        if match:
            chosen = dict(match)
            if chosen["clash"] > 0.005:
                warn = (f"{chosen['name']} covers {chosen['clash'] * 100:.1f}% of the "
                        f"character — the key will eat part of the costume")
            return {"chosen": chosen, "candidates": cands, "warn": warn,
                    "auto": False}

    safe = [c for c in cands if c["clash"] <= 0.005]
    chosen = (safe or sorted(cands, key=lambda c: c["clash"]))[0]
    if not safe:
        warn = (f"no clean key: every candidate appears in the character "
                f"(worst {max(c['clash'] for c in cands) * 100:.1f}%) — "
                f"picked {chosen['name']}, expect fringe")
    return {"chosen": dict(chosen), "candidates": cands, "warn": warn, "auto": True}


def prep_set(paths: dict[str, str], out_dir: str, key_rgb: tuple[int, int, int],
             coverage: float = COVERAGE_DEFAULT, pad_px: int = 2) -> dict:
    """Square-canvas every view at one shared scale. Returns per-view info."""
    from PIL import Image

    infos = {v: analyse(p) for v, p in paths.items()}
    usable = {v: i for v, i in infos.items() if not i["empty"]}
    if not usable:
        raise SystemExit("no foreground found in any reference view — "
                         "check the images, or pass --no-prep")
    fig_max = max(max(i["w"], i["h"]) for i in usable.values())
    # square canvas, multiple of 8 so H3 has less to round
    side = int(math.ceil((fig_max + 2 * pad_px) / coverage / 8.0) * 8)
    os.makedirs(out_dir, exist_ok=True)

    out = {}
    for view, path in paths.items():
        info = infos[view]
        im = _load(path)
        if info["empty"]:
            out[view] = {**info, "staged": None}
            continue
        x0, y0, x1, y1 = info["bbox"]
        crop = im.crop((x0, y0, x1, y1))
        canvas = Image.new("RGB", (side, side), key_rgb)
        px = (side - crop.width) // 2
        py = (side - crop.height) // 2
        if crop.mode in ("RGBA", "LA"):
            canvas.paste(crop, (px, py), crop)
        else:
            canvas.paste(crop.convert("RGB"), (px, py))
        dst = os.path.join(out_dir, f"{view}.png")
        canvas.save(dst)
        out[view] = {**info, "staged": dst, "canvas": side,
                     "staged_margin_px": (px, py, side - px - crop.width,
                                          side - py - crop.height),
                     "staged_margin_pct": round(100 * px / side, 1),
                     "staged_coverage": round(100 * max(crop.size) / side, 1)}
    warning = None
    tight = [v for v, i in usable.items() if i.get("tight")]
    if tight:
        warning = ("reference fills its own canvas in " + ",".join(sorted(tight)) +
                   " (margin < 2%) — that framing is what cropped the last run; "
                   "the padding below is the fix")
    return {"side": side, "coverage": coverage, "views": out, "warning": warning,
            "fig_max": fig_max}


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="pad + key-composite reference views")
    ap.add_argument("views", help="folder with front.png/back.png/right.png")
    ap.add_argument("--out", help="where to write the staged copies")
    ap.add_argument("--key", default="auto",
                    help="auto | green | magenta | #RRGGBB (default auto)")
    ap.add_argument("--coverage", default="auto",
                    help="figure size as a fraction of the square canvas "
                         "(default: 0.48 for attack/cast/throw, 0.58 otherwise)")
    ap.add_argument("--action", default="", help="used only to pick the coverage")
    ap.add_argument("--views", dest="only", help="comma list, default all four")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    names = ["front", "back", "left", "right"]
    if a.only:
        names = [n.strip() for n in a.only.split(",") if n.strip()]
    paths = {n: os.path.join(a.views, f"{n}.png") for n in names}
    paths = {n: p for n, p in paths.items() if os.path.exists(p)}
    if not paths:
        raise SystemExit(f"no front/back/left/right PNG in {a.views}")

    key = choose_key(list(paths.values()), None if a.key == "auto" else a.key)
    cov = a.coverage
    if cov == "auto":
        cov = COVERAGE_ARC if a.action.lower() in ARC_ACTIONS else COVERAGE_DEFAULT
    else:
        cov = float(cov)

    out_dir = a.out or os.path.join(a.views.rstrip("/\\") + "_staged")
    res = prep_set(paths, out_dir, key["chosen"]["rgb"], cov)
    res["key"] = key
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0

    print(f"key      {key['chosen']['name']} {key['chosen']['hex']}"
          f"  (max clash {key['chosen']['clash'] * 100:.2f}%)")
    if key["warn"]:
        print(f"WARN     {key['warn']}")
    print(f"canvas   {res['side']}x{res['side']}  coverage {cov:.2f}")
    for v, i in res["views"].items():
        if i.get("staged") is None:
            print(f"{v:6s} EMPTY")
            continue
        print(f"{v:6s} {i['w']}x{i['h']} -> {i['staged_coverage']}% of canvas, "
              f"margin {i['staged_margin_px']} px  {i['staged']}")
    if res["warning"]:
        print(f"note     {res['warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
