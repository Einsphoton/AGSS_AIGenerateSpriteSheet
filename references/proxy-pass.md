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
| the beat text (`--describe-file` / the storyboard) | `--subject` |
| `--frames`, `--size` | `--anchor` (it names what the camera sees, and the two passes see different things) |
| `--coverage`, `--key` | |

Change any of the first column and you are not re-using a motion, you are
rendering a second unrelated clip and hoping. This is the same reason
`references/pitfalls.md#seeds` exists: H3 picks its own tempo per seed.

**With a storyboard, the first column stops being something to remember.** `seed`,
`frames`, `coverage`, `key` and the beats all come from the board in both passes;
only `--views` and `--subject` are on the command line. That is now the
recommended way to run route B — see `references/storyboard.md`.

`--key` still deserves attention: `auto` picks per reference, and wood on magenta
vs green armour on green are different answers. If the two references have
different palettes, pass `--key` explicitly and identically in both passes rather
than letting each one auto-pick.


## 1. Get a mannequin reference

The skill ships one: `templates/mannequin/{front,back,left,right}.png` — a pale
birch artist's dummy with ball joints, a featureless head and **empty hands**,
**drawn so that its front and back cannot be confused**: the chest carries a
leather harness and a brass buckle, the back carries a dark leather panel with X
lacing, a spine seam and a stained walnut nape. Same silhouette, different
material.

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

`mannequin.py` draws one skeleton and projects it four ways, so proportions,
scale and the head-to-heel line cannot drift between panels. It is the reliable
path; `templates/mannequin/PROMPT.txt` is the image-model fallback, and its
output still needs `check_facing.py` to pass before it is worth a render.

Keep the proxy's framing loose. A proxy that fills its own canvas will produce a
chopped-up motion in the pass you trust most.

### The proxy has empty hands — that is the point

The proxy answers *"does the body motion read?"*. The prop belongs to the
character pass, which gets it from the character's own reference and its
`--subject`. H3 inherits props out of the reference image exactly the way it
inherits silhouette, so a proxy that carries two swords teaches an unarmed
character to grow two swords — and to a staff or bow user its prop is actively
wrong. `pitfalls.md#first-frame-dominates` is the mechanism;
`pitfalls.md#thin-props` has the measured case where two hilts 41 px apart in the
reference produced "one hand, two weapons".

So: **no weapon unless the weapon is the motion.** Pick a variant only when the
prop changes the arc or the centre of mass:

| the character uses | proxy | why |
| --- | --- | --- |
| nothing (unarmed, punch, kick, grab) | default, empty hands | any prop in the reference gets inherited |
| one short weapon, off hand free (cast, torch, item) | `--weapon sword` | the free hand has to stay visibly free |
| two weapons, or both arms doing the same thing | `--weapon dual-sword` | also a fine stand-in for a two-handed motion |
| a long shaft (staff, spear, polearm) | `--weapon staff` | the arc crosses the floor; a sword proxy mis-blocks the silhouette |
| a bow | `--weapon bow` | big open arc beside the body. Locomotion and idle only — a draw is a different pose, so it needs a custom proxy |
| anything else (shield, gun, whip, cape-as-prop) | default + describe it in the beats | do not encode the prop in the reference; let the character pass own it |

```bash
# variants ship with the skill — same skeleton, same body pose
ls $SKILL/templates/mannequin/weapons/          # sword, dual-sword, staff, bow
cp $SKILL/templates/mannequin/weapons/staff/*.png $PROJ/views_proxy/
python $SKILL/scripts/mannequin.py --out $PROJ/views_proxy --weapon staff  # or build your own
python $SKILL/scripts/mannequin.py --all        # rebuild every variant + overview.png
```

`overview.png` in that folder is the one-picture answer to "is this proxy only
for dual wield?": five variants, front and profile, one skeleton.

Every variant keeps the **same body pose** so that the four views stay one
figure and so that variants remain comparable when you are choosing between
them. A pose variant is a different job — a bow draw, a two-handed guard, a
crouch — and belongs in `PROMPT.txt` territory, not in `--weapon`.

## 2. Proxy pass

```bash
python $SKILL/scripts/generate.py --views $PROJ/views_proxy \
  --out $PROJ/frames/${ACTION}_proxy \
  --storyboard $PROJ/beats/$ACTION.storyboard.json \
  --subject "a plain wooden artist's mannequin, empty hands, no weapon"
```

Match the `--subject` to the variant you copied: `a plain wooden artist's
mannequin holding one short sword in its right hand` for `--weapon sword`, and so
on. The proxy pass and the character pass must agree about what is in the
hands, or the second pass spends its attention removing a prop that is no longer
there.

Everything else — the seed, the frame count, the beats, the limits — comes from
the board, so the second pass cannot drift from this one. Nothing to type twice,
nothing to paraphrase.

Put the clip on screen (see *Non-negotiable* in SKILL.md) and **keep going**: this
is the cheapest look at the motion the pipeline ever offers, so if QC flags it, or
a limb is clipped, re-render *here* — one retry, on the cheap half — and then
render the character pass. Do not stop to ask whether the motion is approved. A
question costs the user a round trip; a re-run costs them one command, and
`renders` in the board already records what was tried.

## 3. Character pass

```bash
python $SKILL/scripts/generate.py --views $PROJ/views \
  --out $PROJ/frames/${ACTION} \
  --storyboard $PROJ/beats/$ACTION.storyboard.json \
  --subject "a chibi warrior in green scale armour, dark grey helmet, a tall red
  horsehair plume, a long red cape, one silver broadsword in each hand" \
  --limits "arms,torso,legs,cape,plume"
```

`--subject` comes from the character reference, not from the user's words — it is
the only place the costume is described, and the proxy pass proves H3 will ignore
costume details if the subject line is vague. `--limits` overrides the board for
this pass only; prefer editing `limits` in the board, where both passes read it.

The character pass is *the* pass. From here it is the normal pipeline: QC (step
3b, including the cross-view scale gate), mirror, manifest, studio.

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
- **The character grew the proxy's weapon.** The proxy's prop is inherited, not
  outvoted. Re-run the proxy pass with the default empty-handed reference (or the
  variant that matches the character's actual weapon) — do not try to remove it
  with wording, and do not write a negation: `no swords` produces swords.
- **The proxy motion was already wrong.** Do not re-render the character and hope
  the costume fixes it. Go back to step 2; that is the cheap half.
- **The character cannot hold the same silhouette.** A very wide or very tall
  character needs a wider frame for the same arc — lower `--coverage` for the
  character pass only, and accept that the two passes differ in framing (framing
  is not the invariant; tempo is).
