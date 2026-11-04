---
name: pixel-sprite-sheet
display_name: 像素角色 Sprite Sheet 生产线
display_name_en: Pixel Sprite Sheet Pipeline
description_zh: 从一张角色四视图生成像素游戏角色动画 Sprite Sheet。用户给四视图（或多张视图）并用一句话描述要什么动画（走路、跑步、攻击、施法、受击、跳跃等），本 Skill 负责切图 → MiniMax H3 图生视频（ComfyUI）→ 抠绿幕 → 逐帧挑拣 → 导出 PNG + Atlas；每次渲染的原始视频归档到 videos/ 并带版本号，且每次交付都会把源视频直接放进对话播放（不只给路径），附带的 Sprite Sheet Studio 可直接导入视频 / GIF / PNG（PNG 追加进候选帧）、按版本载入视频，预览可四方向同屏并切换背景（棋盘/黑/白/灰/洋红）。当用户要求"把角色做成 sprite sheet / 走路循环 / 动画帧序列 / 2D 游戏角色动画"时使用。
description_en: Generate pixel-game character animation sprite sheets from a 4-view character reference. The user supplies view images and a one-line description of the animation (walk, run, attack, cast, hurt, jump, ...); the skill runs split → MiniMax H3 image-to-video (ComfyUI) → chroma key → frame picking → export PNG + atlas, archives every render's source clip into a version-numbered videos/ folder, and ships an interactive Sprite Sheet Studio that imports video, animated GIF and PNG (PNGs are appended to the candidate pool), reloads any archived version, and previews all four directions at once over a switchable backdrop. Use when asked to turn a character into a sprite sheet, walk cycle, or 2D game animation frames.
description: Generate pixel-game character animation sprite sheets from a 4-view character reference. Use when asked to turn a character into a sprite sheet, walk cycle, attack/cast/hurt animation, or 2D game animation frames. Runs split → MiniMax H3 image-to-video (ComfyUI) → chroma key → frame picking → PNG + atlas, archives source clips under version numbers in videos/, and ships an interactive Sprite Sheet Studio (imports video / GIF / PNG, four-direction preview, switchable backdrop).
version: 1.3.0
---

# Pixel Sprite Sheet Pipeline

Turn a character reference sheet into an engine-ready animation sprite sheet,
driven by a plain-language description of the animation.

```
4-view image  →  split_views  →  generate (H3/ComfyUI)  →  studio (key + pick)  →  PNG + atlas
   切图             四方向参考帧        绿幕视频 → 帧序列        抠图·挑帧·预览·导出
                                            ↓
                                    videos/<action>_vNN_<view>.mp4   ← 每次渲染留档，带版本号
```

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

**每次交付都必须把视频直接放进对话里播出来 —— 只给路径不算交付。**

The clip is also the fallback contract: if the harness genuinely cannot play
mp4 inline, say that in one line and show the GIF instead — but never drop the
video silently, and never let the GIF stand in for it unannounced (the GIF is
quantised and 10 fps; it hides exactly the crawling and popping the user needs to
judge).

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
2. **The animation, in words** — "走路" / "跑步" / "攻击一次" / "施法" /
   "受击后仰" / anything else. Pick a preset if it matches, otherwise pass the
   description through as `--describe`.
3. **Optional**: frame count (default 56), which views (default front/back/right).

Do not ask about seeds, prompt wording, model files, or ComfyUI paths — those
have sane defaults. Ask only if the reference layout is genuinely ambiguous.

## Environment check (do this first, every run)

```bash
python scripts/generate.py --health
python scripts/h3client.py input-dir
```

`--health` prints `{"ok": true, "running": 0, "pending": 0}` when ComfyUI is up.
If `ok` is false, stop and tell the user ComfyUI (MiniMax H3) is not reachable —
everything downstream needs it. If `input-dir` prints "(not found)", export
`H3_COMFY_INPUT=/path/to/ComfyUI/input`.

Required models live in `scripts/h3client.py` under `DEFAULT_MODELS`. If the
user's filenames differ, override with the `H3_MODELS` env var (JSON object with
keys `unet`, `clip`, `vae_video`, `vae_audio`, `lora_turbo`).

## The pipeline

Set up a project folder next to the user's files. Everything below is relative
to it.

```bash
SKILL=~/.workbuddy/skills/pixel-sprite-sheet
PROJ=./sprite-project          # any folder the user is happy with
mkdir -p $PROJ/{views,frames,out,videos}
```

`videos/` is not a cache — it is the deliverable folder the user will re-open
later. Every render drops its mp4 there under a version number (see step 3).

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

### 2. Describe the animation

Listing the presets costs nothing and tells you whether you even need a custom
prompt:

```bash
python $SKILL/scripts/make_prompt.py --help       # lists walk/run/idle/attack/cast/hurt/jump
```

For a preset:

```bash
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/walk \
  --action walk --subject "a chibi armored warrior with a red plume" \
  --frames 56
```

For anything not in the presets, write the beats yourself. `--describe` takes a
free-form sentence; the timing (beat structure) is what H3 actually responds to:

```bash
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/slash \
  --action custom --views-wanted right --frames 56 \
  --describe "a fast horizontal slash from right to left, the torso rotating
  into it, the leading foot planting, then a short recovery back to guard"
```

**Write `--subject` from the reference image, not from the user's words alone.**
It is the only place the character's identity (armour, colours, weapon count,
silhouette) is stated, and H3 uses it to hold the design across frames. One
sentence, concrete nouns, no adjectives like "cool" or "beautiful".

Presets deliberately avoid naming character parts that not every character has
(a slime has no cape, a mech has no plume). If your character *does* have loose
pieces that should flap, add them explicitly:

```bash
--limits "legs,arms,skirt,cape,plume"
```

Without `--limits`, only `legs / arms / torso` (the parts every biped shares)
are declared movable.

### 3. Wait for the render

`generate.py` submits all requested views in **one batch with one seed**, then
waits. That is deliberate — see `references/pitfalls.md#seeds`. A 56-frame
768px clip takes roughly 2–4 minutes per view on a 5090. Do not poll with
`sleep`; the script prints queue position itself. Run it in the background if
the harness supports it and check the log.

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

**Stop here and put the clips on screen.** Before step 4, hand every
`videos/<action>_v<NN>_<view>.mp4` from this batch to the file-presentation tool
so the user watches the render while you continue setting up the studio. One
sentence of what to look for (`腿有没有打滑 / 有没有多出来的手 / 首尾能不能接上`)
turns that clip into a decision: keep it, or re-render with a fixed prompt. Ask
for the verdict before picking frames — a re-render is 2–4 minutes, a wasted
picking pass is an hour.

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

### 7. Bake previews

```bash
python $SKILL/scripts/bake_gifs.py $PROJ/out/walk.png --fps 10 --out $PROJ/out
```

Produces `<name>_strip.gif` (all views, labelled) and one GIF per view. Re-run
after every re-export — GIFs are static artifacts.

## Presenting the result

Four artifacts, in this order, **every single time** — the video is not optional
and not last:

| # | Artifact | How |
| --- | --- | --- |
| 1 | **The clip(s)** `videos/<action>_v<NN>_<view>.mp4` | pass the absolute paths to the file-presentation tool so they play as cards. One per rendered view; when that is three files, show all three — they are the same seed and the comparison is the point |
| 2 | **The all-views GIF** `<name>_strip.gif` | from step 7 |
| 3 | **The sheet** `out/<name>.png` + `<name>.json` | with cell size, sheet dimensions, columns × rows, frames per view |
| 4 | **The studio URL** | last, so it does not get in front of the result |

Then state which version this batch is (`v03`) and where `videos/` lives. That
folder answers "which render is this from", and the user should never have to
grep `frames/` for an mp4.

Never do these:

- print the mp4 path and call it delivered (`视频在 videos/walk_v03_front.mp4`)
- show only the GIF and let it stand in for the clip
- show the sheet first and the video "if needed" — the sheet is the end product,
  the clip is the proof it is the right product
- present a drifting or half-finished animation as done. Name the direction that
  is missing or the part of the motion that broke, and let the clip say it.

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

- Render **one** side view and mirror it.
- Start at 39 or 56 frames. More frames = more candidates, not better motion.
- If the character's legs are hidden by a long skirt/robe, read
  `references/pitfalls.md#legibility` before spending renders on it.

## Failure modes worth knowing before you start

`references/pitfalls.md` collects the ones that cost real renders:

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

## Files

```
scripts/
  h3client.py      ComfyUI H3 client (build / submit / wait / collect)
  split_views.py   sheet → per-view PNGs
  make_prompt.py   description → H3 prompt (presets + custom)
  generate.py      batch: all views, one seed, prompts + frames + manifest
  videos.py        versioned archive of the source clips (videos/index.json)
  mirror.py        right → left
  manifest.py      renumber frames + write manifest.json
  serve.py         mount + serve the studio (Range-capable for video), print URL
  bake_gifs.py     sheet → preview GIFs
studio/
  index.html       Sprite Sheet Studio (single file, no build step)
references/
  studio.md        full studio interaction model
  pitfalls.md      what breaks H3 sprite generation, and the fix
  prompt-recipes.md  prompt patterns for actions not covered by presets
```
