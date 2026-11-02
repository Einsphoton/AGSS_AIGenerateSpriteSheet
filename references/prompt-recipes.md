# Prompt recipes for actions outside the presets

The presets (`walk`, `run`, `idle`, `attack`, `cast`, `hurt`, `jump`) cover the
common cases. When the user asks for something else, build it from the patterns
below and pass it via `--describe`.

## The shape every recipe follows

```
<setup: view + constraint, already handled by make_prompt.py>
Beat 1 (0.00): starting pose / wind-up
Beat 2 (~0.30): the main motion, fast
Beat 3 (~0.60): contact / extreme / apex
Beat 4 (~0.85): recovery
<close: final pose == opening pose>
<limits: only these parts move>
```

Two rules that matter more than the wording:

1. **Name the extremes, not the path.** "the arm drawn back across the body"
   and "the arm whipped forward in a flat arc" will interpolate correctly.
   "the arm moves smoothly" will not.
2. **One action per clip.** Two actions in one render produce a smeared average
   of both.

---

## Locomotion variants

**Sneak / crouch walk**
```
the body stays low the whole time, knees bent, weight on the balls of the feet,
the torso leaning forward; the boots slide forward one at a time barely leaving
the ground, the hem hanging low
```
limits: legs, torso, skirt, cape

**Carry / haul (arms occupied)**
```
both arms held forward at chest height carrying a heavy weight, elbows bent,
the torso leaning back to counterbalance; the legs take short heavy steps and
the body dips deeper at each contact
```
limits: legs, torso, skirt, cape — **not** arms (they hold their pose)

**Turn in place**
```
the character pivots on the spot: the torso rotates first, the head following,
then the feet step around to catch up, ending back in the opening stance but
having described a full turn
```
limits: everything; this one needs the camera lockoff most of all

---

## Combat

**Overhead chop**
```
the weapon arm draws up and back over the shoulder, the torso rotating away;
the arm drives down and forward in a single fast chop, the front foot planting
at the same instant; the weapon stops low and forward, the body settling into
the follow-through; then the arm lifts back to guard
```
limits: arms, torso, legs, skirt, cape

**Thrust / stab**
```
the weapon arm pulls back to the hip, the shoulder turning away; the arm
extends straight forward as the front foot slides ahead, the torso driving
behind it; the arm holds at full extension for a beat; then retracts to guard
```
limits: arms, torso, legs

**Block / parry**
```
the weapon comes up across the body at chest height, both hands on it, the
torso turning slightly; the impact lands and the arms absorb it, the body
pushed back a little; then the weapon lowers back to the opening stance
```
limits: arms, torso, legs, cape

**Charged cast**
```
both hands draw together at the chest and stay there while the body crouches
slightly, gathering; the hands press forward and out as the torso rises and
leans in; the arms hold extended, hands open, cape and plume blown back; then
the arms draw in and the body returns to the opening stance
```
limits: arms, torso, skirt, cape, plume

Note: H3 will **not** render a fireball, lightning, or any new object reliably.
Add VFX in the engine, or as a separate layer. Prompt the *body* doing the cast.

---

## Reactions

**Hit, light**
```
the torso snaps back a few degrees, the head recoiling, the arm on the struck
side flinging outward; the body catches itself and straightens back to the
opening stance over the rest of the clip
```
limits: torso, arms, cape, plume

**Hit, heavy / knocked down**
```
the whole body folds backward from the impact, one foot lifting as the weight
goes; the character drops to one knee, an arm out for balance; then pushes back
up to standing over the second half of the clip
```
limits: everything

**Death / collapse**
```
the body goes limp from the legs up: knees buckle first, the torso folds
forward, the arms fall; the character drops to the ground and settles
```
limits: everything. **No `close` sentence** — a death does not loop. Pass
`--describe` and expect the last frame to be the ground pose.

---

## Idle variants

**Combat idle (bouncing)**
```
weight shifting foot to foot in a slow rhythm, the weapon held ready and moving
slightly with the shift, the shoulders loose, the cape swaying with each shift
```
limits: everything, small amplitude

**Look around**
```
the head turns to one side first, the torso following a beat later, holding;
then turns back through centre to the other side and returns
```
limits: head, torso, plume

**Sheathe / draw**
```
the weapon arm crosses the body and the blade slides down toward the hip,
the free hand coming up; the hand releases and the arm drops; then the free
hand rises to the hilt and the blade comes back up to guard
```
limits: arms, torso

---

## Multi-view notes

- Render **front, back, and one side**. Mirror the side.
- The side view is the hardest: a character with props close to the body will
  read ambiguously. Check the reference first (see `pitfalls.md#first-frame-dominance`).
- If a view consistently produces a worse clip for a given action (common with
  a big cape from behind), it is legitimate to render only two views and let the
  user decide whether to include a fourth.
- Actions with asymmetric arms (thrust, chop) look best from the side; symmetric
  ones (cast, block) look best from the front.

---

## When to give up on a prompt and change the input

Stop rewriting the prompt when:

- the same structural error appears in the same frame range across three
  different phrasings
- the error is present in frame 1 (that is the reference, not the prompt)
- the error is "an extra/missing limb or prop" rather than "wrong motion"

In all three cases the model is faithfully reproducing something in the
reference. Re-draw or re-generate the reference image, or accept the frame
picking workload.
