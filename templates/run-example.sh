#!/usr/bin/env bash
# A complete run — route A only. Copy, edit the paths and the --subject line.
#
# Route B (mannequin first, then the character) is two passes of step 3/4 with
# the same --seed and the same beat file; see references/proxy-pass.md. Do not
# bolt it on here: ask the user which route first.
set -euo pipefail

SKILL="${HOME}/.workbuddy/skills/pixel-sprite-sheet"
SHEET="$1"                       # e.g. ~/art/hero_4views.png
PROJ="${2:-./sprite-project}"
ACTION="${3:-walk}"              # walk run idle attack cast hurt jump, or custom
FRAMES="${4:-39}"

mkdir -p "$PROJ"/{views,frames,out,videos,beats}

echo "== 1/6 environment"
python "$SKILL/scripts/generate.py" --health || {
  echo "   not on 8190? a ComfyUI Desktop install usually serves 8188:"
  echo "   export H3_SERVER=http://127.0.0.1:8188"
  exit 1
}

echo "== 2/6 split views"
python "$SKILL/scripts/split_views.py" "$SHEET" --out "$PROJ/views"

echo "== 3/6 generate (prep + one batch, one seed)"
# generate.py pads the reference onto a square key-coloured canvas first — that
# is what stops a sword from leaving the frame. It prints the staged files.
# EDIT the subject line to match the character in the reference image.
BEATS="$PROJ/beats/$ACTION.txt"
DESC_ARG=()
if [ -f "$BEATS" ]; then
  DESC_ARG=(--describe-file "$BEATS")
else
  # a preset action can run without beats; a custom one cannot
  echo "   no $BEATS — falling back to the '$ACTION' preset."
  echo "   example beat file: $SKILL/templates/beats/attack-dual-sword.txt"
fi
python "$SKILL/scripts/generate.py" \
  --views "$PROJ/views" \
  --out "$PROJ/frames/$ACTION" \
  --action "$ACTION" \
  --subject "TODO: describe the character in the reference image" \
  "${DESC_ARG[@]}" \
  --frames "$FRAMES" --seed 808080

echo "== 4/6 mirror + manifests"
if [ -d "$PROJ/frames/$ACTION/right" ]; then
  python "$SKILL/scripts/mirror.py" "$PROJ/frames/$ACTION/right" "$PROJ/frames/$ACTION/left"
fi
python "$SKILL/scripts/manifest.py" "$PROJ/frames/$ACTION" --dirs front,back,left,right

echo "== 5/6 studio (the user keys and picks here — do not export for them)"
python "$SKILL/scripts/serve.py" --root "$PROJ" --frames "frames/$ACTION" --cmp 1x4 --open

echo "== 6/6 after you export, bake previews:"
echo "   python $SKILL/scripts/bake_gifs.py $PROJ/out/$ACTION.png --out $PROJ/out"
echo
# MANDATORY: the clip goes into the conversation, not just in a sentence.
# Hand these absolute paths to the file-presentation tool so the user watches
# the render, and again when you deliver the sheet. A path is not a deliverable.
echo ".. show these clips to the user (do not just print the paths):"
ls -1 "$PROJ/videos"/*.mp4 2>/dev/null || echo "   (no mp4 yet - did generate.py run?)"
