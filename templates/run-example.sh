#!/usr/bin/env bash
# A complete run — route A only. Copy, edit the paths and the --subject line.
#
# Route B (mannequin first, then the character) is the same storyboard rendered
# twice; see references/proxy-pass.md. Do not bolt it on here: the route is the
# one question worth asking, and it is asked once at the start.
#
# This script stops at step 4 the first time it runs, on purpose: there is no
# animation until the storyboard's subject says what the character is. Fill it
# in, re-run, and the rest of the pipeline runs unattended.
set -euo pipefail

SKILL="${HOME}/.workbuddy/skills/pixel-sprite-sheet"
SHEET="$1"                       # e.g. ~/art/hero_4views.png
PROJ="${2:-./sprite-project}"
ACTION="${3:-walk}"              # walk run idle attack cast hurt jump, or custom
FRAMES="${4:-39}"

mkdir -p "$PROJ"/{views,frames,out,videos,beats}

echo "== 1/8 environment"
python "$SKILL/scripts/generate.py" --health || {
  echo "   not on 8190? a ComfyUI Desktop install usually serves 8188:"
  echo "   export H3_SERVER=http://127.0.0.1:8188"
  exit 1
}

echo "== 2/8 split views"
python "$SKILL/scripts/split_views.py" "$SHEET" --out "$PROJ/views"

echo "== 3/8 facing audit"
# A reference whose front and back are the same picture makes the model turn the
# figure around mid-clip, and no prompt fixes it. This is a hard stop: every
# back-view render would be wasted. See references/facing.md.
if ! python "$SKILL/scripts/check_facing.py" "$PROJ/views"; then
  echo "   FAIL — the front and back of this reference are the same picture."
  echo "   Give one side a different MATERIAL (back panel, lacing, emblem, stained"
  echo "   nape) and keep the outline identical, then re-run. Do not render yet."
  exit 1
fi

echo "== 4/8 storyboard（分镜）"
BOARD="$PROJ/beats/$ACTION.storyboard.json"
if [ -f "$BOARD" ]; then
  echo "   reusing $BOARD"
else
  echo "   writing a first draft from the '$ACTION' preset — the subject is a placeholder"
  python "$SKILL/scripts/storyboard.py" init --action "$ACTION" \
    --frames "$FRAMES" --out "$BOARD" \
    --subject "${SUBJECT:-TODO: describe the character in the reference image}"
fi

if ! python "$SKILL/scripts/storyboard.py" check "$BOARD"; then
  echo
  echo "   Fix the ERRORs above — every message says what to write instead."
  echo "   First run almost always fails on the subject: replace it with one"
  echo "   concrete sentence taken from the reference image (armour, colours,"
  echo "   weapon count), and add the loose parts to \"limits\" (cape, plume, skirt)."
  echo "   Then re-run this script; the board is reused from here on."
  exit 1
fi

# The 分镜表 is the human-readable half: beats, contract, render history.
python "$SKILL/scripts/storyboard.py" table "$BOARD" --out "${BOARD%.json}.md"
echo "   board -> $BOARD"
echo "   table -> ${BOARD%.json}.md"

echo "== 5/8 generate (prep + one batch, one seed — all from the board)"
# generate.py pads the reference onto a square key-coloured canvas first (that is
# what stops a sword from leaving the frame), picks the key colour from the
# character's own pixels, validates the board, and submits every view with the
# board's seed and frame count. No --seed / --frames / --action here on purpose:
# a flag on this line is a flag that can drift between the passes.
python "$SKILL/scripts/generate.py" \
  --views "$PROJ/views" \
  --out "$PROJ/frames/$ACTION" \
  --storyboard "$BOARD"

echo "== 6/8 mirror + manifests"
if [ -d "$PROJ/frames/$ACTION/right" ]; then
  python "$SKILL/scripts/mirror.py" "$PROJ/frames/$ACTION/right" "$PROJ/frames/$ACTION/left"
fi
python "$SKILL/scripts/manifest.py" "$PROJ/frames/$ACTION" --dirs front,back,left,right

echo "== 7/8 studio (the user keys and picks here — do not export for them)"
python "$SKILL/scripts/serve.py" --root "$PROJ" --frames "frames/$ACTION" --cmp 1x4 --open

echo "== 8/8 after the user exports, bake previews:"
echo "   python $SKILL/scripts/bake_gifs.py $PROJ/out/$ACTION.png --out $PROJ/out"
echo
# MANDATORY: the clip goes into the conversation, not just in a sentence.
# Hand these absolute paths to the file-presentation tool so the user watches
# the render, and again when you deliver the sheet. A path is not a deliverable.
# Do not ask whether the motion looks right — show it and continue.
echo ".. show these clips to the user (do not just print the paths):"
ls -1 "$PROJ/videos"/*.mp4 2>/dev/null || echo "   (no mp4 yet - did generate.py run?)"
