"""One script, every direction — the storyboard that keeps four renders one performance.

H3 is image-to-video and gives every call its own tempo. Four directions rendered
from four paraphrases of one idea are therefore four different performances:

* mixed seeds alone measured **33%** stride spread across views (9% with one
  shared seed — see references/pitfalls.md#seeds);
* paraphrased beat wording adds drift on top of that, because the beats are the
  only thing telling the model *when* the extremes happen;
* and any parameter that differs per view (frames, key, coverage, limits) is a
  second performance dressed as a camera angle.

A storyboard is one JSON file that holds the whole animation decision — the beats
with their times, the extreme each beat has to reach, what the camera sees in
each direction, and every parameter that must not drift. `generate.py
--storyboard` reads it, so "the front view walks differently from the back view"
becomes a diff instead of a mystery.

    # from a preset
    python storyboard.py init --action walk --subject "a chibi knight" \\
        --out beats/walk.storyboard.json

    # from beat text you already wrote ("At 0.30 seconds ..." sentences)
    python storyboard.py init --action slash --kind one-shot \\
        --from beats/slash.txt --out beats/slash.storyboard.json

    # the three things worth doing before a render is spent
    python storyboard.py check beats/walk.storyboard.json
    python storyboard.py table beats/walk.storyboard.json --out beats/walk.md
    python storyboard.py plan  beats/walk.storyboard.json

    # afterwards: fold the result back in, so the board is the project record
    python storyboard.py record beats/walk.storyboard.json --version 3 \\
        --qc pass --clip front=videos/walk_v03_front.mp4 ...

The file stays human-editable on purpose: the beats are sentences, the times are
fractions, and `check` re-validates after every edit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCHEMA = "pixel-sprite-storyboard/1"
FPS = 24.0
KINDS = ("loop", "one-shot", "death")
VIEW_ORDER = ("front", "back", "right", "left")
VALID_VIEWS = set(VIEW_ORDER)

# A beat shorter than this many frames is a smear, not a pose — the model
# resolves it as part of its neighbour and the extreme never reads.
BEAT_MIN_FRAMES = 4

# Presets that are cycles by nature. init uses this to pick `kind`, which decides
# whether a `close` sentence (last frame == first frame) is required.
LOOP_PRESETS = {"walk", "run", "idle"}

# The four things every clip must hold, whatever the action. Anything action
# specific belongs in the beats or in --invariant.
DEFAULT_INVARIANTS = [
    "identical proportions, colors and costume details in every frame",
    "the camera is locked off for the whole clip",
    "the weight stays over the feet and a planted foot never slides",
    "every beat lands at its stated second, in every direction",
]

# "without a seam" is a loop instruction, not a visual negation — the words that
# actually flip into objects are no / not / never.
NEGATION_RE = re.compile(r"\b(no|not|never)\b", re.I)
# What makes a board unrenderable: a placeholder nobody filled in, and two
# actions in one clip (they average into neither).
TODO_MARKERS = ("TODO", "TBD", "XXX")


def snap_length(n: int) -> int:
    """Round n up to the nearest value with n % 17 == 5 — H3's frame grid."""
    n = max(5, int(n))
    return n + (5 - n % 17) % 17


def _mp():
    """make_prompt, imported late: PRESETS/VIEWS are the only shared vocabulary."""
    import make_prompt
    return make_prompt


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------

def default_kind(action: str) -> str:
    return "loop" if action in LOOP_PRESETS else "one-shot"


def default_views() -> dict:
    return {
        "front": {},
        "back": {},
        "right": {},
    }


def from_preset(action: str, subject: str = "", frames: int = 56,
                seed: int = 808080, key: str = "auto",
                coverage: str = "auto", limits: str | None = None,
                views: list[str] | None = None, kind: str | None = None,
                note: str = "", anchors: dict[str, str] | None = None) -> dict:
    """A board for one of the built-in presets.

    The preset beats are reused *verbatim* — that wording is the measured one —
    and only gain a timing fraction and a name for the table.
    """
    mp = _mp()
    preset = mp.PRESETS.get(action)
    if not preset:
        raise SystemExit(f"unknown preset '{action}'. Try one of "
                         f"{', '.join(mp.PRESETS)}, or --from <beat file>.")
    frames = snap_length(frames)
    marks = preset.get("marks") or []
    beats = []
    for i, (frac, sentence) in enumerate(preset["beats"]):
        beats.append({
            "frac": round(frac, 4),
            "mark": marks[i] if i < len(marks) else f"beat {i + 1}",
            "motion": sentence,
        })
    return {
        "schema": SCHEMA,
        "action": action,
        "label": preset.get("label", action),
        "kind": kind or default_kind(action),
        "note": note,
        "subject": subject,
        "fps": FPS,
        "frames": frames,
        "seed": seed,
        "key": key,
        "coverage": coverage,
        "limits": [s.strip() for s in
                   (limits or ",".join(preset.get("limits", []))).split(",")
                   if s.strip()],
        "invariants": list(DEFAULT_INVARIANTS),
        "beats": beats,
        "close": preset.get("close", ""),
        "views": _views_from(views, anchors),
        "renders": [],
    }


def _views_from(views: list[str] | None, anchors: dict[str, str] | None) -> dict:
    out = {}
    for v in (views or ["front", "back", "right"]):
        v = v.strip().lower()
        if v not in VALID_VIEWS:
            raise SystemExit(f"unknown view '{v}' — front / back / right / left")
        out[v] = {}
        if anchors and anchors.get(v):
            out[v]["anchor"] = anchors[v]
    return out


TIME_RE = re.compile(
    r"(?:^|\s|[,;.])(?:at\s+)?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b[^a-zA-Z]*",
    re.I)


def from_text(text: str, action: str, subject: str = "", frames: int = 56,
              seed: int = 808080, key: str = "auto", coverage: str = "auto",
              limits: str | None = None, views: list[str] | None = None,
              kind: str | None = None, label: str = "",
              anchors: dict[str, str] | None = None) -> dict:
    """A board from prose.

    Two shapes are accepted:

    * ``At 0.30 seconds the weight passes over the right foot ...`` — the format
      `templates/beats/*.txt` already uses. Each timestamp opens a beat.
    * free prose with no timestamps — kept as one beat covering the whole clip,
      and `check` says so, because a single beat gives the model no rhythm to
      hit. Splitting it into 3–5 "At X seconds" sentences is the fix.

    A trailing "The final pose matches the opening pose" sentence is lifted into
    ``close``: it is a loop instruction, not a beat.
    """
    frames = snap_length(frames)
    seconds = frames / FPS
    kind = kind or default_kind(action)
    flat = re.sub(r"\s+", " ", text).strip()

    found = list(TIME_RE.finditer(flat))
    beats: list[dict] = []
    if len(found) >= 2:
        cuts = [m.start() for m in found] + [len(flat)]
        for i, m in enumerate(found):
            t = float(m.group(1))
            body = flat[cuts[i]:cuts[i + 1]]
            body = TIME_RE.sub("", body).strip(" ,;.")
            if not body:
                continue
            beats.append({"frac": round(min(t / seconds, 0.98), 4),
                          "mark": f"beat {len(beats) + 1}",
                          "motion": _sentence(body)})
    else:
        beats = [{"frac": 0.0, "mark": "whole clip", "motion": _sentence(flat)}]

    # A trailing "The final pose matches the opening pose …" is a loop
    # instruction, not a beat — left in the beat list it competes with the pose
    # that shares its second.
    close = ""
    if beats:
        m = re.search(r"\bThe final pose\b.*$", beats[-1]["motion"], re.I)
        if m:
            close = m.group(0).strip()
            rest = beats[-1]["motion"][:m.start()].strip(" ,;.")
            if rest:
                beats[-1]["motion"] = _sentence(rest)
            else:
                beats.pop()
    if not close:
        # A loop still needs the instruction; a death must not have one.
        close = ("" if kind == "death"
                 else "The final pose matches the opening pose so the clip can be looped.")

    return {
        "schema": SCHEMA,
        "action": action,
        "label": label or (_mp().PRESETS.get(action, {}).get("label") or action),
        "kind": kind,
        "note": "",
        "subject": subject,
        "fps": FPS,
        "frames": frames,
        "seed": seed,
        "key": key,
        "coverage": coverage,
        "limits": [s.strip() for s in (limits or "legs,arms,torso").split(",")
                   if s.strip()],
        "invariants": list(DEFAULT_INVARIANTS),
        "beats": beats,
        "close": close,
        "views": _views_from(views, anchors),
        "renders": [],
    }


def _sentence(s: str) -> str:
    s = s.strip()
    if s and not s.endswith("."):
        s += "."
    return s


# --------------------------------------------------------------------------
# Reading / writing
# --------------------------------------------------------------------------

def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        board = json.load(f)
    return normalise(board)


def normalise(board: dict) -> dict:
    """Accept hand-written boards without demanding every field.

    Everything here has a defensible default, so a board with `action`,
    `subject` and `beats` is already renderable — which is the point: writing
    five sentences must not require reading a schema.
    """
    b = dict(board)
    b.setdefault("schema", SCHEMA)
    b.setdefault("kind", default_kind(b.get("action", "")))
    b.setdefault("label", b.get("action", ""))
    b.setdefault("note", "")
    fps = float(b.get("fps") or FPS)
    b["fps"] = int(fps) if fps == int(fps) else fps   # 24, not 24.0, in the file
    # Snap to H3's grid here rather than at submit time, so the beat times shown
    # in the table are the times the render will actually use. The number the
    # file asked for is kept under _input so `check` can say what happened.
    raw_frames = int(b.get("frames") or 56)
    b["frames"] = snap_length(raw_frames)
    if b["frames"] != raw_frames:
        b.setdefault("_input", {})["frames"] = raw_frames
    b.setdefault("seed", 808080)
    b.setdefault("key", "auto")
    b.setdefault("coverage", "auto")
    b.setdefault("limits", ["legs", "arms", "torso"])
    b.setdefault("invariants", list(DEFAULT_INVARIANTS))
    b.setdefault("renders", [])
    b["seconds"] = round(b["frames"] / float(b.get("fps") or FPS), 4)

    views = b.get("views")
    if not views:
        b["views"] = default_views()
    elif isinstance(views, list):
        b["views"] = {v: {} for v in views}
    else:
        b["views"] = {k: (v or {}) for k, v in views.items()}

    raw_beats = b.get("beats") or []
    beats = []
    for i, raw in enumerate(raw_beats):
        beat = {"mark": f"beat {i + 1}", "motion": ""}
        if isinstance(raw, str):
            beat["motion"] = _sentence(raw)
        else:
            beat.update({k: v for k, v in raw.items() if v is not None})
        # `t` (seconds) and `fr`/`frac` are both accepted; frac is canonical so a
        # change of --frames rescales the performance instead of truncating it.
        if "frac" not in beat:
            if "t" in beat:
                beat["frac"] = round(float(beat.pop("t")) / b["seconds"], 4)
            elif "fr" in beat:
                beat["frac"] = round(float(beat.pop("fr")) / b["frames"], 4)
            else:
                beat["frac"] = round(i / max(1, len(raw_beats) - 1) * 0.9, 4)
        beat["frac"] = round(float(beat["frac"]), 4)
        beat["motion"] = _sentence(str(beat.get("motion", "")))
        if beat.get("see"):
            beat["see"] = {k: _sentence(str(v)) for k, v in beat["see"].items() if v}
            if not beat["see"]:
                beat.pop("see")
        # Fixed key order: frac, mark, motion, see. A board is read by humans
        # first and parsed second.
        ordered = {"frac": beat["frac"], "mark": beat.get("mark", ""),
                   "motion": beat["motion"]}
        if beat.get("see"):
            ordered["see"] = beat["see"]
        beats.append(ordered)
    b["beats"] = beats
    return b


def save(board: dict, path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    clean = {k: v for k, v in board.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=1, ensure_ascii=False)
        f.write("\n")


# --------------------------------------------------------------------------
# Validation — the part that saves renders
# --------------------------------------------------------------------------

def check(board: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings). An error means do not render; a warning means go and
    look, because it is the kind of thing that costs one clip, not six."""
    err: list[str] = []
    warn: list[str] = []
    secs = board["seconds"]
    frames = board["frames"]

    if not str(board.get("action", "")).strip():
        err.append("action is empty — name it after the motion (walk, slash, …)")
    if board.get("kind") not in KINDS:
        err.append(f"kind must be one of {', '.join(KINDS)} "
                   f"(got {board.get('kind')!r})")

    subject = str(board.get("subject") or "").strip()
    if not subject:
        err.append("subject is empty — it is the only place the costume is described")
    else:
        if any(t in subject for t in TODO_MARKERS):
            err.append("subject still contains a TODO marker — describe the character "
                       "from the reference image")
        if len(subject.split()) < 4:
            warn.append(f"subject is very short ({len(subject.split())} words): H3 "
                        f"holds identity from this line alone")
        if NEGATION_RE.search(subject):
            warn.append("subject contains a negation — H3 drops negations and often "
                        "inverts them; describe what IS there")

    raw_frames = (board.get("_input") or {}).get("frames")
    if raw_frames and raw_frames != frames:
        warn.append(f"frames {raw_frames} is not on H3's grid (…, 39, 56, 73, …) — "
                    f"loaded as {frames}, and the beat times below are for {frames}")
    if frames < 22:
        warn.append(f"{frames} frames is under a second; most actions need 39–73")

    beats = board.get("beats") or []
    if len(beats) < 2:
        err.append("only one beat — the model has no rhythm to hit. Split the action "
                   "into 3–5 'At X seconds …' sentences (extremes, not the path)")
    if len(beats) > 6:
        warn.append(f"{len(beats)} beats is a lot for {secs:.2f}s; H3 merges the "
                    f"crowded ones. 3–5 reads better")

    last = -1.0
    for i, b in enumerate(beats):
        tag = f"beat {i + 1} ({b.get('mark')})"
        f = float(b["frac"])
        if not 0.0 <= f < 1.0:
            err.append(f"{tag}: frac {f} must be inside [0, 1)")
        if f <= last:
            err.append(f"{tag}: frac {f} is not after the previous beat ({last}) — "
                       f"beats must strictly increase")
        last = f
        words = b["motion"].split()
        if len(words) < 4:
            err.append(f"{tag}: motion is {len(words)} words — name the extreme "
                       f"(\"the arm drawn back across the body\"), not the path")
        if len(words) > 60:
            warn.append(f"{tag}: {len(words)} words is a paragraph; H3 reads the "
                        f"first clause and drops the rest")
        if NEGATION_RE.search(b["motion"]):
            warn.append(f"{tag}: negation in the beat — phrase it positively "
                        f"(references/pitfalls.md#negations)")

    if beats and float(beats[0]["frac"]) > 0.02:
        warn.append(f"first beat starts at {beats[0]['frac']:.2f} of the clip — the "
                    f"head of the render has no instruction")
    if beats and float(beats[-1]["frac"]) > 0.95:
        warn.append("last beat is at the very end — there is no time to settle into "
                    "the closing pose")
    if beats and float(beats[-1]["frac"]) < 0.62:
        end = float(beats[-1]["frac"])
        warn.append(f"the last beat is at {end:.2f} of the clip: the model holds the "
                    f"final pose for the remaining {1 - end:.0%} "
                    f"({(1 - end) * secs:.2f}s). That is what happens when beat text "
                    f"written for a shorter clip is rendered longer — spread the "
                    f"beats or lower --frames")

    # Is every beat long enough to be seen as a pose?
    for i, b in enumerate(beats):
        nxt = beats[i + 1]["frac"] if i + 1 < len(beats) else 1.0
        span = (float(nxt) - float(b["frac"])) * frames
        if 0 <= span < BEAT_MIN_FRAMES:
            warn.append(f"beat {i + 1} ({b.get('mark')}) lasts {span:.0f} frames at "
                        f"24 fps — under {BEAT_MIN_FRAMES} it smears into its "
                        f"neighbour")

    if board.get("kind") == "loop":
        if not str(board.get("close") or "").strip():
            err.append("a loop needs a close sentence: the last frame must match the "
                       "first or the cycle pops when it wraps")
        elif not re.search(r"match|same as|equal", str(board["close"]), re.I):
            warn.append("close does not say the last pose matches the first — that is "
                        "the only instruction that closes a cycle")
    if board.get("kind") == "death" and str(board.get("close") or "").strip():
        warn.append("a death does not loop; the close sentence will pull it back to "
                    "standing. kind=one-shot or drop close")

    if not board.get("limits"):
        err.append("limits is empty — nothing is declared movable, so nothing moves")

    views = list((board.get("views") or {}).keys())
    if not views:
        err.append("no views — declare at least front and back")
    unknown = [v for v in views if v not in VALID_VIEWS]
    if unknown:
        err.append(f"unknown view(s): {', '.join(unknown)} — "
                   f"front / back / right / left")
    if "left" in views and "right" in views:
        warn.append("left and right declared: the side is mirror.py's job, rendering "
                    "both spends a render to get the same pixels with different jitter")
    if "left" in views and "right" not in views:
        warn.append("left without right: generate.py falls back to right.png and "
                    "mirror.py expects right → left")
    for v in views:
        anchor = str((board["views"].get(v) or {}).get("anchor") or "")
        if NEGATION_RE.search(anchor):
            warn.append(f"anchor for {v} contains a negation — describe what the "
                        f"camera sees")

    for i, b in enumerate(beats):
        for v in (b.get("see") or {}):
            if v not in views:
                warn.append(f"beat {i + 1} has a 'see' line for '{v}', which is not a "
                            f"declared view — it will never be used")

    cov = board.get("coverage")
    if cov not in (None, "auto"):
        try:
            c = float(cov)
            if not 0.34 <= c <= 0.70:
                err.append(f"coverage {c} is outside 0.34–0.70 — too big crops the "
                           f"arc, too small loses the pixels")
        except (TypeError, ValueError):
            err.append(f"coverage {cov!r} is neither 'auto' nor a number")

    key = str(board.get("key") or "auto")
    if key.lower() not in ("auto", "green", "magenta", "cyan") and not re.fullmatch(
            r"#[0-9a-fA-F]{6}", key):
        err.append(f"key {key!r} must be auto / green / magenta / cyan / #RRGGBB")

    if not board.get("invariants"):
        warn.append("no invariants — the consistency contract is the part that keeps "
                    "the four directions one performance")

    return err, warn


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------

def table(board: dict) -> str:
    """The Markdown 分镜表 — what the user reads instead of a JSON file."""
    secs = board["seconds"]
    L = [f"# {board['action']} — {board.get('label') or board['action']}", ""]
    if board.get("note"):
        L += [f"> {board['note']}", ""]
    L += [f"`{board['action']}` · {board['kind']} · {board['frames']} 帧 @ "
          f"{board['fps']}fps = {secs:.2f} 秒 · {len(board['beats'])} 拍"
          f" · views {', '.join(board['views'])}", ""]

    L += ["| # | 时间 | 标记 | 动作（进 prompt，四个方向同一句） |",
          "| --- | --- | --- | --- |"]
    for i, b in enumerate(board["beats"]):
        t = float(b["frac"]) * secs
        L.append(f"| {i + 1} | {t:.2f}s | {b['mark']} | {b['motion']} |")
    L.append("")

    seen = [b for b in board["beats"] if b.get("see")]
    if seen:
        L += ["## 各方向的证据句", ""]
        for b in seen:
            t = float(b["frac"]) * secs
            L.append(f"- **{t:.2f}s {b['mark']}** — " +
                     "；".join(f"{v}: {str(x).rstrip('.')}"
                              for v, x in b["see"].items()))
        L.append("")

    L += ["## 一致性契约（四个方向共用，缺一条就会出现\"某个方向不一样\"）", ""]
    L.append(f"- seed `{board['seed']}` · frames `{board['frames']}` · "
             f"key `{board.get('key')}` · coverage `{board.get('coverage')}`")
    L.append(f"- 只允许动：{', '.join(board.get('limits') or [])}")
    L.append(f"- subject（唯一描述服装的一句）：{board.get('subject') or '—'}")
    for inv in board.get("invariants") or []:
        L.append(f"- {inv}")
    if board.get("close"):
        L.append(f"- 收势：{board['close']}")
    L.append("")

    if board.get("renders"):
        L += ["## 渲染记录", "", "| 版本 | 尝试 | QC | 种子 | coverage | 片段 |",
              "| --- | --- | --- | --- | --- | --- |"]
        for r in board["renders"]:
            clips = ", ".join(os.path.basename(str(x))
                              for x in (r.get("clips") or {}).values())
            L.append(f"| v{int(r.get('version', 0)):02d} | {r.get('attempt', 1)} | "
                     f"{r.get('qc', '?')} | {r.get('seed', '')} | "
                     f"{r.get('coverage', '')} | {clips or '—'} |")
        L.append("")
    return "\n".join(L)


def plan(board: dict, board_path: str = "BOARD.json", views_dir: str = "views",
         out_dir: str | None = None, proxy: bool = False) -> str:
    """The exact commands, with every shared parameter coming from the board.

    Written out rather than executed because this is the text the agent pastes:
    if a flag is going to be forgotten, it should be forgotten here, where it is
    visible, and not in a run that spends eight minutes.
    """
    out = out_dir or f"frames/{board['action']}"
    views = ",".join(board["views"])
    steps = ["# 1) prompts only — read them before spending a render",
             f"python scripts/storyboard.py prompts {board_path} "
             f"--out-dir {out}/_prompts",
             ""]
    if proxy:
        steps += ["# 2) proxy pass — mannequin, empty hands (route B only)",
                  f"python scripts/generate.py --views {views_dir}_proxy "
                  f"--out {out}_proxy \\",
                  f"  --storyboard {board_path} --views-wanted {views} \\",
                  '  --subject "a plain wooden artist\'s mannequin, empty hands, '
                  'no weapon"',
                  ""]
    n = 3 if proxy else 2
    steps += [f"# {n}) one batch, one seed, every view — the board carries the seed, "
              f"the frames, the key, the coverage and the limits",
              f"python scripts/generate.py --views {views_dir} --out {out} \\",
              f"  --storyboard {board_path} --views-wanted {views}",
              "",
              f"# {n + 1}) mirror the side, then renumber",
              f"python scripts/mirror.py {out}/right {out}/left",
              f"python scripts/manifest.py {out} --dirs front,back,left,right",
              "",
              f"# {n + 2}) the studio",
              f"python scripts/serve.py --root . --frames {out} --cmp 1x4 --open"]
    return "\n".join(steps)


# --------------------------------------------------------------------------
# Record — the board is the project record, not a scratch file
# --------------------------------------------------------------------------

def add_render(board: dict, version: int, clips: dict[str, str], qc: str = "unknown",
               attempt: int = 1, coverage=None, key=None, note: str = "",
               seed: int | None = None) -> dict:
    board.setdefault("renders", []).append({
        "version": int(version),
        "attempt": int(attempt),
        "at": _now(),
        "qc": qc,
        "seed": seed if seed is not None else board.get("seed"),
        "coverage": coverage if coverage is not None else board.get("coverage"),
        "key": key if key is not None else board.get("key"),
        "frames": board.get("frames"),
        "clips": dict(clips),
        "note": note,
    })
    return board


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _parse_pairs(items: list[str] | None, what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--{what} needs view=text (got {it!r})")
        k, v = it.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Storyboard: one script for every direction.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--action", default="walk")
        p.add_argument("--subject", default="")
        p.add_argument("--subject-file")
        p.add_argument("--frames", type=int, default=56)
        p.add_argument("--seed", type=int, default=808080)
        p.add_argument("--key", default="auto")
        p.add_argument("--coverage", default="auto")
        p.add_argument("--limits")
        p.add_argument("--views", default="front,back,right")
        p.add_argument("--anchor", action="append",
                       help="view=text: what the camera sees in that view")
        p.add_argument("--kind", choices=KINDS)
        p.add_argument("--out", required=True)

    p_init = sub.add_parser("init", help="write a new board (preset or beat text)")
    add_common(p_init)
    p_init.add_argument("--from", dest="src", help="beat text file to convert")
    p_init.add_argument("--label", default="")
    p_init.add_argument("--note", default="", help="one line of intent")
    p_init.add_argument("--invariant", action="append",
                        help="extra consistency line, repeatable")
    p_init.add_argument("--force", action="store_true",
                        help="overwrite an existing board")

    p_check = sub.add_parser("check", help="validate a board")
    p_check.add_argument("board")
    p_check.add_argument("--quiet", action="store_true")

    p_table = sub.add_parser("table", help="print the Markdown 分镜表")
    p_table.add_argument("board")
    p_table.add_argument("--out", help="write the .md here")

    p_prompts = sub.add_parser("prompts", help="build one prompt per view (no render)")
    p_prompts.add_argument("board")
    p_prompts.add_argument("--out-dir", required=True)
    p_prompts.add_argument("--key", help="resolved key hex, e.g. #FF00FF")
    p_prompts.add_argument("--key-name", help="how the prompt names the key colour")

    p_plan = sub.add_parser("plan", help="print the render commands")
    p_plan.add_argument("board")
    p_plan.add_argument("--views-dir", default="views")
    p_plan.add_argument("--out-dir")
    p_plan.add_argument("--proxy", action="store_true",
                        help="include the mannequin pass (route B)")

    p_rec = sub.add_parser("record", help="fold a render's result back in")
    p_rec.add_argument("board")
    p_rec.add_argument("--version", type=int, required=True)
    p_rec.add_argument("--clip", action="append", help="view=path, repeatable")
    p_rec.add_argument("--qc", default="unknown",
                       choices=("pass", "warn", "fail", "unknown"))
    p_rec.add_argument("--attempt", type=int, default=1)
    p_rec.add_argument("--coverage")
    p_rec.add_argument("--key")
    p_rec.add_argument("--note", default="")

    p_sub = sub.add_parser("subject", help="print the resolved subject line")
    p_sub.add_argument("board")

    args = ap.parse_args(argv)

    if args.cmd == "init":
        subject = args.subject
        if args.subject_file:
            with open(args.subject_file, encoding="utf-8") as f:
                subject = f.read().strip()
        anchors = _parse_pairs(args.anchor, "anchor")
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        if args.src:
            with open(args.src, encoding="utf-8") as f:
                text = f.read()
            board = from_text(text, args.action, subject, args.frames, args.seed,
                              args.key, args.coverage, args.limits, views,
                              args.kind, args.label, anchors)
        else:
            board = from_preset(args.action, subject, args.frames, args.seed,
                                args.key, args.coverage, args.limits, views,
                                args.kind, args.note, anchors)
        for extra in args.invariant or []:
            board["invariants"].append(extra)
        if os.path.exists(args.out) and not args.force:
            raise SystemExit(f"{args.out} exists — pass --force to overwrite "
                             f"(a board is a project record, not a cache)")
        board = normalise(board)
        save(board, args.out)
        err, warn = check(board)
        print(f"wrote {args.out}  ({len(board['beats'])} beats, "
              f"{board['frames']} frames, {board['seconds']:.2f}s)")
        for w in warn:
            print(f"  warn  {w}")
        for e in err:
            print(f"  ERROR {e}")
        return 1 if err else 0

    board = load(args.board)

    if args.cmd == "check":
        err, warn = check(board)
        if not args.quiet:
            print(f"{board['action']}  {board['frames']}f  {board['seconds']:.2f}s  "
                  f"{len(board['beats'])} beats  seed {board['seed']}  "
                  f"views {', '.join(board['views'])}")
            for w in warn:
                print(f"  warn  {w}")
            for e in err:
                print(f"  ERROR {e}")
            print("PASS" if not err else "FAIL")
        return 1 if err else 0

    if args.cmd == "table":
        md = table(board)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(md + "\n")
            print(f"wrote {args.out}")
        else:
            print(md)
        return 0

    if args.cmd == "prompts":
        import make_prompt as mp
        os.makedirs(args.out_dir, exist_ok=True)
        keyname = args.key_name or mp.KEY_NAME
        keyhex = args.key or mp.KEY_HEX
        cov = board.get("coverage")
        cov = None if cov in (None, "auto") else float(cov)
        for v, spec in board["views"].items():
            prompt = mp.build_prompt(
                v, board["action"], board.get("subject") or "", board["seconds"],
                board=board, anchor=(spec or {}).get("anchor"),
                key_name=keyname, key_hex=keyhex, coverage=cov)
            path = os.path.join(args.out_dir, f"prompt_{v}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(prompt + "\n")
            print(f"{v:6s} {len(prompt):5d} chars -> {path}")
        return 0

    if args.cmd == "plan":
        print(plan(board, args.board, args.views_dir, args.out_dir, args.proxy))
        return 0

    if args.cmd == "record":
        add_render(board, args.version, _parse_pairs(args.clip, "clip"), args.qc,
                   args.attempt, args.coverage, args.key, args.note)
        save(board, args.board)
        print(f"recorded v{args.version:02d} ({args.qc}) in {args.board}")
        return 0

    if args.cmd == "subject":
        print(board.get("subject") or "")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
