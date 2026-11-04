"""Turn a plain-language animation request into an H3 prompt for one view.

The whole point of this file is that **the animation is data, not code**. A new
action ("attack with an overhead swing", "cast a fireball", "take a hit and
stagger back") is a new preset or a new sentence — never a new script.

Two levels of customisation:

  1. ``--action walk`` picks a preset from PRESETS (walk / run / idle / attack /
     cast / hurt / jump / custom).
  2. ``--describe "..."`` appends your own beat text; with ``--action custom``
     it replaces the preset's performance section outright.

Everything that makes H3 output usable as a sprite source lives in CONSTRAINTS
and is not optional. Read the comments before editing them.

    python make_prompt.py --view right --action walk --out prompt.txt
    python make_prompt.py --view front --action attack \
        --describe "a single overhead chop with the right arm" --out p.txt
    python make_prompt.py --view right --action walk --subject-file subject.txt
    python make_prompt.py --view right --action walk --print-context
"""

from __future__ import annotations

import argparse
import json
import os
import re

# --------------------------------------------------------------------------
# Constraints that keep the output usable as sprite frames.
# Do not trim these casually — each one exists because its absence broke a
# real pipeline run:
#   lockoff ....... any camera drift destroys frame-to-frame alignment
#   in place ...... sprites loop in place; translation is the engine's job
#   last==first ... H3 will not close the cycle without being told
#   no shadow ..... a cast shadow gets eaten by the key and leaves a dirty edge
# --------------------------------------------------------------------------
# The key colour must never appear in the costume. Green armour / a green cloak
# under a green key gets keyed out with the backdrop. Override per run:
#   SPRITE_KEY_NAME=magenta SPRITE_KEY_HEX=#FF00FF
# and pick the same colour with the studio's 吸管取色 (or ?key=ff00ff).
KEY_NAME = os.environ.get("SPRITE_KEY_NAME", "chroma green")
KEY_HEX = os.environ.get("SPRITE_KEY_HEX", "#23E914")

CONSTRAINTS = (
    "2D pixel-art animation, crisp hard-edged pixels, limited palette, no "
    "anti-aliasing, no blur. The single subject from <Picture 1> keeps "
    "identical proportions, colors, and costume details. Full body, centered, "
    "occupying about 70% of the frame height, over a completely flat pure "
    f"{KEY_NAME} background ({KEY_HEX}): no ground plane, no shadow, no extra "
    "props, no text. The camera is locked off: no pan, no tilt, no zoom, no "
    "shake, no rotation of the subject. The character never travels across the "
    "frame."
)

# Views. 'left' and 'right' are the same clip mirrored; generate one of them.
VIEWS = {
    "front": ("pure frontal view, the character facing the camera directly",
              "its front to the camera"),
    "back": ("pure rear view, the character facing away from the camera",
             "its back to the camera"),
    "right": ("pure profile, the character's right flank to the camera, "
              "facing the right edge of the frame",
              "its right flank to the camera"),
    "left": ("pure profile, the character's left flank to the camera, "
             "facing the left edge of the frame",
             "its left flank to the camera"),
}

# --------------------------------------------------------------------------
# Action presets. `beats` is a list of (fraction_of_clip, sentence).
# Keep the sentences in the same grammatical shape so the rhythm wording stays
# comparable between actions — H3 responds to beat structure, not frame counts.
# --------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "walk": {
        "label": "走路循环",
        "strides": 2,
        "limits": ["legs", "arms", "the lower garment"],
        "beats": [
            (0.00, "the NEAR foot swings forward in a clear arc, knee lifting "
                   "high enough to push the hem up, and plants ahead of the far "
                   "foot; the far foot pushes back so the stride is wide"),
            (0.25, "both feet gather under the hips and the body rises to the "
                   "passing pose"),
            (0.50, "the FAR foot swings forward and plants ahead while the near "
                   "foot drives back — the legs visibly swap places"),
            (0.75, "gather and rise, then land back on the opening stance"),
        ],
        "close": "The final pose matches the opening pose so the last frame can "
                 "be followed directly by the first.",
    },
    "run": {
        "label": "跑步循环",
        "strides": 2,
        "limits": ["legs", "arms", "the lower garment"],
        "beats": [
            (0.00, "the NEAR knee drives up high and the near foot reaches "
                   "forward, the far leg extended far back, the torso leaning "
                   "forward and the body low"),
            (0.25, "both feet leave the ground and the body rises into a short "
                   "airborne passing pose, legs tucked"),
            (0.50, "the FAR knee drives up and the far foot reaches forward "
                   "while the near leg kicks back — the legs swap places"),
            (0.75, "airborne again, then the near foot strikes and absorbs the "
                   "landing back into the opening stance"),
        ],
        "close": "The final pose matches the opening pose so the last frame can "
                 "be followed directly by the first.",
    },
    "idle": {
        "label": "待机呼吸",
        "strides": 1,
        "limits": ["torso", "arms"],
        "beats": [
            (0.00, "the character stands with the weight settled, shoulders low"),
            (0.30, "the chest rises a little as it inhales, the loose parts of "
                   "the costume lifting slightly"),
            (0.60, "the chest settles as it exhales, those parts drifting back down"),
            (0.85, "a small weight shift between the feet, then back to rest"),
        ],
        "close": "The last frame matches the first so the loop is seamless. The "
                 "feet stay planted the whole time.",
    },
    "attack": {
        "label": "攻击一次",
        "strides": 1,
        "limits": ["arms", "torso", "legs"],
        "beats": [
            (0.00, "the character winds up, the weapon arm drawing back and up "
                   "while the torso rotates away from the target"),
            (0.25, "the arm drives forward and down in a single fast strike, the "
                   "torso rotating into the blow, the front foot planting"),
            (0.50, "the strike lands and the body settles into the follow-through, "
                   "the weapon arm extended"),
            (0.75, "the arm recovers and the torso unwinds back toward the "
                   "opening stance"),
        ],
        "close": "The final pose matches the opening pose so a chain of attacks "
                 "can be looped.",
    },
    "cast": {
        "label": "施法",
        "strides": 1,
        "limits": ["arms", "torso"],
        "beats": [
            (0.00, "the character brings both hands together in front of the "
                   "chest"),
            (0.30, "the hands push forward and apart as the torso leans in, the "
                   "loose parts of the costume pulled back by the motion"),
            (0.60, "the arms hold the extended pose, hands open, a beat of "
                   "stillness at full extension"),
            (0.85, "the arms draw back in and the body returns to the opening "
                   "stance"),
        ],
        "close": "The final pose matches the opening pose so the cast can be "
                 "looped or held.",
    },
    "hurt": {
        "label": "受击后仰",
        "strides": 1,
        "limits": ["arms", "torso", "legs"],
        "beats": [
            (0.00, "the character stands in the opening stance"),
            (0.20, "impact: the torso snaps backward, the head recoiling, the "
                   "arms flinging outward"),
            (0.50, "the body staggers back half a step, one foot lifting to "
                   "catch the weight"),
            (0.80, "the character recovers and straightens back into the opening "
                   "stance"),
        ],
        "close": "The final pose matches the opening pose.",
    },
    "jump": {
        "label": "跳跃",
        "strides": 1,
        "limits": ["legs", "arms", "torso"],
        "beats": [
            (0.00, "the character crouches, knees bending deeply, arms swinging "
                   "back"),
            (0.25, "the legs extend and the body launches upward, arms swinging "
                   "up, the loose parts of the costume snapping downward"),
            (0.55, "the apex: the body is at its highest, legs tucked, those "
                   "parts floating"),
            (0.85, "the legs reach down and the character lands back in the "
                   "opening crouch"),
        ],
        "close": "The final pose matches the opening pose.",
    },
}

# What may move. Deliberately neutral: a slime has no legs, a mech has no cape.
# Presets narrow this list; when nothing fits, use --limits.
DEFAULT_LIMITS = ["legs", "arms", "torso"]

# --------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------

HEAD = ("For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")

TAIL = ("overall_soundscape: Complete silence. No footsteps, no cloth rustle, "
        "no ambient room tone.\n\nnon_diegetic_music: None.")


def beat_sheet(view: str, action: str, total_seconds: float,
               describe: str | None = None) -> str:
    """Human-readable timeline. H3 wants wall-clock seconds, not frame numbers."""
    preset = PRESETS.get(action)
    if describe:
        performance = describe.strip()
        if not performance.endswith("."):
            performance += "."
        if action in PRESETS:
            performance = (f"The action is {preset['label'] if 'label' in preset else action}: "
                           f"{performance}")
        else:
            performance = f"The action described: {performance}"
        return performance

    if not preset:
        raise SystemExit(f"unknown action '{action}' — pass --describe or one of "
                         f"{', '.join(PRESETS)}")

    parts = []
    for frac, sentence in preset["beats"]:
        t = frac * total_seconds
        parts.append(f"At {t:.2f} seconds, {sentence}.")
    parts.append(preset["close"])
    return " ".join(parts)


def limit_sentence(limits: list[str]) -> str:
    """Say what is allowed to move. Positive framing only — H3 drops negations."""
    if not limits:
        return ""
    names = ", ".join(limits[:-1]) + (" and " + limits[-1] if len(limits) > 1 else limits[0])
    return (f"Throughout, only the {names} move; everything else in the "
            f"character and the background stays pixel-identical.")


def build_prompt(view: str, action: str, subject: str, seconds: float,
                 describe: str | None = None,
                 limits: list[str] | None = None,
                 extra: str | None = None) -> str:
    if view not in VIEWS:
        raise SystemExit(f"view must be one of {', '.join(VIEWS)}")
    vdesc, _ = VIEWS[view]
    preset = PRESETS.get(action, {})
    lim = limits if limits is not None else preset.get("limits", DEFAULT_LIMITS)

    setup = CONSTRAINTS.replace(
        "The single subject from <Picture 1>",
        f"The single subject from <Picture 1> — {subject.strip()} —"
    )
    setup += f" The view is {vdesc}."

    body = f"{beat_sheet(view, action, seconds, describe)} {limit_sentence(lim)}"
    if extra:
        body += " " + extra.strip()

    return (f"{HEAD}\n\nintegrated_multimodal_description: [Shot 1] "
            f"{setup} {body}\n\n{TAIL}")


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", required=True, help="front / back / right / left")
    ap.add_argument("--action", default="walk", help=" / ".join(PRESETS) + " / custom")
    ap.add_argument("--subject", default="", help="one-line character description")
    ap.add_argument("--subject-file", help="read --subject from a file instead")
    ap.add_argument("--describe", help="your own beat text (overrides the preset)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="clip length in seconds; default derives from --frames")
    ap.add_argument("--frames", type=int, default=56)
    ap.add_argument("--limits", help="comma list of what may move")
    ap.add_argument("--extra", help="one extra sentence appended to the body")
    ap.add_argument("--out", help="write the prompt here")
    ap.add_argument("--print-context", action="store_true",
                    help="print a short JSON summary instead of the prompt")
    args = ap.parse_args()

    subject = args.subject
    if args.subject_file:
        with open(args.subject_file, encoding="utf-8") as f:
            subject = f.read().strip()
    if not subject:
        subject = "the character shown in the reference"
        print("note: no --subject given; using a generic description. Pass "
              "--subject with the character's look for better identity retention.",
              file=__import__("sys").stderr)

    seconds = args.seconds
    if seconds is None:
        seconds = max(0.3, args.frames / 24.0)

    limits = None
    if args.limits:
        limits = [s.strip() for s in args.limits.split(",") if s.strip()]

    prompt = build_prompt(args.view, args.action, subject, seconds,
                          args.describe, limits, args.extra)

    if args.print_context:
        print(json.dumps({
            "view": args.view, "action": args.action, "seconds": round(seconds, 3),
            "frames": args.frames, "chars": len(prompt),
        }, indent=1, ensure_ascii=False))
    elif args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(prompt + "\n")
        print(f"wrote {args.out}  ({len(prompt)} chars)")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())