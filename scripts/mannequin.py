"""Draw the route-B proxy mannequin — from one skeleton, in four views.

Why this file exists
--------------------
The proxy pass is supposed to answer "does the motion read?", and it kept
answering a different question: *which way is this dummy facing?* The old
bundled mannequin was four near-identical pictures (measured: the front and
back PNGs differ only in a little torso shading, same silhouette to the pixel).
H3 believes the reference over the prompt — that is the rule in
``references/pitfalls.md`` that costs the most renders — so a prompt saying
"pure rear view" in front of a drawing that looks frontal does not produce a
rear view. It produces a figure that turns around halfway through the clip, or
a back-facing direction that walks with its chest forward.

The fix is not a better sentence. It is a reference where the two sides are
*different materials*, so "which side am I looking at" is answerable from a
single frame at 5 px per limb — by the model and by us.

Two rules the drawing obeys
---------------------------
1. **Material, not silhouette.** The front is pale birch with a leather chest
   harness and a brass buckle; the back is a dark leather back panel with X
   lacing, a spine seam, stained walnut on the nape, and heels instead of toes.
   Nothing is added to the *outline*, because the character pass inherits the
   proxy's silhouette: a proxy with a backpack teaches the model to swing a
   backpack.
2. **One skeleton, four projections.** Every joint is defined once and
   projected orthographically. That is what makes the four views the same
   person at the same scale with the same proportions — the thing an image
   model is worst at and a turnaround cannot survive without.

The check that this actually worked is ``check_facing.py`` — run it on the
output. "I made the back different" is an opinion; ``torso_diff 0.42`` is a
measurement.

    python mannequin.py                          # -> templates/mannequin/
    python mannequin.py --out /tmp/mq --scale 6
    python mannequin.py --out /tmp/mq --key '#00FF00'
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# Palette. Flat clusters only, no anti-aliasing, no gradients — the frames get
# quantised in the studio anyway, and H3 reads flat colour blocks more
# reliably than shading.
# --------------------------------------------------------------------------

OUTLINE = (48, 32, 21)

WOOD = ((239, 211, 168), (211, 172, 123), (150, 108, 66))       # light mid dark
WALNUT = ((150, 108, 66), (112, 76, 44), (70, 46, 26))          # the nape stain
LEATHER = ((122, 82, 50), (86, 55, 33), (52, 32, 19))           # back panel, straps
BRASS = ((240, 200, 104), (196, 152, 56), (140, 104, 32))
STEEL = ((201, 210, 218), (138, 151, 164), (90, 100, 112))
# The near arm in profile sits inside the torso silhouette, so an identical wood
# tone makes it vanish. One step darker separates it without touching the
# outline — the same "material not silhouette" rule as the back panel.
ARM_SHADE = ((205, 166, 118), (186, 146, 100), (140, 100, 60))
THREAD = (245, 228, 196)

# --------------------------------------------------------------------------
# One skeleton, in figure units (y measured down from the top of the head).
# Front / back / side are projections of these numbers, so the proportions
# cannot drift between views.
# --------------------------------------------------------------------------

HEAD_CY, HEAD_RX, HEAD_RY = 9.4, 5.4, 6.7
HEAD_DZ, HEAD_DEPTH = 0.4, 5.5          # profile: centre offset and half depth
NECK = ((0.0, 15.9), (0.0, 19.0), 1.75)

SHOULDER = (8.0, 19.4)
ELBOW = (10.9, 31.0)
WRIST = (12.3, 43.6)
HIP = (4.2, 43.4)
KNEE = (4.6, 60.0)
ANKLE = (4.4, 75.2)

R_SHOULDER, R_ELBOW, R_HIP, R_KNEE = 2.7, 2.0, 2.4, 2.2

FOOT_BOTTOM = 77.5
FIGURE_H = 77.5

# Torso outline: wide shoulders, narrow waist, flared hips. The polygon closes
# over the top with a short trapezoid shoulder bed.
TORSO = [
    (-8.8, 20.0), (-7.9, 25.0), (-6.6, 30.2), (-6.3, 33.6), (-7.5, 38.2),
    (-6.1, 42.8), (0.0, 44.4), (6.1, 42.8), (7.5, 38.2), (6.3, 33.6),
    (6.6, 30.2), (7.9, 25.0), (8.8, 20.0), (5.2, 17.4), (-5.2, 17.4),
]

# Depth extents for the profile view: (z_back, z_front) at each y. The figure
# faces +z, so the back panel is the -z edge of the torso in profile.
PROFILE_TORSO_Y = [17.6, 20.0, 26.0, 30.0, 34.0, 37.5, 40.5, 43.5]
PROFILE_TORSO_Z = [
    (-3.6, 4.0), (-5.4, 5.2), (-5.6, 5.4), (-4.4, 4.2), (-4.2, 4.1),
    (-5.3, 4.4), (-5.8, 4.3), (-5.4, 4.0),
]

BELT_Y = (36.4, 39.4)
PANEL_TOP = 22.4
SPINE_BOTTOM = 42.6

CANVAS_W, CANVAS_H = 64, 88
TOP_PAD = 4.5

# Internal supersample. At 1x a profile forearm is 4 px wide and the 1 px rim
# plus 1 px outline eat half of it, so the arm stops reading as an arm. Drawing
# at 2x and upscaling by an integer keeps hard pixel edges while giving limbs
# enough pixels to have a shape.
SS = 2
PX_W, PX_H = CANVAS_W * SS, CANVAS_H * SS

KEY_DEFAULT = "#FF00FF"


# --------------------------------------------------------------------------
# Mask building
# --------------------------------------------------------------------------

class Group:
    """A set of primitives painted as one form: one outline, one rim.

    Building a torso as *one* group rather than a stack of ellipses is what
    keeps a body from being drawn as a pile of seams; ball joints are separate
    groups precisely because they are supposed to read as separate parts.
    """

    def __init__(self, w: int, h: int):
        self.img = Image.new("L", (w, h), 0)
        self.d = ImageDraw.Draw(self.img)

    # coordinates arrive already projected (pixels); radii arrive in figure
    # units, so they are scaled here and nowhere else.
    def ell(self, cx: float, cy: float, rx: float, ry: float) -> "Group":
        rx, ry = rx * SS, ry * SS
        self.d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
        return self

    def cap(self, p0, p1, r: float) -> "Group":
        """Capsule: thick line plus round caps (PIL's wide lines are butt-ended)."""
        self.d.line([p0, p1], fill=255, width=max(1, int(round(2 * r * SS))))
        self.ell(p0[0], p0[1], r, r).ell(p1[0], p1[1], r, r)
        return self

    def taper(self, p0, p1, r0: float, r1: float) -> "Group":
        """Capsule with different end radii — limbs thin out toward the wrist."""
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        ln = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / ln, dx / ln
        a, b = r0 * SS, r1 * SS
        self.d.polygon([
            (p0[0] + nx * a, p0[1] + ny * a), (p1[0] + nx * b, p1[1] + ny * b),
            (p1[0] - nx * b, p1[1] - ny * b), (p0[0] - nx * a, p0[1] - ny * a),
        ], fill=255)
        self.ell(p0[0], p0[1], r0, r0).ell(p1[0], p1[1], r1, r1)
        return self

    def poly(self, pts) -> "Group":
        self.d.polygon([tuple(p) for p in pts], fill=255)
        return self

    def quad(self, p0, p1, p2, p3) -> "Group":
        return self.poly([p0, p1, p2, p3])

    def rect(self, x0, y0, x1, y1) -> "Group":
        # normalise: mirrored views hand these over in either order
        self.d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                         fill=255)
        return self

    def mask(self) -> np.ndarray:
        return np.asarray(self.img) > 127


def _shift(m: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(m)
    h, w = m.shape
    xs0, xs1 = max(0, dx), min(w, w + dx)
    ys0, ys1 = max(0, dy), min(h, h + dy)
    out[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def dilate8(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                out |= _shift(m, dx, dy)
    return out


def erode8(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                out &= _shift(m, dx, dy)
    return out


def halfplane(w: int, h: int, x_cut: float, left: bool,
              y0: float = 0, y1: float = 1e9) -> np.ndarray:
    """Everything on one side of a vertical line, restricted to a y band.

    A quad drawn through PIL was the first attempt and it silently filled the
    wrong side (a polygon whose corners fall outside the canvas). A mask built
    from an index comparison cannot be wrong in that way.
    """
    xs = np.arange(w)[None, :]
    ys = np.arange(h)[:, None]
    side = xs < x_cut if left else xs > x_cut
    return np.broadcast_to(side, (h, w)) & (ys >= y0) & (ys <= y1)


def paint(buf: np.ndarray, mask: np.ndarray, tones, outline: bool = True,
          rim: bool = True) -> None:
    """Fill a form: outline outside, mid inside, one lit rim up-left, one dark
    rim down-right. Cheap volume, one rule everywhere, so the four views shade
    consistently instead of each looking like its own drawing."""
    light, mid, dark = tones
    if outline:
        buf[dilate8(mask) & ~mask] = (*OUTLINE, 255)
    buf[mask] = (*mid, 255)
    if rim:
        lit = mask & ~_shift(mask, 1, 1)      # up-left edge
        shade = mask & ~_shift(mask, -1, -1)  # down-right edge
        buf[lit] = (*light, 255)
        buf[shade] = (*dark, 255)


def decal(buf: np.ndarray, shape: np.ndarray, clip: np.ndarray, color,
          edge=None) -> None:
    """Paint onto a form's surface (clipped to it), optionally with a darker
    1 px edge so a flat patch still reads as a patch and not as a stain."""
    m = shape & clip
    if edge:
        buf[m & ~erode8(m)] = (*edge, 255)
    buf[m] = (*color, 255)


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

class View:
    """Figure units -> canvas pixels, per view. Orthographic, no perspective:
    a turnaround that changes scale between panels is a turnaround H3 has to
    guess about."""

    def __init__(self, kind: str):
        self.kind = kind
        self.cx = CANVAS_W * SS / 2
        self.top = TOP_PAD * SS

    def flip(self) -> float:
        return -1.0 if self.kind == "back" else 1.0

    def fx(self, x: float) -> float:
        return self.cx + x * self.flip() * SS

    def fy(self, y: float) -> float:
        return self.top + y * SS

    @property
    def dsign(self) -> float:
        """+1 when the figure faces screen-right, -1 when it faces left. Sword
        directions are given in screen space, so they have to be built with this
        or the left view ends up with a blade pointing out of its own back."""
        return 1.0 if self.kind == "right" else -1.0

    def fz(self, z: float) -> float:
        return self.cx + z * (1.0 if self.kind == "right" else -1.0) * SS

    @property
    def profile(self) -> bool:
        return self.kind in ("left", "right")


def _sword(g: Group, hand, out_dir, blade_len: float = 16.5):
    """A short straight sword, blade angled down and away from the body.

    Pointed *away* on purpose: a blade laid across the thigh is the classic
    thin-prop failure (see pitfalls.md#thin-props) and it also makes the
    reference read as "one weapon crossing the body".
    """
    hx, hy = hand
    dx, dy = out_dir
    ln = (dx * dx + dy * dy) ** 0.5
    dx, dy = dx / ln, dy / ln
    nx, ny = -dy, dx

    guard = (hx + dx * 2.4 * SS, hy + dy * 2.4 * SS)
    tip = (guard[0] + dx * blade_len * SS, guard[1] + dy * blade_len * SS)
    pommel = (hx - dx * 2.8 * SS, hy - dy * 2.8 * SS)

    g.cap(pommel, guard, 1.1)                                       # grip
    g.cap((guard[0] + nx * 1.6 * SS, guard[1] + ny * 1.6 * SS),
          (guard[0] - nx * 1.6 * SS, guard[1] - ny * 1.6 * SS), 0.6)  # crossguard
    g.taper(guard, tip, 1.25, 0.55)                                  # blade
    return {"guard": guard, "tip": tip, "pommel": pommel}


# --------------------------------------------------------------------------
# Front / back
# --------------------------------------------------------------------------

def draw_front_back(view: View, buf: np.ndarray) -> dict:
    """Front and back share one silhouette on purpose — the difference is the
    material, because silhouette is what the character pass inherits and
    material is what it does not."""
    W, H = PX_W, PX_H
    back = view.kind == "back"
    fx, fy = view.fx, view.fy

    # ---- legs + feet ------------------------------------------------------
    for side in (-1, 1):
        hip = (fx(side * HIP[0]), fy(HIP[1]))
        knee = (fx(side * KNEE[0]), fy(KNEE[1]))
        ankle = (fx(side * ANKLE[0]), fy(ANKLE[1]))
        leg = Group(W, H)
        leg.taper(hip, knee, 3.2, 2.6).taper(knee, ankle, 2.6, 2.0)
        paint(buf, leg.mask(), WOOD)

        ax = fx(side * ANKLE[0])
        foot = Group(W, H)
        foot.quad((ax - 2.3, fy(74.4)), (ax + 2.3, fy(74.4)),
                  (ax + 2.1, fy(FOOT_BOTTOM)), (ax - 2.1, fy(FOOT_BOTTOM)))
        foot.ell(ax, fy(FOOT_BOTTOM) - 1.1, 2.1, 1.1)
        fm = foot.mask()
        paint(buf, fm, WOOD)
        if back:
            # heel pad: the back of a foot, not the front
            decal(buf, Group(W, H).quad(
                (ax - 1.5, fy(75.6)), (ax + 1.5, fy(75.6)),
                (ax + 1.3, fy(77.0)), (ax - 1.3, fy(77.0))).mask(), fm, WALNUT[1])
        else:
            # toe split: two toes visible from the front
            decal(buf, Group(W, H).rect(
                ax - 0.5, fy(75.4), ax + 0.5, fy(77.2)).mask(), fm, WOOD[2])

    # ---- torso ------------------------------------------------------------
    torso = Group(W, H)
    torso.poly([(fx(x), fy(y)) for x, y in TORSO])
    torso.cap((fx(NECK[0][0]), fy(NECK[0][1])), (fx(NECK[1][0]), fy(NECK[1][1])),
              NECK[2])
    tm = torso.mask()
    paint(buf, tm, WOOD)

    # ---- arms -------------------------------------------------------------
    for side in (-1, 1):
        sh = (fx(side * SHOULDER[0]), fy(SHOULDER[1]))
        el = (fx(side * ELBOW[0]), fy(ELBOW[1]))
        wr = (fx(side * WRIST[0]), fy(WRIST[1]))
        arm = Group(W, H)
        arm.taper(sh, el, 2.5, 2.1).taper(el, wr, 2.1, 1.8)
        paint(buf, arm.mask(), WOOD)
        hand = Group(W, H)
        hand.ell(wr[0], wr[1] + 1.0, 2.0, 2.2)
        paint(buf, hand.mask(), WOOD)

    # ---- head -------------------------------------------------------------
    head = Group(W, H)
    head.ell(fx(0), fy(HEAD_CY), HEAD_RX, HEAD_RY)
    hm = head.mask()
    paint(buf, hm, WOOD)

    if back:
        # The nape: the lower part of the back of the skull, stained walnut.
        # The most valuable cue in the whole sheet — the head is what a viewer
        # checks first and it is visible in every frame of every action.
        nape = Group(W, H)
        nape.ell(fx(0), fy(HEAD_CY + 1.3), HEAD_RX - 0.6, HEAD_RY - 1.9)
        # no dark edge here: it would merge with the figure outline and make the
        # skull look notched. A hard colour change is the cue.
        decal(buf, nape.mask(), hm, WALNUT[1])

    # ---- joint balls ------------------------------------------------------
    # After the limbs, so they read as protruding balls: this is what makes the
    # drawing legible as an articulated dummy rather than a person.
    for side in (-1, 1):
        for (jx, jy), r in (((side * SHOULDER[0], SHOULDER[1]), R_SHOULDER),
                            ((side * ELBOW[0], ELBOW[1]), R_ELBOW),
                            ((side * HIP[0], HIP[1]), R_HIP),
                            ((side * KNEE[0], KNEE[1]), R_KNEE)):
            b = Group(W, H)
            b.ell(fx(jx), fy(jy), r, r)
            paint(buf, b.mask(), WOOD)

    # ---- belt (both sides; it is a 3D band, so it exists on both) ---------
    belt = Group(W, H)
    belt.poly([(fx(-7.6), fy(BELT_Y[0])), (fx(7.6), fy(BELT_Y[0])),
               (fx(7.2), fy(BELT_Y[1])), (fx(-7.2), fy(BELT_Y[1]))])
    bm = belt.mask() & tm
    paint(buf, bm, LEATHER)

    # ---- the two faces ----------------------------------------------------
    if back:
        panel = Group(W, H)
        panel.poly([
            (fx(-6.5), fy(PANEL_TOP)), (fx(-3.0), fy(PANEL_TOP - 1.5)),
            (fx(3.0), fy(PANEL_TOP - 1.5)), (fx(6.5), fy(PANEL_TOP)),
            (fx(6.7), fy(33.8)), (fx(4.2), fy(BELT_Y[0] - 0.2)),
            (fx(-4.2), fy(BELT_Y[0] - 0.2)), (fx(-6.7), fy(33.8)),
        ])
        pm = panel.mask() & tm
        paint(buf, pm, LEATHER, rim=False)

        lace = Group(W, H)
        for a, b in (((-4.6, 24.6), (4.6, 33.4)), ((4.6, 24.6), (-4.6, 33.4))):
            lace.cap((fx(a[0]), fy(a[1])), (fx(b[0]), fy(b[1])), 0.55)
        decal(buf, lace.mask(), pm, THREAD)

        seam = Group(W, H)
        seam.rect(fx(-0.6), fy(PANEL_TOP - 1.5), fx(0.6), fy(SPINE_BOTTOM))
        decal(buf, seam.mask(), tm, LEATHER[2])
    else:
        # Pale chest, leather harness meeting a brass ring at the sternum. A
        # shape that cannot be mirrored onto a back view without looking wrong,
        # which is the entire point.
        harness = Group(W, H)
        for side in (-1, 1):
            harness.cap((fx(side * 6.6), fy(20.4)), (fx(0.0), fy(32.2)), 0.9)
            harness.cap((fx(side * 6.6), fy(20.4)),
                        (fx(side * 7.7), fy(18.4)), 0.9)
        paint(buf, harness.mask() & tm, LEATHER, rim=False, outline=False)

        ring = Group(W, H)
        ring.ell(fx(0), fy(32.4), 2.1, 2.1)
        rm = ring.mask() & tm
        paint(buf, rm, BRASS, rim=False)
        hole = Group(W, H)
        hole.ell(fx(0), fy(32.4), 0.8, 0.8)
        buf[hole.mask() & rm] = (*LEATHER[2], 255)

        buckle = Group(W, H)
        buckle.rect(fx(-1.9), fy(36.9), fx(1.9), fy(39.0))
        kbm = buckle.mask() & bm
        paint(buf, kbm, BRASS, rim=False)
        hole = Group(W, H)
        hole.rect(fx(-0.8), fy(37.4), fx(0.8), fy(38.4))
        buf[hole.mask() & kbm] = (*LEATHER[2], 255)

    # ---- swords -----------------------------------------------------------
    for side in (-1, 1):
        g = Group(W, H)
        # the direction has to be mirrored with the view as well, or the back
        # view hangs both blades inward and crosses them at the crotch
        _sword(g, (fx(side * WRIST[0]), fy(WRIST[1] + 1.6)),
               (side * view.flip() * 0.50, 0.87))
        paint(buf, g.mask(), STEEL, rim=False)

    return {"view": view.kind}


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

def draw_profile(view: View, buf: np.ndarray) -> dict:
    """True 90° profile: depth on screen-x, one arm, one leg, toes forward.

    Built as **one body**, then split by material. Drawing the torso, leg and
    head as separate outlined forms produced a stack of blobs with visible
    internal seams — a side view has to read as a single silhouette, and the
    only thing that should break it is the near arm.

    The facing cue is that the rear half of the torso is the dark leather panel
    and the front half is pale wood. Skip the split and the profile is a
    symmetric sliver — which is exactly how the side view came to be rendered
    facing the wrong way.
    """
    W, H = PX_W, PX_H
    fz, fy = view.fz, view.fy
    right = view.kind == "right"

    body = Group(W, H)

    # torso: front and back edges at each y band
    pts_l = [(fz(zb), fy(y)) for (zb, _zf), y in zip(PROFILE_TORSO_Z, PROFILE_TORSO_Y)]
    pts_r = [(fz(zf), fy(y)) for (_zb, zf), y in zip(PROFILE_TORSO_Z, PROFILE_TORSO_Y)]
    body.poly(pts_l + pts_r[::-1])

    # neck, head
    body.cap((fz(-1.7), fy(15.6)), (fz(1.7), fy(19.2)), 1.8)
    body.ell(fz(HEAD_DZ), fy(HEAD_CY), HEAD_DEPTH, HEAD_RY)

    # near leg: one leg only, that is what a profile shows
    body.taper((fz(0.9), fy(HIP[1])), (fz(1.1), fy(KNEE[1])), 3.3, 2.7)
    body.taper((fz(1.1), fy(KNEE[1])), (fz(1.3), fy(ANKLE[1])), 2.7, 2.0)

    # foot: toes forward. The longest single facing cue in the profile.
    ax = fz(1.3)
    body.poly([(ax - 3.0, fy(74.0)), (ax + 1.4, fy(74.0)),
               (ax + 5.2, fy(76.0)), (ax + 5.2, fy(FOOT_BOTTOM - 0.4)),
               (ax - 3.2, fy(FOOT_BOTTOM - 0.4)), (ax - 3.2, fy(75.6))])

    bm = body.mask()
    paint(buf, bm, WOOD)

    # ---- material: rear half of the torso is the leather back panel --------
    rear = halfplane(W, H, fz(0.0), left=right,
                     y0=fy(19.4), y1=fy(BELT_Y[1] - 0.2))
    panel = Group(W, H)
    panel.poly([(fz(-6.0), fy(PANEL_TOP - 2.0)), (fz(0.0), fy(PANEL_TOP - 2.0)),
                (fz(0.0), fy(BELT_Y[1] - 0.2)), (fz(-6.0), fy(BELT_Y[1] - 0.2))])
    decal(buf, panel.mask(), rear & bm, LEATHER[1], edge=LEATHER[2])

    # spine seam on the rear edge, and a hint of the lacing
    seam = Group(W, H)
    seam.rect(min(fz(-2.6), fz(-1.9)), fy(PANEL_TOP - 1.0),
              max(fz(-2.6), fz(-1.9)), fy(SPINE_BOTTOM))
    decal(buf, seam.mask(), bm, LEATHER[2])
    lace = Group(W, H)
    za, zb = -4.4, -0.6
    lace.cap((fz(za), fy(25.0)), (fz(zb), fy(33.0)), 0.5)
    lace.cap((fz(zb), fy(25.0)), (fz(za), fy(33.0)), 0.5)
    decal(buf, lace.mask(), rear & bm, THREAD)

    # nape: rear of the skull
    nape = halfplane(W, H, fz(HEAD_DZ - 1.2), left=right,
                     y0=fy(HEAD_CY - HEAD_RY + 1.2), y1=fy(HEAD_CY + HEAD_RY))
    decal(buf, nape, bm, WALNUT[1], edge=WALNUT[2])
    # heel: rear of the foot
    heel = halfplane(W, H, fz(-0.4), left=right,
                     y0=fy(74.4), y1=fy(FOOT_BOTTOM))
    decal(buf, heel, bm, WALNUT[1])

    # ---- belt -------------------------------------------------------------
    belt = Group(W, H)
    belt.poly([(fz(-4.6), fy(BELT_Y[0])), (fz(4.2), fy(BELT_Y[0])),
               (fz(4.1), fy(BELT_Y[1])), (fz(-4.5), fy(BELT_Y[1]))])
    paint(buf, belt.mask() & bm, LEATHER, rim=False, outline=False)

    # ---- near arm, on top with its own outline: that is how a profile shows
    # an arm at all ---------------------------------------------------------
    arm = Group(W, H)
    arm.taper((fz(1.8), fy(SHOULDER[1])), (fz(2.3), fy(ELBOW[1])), 2.5, 2.1)
    arm.taper((fz(2.3), fy(ELBOW[1])), (fz(2.6), fy(WRIST[1])), 2.1, 1.8)
    paint(buf, arm.mask(), ARM_SHADE)
    hand = Group(W, H)
    hand.ell(fz(2.6), fy(WRIST[1] + 1.6), 2.0, 2.2)
    paint(buf, hand.mask(), ARM_SHADE)

    # harness strap on the chest edge — the front's marker, seen side-on
    strap = Group(W, H)
    strap.cap((fz(4.4), fy(20.6)), (fz(2.4), fy(31.4)), 0.85)
    paint(buf, strap.mask() & bm, LEATHER, rim=False, outline=False)

    # ---- joint balls ------------------------------------------------------
    for (z, y), r in (((1.6, SHOULDER[1]), R_SHOULDER),
                      ((2.0, ELBOW[1]), R_ELBOW),
                      ((1.1, HIP[1]), R_HIP),
                      ((1.1, KNEE[1]), R_KNEE)):
        b = Group(W, H)
        b.ell(fz(z), fy(y), r, r)
        paint(buf, b.mask(), WOOD)

    # ---- sword ------------------------------------------------------------
    g = Group(W, H)
    # blade tilted forward as well as down: a purely vertical blade projects onto
    # the thigh and hides the leg, and it is what a blade angled outward in the
    # front view actually does in depth
    _sword(g, (fz(2.6), fy(WRIST[1] + 1.6)), (0.40 * view.dsign, 0.92))
    paint(buf, g.mask(), STEEL, rim=False)

    return {"view": view.kind}


# --------------------------------------------------------------------------

def render(kind: str) -> Image.Image:
    buf = np.zeros((PX_H, PX_W, 4), dtype=np.uint8)
    v = View(kind)
    if v.profile:
        draw_profile(v, buf)
    else:
        draw_front_back(v, buf)
    return Image.fromarray(buf, "RGBA")


def _compose(images: dict, key_rgb, cols: int, label: bool):
    names = [n for n in ("front", "back", "right", "left") if n in images]
    w, h = images[names[0]].size
    rows = (len(names) + cols - 1) // cols
    pad = 10
    head = 12 if label else 0
    W = cols * w + pad * (cols + 1)
    H = rows * h + pad * (rows + 1) + head
    canvas = Image.new("RGB", (W, H), key_rgb)
    d = ImageDraw.Draw(canvas)
    for i, n in enumerate(names):
        c, r = i % cols, i // cols
        x = pad + c * (w + pad)
        y = pad + r * (h + pad) + head
        canvas.paste(images[n], (x, y), images[n])
        if label:
            d.text((x + 2, y - 11), n.upper(), fill=(0, 0, 0))
    return canvas


def contact_sheet(images: dict, key_rgb, label: bool = True):
    """2x2 — the sheet an image model would be asked for, and the one a human
    eyeballs to confirm the two sides really are different."""
    return _compose(images, key_rgb, cols=2, label=label)


def strip(images: dict, key_rgb, label: bool = True):
    """One row, for pasting into a doc or a chat."""
    return _compose(images, key_rgb, cols=4, label=label)


def contract(out_dir: str, scale: int) -> dict:
    return {
        "generator": "scripts/mannequin.py",
        "scale": scale,
        "unit_canvas": [CANVAS_W, CANVAS_H],
        "figure_units": FIGURE_H,
        "front_markers": [
            "pale birch chest and face",
            "leather harness in a V meeting a brass ring at the sternum",
            "brass belt buckle at centre",
            "toe split on each foot",
        ],
        "back_markers": [
            "dark leather back panel with light X lacing over the shoulder blades",
            "vertical spine seam from the neck to the waist",
            "stained walnut nape over the lower part of the back of the head",
            "plain belt, no buckle",
            "heel pad instead of a toe split",
        ],
        "profile_markers": [
            "rear half of the torso is the leather panel, front half pale wood",
            "nape stained on the back of the skull",
            "toes point the way the figure faces",
        ],
        "invariants": [
            "front and back share one silhouette on purpose: the character pass "
            "inherits the proxy silhouette, so an extra bump becomes a backpack",
            "identical head-to-heel height and pixel scale in all four views",
            "one arm and one leg in the profile views",
        ],
        "rule": "the difference between the two sides is material, never outline",
        "verify": "python scripts/check_facing.py " + out_dir,
    }


def build(out_dir: str, scale: int = 5, key: str = KEY_DEFAULT) -> dict:
    key_rgb = tuple(int(key[i:i + 2], 16) for i in (1, 3, 5))
    os.makedirs(out_dir, exist_ok=True)

    base = {k: render(k) for k in ("front", "back", "right", "left")}
    written = {}
    for name, im in base.items():
        big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
        p = os.path.join(out_dir, f"{name}.png")
        big.save(p)
        written[name] = p

    def scaled(img):
        return img.resize((img.width * scale, img.height * scale), Image.NEAREST) \
            if scale > 1 else img

    sheet_p = os.path.join(out_dir, "sheet_2x2.png")
    scaled(contact_sheet(base, key_rgb)).save(sheet_p)
    strip_p = os.path.join(out_dir, "turnaround.png")
    scaled(strip(base, key_rgb)).save(strip_p)

    c = contract(out_dir, scale)
    # Bake the verification into the asset. "The back is different now" is a
    # claim; the audit is the receipt, and it travels with the PNGs.
    try:
        import check_facing as cf
        aud = cf.audit(out_dir)
        c["facing_audit"] = {
            "verdict": aud["verdict"],
            "score": aud["score"],
            "whole": aud["whole"]["material_tv"],
            "torso": aud["torso"]["material_tv"],
            "head": aud["head"]["material_tv"],
            "silhouette_iou": aud["silhouette_iou"],
            "mirror_iou": aud["profile"].get("mirror_iou"),
        }
    except Exception as e:                # noqa: BLE001 - never block the build
        c["facing_audit"] = {"error": f"{type(e).__name__}: {e}"}

    cp = os.path.join(out_dir, "facing_contract.json")
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1, ensure_ascii=False)

    return {"files": written, "sheet": sheet_p, "turnaround": strip_p,
            "contract": cp, "audit": c.get("facing_audit")}


def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(os.path.dirname(here), "templates", "mannequin")
    ap = argparse.ArgumentParser(description="draw the 4-view proxy mannequin")
    ap.add_argument("--out", default=default_out, help="output folder")
    ap.add_argument("--scale", type=int, default=5,
                    help="integer upscale (5 -> 320x440)")
    ap.add_argument("--key", default=KEY_DEFAULT,
                    help="backdrop for the contact sheets only; the per-view "
                         "PNGs stay transparent so prep_ref measures the bbox "
                         "exactly")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    res = build(a.out, a.scale, a.key)
    if not a.quiet:
        for k, v in res["files"].items():
            print(f"{k:6s} {v}")
        print(f"sheet  {res['sheet']}")
        print(f"strip  {res['turnaround']}")
        print(f"contract {res['contract']}")
        aud = res.get("audit") or {}
        if "verdict" in aud:
            print(f"\nfacing {aud['verdict']}  score {aud['score']:.3f}  "
                  f"(whole {aud['whole']:.2f}, torso {aud['torso']:.2f}, "
                  f"head {aud['head']:.2f}, mirror {aud['mirror_iou']})")
        print("next: python scripts/check_facing.py " + a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
