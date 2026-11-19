# The storyboard — one script, four directions

A sprite sheet needs the same action from three or four cameras. H3 gives you
each camera as an **independent sample**: it has no memory of the previous call,
so nothing carries over except what you literally write into the next prompt.

What that costs, measured on this pipeline:

| what was varied between views | result |
| --- | --- |
| the seed | up to **33%** stride spread (9% when shared) |
| the wording of the beats | the views perform the motion in a different order |
| `--frames`, `--coverage`, `--key` | one direction is zoomed, or keyed differently |
| nothing — same seed, same text, same numbers | the four clips cut together |

A storyboard is that "nothing". It is one JSON file holding the beats, the times,
the per-view evidence and every parameter the views share; `generate.py
--storyboard` reads it and refuses to vary the shared half.

It is **not** a camera storyboard. The camera never moves in a sprite pass — the
"shots" here are the four directions, and they are supposed to be similar, not
different. What is being storyboarded is the *performance*: which extremes happen
and in what order, which is the only thing that makes four renders one animation.

## The file

```json
{
 "schema": "pixel-sprite-storyboard/1",
 "action": "walk",
 "label": "走路循环",
 "kind": "loop",
 "note": "散步速度，两步一个循环，手空着",
 "subject": "a chibi armored warrior with a red horsehair plume and a long red cape",
 "fps": 24,
 "frames": 56,
 "seed": 808080,
 "key": "auto",
 "coverage": "auto",
 "limits": ["legs", "arms", "torso", "cape"],
 "invariants": [
  "identical proportions, colors and costume details in every frame",
  "the camera is locked off for the whole clip",
  "the weight stays over the feet and a planted foot never slides",
  "every beat lands at its stated second, in every direction"
 ],
 "beats": [
  {"frac": 0.00, "mark": "迈步",
   "motion": "the near foot swings forward in a clear arc, knee lifting high enough to push the hem up, and plants ahead of the far foot; the far foot pushes back so the stride is wide"},
  {"frac": 0.25, "mark": "过渡",
   "motion": "both feet gather under the hips and the body rises to the passing pose",
   "see": {"right": "the front leg straightens under the hip while the back leg lifts behind it"}},
  {"frac": 0.50, "mark": "换腿",
   "motion": "the far foot swings forward and plants ahead while the near foot drives back — the legs visibly swap places"},
  {"frac": 0.75, "mark": "归位",
   "motion": "gather and rise, then land back on the opening stance"}
 ],
 "close": "The final pose matches the opening pose so the last frame can be followed directly by the first.",
 "views": {
  "front": {"anchor": "the red chest emblem, both shoulder guards and the face under the plume"},
  "back":  {"anchor": "the long red cape hanging over the whole back and the plume from behind"},
  "right": {}
 },
 "renders": []
}
```

## Field by field

| field | why it exists |
| --- | --- |
| `action` | names the run: frame folder, video files, `videos/index.json`. Keep it one word |
| `kind` | `loop` \| `one-shot` \| `death`. Decides whether a `close` sentence is required (`loop`), optional (`one-shot`) or forbidden (`death`) |
| `note` | one line of intent in the user's own words. Never enters a prompt; it is what you read in six weeks |
| `subject` | the character, in one sentence, **written from the reference image**. The only place costume is described |
| `frames` | snapped to H3's grid (…, 39, 56, 73, …). The value the JSON asked for is kept and reported if it had to move |
| `seed` | one number for the whole batch. This is the single strongest lever for matching tempo |
| `key` | `auto` unless you have a reason. `auto` scores green/magenta/cyan against the character's own pixels |
| `coverage` | figure size on the square reference canvas. `auto` = 0.48 for arc-heavy actions, 0.58 otherwise |
| `limits` | what may move. **Must name the loose pieces the character actually has** (cape, plume, skirt, tail) or they stay rigid |
| `invariants` | the consistency contract, appended to every prompt as one sentence. Action-specific ones go here too |
| `beats[].frac` | *when*, as a fraction of the clip. Canonical: change `frames` and the performance rescales instead of truncating |
| `beats[].mark` | a 2–4 character label for the 分镜表. Humans only |
| `beats[].motion` | the extreme, in one sentence. Every view gets this sentence verbatim |
| `beats[].see.<view>` | optional: how that beat *looks* from one camera. Only that view's prompt |
| `close` | the loop/seal instruction — "the final pose matches the opening pose". Omit for `death` |
| `views.<view>.anchor` | what the camera sees in that direction. This is also the facing evidence (`facing.md`) |
| `renders` | written by `generate.py` and `record`: version, attempt, QC verdict, seed, coverage, clips |

## Writing the beats

**Three to five beats. Extremes, not paths.**

```
good:  "the arm draws back across the body, the torso rotating away"
bad:   "the arm moves smoothly"            ← nothing to interpolate toward
bad:   "the character attacks"             ← two actions, neither survives
```

The preset shapes are worth copying because they are known to read:

- **loop** (walk, run, idle): two strides — 0.00 near extreme, 0.25 passing,
  0.50 far extreme, 0.75 passing, then close on the opening pose.
- **one-shot** (attack, cast, hurt): 0.00 wind-up, 0.25–0.30 the drive,
  0.50–0.60 contact/extreme, 0.85 recovery, then close.
- **death**: no close. The last beat *is* the ground pose, and the clip ends
  there.

Rules that `check` enforces or warns about, and why:

- **`frac` strictly increasing, first at 0.00.** A beat before the opening beat
  means the head of the clip has no instruction and H3 improvises one.
- **Each beat at least 4 frames long** (≈0.07 of a 56-frame clip). Shorter than
  that and the extreme is absorbed into its neighbour — you wrote it, it never
  renders.
- **The last beat before ~0.62 of the clip.** Beat text written for a 39-frame
  clip rendered at 56 frames ends at 55% and the model *holds* the final pose for
  a second. Either spread the fractions or lower `frames`.
- **No negations** (`no`, `not`, `never`). H3 drops them and often inverts them:
  "no third sword" produces swords. Say what is there.
- **Name what can be seen.** "the boots cross" reads from every camera; "the left
  knee bends inward" does not read from the back.

## Per-view evidence — `see`

The same sentence projects differently from each camera, and leaving that to
inference is how a side view invents a different motion. One short line per beat,
only where it is not obvious:

| action | beat | `see` |
| --- | --- | --- |
| slash | 0.30 drive | `right`: "the blade sweeps past the chest edge and out toward the right of the frame" |
| cast | 0.30 push | `front`: "both hands separate outward at chest height" · `right`: "the near arm crosses in front of the torso" |
| walk | 0.25 passing | `right`: "the front leg straightens under the hip while the back leg lifts behind it" |
| hurt | 0.20 impact | `back`: "the shoulders snap back and the cape ripples outward" |

Use it for 1–2 beats, not all of them. Each line adds ~20 words to one prompt;
twenty of them turn the prompt into a script H3 reads as a list of instructions
rather than a performance.

## The consistency contract

**Shared by every view:** `beats`, `close`, `seed`, `frames`, `fps`, `coverage`,
`key`, `limits`, `subject`, `invariants`.

**May differ per view:** `anchor` (what that camera can see) and `see` lines.
Both are *evidence about one camera*, never a change of motion.

That is the whole idea, and both halves are enforced:

1. **In the prompt** — every view is told its beats, timing, weight and
   silhouette are identical to the other passes, and that each beat time is
   exact. `make_prompt.build_prompt(board=…)` writes that sentence;
   `generate.py` prints where each shared value came from (`board` / `flag` /
   `default`) so a leftover flag cannot quietly split the batch.
2. **After the render** — `qc.py` gates each view (crop, black/empty frames,
   backdrop), then `generate.py` adds a cross-view gate: median body height must
   agree within 8% (note) / 18% (fail, the frames cannot share one cell size),
   and frame counts must match across views. A fail is recorded in `renders`.

Rhythm cannot be measured from a still. That half is the board's job — same
beats, same seed, same frames — and the clip is the only thing that proves it.

## `check` — reading the messages

An **ERROR** means do not render: `generate.py` refuses the board. A **warn**
means the render will probably work but the reason it might not is known.

| message | cause | fix |
| --- | --- | --- |
| `beats must strictly increase` | two beats at the same time, or one moved earlier | reorder or retime; a clip cannot show two poses at once |
| `only one beat` | the whole action in one blob (usually straight `--from` prose) | split it into 3–5 "At X seconds …" sentences |
| `lasts N frames … it smears` | beat gap under 4 frames | move the neighbour or lower `frames` |
| `the last beat is at 0.55 of the clip` | beat text written for a shorter clip | spread the fractions, or set `frames` to what the text was written for |
| `subject still contains a TODO marker` | generated from a template, never filled in | describe the character from the reference |
| `subject contains a negation` | "no cape" | describe the positive: "a short cape over the shoulders" |
| `a loop needs a close sentence` | `kind: loop` without a seal | add "the final pose matches the opening pose" |
| `a death does not loop` | `kind: death` with a close sentence | drop `close`, or use `one-shot` |
| `left and right declared` | two renders for one direction | declare `right` only; `mirror.py` makes `left` |
| `frames N is not on H3's grid` | 60, 48, 100 … | harmless: it is loaded as the next valid value, and the beat times follow |
| `coverage 0.9 is outside 0.34–0.70` | figure too big (arc gets cropped) or too small (loses pixels) | `0.42`–`0.48` for arc actions, `0.55`–`0.60` otherwise |

## The loop: render → record → edit → re-run

```bash
python scripts/storyboard.py check  beats/walk.storyboard.json
python scripts/storyboard.py table  beats/walk.storyboard.json --out beats/walk.md
python scripts/storyboard.py prompts beats/walk.storyboard.json --out-dir frames/walk/_prompts
python scripts/generate.py --views views --out frames/walk \
  --storyboard beats/walk.storyboard.json
```

`generate.py` writes `frames/walk/storyboard.json` (the exact board this run
used, plus the resolved key/coverage) and appends to `renders` in the source
board. So "which beats produced v03" is answered by the folder, not by memory.

When a re-run is needed, **change one thing** and let the record say what it was:

| the problem | change | do not change |
| --- | --- | --- |
| motion is mush, timing is right | `coverage` smaller, or route B | beats, seed |
| motion is the wrong action | `beats[].motion` (and its `see` lines) | seed, frames |
| one direction is off | that view's `anchor` / `see` | everything else |
| tempo drifts between views | nothing — check that every view actually used the board | — |
| a limb leaves the frame | `coverage` (retry once, fresh `--out`) | beats |

`renders` makes that a diff instead of a guess:

```bash
python scripts/storyboard.py record beats/walk.storyboard.json \
  --version 4 --attempt 2 --qc pass --coverage 0.42 \
  --clip front=videos/walk_v04_front.mp4 --clip back=videos/walk_v04_back.mp4
```

## Route B with a board

A proxy run is the same board twice — that is the entire reason the board exists:

```bash
# pass 1 — mannequin, empty hands, same board
python scripts/generate.py --views views_proxy --out frames/walk_proxy \
  --storyboard beats/walk.storyboard.json \
  --subject "a plain wooden artist's mannequin, empty hands, no weapon"

# pass 2 — the character, same board, same seed, same beats
python scripts/generate.py --views views --out frames/walk \
  --storyboard beats/walk.storyboard.json
```

Only `--views` and `--subject` change. `seed`, `frames`, `key`, `coverage` and
`limits` are read from the file in both passes, so they cannot drift — which was
the one thing `proxy-pass.md` had to ask the operator to remember. The proxy pass
is a motion sketch and never the deliverable; `renders` keeps its version one
number below the character pass so the two are easy to compare in the studio's
`版本化视频` dropdown.

**`--key` is an exception worth knowing**: `auto` picks per reference, and wood
on magenta / green armour on green are different answers. Pass `--key` explicitly
and identically in both passes if the two references have different palettes.
