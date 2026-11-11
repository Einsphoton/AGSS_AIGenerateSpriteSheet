# What breaks H3 sprite-sheet generation, and the fix

Every item here cost real renders to find. Read this before writing prompts or
concluding that "the model can't do it".

---

## Seeds: the single biggest lever on cross-view consistency

Four views are four independent renders. H3 decides its own tempo each time, so
"walk" in the front view may take two strides while the side view takes one and
a half. Measured on the same prompt with mixed seeds: a **33% spread** in
frames-per-stride. With one shared seed and identical beat wording: **9%**.

**Do**: submit all views in one batch, same seed, same frame count, same beat
sentences. `generate.py` does this; keep it that way.

**Don't**: tune one view at a time to "match" another. You are chasing a moving
target — the next render moves it again.

---

## Legibility: prompt what is visible, not what is anatomically true

A character in a long skirt, robe, or tabard has legs that the camera cannot
see. Writing `legs must be clearly readable` does nothing; the model has no
pixels to read.

Prompt the **visible consequence** instead:

| Instead of | Write |
| --- | --- |
| legs step alternately | the hem lifts and parts on the stepping side, the whole boot visible outside it |
| heels lift | the back boot rises onto its toe, sole angled up |
| knees bend | the skirt front pushes out as the knee comes up |
| from behind, walk away | the rear hem swings and you can see the sole of the lifted boot |

This is the difference between a front walk that reads as walking and one that
reads as standing with a slight bob.

---

## Negations are inverted

H3 is an image-to-video model; it does not parse negation. `no third sword`,
`never raise the blade`, `don't turn` all put the forbidden noun into the prompt
and *increase* it. Measured: adding "no third sword" made the extra blade more
common, not less.

Rewrite as a positive statement about where things **are**:

| Don't write | Write |
| --- | --- |
| no extra blades | exactly two blades, one at each hip |
| don't swing the weapon | the weapon hangs at the hip and rides the body bob |
| camera doesn't move | the camera is locked off |
| never the same foot twice | alternate strictly: left, right, left |

(The one exception: `never travels across the frame` and `never the same foot
twice` in the beat sheet are about the *action*, not a physical object, and were
measured to work. Keep them.)

---

## Thin, high-contrast props get re-invented

A thin long prop that crosses the body — sword blade, staff, tail, ponytail —
has no object permanence. Watch for it: the model redraws it from scratch every
few frames, and once two of them overlap a third appears.

Two fixes, in order of preference:

1. **Anchor it to a body part and keep it still relative to that part.** "Each
   blade is an extension of its own fist: the grip and angle relative to that
   fist stay the same, so the blade swings with the hand." This gives the prop a
   physical owner so it does not float.
2. **Accept that you will be picking frames.** Some frames will be wrong. The
   studio exists precisely so the user can drop them.

**Measured failure shapes** (useful for diagnosing a bad clip):

- the prop turns into a *wide squat slab* lying across the hips/belly — this is
  the model losing the silhouette, and it reads as "a weapon strapped to the
  belt"
- a *detached fragment* appears near the hand — the model drew the tip
  separately
- count goes 2 → 3 → 4 over the clip — two props overlapping

**What does not work**: describing the count in negative terms, promising it
will not move at all, or moving the anchor from the body to the hip (that
literally tells the model to belt-mount it).

---

## First frame dominates

H3 is image-to-video. The reference image is the ground truth; the prompt is a
suggestion. If they disagree, the reference wins — always.

Practical consequence: **if the reference has a structural problem, no prompt
will fix it.** Two examples from real runs:

- reference had both weapon hilts within 41 px of each other on the side view,
  so the model read "one hand, two weapons" and produced exactly that for the
  whole clip. Front view, where the hands were 178 px apart, was always correct.
- reference showed the far arm hidden behind the torso, so the model omitted it,
  and a hand appeared not to hold anything.

**Check the reference against the prompt before spending a render on it.** Open
it, count the limbs, count the props, ask "does this drawing already say what I
am about to ask for?" If not, fix the drawing (re-generate or re-draw the
reference), not the prompt.

---

## Props in the reference become props in the output

Same mechanism as above, one level up: H3 inherits **props** from the reference
as readily as it inherits silhouette. A proxy mannequin holding two swords does
not mean "here is a generic body" — it means "this body has two swords", and the
character pass reproduces them. An unarmed character comes back armed; a staff
user gets a proxy whose prop fights their own.

This is why the bundled proxy has **empty hands**, and why `--weapon` exists only
for the cases where the prop *is* the motion (a shaft's arc, a bow's open limb, a
two-handed grip). The prop belongs to the character pass, which owns it through
`--subject` and the character's own reference.

Two rules that follow:

- **Never remove an inherited prop with wording.** "no swords" is a negation, and
  negations are inverted (see above) — it produces more swords.
- **Match the two passes.** If the proxy has a blade, the character pass's
  `--subject` has to name the same thing, or the second pass spends its attention
  deleting the blade instead of following the beats.

---

## Front and back look the same

The most expensive version of *first frame dominates*, and the only one where a
prompt cannot help at all: if the front and back views of the reference are the
same picture, then "pure rear view, the character facing away from the camera"
contradicts the reference, and H3 resolves that by turning the figure around
mid-clip — or by playing the whole back direction chest-first.

Measured on the mannequin that used to ship with this skill: dominant torso
colour `(240, 208, 144)` on the front **and** `(240, 208, 144)` on the back,
colour separation `0.0`. One drawing, two filenames.

**The rule: the two sides differ in material, never in outline.** Silhouette is
what the character pass inherits, so an extra bump on the proxy becomes a
backpack on the character.

| do | don't |
| --- | --- |
| a back panel / mantle / cape over the upper back | a slightly different shade of the same colour |
| lacing, straps, a spine seam, visible stitching | anything that adds to the outline |
| an emblem on the chest and a bare back | a marker on one forearm or one boot |
| a stained nape, or a helm crest at the back of the head | a marker colour that matches the chroma key |
| toes at the front of the foot, heels at the back | leaving the feet identical |

Measure it instead of arguing about it:

```bash
python scripts/check_facing.py views/            # PASS / WEAK / FAIL
```

`generate.py` runs this before submitting. The bundled mannequin scores `0.44`
(leather back panel + stained nape, silhouette `IoU 0.99` unchanged); the old one
scores `0.05`. Full diagnosis, and the equivalent moves for a character
reference, in [`facing.md`](facing.md).

The prompt half of the fix is already in `make_prompt.py`: every view now
enumerates what the camera can see, and locks the camera for the whole clip.
Override the enumeration with `--anchor back="…"` when the character has its own
markers.

---

## The frame is a crop, and H3 copies it

A reference that fills its canvas is read as "this is the whole character, and
the frame edges are where it ends". The render then holds that framing, so the
first time a sword sweeps outward it leaves the frame — and comes back as a
stump, or a blade cut flat along the top edge.

Real numbers from one run: `split_views` crops to the bounding box, so the
reference came out at **98% of its own canvas**. The rendered clip came back with
the figure at 96% of a 768 px frame, and **29 of 39 front-view frames had the
plume and blade sliced off at the top**. Nothing in the prompt asked for that;
the reference did.

The fix is one step, before rendering:

```bash
python scripts/prep_ref.py views/ --action attack    # or let generate.py do it
```

- square canvas sized from the figure, figure at **48%** for arc-heavy actions
  (`attack cast throw punch kick`), **58%** otherwise
- one shared scale for all four views, so the narrow side view stays narrow
- composited onto the key colour → also kills the black first frame that a
  transparent PNG produces

Two failure modes are easy to confuse here:

| symptom | cause | fix |
| --- | --- | --- |
| blade/plume cut flat at the *top* | figure too tall for the frame | more top margin → lower `--coverage` |
| blade cut at the *side* mid-swing | arc leaves the standing bbox | same, plus keep the blades parallel rather than sweeping them wide |

`scripts/qc.py frames <dir>` measures it: the longest unbroken run of foreground
along each of the four frame borders. A couple of frames grazing the edge is
normal for a wide arc; ten or more means the framing is wrong.

---

## Frame count is on a grid

`length % 17 == 5`. Valid: 5, 22, 39, 56, 73, 90, 107, 124. Asking for 50
silently gives you 56. `snap_length()` rounds up and prints a note.

For a walk cycle, 56 frames ≈ 2.3 s at 24 fps ≈ two full strides. That is a good
default; 39 is the minimum that still gives you a usable loop.

---

## Beat structure beats adjectives

H3 responds to *sequence and timing* far more than to descriptive adjectives.
"Dynamic", "powerful", "smooth" do nothing. What works is naming the beats and
when they happen:

```
At 0.00 seconds, the near foot swings forward and plants ahead of the far foot.
At 0.58 seconds, both feet gather under the hips and the body rises.
At 1.17 seconds, the far foot swings forward and plants ahead.
At 1.75 seconds, gather and rise back to the opening stance.
```

`make_prompt.py` builds this from `PRESETS[action]["beats"]` with fractions, so a
new action is data:

```python
"slash": {
    "strides": 1,
    "limits": ["arms", "torso", "skirt", "cape"],
    "beats": [
        (0.00, "the arm draws back across the body, weight loading onto the back foot"),
        (0.30, "the arm whips forward in a flat horizontal arc, the torso rotating into it"),
        (0.60, "the strike finishes across the far side, the leading foot planted"),
        (0.85, "the arm recovers back to guard"),
    ],
    "close": "The final pose matches the opening pose so the chain can be looped.",
}
```

---

## The loop will not close unless you say so

Without an explicit instruction, the last frame does not match the first and the
animation pops on repeat. Every preset's `close` sentence says the final pose
returns to the opening stance. Keep it.

Verify by eye: open the exported sheet, look at column 1 and column N side by
side. If they differ in leg position, the loop will pop.

---

## Chroma key needs a clean backdrop

Ask for `a completely flat pure chroma green background (#23E914): no ground
plane, no shadow, no extra props`. A cast shadow gets partially keyed and leaves
a dirty grey edge around the feet that no tolerance setting cleans up.

If the character has green in its design (green armour, green cloak), pick a
different key colour in the studio and say so — the default green will eat the
costume. `generate.py` now scores green / magenta / cyan against the character's
own pixels and picks one that does not already exist in the costume, printing the
clash percentage; `--key magenta` (or `#FF00FF`) overrides. The prompt wording
follows that choice, so the backdrop and the key agree.

The other half of this: **a transparent reference gives a black first frame.**
H3 echoes the reference as frame 1, and an RGBA PNG pasted on black is a black
frame. `prep_ref.py` composites onto the key colour first, which is why the
prepared file — not the split file — is what gets uploaded.

---

## Alignment is a within-run decision, not a per-frame one

Per-frame bounding-box alignment makes the sprite jitter horizontally by 5–8 px
because the bbox width changes as the cape and weapons move. Use a
**direction-level constant anchor** instead (the studio's `footlock` default):
measure the anchor once per direction and hold it for every frame in that
direction. Body bob is preserved; horizontal jitter disappears.

Also: all views must share **one** scale denominator and **one** cell size, or
their heights will disagree and the comparison preview becomes useless.
