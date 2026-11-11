# Front and back look the same

The symptom, in the user's words: *"背面动画经常出现逻辑错误，动画生成的时候分不清正面和背面"* —
the back-view clip turns the character around halfway through, or the whole
back-facing direction plays as if the character were walking chest-first.

This document is the diagnosis, the fix, and the measurement that proves the fix
landed. It is the one failure mode that a better prompt cannot solve.

---

## The root cause: the reference, not the model

H3 is image-to-video. It reads the reference far more than the prompt, and when
they disagree the reference wins (`pitfalls.md#first-frame-dominates`). So a
prompt that says *"pure rear view, the character facing away from the camera"*
in front of a drawing that looks exactly like the front view produces **a
contradiction**, and H3 resolves contradictions by drifting: the subject rotates
over the clip, or it holds the front pose and calls it a back view.

The bundled mannequin used to be precisely that. Measured on the two PNGs that
shipped as `front.png` and `back.png`:

| | old mannequin |
| --- | --- |
| dominant torso colour, front | `(240, 208, 144)` |
| dominant torso colour, back | `(240, 208, 144)` |
| colour-separation of those two | **0.0** |
| `material_tv` (share of the figure that is a different material) | **0.05** |

The two files were the same drawing with a slightly different centre panel. To a
video model they were one image, and no wording fixes that.

The same trap applies to every character reference, not just the proxy: a hooded
figure, a robed figure, a mech, a character whose back is simply unadorned. **If
you cannot tell the two sides apart in one glance at the reference, the model
cannot either.** Sort out the reference before spending a render.

---

## What the fix is not

Do not add something to the **outline**. The character pass (route B) inherits
the proxy's silhouette — that is what "same seed, same beats" buys you — so a
proxy with a backpack, a hump, or a protruding crest teaches the model to swing a
backpack. Every marker below is a flat decal or a colour block, never a shape.

Do not rely on the prompt to describe a difference the reference does not have.
Naming it helps a little (`--anchor`, below) but the reference still wins.

Do not scatter the marker on a limb. In a walk cycle the arms swing and the legs
cross; a marker on one forearm is invisible for half the frames. **Torso and
head**, where the silhouette is stable, or nothing.

---

## The fix, in three places

### 1. The reference — different material, same silhouette

The current bundled mannequin (`scripts/mannequin.py`, drawn from one skeleton
and projected four ways) splits the two sides like this:

| | front | back |
| --- | --- | --- |
| torso | pale birch | dark leather back panel |
| torso detail | leather harness in a V meeting a brass ring; brass belt buckle | light **X lacing** across the shoulder blades; vertical **spine seam** |
| head | plain pale wood | **stained walnut nape** over the lower back of the skull |
| belt | buckled | plain |
| feet | toe split | heel pad |
| profile | front half pale wood, rear half the dark panel | — |

That is `material_tv 0.44` (torso 0.28, head 0.44) against `0.05` before, with
the silhouette left at `IoU 0.99` — same shape, different material, which is the
whole point.

For a *character* reference, the equivalent moves are:

| works | why |
| --- | --- |
| a back panel, cape, or mantle that covers the upper back | large area, visible in every frame |
| lacing, straps, a spine seam, a seam of stitching | reads as a different construction, not just a different tint |
| a large emblem on the chest and nothing on the back (or the reverse) | high contrast, and it is the region the eye checks first |
| stained / bare / metallic nape or a helm crest at the back of the head | the head is small, stable, and never occluded |
| a hood down at the back vs. a collar at the front | changes the head-and-shoulder read, which is what the model uses for facing |

| does not work | why |
| --- | --- |
| a slightly different shade of the same colour | below the model's threshold at 8 px per limb |
| a marker only on one arm, hand, foot, or weapon | hidden or crossing for most of a cycle |
| anything that changes the silhouette | inherited by the character pass |
| a colour that matches the chroma key | gets keyed out with the backdrop |

If you generate a character sheet with an image model, the prompt has to ask for
the split explicitly — see the recipe at the bottom.

### 2. The prompt — name the evidence, lock the camera

`make_prompt.py` now appends two sentences to every view:

```
The view is pure rear view, the character facing away from the camera: the
camera sees the back of the head, both shoulder blades, the back of the torso
and the heels of both feet. The camera stays behind the figure for the entire
clip and the back faces the camera at every frame.
```

The first sentence enumerates what is *visible*, in plain nouns — this is the
same principle as `pitfalls.md#legibility`: prompt what is visible. The second
locks the camera, positively stated (`pitfalls.md#negations` — "the character
never turns around" would put "turn around" in the prompt).

Override the enumeration when the character has its own markers:

```bash
python scripts/generate.py --views views/ --out frames/walk --action walk \
  --subject "a chibi warrior in green scale armour" \
  --anchor "back=the tall red cape, the silver clasp at the neck and the plain hood" \
  --anchor "front=the gold chest emblem and the belt buckle"
```

`--anchor` takes `view=text` and can be repeated. A bare string applies only when
a single view is being rendered, because the same sentence on both a front and a
back prompt is itself a contradiction.

### 3. The gate — measure it before spending renders

```bash
python scripts/check_facing.py views/            # front vs back
python scripts/check_facing.py views/ --strict   # WEAK also fails
```

`generate.py` runs it automatically before submitting and prints one line plus
any warnings; `--no-facing-check` skips it.

The primary number is `material_tv`: the total-variation distance between the two
views' colour-area histograms, i.e. *what share of the figure is a different
material*. It is deliberately blind to geometry. A pixel-by-pixel comparison was
the first implementation and it lied in both directions — a silhouette off by two
pixels compared backdrop against wood along every edge and scored 0.40 for a
mannequin whose front and back were the same drawing, while a real material swap
that was slightly rotated scored less than a shading change. Areas cannot do
that: same colours in the same proportions means the same picture, however the
pixels line up.

| verdict | `material_tv` | means |
| --- | --- | --- |
| PASS | ≥ 0.22 | a fifth of the figure is a different material |
| WEAK | 0.10 – 0.22 | it differs, but expect the model to lose the facing on some frames |
| FAIL | < 0.10 | to the model these are the same picture |

Secondary checks, printed alongside: `silhouette_iou` (should be *high* — same
body), `profile_aspect` (a true profile is 0.15–0.60 wide; 0.8 is a
three-quarter view), `mirror_iou` (left and right must be mirrors, ≥ 0.90).

The bundled mannequin ships with its own receipt: `templates/mannequin/facing_contract.json`
contains the audit that `mannequin.py` ran at build time.

---

## What is measured, and what is not

Measured, and reproducible on any machine:

- the reference itself: `material_tv 0.05` before, `0.44` after, silhouette
  unchanged at `IoU 0.99`, left/right mirror `IoU 0.99`
- the audit's own separation: it scores the old mannequin FAIL and the new one
  PASS, with the old one's dominant torso colour identical on both sides
  (`sep 0.0`) and the new one's separated by 320 RGB units

**Not** measured here: the render. Verifying that the model actually holds the
facing needs a GPU and the same seed twice —

```bash
# with the old reference, then with the new one, same everything else
python scripts/generate.py --views views_proxy --out frames/back_old \
  --action walk --views-wanted back --frames 39 --seed 808080
python scripts/generate.py --views views_proxy_new --out frames/back_new \
  --action walk --views-wanted back --frames 39 --seed 808080
```

and then compare the two clips frame by frame: does the figure keep its back to
the camera for all 39 frames, and does the *nape stay on screen*? The nape is the
cheapest tell — if it disappears mid-clip, the model turned the head around.

---

## Checklist before you spend a render

- [ ] `python scripts/check_facing.py views/` prints PASS
- [ ] the two sides differ in **material**, and the outline is unchanged
- [ ] the difference is on the **torso** and/or **head**, not a limb
- [ ] the marker colour is not the chroma key
- [ ] the side views are profiles (`aspect` 0.15–0.60) and mirror each other
- [ ] `--anchor` describes the character's own markers, when it has them

---

## Regenerating the mannequin

```bash
python scripts/mannequin.py                     # -> templates/mannequin/
python scripts/mannequin.py --out /tmp/mq --scale 4 --key '#00FF00'
```

Four views are projections of one skeleton, so proportions, scale and the
head-to-heel line are identical by construction — the thing an image model is
worst at. The per-view PNGs are transparent (so `prep_ref.py` measures the bbox
exactly); `sheet_2x2.png` and `turnaround.png` are the magenta previews for a
human to eyeball.

If you would rather generate the proxy with an image model, `templates/mannequin/PROMPT.txt`
carries a prompt that asks for the same material split — then run
`check_facing.py` on the result, because an image model will not honour the
"same silhouette" rule on its own.
