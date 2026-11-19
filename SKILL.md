---
name: pixel-sprite-sheet
display_name: 像素角色 Sprite Sheet 生产线
display_name_en: Pixel Sprite Sheet Pipeline
description_zh: 从一张角色四视图生成像素游戏角色动画 Sprite Sheet。流程固定为「先写分镜脚本，再渲染」：storyboard.py 把这次动画的节拍、每个节拍的精确秒数、每个方向应该看到的证据、以及必须四个方向共用的 seed / 帧数 / 键色 / coverage / limits / subject 写进一个 JSON，generate.py 只读这一份文件——所以正面、背面、侧面是同一次表演的三个机位，而不是三段各自发挥的动画。之后负责切图 → 参考图补白与幕布 → MiniMax H3 图生视频（ComfyUI）→ 帧级质检（边缘裁切/空帧/幕布）+ 跨方向一致性（比例是否一致、帧数是否一致）→ Sprite Sheet Studio 抠图与逐帧挑拣 → 导出 PNG + Atlas；每次渲染归档到 videos/ 带版本号。全程**不询问效果**：质检不过就自动重渲一次（更小 coverage + 新版本号）再继续，用户觉得不行会自己重跑。路线选择（①直接渲染角色 / ②先人偶代理再换角色）只在开头问一次，用户说过"直接做"就直接按参考图复杂度自动选。渲染前做朝向审计（check_facing.py）：参考图正面和背面若是同一张图，视频模型会分不清朝向、动画中途转身。路线②的人偶默认**空手**——道具会被角色那一遍继承（templates/mannequin/weapons/ 带 sword / dual-sword / staff / bow 变体）。当用户要求"把角色做成 sprite sheet / 走路循环 / 动画帧序列 / 2D 游戏角色动画 / 背面动画朝向不对 / 分镜脚本"时使用。
description_en: Generate pixel-game character animation sprite sheets from a 4-view character reference. A storyboard script (beats with exact seconds, per-view evidence, and one shared seed/frames/key/coverage/limits/subject) is written first and every direction is rendered from that one file, so front/back/side are three camera passes of one performance instead of three unrelated clips; then split → facing audit → reference prep → MiniMax H3 image-to-video (ComfyUI) → per-view QC plus a cross-view consistency gate (scale and frame count must agree) → chroma key → frame picking → PNG + atlas, with every render archived under a version number in videos/ and an automatic single re-render when QC fails (no mid-run approval questions). Use when asked to turn a character into a sprite sheet, walk cycle, or 2D game animation frames, or when a storyboard/beat sheet is wanted before rendering.
description: Generate pixel-game character animation sprite sheets from a 4-view character reference. Two phases, in this order — (1) write the storyboard — one JSON holding the beats with exact seconds, what each direction must show at each beat, and the parameters every view shares (seed, frames, key, coverage, limits, subject); (2) render all directions from that file, so character, motion and rhythm cannot drift between front/back/side. Then MiniMax H3 (ComfyUI) → per-view frame QC plus a cross-view scale/frame-count gate → chroma key → Sprite Sheet Studio → PNG + atlas, with versioned clips in videos/. Never stops to ask whether the motion looks right — a hard QC failure triggers one automatic re-render (smaller coverage, new version) and the run continues; the user re-runs the skill if they disagree. The A/B route (direct character vs. mannequin proxy first) is the only question asked, and it is auto-decided when the user has said "just do it". The bundled proxy has empty hands on purpose — an inherited prop is worse than a missing one. Runs a facing audit (check_facing.py — front and back must differ in material or the video model loses the orientation) before spending renders.
version: 1.8.0
---

# Pixel Sprite Sheet Pipeline

Turn a character reference sheet into an engine-ready animation sprite sheet,
driven by a plain-language description of the animation.

```
分镜脚本 → check_facing → split_views → prep_ref → generate (H3) → qc + 跨方向 → studio (key+pick) → PNG + atlas
storyboard.py  朝向审计     四方向 PNG  → 补白·幕布 → 帧序列/videos →   边缘/比例质检   → 抠图·挑帧    → 导出
```

Two rules shape everything below, and both are about not wasting an eight-minute
batch:

1. **The script comes before the render.** One storyboard JSON holds the beats,
   their exact seconds, what each direction must show, and every parameter the
   views share. `generate.py --storyboard` reads it, so front, back and side are
   three camera passes of one performance — not three unrelated clips that
   happen to feature the same character.
2. **No mid-run approval.** Nobody is asked "动作对不对？" between the render and
   the picking. QC decides, one automatic re-render happens if a structural
   check fails, and the run continues to the studio. If the result is wrong, the
   user re-runs the skill — a question costs them a round trip, the re-run costs
   them one command.

`check_facing` is not optional and not cosmetic: if the reference's front and back
are the same picture, every back-view render is wasted, because the model turns
the figure around mid-clip. See *Facing* below.

## Step 0 — Ask which route, before anything else

There are two ways to get a clip of *this* character, and they cost very
different amounts. Ask once, here, and nowhere else.

|  | **A — direct** | **B — proxy pass** |
| --- | --- | --- |
| what gets rendered | the target character, once | a plain, empty-handed mannequin first, then the character, same seed + same beats |
| cost | 1× renders (≈2–4 min per view) | 2× renders |
| motion when the character is busy | H3 spends its attention on the cape/plume/armour and the beats get mushy | the mannequin has nothing to get wrong, so the beats land cleanly, and the second pass inherits the timing |
| when it wins | simple silhouette, one weapon, tight budget, motion already known | capes, long hair, plumes, dual weapons, layered armour, an unfamiliar design, or the user wants to judge the motion before committing |

Ask with the question tool — two options, "A" first if the character is simple,
"B" first if the reference shows loose cloth, plumes, or more than one prop.
Say what each costs in one line; do not bury it.

> 这次用哪条路线做这段动画？
> **A 直接渲染角色** — 渲染一次，2–4 分钟/方向；角色服装复杂时动作可能变糊
> **B 先做人偶代理** — 先渲一遍人偶把动作敲定，再用同一 seed 换回角色；时间翻倍，动作最干净

- **A** → continue to step 1 below.
- **B** → read `references/proxy-pass.md`. It is the same pipeline run twice,
  with only `--views` and `--subject` changing between the passes.

**If the user has already said "直接做 / 别问我 / just generate it", skip the
question and decide.** Route B when the reference shows a cape, a plume, loose
cloth or two props; route A otherwise. Print the choice and the reason in one
line, then continue — this is the only decision in the pipeline the pipeline
itself cannot make from the pixels.

**The proxy has empty hands, and that is deliberate.** The mannequin pass answers
"does the body motion read?"; the prop belongs to the character pass, which gets
it from the character's own reference. H3 inherits props from the reference image
the same way it inherits silhouette, so a proxy holding two swords teaches an
unarmed character to grow them, and its prop is wrong for a staff or bow user.
Copy a weapon variant from `templates/mannequin/weapons/` only when the weapon
*is* the motion — a long shaft, a bow's arc, a two-handed grip. One-line rule:
**no prop in the proxy unless the prop changes the arc.**

**Route B still ends in the studio.** The mannequin pass is a motion sketch, not
a deliverable: the character pass produces the frames, and the user keys and
picks those frames in Sprite Sheet Studio like any other run. Never hand over
mannequin frames as the result, and never programmatically export the character
pass to skip the studio.

## Non-negotiable: the video goes on screen, every time

**Every output includes the source clip, playing in the conversation.** Not a
path, not a link, not "videos/walk_v03_front.mp4" in a sentence — the file
itself, handed to the file-presentation tool (`present_files`) so it renders as
a playable card. This holds at two moments:

1. **The moment a render finishes** (step 3) — before you open the studio and
   start picking frames. The clip is the only honest evidence of whether the
   motion is right; picking 12 key frames from a bad render wastes an hour and
   teaches nobody anything.
2. **The moment you deliver** (see *Presenting the result*) — clip first, then
   the GIF, then the sheet, then the studio URL.

Showing the clip is not the same as asking about the clip. Show it, say in one
line what to look for, and carry on with the picking pass in the same turn. A
question here trades the user's time for a decision the pipeline can already make
from `qc.py`.

**每次交付都必须把视频直接放进对话里播出来 —— 只给路径不算交付。**

The clip is also the fallback contract: if the harness genuinely cannot play
mp4 inline, say that in one line and show the GIF instead — but never drop the
video silently, and never let the GIF stand in for it unannounced (the GIF is
quantised and 10 fps; it hides exactly the crawling and popping the user needs to
judge).

## Facing: the reference decides whether the back view exists

A back-view clip that turns the character around halfway, or a whole back
direction that plays chest-first, is almost never a prompt problem. It is a
reference problem, and it is the one thing in this pipeline that no wording can
fix:

> H3 is image-to-video and reads the reference far more than the prompt. A
> reference whose **front and back are the same picture** makes the sentence
> "pure rear view" a contradiction, and H3 resolves contradictions by turning
> the figure around. Measured on the mannequin that used to ship here: identical
> dominant torso colour on both sides, colour separation `0.0`.

So, before anything is rendered:

```bash
python scripts/check_facing.py $PROJ/views          # PASS / WEAK / FAIL
```

`generate.py` runs it automatically and prints one line plus warnings. If it
fails, stop and fix the reference:

- **different material on the back, identical outline.** A back panel, mantle or
  cape; lacing, straps or a spine seam; an emblem on the chest and a bare back; a
  stained nape or a crest at the back of the head. Never a bump — the character
  pass inherits the proxy's silhouette, so a backpack on the proxy becomes a
  backpack on the character.
- **the difference has to be on the torso or the head**, not a limb: arms swing
  and legs cross, so a marker on a forearm is invisible for half a cycle.
- **the marker colour must not be the chroma key.**

The bundled mannequin is built this way on purpose and scores `0.44` (old one:
`0.05`) with its silhouette unchanged at `IoU 0.99`. The prompt half of the fix
is already in `make_prompt.py`: every view enumerates what the camera can see and
locks the camera for the whole clip. Override the enumeration with
`--anchor back="the tall red cape and the silver clasp"` when the character has
its own markers.

Full diagnosis, marker recipes and the before/after numbers:
`references/facing.md`.

## When to use

Use this when the user wants:
- a sprite sheet / walk cycle / attack animation for a 2D game character
- an animated pixel character built from a static reference
- to "make this character walk / attack / cast a spell" as game frames

Do **not** use it for: single illustration generation (use an image model),
3D animation, or video editing of existing footage.

## What you need from the user

1. **Reference image(s)** — one sheet with 4 views (front / back / side), or
   separate files. Names or positions both work; `split_views.py` auto-detects.
   **The front and back must be visibly different materials** — a detail on the
   back, a panel, lacing, an emblem, a stained nape. If they are not, say so
   before rendering; see *Facing* below.
2. **The animation, in words** — "走路" / "跑步" / "攻击一次" / "施法" /
   "受击后仰" / anything else. That is enough to write the storyboard: a preset
   when it matches, otherwise 3–5 beats you write yourself.
3. **Optional**: frame count (default 56), which views (default front/back/right).

**The route (A direct / B proxy) is the only question worth asking, and only
once** — see *Step 0*. Do not ask about seeds, beat wording, model files or
ComfyUI paths; the board's defaults are measured ones. Do not ask whether the
motion looks right at all: render, gate it with QC, hand over the clips and the
sheet. The user iterates by re-running the skill, not by answering questions
mid-run.

## Environment check (do this first, every run)

```bash
python scripts/generate.py --health
python scripts/h3client.py input-dir      # informational only
```

`--health` prints `{"ok": true, "running": 0, "pending": 0}` when ComfyUI is up.
If `ok` is false, the port is the first suspect: the default is **8190**, while a
**ComfyUI Desktop** install usually serves **8188**. Try it before concluding the
server is down:

```bash
export H3_SERVER=http://127.0.0.1:8188
```

References are staged by **uploading them over HTTP** (`/upload/image`), so the
server writes the bytes itself and `input-dir` stops being a thing you have to
get right. That matters because a machine can easily have two ComfyUI installs
(a portable one and a Desktop one), each with its own `input/` folder, and only
one of them belongs to the process you are talking to — guess wrong and
LoadImage quietly reads last session's `ref_front.png`. The staged filename
carries a content hash (`ref_front_ab12cd34.png`) for the same reason: the name
on disk says what the bytes are. `input-dir` still prints the folder used by the
filesystem fallback, and `H3_COMFY_INPUT` overrides it.

Required models live in `scripts/h3client.py` under `DEFAULT_MODELS`. If the
user's filenames differ, override with the `H3_MODELS` env var (JSON object with
keys `unet`, `clip`, `vae_video`, `vae_audio`, `lora_turbo`).

## The pipeline

Set up a project folder next to the user's files. Everything below is relative
to it.

```bash
SKILL=~/.workbuddy/skills/pixel-sprite-sheet
PROJ=./sprite-project          # any folder the user is happy with
mkdir -p $PROJ/{views,frames,out,videos,beats}
```

`videos/` is not a cache — it is the deliverable folder the user will re-open
later. Every render drops its mp4 there under a version number (see step 3).
`beats/` holds the storyboard, which is the second thing worth keeping next to
the reference: it is what a re-run edits, and it is the only record of what the
last render was trying to do.

### 1. Split the reference into per-view PNGs

```bash
python $SKILL/scripts/split_views.py character_sheet.png --out $PROJ/views
```

Produces `views/front.png`, `views/back.png`, `views/left.png`, `views/right.png`
plus `views/views.json` (the detected boxes). Auto-detection groups foreground
blobs into reading order. If it picks the wrong things:

```bash
# look at views/views.json, then pass boxes by hand
python $SKILL/scripts/split_views.py sheet.png --out views \
  --boxes 0,0,256,300 256,0,512,300 0,300,256,600 256,300,512,600
```

Keep the transparent-background output (default). Only pass `--keep-bg` if H3
needs the opaque backdrop.

Then run the facing audit on the four PNGs you just produced — a character sheet
cut from an image model is the most common source of a front and a back that are
the same drawing, because the model was never asked to differ them:

```bash
python scripts/check_facing.py $PROJ/views
```

### 1b. Give the motion room — the reference decides the crop

`split_views` crops to the figure's bounding box. That is what the studio wants
and the wrong thing to hand H3: a figure that fills its own canvas teaches the
model that the canvas edge is where the character ends. The first time a sword
sweeps outward it leaves the frame and comes back as a stump. In a real run,
29 of 39 front-view frames had the blade and plume cut flat at the top edge —
invisible in a thumbnail, obvious in game.

H3 inherits the reference framing; it does not invent margin. So widen the
canvas *before* rendering:

```bash
python $SKILL/scripts/prep_ref.py $PROJ/views --action attack
```

- one **square** canvas (the render is 768×768; matching the aspect removes one
  more thing H3 can drift), same scale for all four views
- figure at **48%** for arc-heavy actions (`attack cast throw punch kick`), **58%**
  otherwise → 20–26% empty margin per side
- composited onto the key colour, which also fixes the "black first frame":
  H3 echoes the reference as frame 1, and a transparent PNG on a black canvas
  gives one black frame at the head of every clip

`generate.py` runs this automatically and prints both the canvas and the staged
files; `--coverage 0.42` if a clip still clips, `--no-prep` to send the reference
untouched (rarely what you want).

### 2. Write the storyboard（分镜）— before any render

One JSON file is the whole animation decision. Write it, read it, *then* render.

```bash
# a preset that already reads well
python $SKILL/scripts/storyboard.py init --action walk \
  --subject "a chibi armored warrior with a red plume and a long red cape" \
  --out $PROJ/beats/walk.storyboard.json

# anything else: write the beats, then convert them
python $SKILL/scripts/storyboard.py init --action slash --kind one-shot \
  --from $PROJ/beats/slash.txt --out $PROJ/beats/slash.storyboard.json

python $SKILL/scripts/storyboard.py check $PROJ/beats/walk.storyboard.json   # PASS / warn / ERROR
python $SKILL/scripts/storyboard.py table $PROJ/beats/walk.storyboard.json --out $PROJ/beats/walk.md
```

The board holds four things, and the split matters:

| field | what it is | who reads it |
| --- | --- | --- |
| `beats[].frac` + `beats[].motion` | the extremes and *when* they happen, as sentences | every view, verbatim, the same sentence at the same second |
| `beats[].see.<view>` | optional: what that beat looks like from this camera ("the blade sweeps past the chest edge") | only that view's prompt |
| `views.<view>.anchor` | what the camera can see in this direction (the facing evidence) | only that view's prompt |
| `seed` `frames` `key` `coverage` `limits` `subject` `invariants` | the parameters that must be identical in every direction | `generate.py`, which refuses to vary them per view |

**Write 3–5 beats, name extremes, not paths.** "the arm drawn back across the
body" and "the arm whipped forward in a flat arc" interpolate correctly;
"the arm moves smoothly" does not. The timings are what H3 actually locks onto,
which is why they live in the file as fractions (0.00 / 0.30 / 0.60 / 0.85) and
not as frame numbers — change `--frames` later and the performance rescales
instead of being truncated.

`check` is the cheap gate. It catches the mistakes that cost a batch, and each
message says what to write instead: beats out of order, a beat too short to read
as a pose, a clip whose last beat lands at 55% (the model then *holds* the final
pose for a second), two actions in one beat, a `subject` still containing "TODO",
a negation ("no third sword" grows a third sword — H3 drops negations), a
`diagonal` view that does not exist, a loop with no close sentence, coverage 0.9.

Then read the prompts once — they are the actual input, and they cost nothing:

```bash
python $SKILL/scripts/storyboard.py prompts $PROJ/beats/walk.storyboard.json \
  --out-dir $PROJ/frames/walk/_prompts
```

Three prompt details are not optional and not obvious:

**`subject` is written from the reference image, not from the user's words.**
It is the only place the character's identity (armour, colours, weapon count,
silhouette) is stated, and H3 uses it to hold the design across frames. One
sentence, concrete nouns, no adjectives like "cool" or "beautiful".

**`--limits` must name the loose pieces your character actually has.** Presets
deliberately avoid parts not every character has (a slime has no cape, a mech has
no plume), so a caped character needs `"limits": ["legs","arms","torso","cape","plume"]`
or the cape stays rigid while the body walks.

**The key colour comes from the reference, not from the board.** `generate.py`
scores chroma green / magenta / cyan against the character's own pixels and picks
the one that does not already exist in the costume — a green armoured character
shot against green loses its armour to the key. Leave `"key": "auto"` unless you
have a reason; it prints the choice and the clash percentage. Whatever it prints,
key the frames with the same colour in the studio.

Full schema, worked example and the failure catalogue: `references/storyboard.md`.

### 2b. The consistency contract — what the board is actually for

H3 has no memory between calls. Four directions are four independent samples,
and everything that makes them *not* one performance has a name:

| symptom | cause | the board field that fixes it |
| --- | --- | --- |
| the front walks at a different tempo than the back | different seed → up to 33% stride spread | `seed` (one value, every view) |
| the side view does the motion in a different order | paraphrased beat text | `beats` (one list, verbatim, every view) |
| one direction is zoomed differently | different `coverage` / `frames` | `coverage`, `frames` |
| the cape flaps in one view only | `limits` named the cape but not in another pass | `limits` |
| the back view quietly turns around | the anchor does not name what the camera sees | `views.back.anchor` |
| a beat reads wrong from the side ("both hands push forward" seen edge-on) | the projection was left to inference | `beats[].see.right` |

The prompt states the contract explicitly — every view is told that its beats,
timing, weight and silhouette are identical to the other passes, and that each
beat time is exact. **The claims are then checked**, not trusted: `qc.py` gates
each view on its own, and `generate.py` adds a cross-view gate that fails the
batch when the four directions disagree on the character's size by more than 18%
(they cannot share one cell size) or notes a spread over 8% and mismatched frame
counts. A fail verdict is recorded in the board's `renders` table, so the next
run can see what went wrong instead of re-guessing.

Rhythm cannot be measured from a still — that part is the board's job (same
beats, same seed, same frames), and the clip is the only thing that proves it.

### 3. Render every direction from that board

```bash
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/walk \
  --storyboard $PROJ/beats/walk.storyboard.json
```

No `--seed`, no `--frames`, no `--action` on the command line: they come from the
board, and the run prints which of the three places each value came from
(`board` / `flag` / `default`) so a stale flag can never quietly split the batch.
Flags still win when you pass them — that is for experiments, not for the
delivery run.

`generate.py` validates the board first and refuses to submit a board that fails
`check`. Then it submits all requested views in **one batch with one seed** and
waits. That is deliberate — see `references/pitfalls.md#seeds`. A 56-frame 768px
clip takes roughly 2–4 minutes per view on a 5090. Do not poll with `sleep`; the
script prints queue position itself. Run it in the background if the harness
supports it and check the log.

Output:

```
frames/walk/
  prompt_front.txt prompt_back.txt prompt_right.txt
  front/frame_001.png … frame_056.png
  back/…
  right/…
  manifest.json
videos/
  index.json                          ← what each version was
  walk_v01_front.mp4                  ← the clip this batch came from
  walk_v02_front.mp4                  ← next render of the same action
```

The mp4s do **not** stay inside `frames/walk/back/`: one batch = one version
number, and the clips move to `<project>/videos/` (naming
`<action>_v<NN>_<view>.mp4`). That folder is what you point the studio at with
`?videos=`, and it is the folder to show the user when they ask "where are the
videos?". Version numbers are global and never reused — deleting `index.json`
does not reset them.

```bash
python $SKILL/scripts/videos.py list --dir $PROJ/videos      # v01 walk 56帧 views=[back,front,right]
```

Pass `--videos DIR` to put them elsewhere, `--no-archive` to keep the old
behaviour (mp4 left next to the frames).

**Put the clips on screen the moment they land — then keep going.** Hand every
`videos/<action>_v<NN>_<view>.mp4` from this batch to the file-presentation tool
so the user watches the render while you set up the studio. One sentence of what
to look for (`腿有没有打滑 / 有没有多出来的手 / 首尾能不能接上`) turns the clip
into evidence; **do not ask a question and do not wait for an answer.** A render
is a deliverable, not a checkpoint. If it is genuinely broken, QC already said so
in 3b and the fix is a re-render — a question only postpones that.

### 3b. Check the frames before picking any of them

`generate.py` runs this at the end of every batch and prints a `FAIL`/`PASS`
block plus a cross-view verdict; run it yourself after any re-render or
hand-staged reference:

```bash
python $SKILL/scripts/qc.py frames $PROJ/frames/walk --key '#FF00FF'
```

What it measures, and what each failure actually means:

| check | fail means | fix |
| --- | --- | --- |
| **border** — longest unbroken run on the four frame edges | a blade, plume or foot is leaving the frame; that limb is cut in the clip | re-render with a smaller coverage (0.42) into a fresh `--out` — H3 copies the reference framing |
| **black frames** | the reference PNG had alpha and H3 echoed it on black | `prep_ref.py` (automatic in `generate.py`) |
| **empty frames** | a frame with no subject — usually a bad first/last frame | drop it while picking, or re-render |
| **body height swing** | H3 zoomed mid-clip; shortening the clip usually fixes it | lower `--frames`, keep the camera wording |
| **backdrop purity** | the corners are not one flat colour — wrong key colour, or a ground plane crept in | check `--key`; a ground plane cannot be keyed away |
| **cross-view scale** | the directions disagree on how big the character is by >18% — the views cannot share one cell size | re-render; do not rescale, that hides a per-view zoom |

A note is not a failure: a couple of frames with a blade tip grazing the edge is
normal for a wide arc. Ten or more means the framing is wrong, and picking
around it just hides a stump in the sprite sheet.

**Automatic retry — once, without asking.** A `FAIL` on `border` is the one class
of failure with a known mechanical fix: H3 inherited too tight a crop from the
reference. Re-run the same batch with `--coverage 0.42` (and the same board, so
the seed and beats do not change) into a **fresh** `--out`
(`frames/walk_r2`) — never into the folder holding the clipped frames, because
the old frames and the new ones would be renumbered into one timeline. Record the
attempt in the board and carry on to the studio with whichever version is
cleaner:

```bash
python $SKILL/scripts/storyboard.py record $PROJ/beats/walk.storyboard.json \
  --version 4 --attempt 2 --qc pass --coverage 0.42 --clip front=… 
```

Do not loop. One retry, then deliver with the failure named in one line — the
user re-runs the skill if they want another pass, and `renders` in the board
tells them (and the next run) exactly what was tried.

### 4. Mirror the side view

Never render both sides — mirror one. The two directions then share every
pixel of jitter, so they cannot desync.

```bash
python $SKILL/scripts/mirror.py $PROJ/frames/walk/right $PROJ/frames/walk/left
```

### 5. Write manifests

```bash
python $SKILL/scripts/manifest.py $PROJ/frames/walk --dirs front,back,left,right
```

Renumbers frames to `frame_001..NNN` (H3's SaveImage counter continues across
runs, so a second render lands at 057..112) and writes `manifest.json` per view.

### 6. Open the studio

```bash
python $SKILL/scripts/serve.py --root $PROJ --frames frames/walk --open
```

This copies `studio/index.html` into `$PROJ/_studio/` and serves `$PROJ`, so the
studio and the frames share one origin and `?frames=` resolves. When
`$PROJ/videos/index.json` exists it also appends `&videos=/videos` and prints the
version list, so the clips are one dropdown away. Give the user the printed URL —
and re-show the batch's clips alongside it (see *Non-negotiable* above); the
studio link is for iterating, not a substitute for showing what was rendered. In
the studio they:

- pick the frame count and candidate density, then **re-sample**
- switch between the four directions with the big buttons at the top right
- click candidate frames to build each direction's timeline independently
- watch the preview: `单 / 2×2 / 1×4` switches between the current direction
  alone and all four directions on screen at once (keys `1` `2` `3`)
- change the preview backdrop with the `背景` strip at the bottom-right —
  dark/light checker, black, white, 50% grey, magenta (fringe check). Export is
  unaffected: the PNG stays transparent
- **导入视频·GIF** — video or animated GIF becomes that direction's material
- **＋PNG / 拖 PNG** — hand-picked PNGs are appended to the candidate pool 1:1
  (purple `附加` badge, `清附加` to remove)
- **版本化视频** — pick `v01…vNN` and load that render's mp4s to re-sample
- **保存工程 / 导入工程** — pack params, four timelines, the material and the
  exported sheet into one `.zip`, and restore it on any machine (the pipeline is
  re-run on import, so the params stay editable). Drop the zip on the left panel
  to import. Reach for it when a picking session has to survive a restart, or
  when the user wants the project back in their hands rather than a screenshot
- export PNG + atlas JSON from the bottom bar

`?frames=` no longer needs a `manifest.json`: if there is none the studio reads
the directory listing, so `frame_001.png` folders, GIFs and single mp4s all work.

Add `--cmp 2x2|1x4` (or `1x4`) and `--bg white|black|gray|lcheck|dcheck|magenta`
to the `serve.py` command and the printed URL opens with that many panels on that
backdrop. Do this whenever the user is comparing directions — the default is one
direction at a time, so a bare link shows one panel.

**Do not skip this step and export programmatically** — the picking is the
point. The user wants to choose which frames go in the animation. If they ask
you to export without opening the studio, use the defaults but say so.

Opening the studio is the last step of the run, not another checkpoint: hand over
the URL, say which direction is worth looking at first, and stop. Do not ask
whether the picking result is acceptable — the user exports when they are happy
and re-runs the skill when they are not.

This holds for route B without exception: the mannequin pass is a motion sketch.
The frames the user keys and picks are the *character* frames, and the proxy clip
sits one version lower in `版本化视频` if they want to compare the two.

### 7. Bake previews

```bash
python $SKILL/scripts/bake_gifs.py $PROJ/out/walk.png --fps 10 --out $PROJ/out
```

Produces `<name>_strip.gif` (all views, labelled) and one GIF per view. Re-run
after every re-export — GIFs are static artifacts.

## Presenting the result

Five artifacts, in this order, **every single time** — the video is not optional
and not last:

| # | Artifact | How |
| --- | --- | --- |
| 1 | **The clip(s)** `videos/<action>_v<NN>_<view>.mp4` | pass the absolute paths to the file-presentation tool so they play as cards. One per rendered view; when that is three files, show all three — they are the same seed and the comparison is the point |
| 2 | **The 分镜表** `beats/<action>.md` | the beat table + the consistency contract + the `renders` history, from `storyboard.py table`. It is what the user edits when they want different motion next run |
| 3 | **The all-views GIF** `<name>_strip.gif` | from step 7 |
| 4 | **The sheet** `out/<name>.png` + `<name>.json` | with cell size, sheet dimensions, columns × rows, frames per view |
| 5 | **The studio URL** | last, so it does not get in front of the result |

Then state which version this batch is (`v03`), where `videos/` lives, and — if
QC raised anything — the one line that names it. That folder answers "which
render is this from", and the user should never have to grep `frames/` for an
mp4.

Never do these:

- print the mp4 path and call it delivered (`视频在 videos/walk_v03_front.mp4`)
- show only the GIF and let it stand in for the clip
- show the sheet first and the video "if needed" — the sheet is the end product,
  the clip is the proof it is the right product
- present a drifting or half-finished animation as done. Name the direction that
  is missing or the part of the motion that broke, and let the clip say it.
- **end the turn with a question about the animation.** Deliver, and let the user
  decide whether to re-run; a "这样可以吗？" between the clip and the studio is
  the one gate this pipeline removed on purpose.

## What the studio does that the scripts cannot

The scripts produce *candidate* frames. The studio is where quality happens:

- **Chroma key** — tolerance / softness / despill / erode, shared across views.
  Material that already has alpha (a keyed PNG, a transparent GIF) keeps its own
  — the key only ever removes opacity, so nothing gets re-keyed into a black halo
- **Sampling** — how many frames to keep, at what density, over what time range
- **Per-direction timelines** — the four views are independent lists; lengths
  may differ
- **Two picking modes** — `顺序选帧` ticks candidates off like a checklist (each
  frame at most once, row order always follows the pool, click again to
  deselect); `插入选帧` places frames by hand at the cursor and allows the same
  frame several times. Default is 插入选帧.
- **多方向墙** — one button expands the candidate pool into four groups of two
  columns, one group per direction, rows aligned across groups (row *i* = the
  candidate pair 2*i* / 2*i*+1), so a whole direction fits on screen and key
  frames can be picked while comparing all views; a click edits its own group,
  the two picking modes still apply globally. Collapsed, the pool stays
  single-direction.
- **Extras** — PNGs appended by hand live at the end of the candidate pool, keep
  the same key/scale/palette/anchor/placement, and stay out of gait analysis
  (their phase is unknown, and mixing them in would skew 步长 for all four rows)
- **Alignment** — one anchor mode and one scale denominator for all views, so
  heights and baselines match (`footlock` is the right default)
- **Consistency panel** — flags height spread and per-view stride
- **Export** — uniform cell size, palette quantization, 4× nearest-neighbour
  upscale, atlas JSON with per-frame rects

See `references/studio.md` for the full interaction model.

## Frame-count rules (H3)

`length % 17 == 5` — 5, 22, 39, 56, 73, 90, 107, 124. `snap_length()` rounds up
and says so. 56 is a good default: two full walk strides at 24 fps.

## Cost control

- **Never spend a render on a reference that fails `check_facing`.** A back view
  that drifts is not a clip you can pick your way out of — the whole direction is
  unusable, so it is a re-render of every view with the seed shared again.
- **Never spend a batch on a board that fails `check`.** A beat at 0.2 after one
  at 0.5, two actions in one beat, a `TODO` in the subject — `check` finds them
  for free, `generate.py` refuses to submit them.
- Render **one** side view and mirror it.
- Start at 39 or 56 frames. More frames = more candidates, not better motion.
- Route B doubles the render count. Pay for it only when the character is busy
  enough that a direct render is hard to judge — and settle the motion on the
  mannequin, where a re-render is cheap and legible.
- Never "fix" a clip by picking around a broken frame. A clipped sword or a
  zooming torso is a 2-minute re-render, not a picking problem.
- One automatic retry per batch, then deliver. Two retries in a row on the same
  check means the input is wrong (reference crop, facing, character design), and
  a third render will not find that out.
- If the character's legs are hidden by a long skirt/robe, read
  `references/pitfalls.md#legibility` before spending renders on it.

## Failure modes worth knowing before you start

`references/pitfalls.md` collects the ones that cost real renders:

- **Facing** — a reference whose front and back are the same picture makes the
  model turn the figure around mid-clip; no prompt fixes it. Differ the two sides
  in material, keep the outline identical, and gate it with `check_facing.py`
  (`references/facing.md`).
- **Direction drift** — the four views are four independent samples of H3, and
  without a shared script they diverge: different tempo, different beat order,
  different scale. The storyboard (`references/storyboard.md`) is the fix, and
  the cross-view gate in `generate.py` is how you find out it did not work.
- **Framing** — H3 copies the reference's crop. A figure that fills its canvas
  comes back with the sword cut off the moment it swings. Pad to 48–58% before
  rendering (`prep_ref.py`, automatic in `generate.py`).
- **Seeds** — mixed seeds give up to 33% stride spread across views; one shared
  seed brings it to ~9%.
- **Legibility** — prompt the *visible* consequence (boots crossing, hem
  lifting), never the hidden limb.
- **Negations** — H3 drops them; "no third sword" produces more swords. Always
  phrase positively.
- **Thin props** — a sword/blade/tail that crosses the body will be re-invented
  every few frames. Anchor it to a body part in the prompt, or accept that you
  will be picking frames.
- **First frame dominance** — H3 reads the reference far more than the prompt.
  If the reference contradicts the prompt, the reference wins. Fix the
  reference, not the wording.
- **Two ComfyUI installs** — a portable one and a Desktop one each have an
  `input/` folder; guessing wrong renders last session's character. Staging
  uploads over HTTP so the server picks, and the filename carries a hash.

## Files

```
scripts/
  storyboard.py    分镜: beats + per-view evidence + the shared render parameters,
                   as one JSON — init / check / table / prompts / plan / record
  h3client.py      ComfyUI H3 client (build / submit / wait / collect, HTTP upload staging)
  check_facing.py  front vs back distinguishability audit (material_tv, silhouette, profiles)
  mannequin.py     draws the 4-view proxy from one skeleton (material-coded front/back,
                   --weapon none|sword|dual-sword|staff|bow, --all for every variant)
  split_views.py   sheet → per-view PNGs
  prep_ref.py      reference → square key-coloured canvas with margins (anti-crop, anti-black-frame)
  make_prompt.py   beats / storyboard → H3 prompt (presets + custom)
  generate.py      batch: prep → all views from one storyboard, one seed,
                   prompts + frames + manifest + QC (per view and cross-view)
  qc.py            quality gate: crop / black / empty frames / backdrop, both before and after
  videos.py        versioned archive of the source clips (videos/index.json)
  mirror.py        right → left
  manifest.py      renumber frames + write manifest.json
  serve.py         mount + serve the studio (Range-capable for video), print URL
  bake_gifs.py     sheet → preview GIFs
studio/
  index.html       Sprite Sheet Studio (single file, no build step)
templates/
  mannequin/       bundled route-B proxy: 4 views of a wooden dummy, EMPTY HANDS, transparent;
                   front = harness + brass buckle, back = leather panel + X lacing + stained
                   nape (same silhouette) — plus sheet_2x2.png, turnaround.png, overview.png
                   and facing_contract.json, which carries the audit the build ran
    weapons/       optional props, same skeleton and same body pose: sword, dual-sword,
                   staff, bow. Copy the one that matches, or mannequin.py --weapon <name>.
                   Empty hands is the default because a prop in the reference is a prop
                   the character pass inherits
  beats/           storyboards worth reusing — start by copying one:
                   walk.storyboard.json (preset, 4 beats, loop) and
                   attack-dual-sword.storyboard.json (5 beats, needs the dual-sword
                   proxy) — plus the plain beat text they were built from:
                   walk.txt (unarmed, neutral), attack-dual-sword.txt
references/
  storyboard.md    the schema, how to write beats, the consistency contract,
                   and what each `check` message is telling you
  facing.md        front vs back: why the model loses the orientation, and the fix
  proxy-pass.md    route B: mannequin pass → character pass, and what may not change
  studio.md        full studio interaction model
  pitfalls.md      what breaks H3 sprite generation, and the fix
  prompt-recipes.md  prompt patterns for actions not covered by presets
```
