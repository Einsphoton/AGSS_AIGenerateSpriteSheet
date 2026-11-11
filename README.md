# AIGenerateSpriteSheet

Turn **one character reference sheet** into an **engine-ready pixel animation sprite sheet**,
driven by a plain-language description of the animation.

```
4-view image → check_facing → split_views → prep_ref → generate (H3) → qc → studio (key+pick) → PNG + atlas
   切图          朝向审计        四方向参考帧   补白·幕布   帧序列/videos   边缘质检   抠图·挑帧·导出
                                               ↓
                                     videos/<action>_vNN_<view>.mp4   ← 每次渲染留档，带版本号
```

You give it a 4-view character sheet (front / back / side) and one sentence —
"走路" / "跑步" / "攻击一次" / anything — and it runs the whole chain:
facing audit → split → reference prep → MiniMax H3 image-to-video → chroma key →
frame QC → frame picking → PNG + atlas JSON.

## The back view only works if the reference makes it work

A back-view animation that turns the character around halfway, or a back
direction that plays chest-first, is a reference problem, not a prompt problem.
H3 reads the picture far more than the wording, so **if the front and back of the
reference are the same drawing, "pure rear view" is a contradiction** and the
model resolves it by rotating the figure. Measured on the mannequin this repo
used to ship: identical dominant torso colour on both sides, colour separation
`0.0`.

The fix is material, never outline — the character pass inherits the proxy's
silhouette, so a bump on the proxy becomes a backpack on the character:

```bash
python scripts/check_facing.py views/          # PASS / WEAK / FAIL, prints the numbers
```

| verdict | `material_tv` | meaning |
| --- | --- | --- |
| PASS | ≥ 0.22 | a fifth of the figure is a different material |
| WEAK | 0.10–0.22 | expect the model to lose the facing on some frames |
| FAIL | < 0.10 | to the model these are the same picture |

The bundled mannequin scores `0.44` (leather back panel, X lacing, spine seam,
stained nape) against `0.05` for the old one, with its silhouette unchanged at
`IoU 0.99`. `generate.py` runs the audit before submitting; prompts now enumerate
what the camera sees in each view and lock the camera for the whole clip, and
`--anchor back="the tall red cape and the silver clasp"` supplies the character's
own markers. Full diagnosis: [`references/facing.md`](references/facing.md).

## Two routes — the skill asks before it renders

|  | **A — direct** | **B — proxy pass** |
| --- | --- | --- |
| what gets rendered | the target character, once | a plain mannequin, then the character, **same seed + same beats** |
| cost | 1× (≈2–4 min per view) | 2× |
| motion when the character is busy | H3 spends attention on cape / plume / layered armour and the beats go mushy | the mannequin has nothing to get wrong, so the beats land cleanly and the second pass inherits the timing |
| wins when | simple silhouette, one weapon, tight budget | capes, long hair, plumes, dual weapons, layered armour, or the user wants to judge the motion before committing |

Route B is the same pipeline run twice and only `--views` / `--subject` change
between passes — everything else (`--seed`, beat text, `--frames`, `--coverage`,
`--key`) must be identical, or the second pass is a new animation rather than a
reskin. Full contract in [`references/proxy-pass.md`](references/proxy-pass.md).

**Route B still ends in the studio.** The mannequin pass is a motion sketch, not
a deliverable: the character pass produces the frames, and the user keys and
picks those in Sprite Sheet Studio like any other run. Never hand over mannequin
frames, and never script the export to skip the studio.

A neutral dual-sword mannequin ships in `templates/mannequin/` — four transparent
views drawn from one skeleton by `scripts/mannequin.py`, with `sheet_2x2.png` and
`turnaround.png` as magenta previews, `facing_contract.json` as the build's own
audit, `PROMPT.txt` for the image-model fallback, and the matching beat text in
`templates/beats/attack-dual-sword.txt`.

---

## What's in the box

| Path | What it is |
| --- | --- |
| `SKILL.md` | The agent skill definition — the pipeline, in order, with the rules that matter |
| `scripts/` | The pipeline as plain CLI tools (`check_facing`, `mannequin`, `split_views`, `prep_ref`, `generate`, `qc`, `mirror`, `manifest`, `serve`, `bake_gifs`) |
| `studio/index.html` | **Sprite Sheet Studio** — single file, no build step: key, sample, pick frames, preview 4 directions, save/restore the whole project as a `.zip`, export |
| `studio/test/` | `archive.e2e.js` — drives real Chrome over CDP to assert the project archive round-trips (all three source kinds) |
| `references/` | `studio.md` (interaction model), `pitfalls.md` (what breaks H3 generation), `facing.md` (front vs back), `prompt-recipes.md`, `proxy-pass.md` (route B) |
| `templates/` | A runnable example (`run-example.sh`), a subject sample, a **mannequin proxy** (`mannequin/`) and reusable beat text (`beats/`) |

## Requirements

- **ComfyUI** running locally with the **MiniMax H3** nodes and models (unet / clip / vae / turbo lora).
  Point the skill at it with `H3_COMFY_INPUT=/path/to/ComfyUI/input`.
- Python 3.9+ with `pillow numpy scipy` (`pip install -r requirements.txt`).
- A GPU that can do 56 frames @ 768px — roughly 2–4 min per view on a 5090.

Health check before anything else:

```bash
python scripts/generate.py --health          # {"ok": true, "running": 0, "pending": 0}
python scripts/h3client.py input-dir         # ComfyUI/input
```

## Install as a WorkBuddy / skill

```bash
git clone https://github.com/Einsphoton/AGSS_AIGenerateSpriteSheet.git \
  ~/.workbuddy/skills/AIGenerateSpriteSheet
```

## Use it

```bash
SKILL=~/.workbuddy/skills/AIGenerateSpriteSheet
PROJ=./sprite-project
mkdir -p $PROJ/{views,frames,out,videos}

# 1. split the reference into per-view PNGs, then audit the facing
python $SKILL/scripts/split_views.py character_sheet.png --out $PROJ/views
python $SKILL/scripts/check_facing.py $PROJ/views      # must not print FAIL

# 2. widen the canvas + composite onto the key colour (generate.py also does this for you)
python $SKILL/scripts/prep_ref.py $PROJ/views --action attack --key auto

# 3. render all views in one batch, one shared seed
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/walk \
  --action walk --subject "a chibi armored warrior with a red plume" --frames 56

# 4. quality gate — edge cropping, empty/black frames, backdrop purity
python $SKILL/scripts/qc.py frames $PROJ/frames/walk --key auto --action attack

# 5. mirror one side instead of rendering both
python $SKILL/scripts/mirror.py $PROJ/frames/walk/right $PROJ/frames/walk/left

# 6. renumber frames + write manifests
python $SKILL/scripts/manifest.py $PROJ/frames/walk --dirs front,back,left,right

# 7. open the studio to key, pick and export
python $SKILL/scripts/serve.py --root $PROJ --frames frames/walk --cmp 2x2 --open

# 8. bake preview GIFs from the exported sheet
python $SKILL/scripts/bake_gifs.py $PROJ/out/walk.png --fps 10 --out $PROJ/out
```

Route B replays steps 3–4 twice against two `--views` folders, with the same
`--seed`, the same `--describe-file`, the same `--frames / --coverage / --key`:

```bash
# pass 1 — block the motion with the mannequin
python $SKILL/scripts/generate.py --views $PROJ/proxy_views --out $PROJ/frames/slash_proxy \
  --action attack --subject "a faceless wooden mannequin holding two straight swords" \
  --describe-file $SKILL/templates/beats/attack-dual-sword.txt --frames 39 --seed 808080

# pass 2 — same seed, same beats, the real character
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/slash \
  --action attack --subject "a chibi warrior in green scale armour with a red plume" \
  --describe-file $SKILL/templates/beats/attack-dual-sword.txt --frames 39 --seed 808080
```

Then in the studio: chroma-key, choose candidate density, build a timeline per direction,
switch the backdrop (checker / black / white / grey / magenta for fringe), and export
PNG + atlas with per-frame rects. The scripts produce *candidate* frames — the picking is the point.

Two things the studio does that are worth knowing before the first run:

- **Two picking modes** (`点击模式`, shared by every column): `顺序选帧` ticks candidates off
  like a checklist — each frame at most once, row order always follows the candidate pool,
  click again to deselect. `插入选帧` places frames by hand at the cursor and allows the same
  frame several times (holds, repeated accents). Duplicates are collapsed and re-sorted when
  you switch into `顺序选帧`, and the toast says how many slots went away.
- **多方向墙** (`⤢` beside the 候选帧 count) expands the pool into four groups of two columns,
  one group per direction, rows aligned across groups (row *i* = candidates 2*i* / 2*i*+1).
  A click edits its own group, so key frames get picked while all four views stay in sight.
- **工程存档** (`保存工程` / `导入工程`, bottom bar) packs params + four timelines +
  the material itself + the exported sheet into one zip, and restores it exactly — re-running
  the pipeline on import, so tolerance, palette and cell grid stay editable afterwards.
  Drop the zip on the left panel to import. Layout and size notes in
  [`references/studio.md`](references/studio.md#project-archive--保存工程--导入工程).
  Collapsed, the pool is single-direction again.

## Every delivery plays the render

The mp4 is part of the answer, not a byproduct. After each render the clip is put on screen
(`videos/<action>_vNN_<view>.mp4`), and the final delivery leads with it — clip → all-views
GIF → sheet + atlas numbers → studio URL. A path printed in prose is not a delivery, and the
GIF is not a stand-in: 10 fps quantisation eats exactly the drift the clip exists to show.
`SKILL.md` states this as a hard rule; see *Non-negotiable: the video goes on screen*.

## Rules that save renders

- **The frame is a crop, and H3 copies it.** A reference tight to its own canvas teaches the model
  that the canvas edge is where the character ends — the first outward sword swing comes back as a
  stump. In one real run 29 of 39 front frames had the blade and plume cut flat. `prep_ref.py`
  pads to a square canvas with the figure at 48% (arc actions) / 58%, and `qc.py` measures the
  longest run of foreground pixels on each border so the failure is caught before picking.
- **The key colour comes from the reference.** Green armour shot against green loses the armour.
  `generate.py` scores green / magenta / cyan against the character's own pixels and picks the one
  that is not already in the costume, then prints the clash percentage.
- **A transparent PNG gives a black first frame.** H3 echoes the reference as frame 1; compositing
  onto the key colour (which `prep_ref` does) is what removes it.
- **One shared seed per batch.** Mixed seeds give up to 33% stride spread across views; a shared seed brings it to ~9%.
- **Never render both sides** — mirror one, so the two directions cannot desync.
- **`length % 17 == 5`** — 5, 22, 39, 56, 73, 90, 107, 124. 56 = two full strides at 24 fps.
- **H3 drops negations.** "no third sword" produces more swords — phrase positively.
- **The reference beats the prompt.** If they disagree, fix the reference, not the wording.
- **A back view is only renderable if the reference distinguishes it.** Same front and back
  picture = the figure turns around mid-clip, and no prompt helps. `check_facing.py` measures
  it (`material_tv`); the fix is a different *material* on one side, never a different outline.

Full list in [`references/pitfalls.md`](references/pitfalls.md).
