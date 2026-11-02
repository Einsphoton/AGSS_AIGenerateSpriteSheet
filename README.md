# AIGenerateSpriteSheet

Turn **one character reference sheet** into an **engine-ready pixel animation sprite sheet**,
driven by a plain-language description of the animation.

```
4-view image  →  split_views  →  generate (H3 / ComfyUI)  →  studio (key + pick)  →  PNG + atlas
   切图             四方向参考帧        绿幕视频 → 帧序列        抠图·挑帧·预览·导出
                                            ↓
                                    videos/<action>_vNN_<view>.mp4   ← 每次渲染留档，带版本号
```

You give it a 4-view character sheet (front / back / side) and one sentence —
"走路" / "跑步" / "攻击一次" / anything — and it runs the whole chain:
split → MiniMax H3 image-to-video → chroma key → frame picking → PNG + atlas JSON.

---

## What's in the box

| Path | What it is |
| --- | --- |
| `SKILL.md` | The agent skill definition — the pipeline, in order, with the rules that matter |
| `scripts/` | The pipeline as plain CLI tools (`split_views`, `generate`, `mirror`, `manifest`, `serve`, `bake_gifs`) |
| `studio/index.html` | **Sprite Sheet Studio** — single file, no build step: key, sample, pick frames, preview 4 directions, export |
| `references/` | `studio.md` (interaction model), `pitfalls.md` (what breaks H3 generation), `prompt-recipes.md` |
| `templates/` | A runnable example (`run-example.sh`) and a subject description sample |

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

# 1. split the reference into per-view PNGs
python $SKILL/scripts/split_views.py character_sheet.png --out $PROJ/views

# 2. render all views in one batch, one shared seed
python $SKILL/scripts/generate.py --views $PROJ/views --out $PROJ/frames/walk \
  --action walk --subject "a chibi armored warrior with a red plume" --frames 56

# 3. mirror one side instead of rendering both
python $SKILL/scripts/mirror.py $PROJ/frames/walk/right $PROJ/frames/walk/left

# 4. renumber frames + write manifests
python $SKILL/scripts/manifest.py $PROJ/frames/walk --dirs front,back,left,right

# 5. open the studio to key, pick and export
python $SKILL/scripts/serve.py --root $PROJ --frames frames/walk --cmp 2x2 --open

# 6. bake preview GIFs from the exported sheet
python $SKILL/scripts/bake_gifs.py $PROJ/out/walk.png --fps 10 --out $PROJ/out
```

Then in the studio: chroma-key, choose candidate density, build a timeline per direction,
switch the backdrop (checker / black / white / grey / magenta for fringe), and export
PNG + atlas with per-frame rects. The scripts produce *candidate* frames — the picking is the point.

## Rules that save renders

- **One shared seed per batch.** Mixed seeds give up to 33% stride spread across views; a shared seed brings it to ~9%.
- **Never render both sides** — mirror one, so the two directions cannot desync.
- **`length % 17 == 5`** — 5, 22, 39, 56, 73, 90, 107, 124. 56 = two full strides at 24 fps.
- **H3 drops negations.** "no third sword" produces more swords — phrase positively.
- **The reference beats the prompt.** If they disagree, fix the reference, not the wording.

Full list in [`references/pitfalls.md`](references/pitfalls.md).
