# Sprite Sheet Studio — interaction model

A single-file web app (`studio/index.html`, no build step). Served by
`serve.py`, which copies it into the project folder so the studio and the frames
share one origin.

```
<sprite-project>/
  _studio/index.html      ← copied by serve.py
  videos/                 ← 每次渲染的原始 mp4，文件名带版本号（generate.py 归档）
    index.json
    walk_v01_front.mp4
  frames/walk/front/…     ← from generate.py + manifest.py
  out/walk.png            ← exported from the studio
```

URL: `http://127.0.0.1:<port>/_studio/index.html?frames=/frames/walk&videos=/videos`

`serve.py` appends `&videos=/videos` by itself when `videos/index.json` exists.

---

## Layout

```
┌ topbar ──────────────────────────────────────────────────────┐
│ Sprite Sheet Studio · badge · 流程说明 · 动画预览 ↗           │
├ 左：素材与参数 ─┬ 中：四方向对比预览 ─┬ 右：候选帧池 ────────┤
│ 四方向素材      │  0.5s / 槽 3/12      │  候选帧 48 ⤢ ＋PNG 参考│
│ 版本化视频 ←videos/ │  ┌────┐ ┌────┐    │  点击模式 [顺序|插入] │
│ 一致性检查      │  │ 前 │ │ 后 │       │  ┌──┬──┬──┐          │
│ 采样            │  └────┘ └────┘       │  │ 1│ 2│ 3│  …       │
│ 步态相位        │  ┌────┐ ┌────┐  背景▦│  └──┴──┴──┘          │
│ 抠图 / 对齐 /   │  │ 左 │ │ 右 │       │                      │
│ 像素化          │  └────┘ └────┘       │                      │
├─────────────────┴───────────┬──────────┴──────────────────────┤
│ ◀ ▶ ▶ 帧率 洋葱皮 参考线 单|2×2|1×4  循环 │                    │
├ 底部：时间轴（四行，每行一个方向）────────────────────────────┤
│ 前 [⟲ ⇄ ✕]│ ▣▣▣▣▣▣▣▣▣▣▣▣ +                                │
│ 后 [⟲ ⇄ ✕]│ ▣▣▣▣▣▣▣▣▣▣▣▣ +                                │
│ 左 [⟲ ⇄ ✕]│ ▣▣▣▣▣▣▣▣▣▣▣▣ +                                │
│ 右 [⟲ ⇄ ✕]│ ▣▣▣▣▣▣▣▣▣▣▣▣ +                                │
├ footer: 列数 间距 放大 四方向合并 文件名 │ 导出 JSON · 导出 Sprite Sheet ┤
```

Expanded (`多方向墙`, the `⤢`-style button next to the 候选帧 count):

```
├ 左：素材与参数 ─┬─ 中：预览 ─┬─ 右：候选帧墙（每向两列）───────────┤
│ (窄屏 <1360px   │            │  候选帧 66 ⤢ ＋PNG                │
│  自动让出)      │            │  点击模式 [顺序选帧|插入选帧]      │
│                 │            │   前18帧·12槽 │ 后17帧·9槽  │ 左…  │
│                 │            │  ┌──┐┌──┐│┌──┐┌──┐│┌──┐┌──┐     │
│                 │            │  │01││02│││01││02│││01││02│  同  │
│                 │            │  ├──┤├──┤│├──┤├──┤│└──┘└──┘  一  │
│                 │            │  │03││04│││03││04││         行  │
│                 │            │  └──┘└──┘│└──┘└──┘│  │ = 同一对 │
```


---

## The core idea: one direction at a time — unless you ask for four

The right panel is a **single-direction candidate pool**, not four views side by
side. Four views in one grid makes it ambiguous which timeline a click lands in.

The exception is the **多方向墙** (`⤢` button beside the 候选帧 count): the panel
widens to four groups, **two columns per direction**, rows aligned across groups.
Row *i* holds candidate *2i* in the left column and *2i+1* in the right one, so
"is 前 frame 7 the same pose as 后 frame 7" is answerable by reading one row
across — which is exactly what picking key frames needs.

Two columns per direction is what makes the wall fit on screen: 18 candidates go
from 18 rows to 9, so a whole direction is visible without scrolling. The pairing
is **interleaved** (2i / 2i+1) rather than "first half down column A, second half
down column B": with uneven frame counts, the block split either leaves one
column entirely empty (when the row count is taken from the longest direction) or
breaks cross-group row alignment (when each direction counts for itself).
Interleaved has neither failure mode, and reading left→right, top→bottom still
walks the candidates in chronological order, exactly like the collapsed pool.

Cells in the wall are ~86px at a 1400px window, so the corner badges degrade to
symbols: `接触` becomes a single orange dot, `✓ 3` becomes `3`, `附加` becomes `+`
(the tooltips keep the full wording). Chinese text at 7.5px renders as an ink
blot; the dot and the digit stay legible.

Inside the wall a click belongs to **its own column**: it switches the current
direction to that column (so the preview and the timeline highlight follow) and
then applies the active click mode. The click mode is deliberately one global
setting — 顺序 vs 插入 changes *what a click means*, not *which direction it
touches*, and having four different modes would be unteachable.

The wall is a layout state, not a data state: `P.wall` only changes CSS classes
plus which renderer builds the pool (`renderWall` vs the single-column path).
Both call the same `candCell()` builder, so badges, tints and click behaviour
cannot drift apart. Below 1360px the left column (素材与参数) is hidden while the
wall is open — picking does not need it, and squeezing the preview to nothing is
worse than hiding an idle panel.

Grouping is done with spacing, not borders: 5px between the two columns of a
direction, 14px between directions, plus a 1px hairline drawn in a `::before`
pseudo-element sitting inside that gap. The line must not consume track width —
unequal column widths would mean unequal row heights and the cross-group row
alignment would silently die.

**The current direction** is shown in four places, all driven by one function
(`focusDir`):

| Where | What it shows |
| --- | --- |
| Direction buttons (top right) | 前 / 后 / 左 / 右, with `48帧·12槽` under each |
| Focus bar | `正在拼：前向 · 候选 48 · 已用 12 槽` |
| Preview tag | `▸ 前 · 槽 3/12 · 候选 17` — the `▸` marks the active one |
| Timeline row | green left border + no dimming (other rows drop to 42% opacity) |

Switching direction via any of: the buttons, a timeline row header, or the
left-hand material slots. All three call `focusDir`, so the pool, the preview
and the highlight never disagree.

---

## Timeline model

Four independent index lists, `seqs = {front: [...], back: [...], left: [...], right: [...]}`.

Each list is a sequence of **candidate indices** for that direction. They may
have different lengths, and exporting lays each row out by its own length.

A shared "slot number" is the playback cursor: slot 5 plays each row's 5th
entry. Where that entry *comes from* is per-row, which is what makes both
"four views in sync" and "fix only the side view" possible at once.

### Controls

The candidate pool has **two click modes**, picked by the `点击模式` segmented
control directly above the frames. Default is `插入选帧` (the pre-existing
behaviour). The setting is shared by all four columns of the wall.

**`顺序选帧` — pick frames, order takes care of itself**

| Action | Result |
| --- | --- |
| Click a candidate | select it; it lands at its **candidate-order** position in the row |
| Click it again | deselect (the slot disappears) |
| Green `✓ n` on a cell | selected, and it sits in timeline slot `n` |
| Click a row header | switch current direction to that row |
| `×` on a slot | delete = deselect that candidate |
| Drag a slot / `⇄` / 复制末帧 | unavailable (order is defined by the pool) |

The invariant is "each candidate at most once, ascending". Because selection and
order are the same fact, there is no second source of truth: *selected* simply
means *present in the row*. Every mutation routes through `redrawTl()`, which
re-applies the invariant, so shortcuts like 依次填满, 反序, stride nudges and
phase re-derivation cannot leave a row that contradicts the check marks.

Use it when you are sifting a 40–60 frame pool down to 8 key poses: you look at
the strip and tick what you want, and the timeline assembles itself in the order
the source actually moves.

**`插入选帧` — place frames by hand**

| Action | Result |
| --- | --- |
| Click a candidate | append to the current direction's row |
| `Alt`/`⌘` + click | replace the selected slot |
| `Shift` + click | insert after the selected slot |
| Click a row header | switch current direction to that row |
| Drag a slot | reorder within the row |
| Double-click a slot | duplicate it (for holds / accents) |
| `×` on a slot | delete |
| `←` `→` | move the selection |
| `Space` | play / pause |

Same candidate may occupy several slots. This is the only mode that can build a
hold (three identical frames) or a repeated accent, which is why switching *into*
`顺序选帧` collapses duplicates and re-sorts — it says so in the toast.

### In the multi-direction wall

| Action | Result |
| --- | --- |
| Click a cell in group *X* | that click belongs to direction *X* (current direction switches to it first) |
| Click a group header | switch current direction; no data changes |
| Scroll | one shared scroll for all eight columns, so row *i* stays row *i* |
| A direction with fewer frames | its tail rows are dashed placeholders — the other groups keep their alignment |

Each direction is a two-column group; groups are separated by 14px of air plus a
hairline, so which two columns belong together is readable without a border
around every frame. The header is sticky, and the four direction buttons above
the pool are hidden while the wall is open (the headers already do that job and
carry the counts).

### Sync modes

- **四方向同步加帧** (off by default): when on, one click adds a slot to all
  four rows, each converted to its own tempo via the normalized phase `u`. Row
  lengths stay equal and the views stay in step.
- **复制到其它方向**: takes the current row and re-derives the other three rows
  from it by phase. This is the "I finished one direction, make the others
  follow" button.

Why it defaults to off: building one direction carefully is the normal case, and
a default-on sync surprises you by quietly changing three rows you did not look
at.

---

## Preview

A three-way segmented control in the transport bar picks the layout.
(It used to be a single `⊞` button that cycled through the three modes — a
feature you can only find by clicking an unlabelled icon over and over.)

| Segment | Keys | Shows | For |
| --- | --- | --- | --- |
| `单` | `1` | current direction only | building frames; largest image |
| `2×2` | `2` | four panels, one per direction | comparing silhouette / height |
| `1×4` | `3` | four in a row | comparing stride width, like reading a sheet |

In the comparison modes **all four panels share one scale factor**. Computing
each independently would scale the shorter view up to fill its box, erasing
exactly the height and stride differences you opened the comparison to see.

Panel tags shrink in comparison mode (`▸ 前 7/12`) so they stay on one line —
the full `槽 / 候选` text is still in the tooltip and in the focus view.

Playback starts automatically on load — otherwise a paused first frame reads as
"there is no animation".

### Background

The `背景` strip at the bottom-right of the preview sets what sits *behind* the
sprite. It never touches the export — the exported PNG is still transparent.

| Swatch | Use it for |
| --- | --- |
| 深棋盘 (default) | judging transparency; matches the dark UI |
| 浅棋盘 | transparency while editing against light UI / docs |
| 纯黑 | how the sprite reads on a dark game background |
| 纯白 | how it reads on a light background — catches outlines that only look right on dark |
| 中性灰 50% | the usual "neutral" ground for judging value and contrast |
| 洋红 | fringing check: a half-transparent edge shows up as a purple rim |

Guide lines switch to a darker blue/orange on light backgrounds, otherwise they
disappear into white. Thumbnails in the candidate pool keep the dark checker on
purpose — selection contrast matters more there than matching the preview.

---

## Quality panels (left column)

**一致性检查** — per-view height, and the spread between them. Above ~5% means
the unified cell size is doing damage; re-check the reference or the scale
denominator.

**步态相位** — per-view:

| Column | Meaning |
| --- | --- |
| 步数 | how many strides the source clip contains (editable; auto-estimate is a median of peak spacing, not autocorrelation) |
| 步长 | frames per stride = source frames / strides |
| 相位 | first slot's offset from the contact frame, plus nudge controls |

Editing 步数 re-lays only that row — other rows are the user's work and must not
be touched.

**抠图** — tolerance / softness / despill / edge erode. **Global**, applied to
every view with the same settings. If the character's costume contains the key
colour, change the key colour rather than fighting the tolerance.

**对齐** — anchor mode (`footlock` is the default and the right choice for
anything with a body bob), offsets, padding.

**像素化** — target height, scale denominator (`each` view / `global`), palette
size. All views share one pixel grid; that is non-negotiable for a sheet.

---

## Export

`导出 Sprite Sheet` opens a preview, then downloads.

- 四方向合并 → one row per view in a single PNG
- 列数 0 = auto (longest row)
- 放大 4× = a 64px character becomes 256px, nearest-neighbour, no blur
- 同时导出 JSON gives per-frame `x/y/w/h/duration` for Phaser / PixiJS / Godot

Then run `bake_gifs.py` on the exported PNG to get shareable previews.

---

## Keyboard / URL

`?frames=/path/to/frames` loads `<path>/{front,back,left,right}/`. For each
direction it tries `manifest.json` first, then **reads the directory listing**, so
a folder of `frame_001.png` (or a GIF, or an mp4) works without any manifest.
Directions that are absent are skipped.

`?videos=/videos` reads `videos/index.json` and turns on the **版本化视频** panel: a
version dropdown plus one button that loads that version's mp4s into their
directions. `serve.py` adds it automatically when the folder exists.

Those same clips are what you put on screen when reporting a result — see
*Non-negotiable: the video goes on screen, every time* in `SKILL.md`. The mp4
goes into the conversation; its path alone is not a delivery.

`?front=…&back=…&right=…` maps explicitly. With no parameters, drag files in.

`?cmp=focus|2x2|1x4` and `?bg=dcheck|lcheck|black|white|gray|magenta` open the
studio with the layout and backdrop already set — use these when handing a link
to someone so they see the same four-up view on the same background. `?cmp=` is
re-applied after the frame folder finishes loading; the loader's own default
(back to `focus`) only wins when the URL says nothing.

`?wall=1` opens with the candidate wall already expanded, for the same reason.

---

## Getting material in (three doors, three meanings)

| You drop | It becomes | Why |
| --- | --- | --- |
| **video / GIF** | 素材 for a direction — re-sampled into candidates | the clip is the source of truth; you want a different slice, not a fixed list |
| **PNG** (onto the candidate panel, or `＋PNG`) | extra candidates, appended 1:1 | hand-picked frames from another render are *additions*, not a replacement |
| **versioned mp4** via 版本化视频 | 素材, straight from `videos/vN` | re-pick from the original clip without hunting for the file |

GIF is decoded frame by frame (ImageDecoder, with a built-in GIF89a parser as
fallback), so an exported `<name>_strip.gif` can be dropped straight back in.

PNG extras:

- keep their own alpha — chroma key only ever *removes* opacity, so an
  already-keyed PNG is not re-keyed into a black halo
- go through the same key / scale / palette / anchor / placement as sampled
  frames, so they line up in the same cell
- are appended **after** the sampled frames and are excluded from gait analysis.
  They are marked with a purple `附加` badge; `清附加` removes them
- dropping PNGs on a track with no material yet makes them the material instead
  (otherwise the drop would look like it did nothing)

