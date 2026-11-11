# Route B — mannequin first, character second

Route A renders the character once. Route B renders a plain wooden mannequin
doing the motion, then renders the character doing *the same motion*, and only
the second pass becomes the sprite sheet.

Why it is worth 2× renders: H3 spends a fixed amount of attention. Given a
character with a cape, a plume, a skirt and two swords, most of that attention
goes into reproducing the costume, and the motion arrives late, half-sized and
mushy. A mannequin has nothing to reproduce, so the beats land. The second pass
then inherits the timing, because the timing is carried by the seed and the beat
text — not by the reference silhouette.

Pick it when the reference shows loose cloth, long hair, a plume, layered armour,
more than one prop, or an unfamiliar design; or when the user wants to argue
about the motion before paying for the character.

## The one rule: only two arguments may change

| must stay identical | may change |
| --- | --- |
| `--seed` | `--views` (mannequin views → character views) |
| the beat text (`--describe-file`) | `--subject` |
| `--frames`, `--size` | `--anchor` (it names what the camera sees, and the two passes see different things) |
| `--coverage`, `--key` | |

Change any of the first column and you are not re-using a motion, you are
rendering a second unrelated clip and hoping. This is the same reason
`references/pitfalls.md#seeds` exists: H3 picks its own tempo per seed.

`--key` is in that column for a subtler reason: it changes the *wording* of the
prompt (the backdrop is named in the constraints), and a green key vs a magenta
key is a different sentence. Wood on magenta and green armour on green is the
normal case — so pass `--key` explicitly and identically in both passes rather
than letting each one auto-pick.

## 1. Get a mannequin reference

The skill ships one: `templates/mannequin/{front,back,left,right}.png` — a pale
birch artist's dummy with ball joints and a featureless head, one straight short
sword in each hand, **drawn so that its front and back cannot be confused**: the
chest carries a leather harness and a brass buckle, the back carries a dark
leather panel with X lacing, a spine seam and a stained walnut nape. Same
silhouette, different material.

```bash
mkdir -p $PROJ/views_proxy
cp $SKILL/templates/mannequin/*.png $PROJ/views_proxy/
```

That distinction is the whole reason the back view renders at all — a proxy whose
two sides are the same picture makes the model turn the figure around mid-clip no
matter what the prompt says. See [`facing.md`](facing.md). If you replace the
dummy, verify the replacement before rendering:

```bash
python scripts/check_facing.py $PROJ/views_proxy     # must print PASS
```

It already holds two swords, so it is the right proxy for dual-wield, unarmed,
and most single-weapon motions (the second sword is ignored by the beats). If the
character carries something with a very different silhouette — a staff, a bow, a
shield, a greatsword, four arms — regenerate it:

```bash
python scripts/mannequin.py --out $PROJ/views_proxy # same skeleton, four views
```

`mannequin.py` draws one skeleton and projects it four ways, so proportions,
scale and the head-to-heel line cannot drift between panels. It is the reliable
path; `templates/mannequin/PROMPT.txt` is the image-model fallback, and its
output still needs `check_facing.py` to pass before it is worth a render.

Keep the proxy's framing loose. A proxy that fills its own canvas will produce a
chopped-up motion in the pass you trust most.

## 2. Proxy pass

```bash
python $SKILL/scripts/generate.py --views $PROJ/views_proxy \
  --out $PROJ/frames/${ACTION}_proxy --action $ACTION \
  --views-wanted front,back,right --frames 39 --seed 808080 \
  --describe-file $PROJ/beats/$ACTION.txt \
  --subject "a plain wooden artist's mannequin, one short sword in each hand"
```

Put the beats in a file — this text is going to be typed twice, character for
character, and a paraphrased second version will produce a different clip.

Show the clip to the user **now** (see *Non-negotiable* in SKILL.md) with the
one question that matters: `动作对不对？起手—劈砍—收势是不是你要的节奏？`
Iterating here is cheap and the clip is easy to read because there is no costume
in the way. Do not proceed on a motion the user has not approved.

## 3. Character pass

```bash
python $SKILL/scripts/generate.py --views $PROJ/views \
  --out $PROJ/frames/${ACTION} --action $ACTION \
  --views-wanted front,back,right --frames 39 --seed 808080 \
  --describe-file $PROJ/beats/$ACTION.txt \
  --subject "a chibi warrior in green scale armour, dark grey helmet, a tall red
  horsehair plume, a long red cape, one silver broadsword in each hand" \
  --limits "arms,torso,legs,cape,plume"
```

`--subject` comes from the character reference, not from the user's words — it is
the only place the costume is described, and the proxy pass proves H3 will ignore
costume details if the subject line is vague.

The character pass is *the* pass. From here it is the normal pipeline: QC (step
3b), mirror, manifest, studio.

## 4. Still the studio

Route B ends exactly where route A does — the user's hands, in Sprite Sheet
Studio:

- key the frames (tolerance / softness / despill / erode) and pick the frames
- the proxy clip is in `videos/` too, one version below the character clip, if
  they want to compare motion and costume side by side with `版本化视频`
- export from the studio

**Never** export the mannequin frames as a deliverable, and never
programmatically export the character frames to "save a step". The picking is
the point of the skill; the proxy pass was the part that saved time.

## When B disappoints

- **The character pass drifts off the proxy's timing.** Usually because the beats
  named something the character does not have (a cape that appears in the beat
  text but not in the reference, or a two-handed grip on a one-hand sword). Fix
  the wording, not the proxy.
- **The proxy motion was already wrong.** Do not re-render the character and hope
  the costume fixes it. Go back to step 2; that is the cheap half.
- **The character cannot hold the same silhouette.** A very wide or very tall
  character needs a wider frame for the same arc — lower `--coverage` for the
  character pass only, and accept that the two passes differ in framing (framing
  is not the invariant; tempo is).
