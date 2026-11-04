#!/usr/bin/env bash
# A complete run. Copy, edit the paths and the --subject line, execute.
set -euo pipefail

SKILL="${HOME}/.workbuddy/skills/pixel-sprite-sheet"
SHEET="$1"                       # e.g. ~/art/hero_4views.png
PROJ="${2:-./sprite-project}"
ACTION="${3:-walk}"              # walk run idle attack cast hurt jump, or custom

mkdir -p "$PROJ"/{views,frames,out,videos}

echo "== 1/6 environment"
python "$SKILL/scripts/generate.py" --health

echo "== 2/6 split views"
python "$SKILL/scripts/split_views.py" "$SHEET" --out "$PROJ/views"

echo "== 3/6 generate (one batch, one seed)"
# EDIT the subject line to match the character in the reference image.
python "$SKILL/scripts/generate.py" \
  --views "$PROJ/views" \
  --out "$PROJ/frames/$ACTION" \
  --action "$ACTION" \
  --subject "TODO: describe the character in the reference image" \
  --frames 56 --seed 808080

echo "== 4/6 mirror + manifests"
if [ -d "$PROJ/frames/$ACTION/right" ]; then
  python "$SKILL/scripts/mirror.py" "$PROJ/frames/$ACTION/right" "$PROJ/frames/$ACTION/left"
fi
python "$SKILL/scripts/manifest.py" "$PROJ/frames/$ACTION" --dirs front,back,left,right

echo "== 5/6 studio"
python "$SKILL/scripts/serve.py" --root "$PROJ" --frames "frames/$ACTION" --open

echo "== 6/6 after you export, bake previews:"
echo "   python $SKILL/scripts/bake_gifs.py $PROJ/out/$ACTION.png --out $PROJ/out"
echo
# MANDATORY: the clip goes into the conversation, not just in a sentence.
# Hand these absolute paths to the file-presentation tool so the user watches
# the render, and again when you deliver the sheet. A path is not a deliverable.
echo ".. show these clips to the user (do not just print the paths):"
ls -1 "$PROJ/videos"/*.mp4 2>/dev/null || echo "   (no mp4 yet - did generate.py run?)"
