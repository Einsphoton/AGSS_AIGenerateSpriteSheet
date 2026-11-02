"""Keep every render's source video in one findable, versioned folder.

Why this exists: H3 writes an mp4 next to the frames it decoded, so the only
copy of "the clip this sheet came from" ends up buried in
``frames/walk/back/`` under ComfyUI's own naming. Nobody finds it again, and
two renders of the same action overwrite each other's evidence.

So each batch moves its videos to ``<project>/videos/`` and names them

    <action>_v<NN>_<view>.mp4        walk_v02_front.mp4

with one version per *batch* (a batch is what generated.py submits at once),
and an ``videos/index.json`` that records what each version was:

    { "versions": [ { "version": 2, "action": "walk", "frames": 56,
                      "seed": 808080, "frames_dir": "frames/walk",
                      "files": {"front": "walk_v02_front.mp4", ...} } ] }

The studio reads that same index (``?videos=/videos``) and offers a version
picker, so "load the clip, not the frames" is one click.

CLI:

    python videos.py list --dir videos
    python videos.py import --dir videos --action walk --frames-dir frames/walk \
        --frames back:$PROJ/frames/walk/back/h3_00001_.mp4
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil

INDEX = "index.json"
VIDEO_EXT = (".mp4", ".webm", ".mov")


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def videos_dir(out_dir: str, override: str | None = None) -> str:
    """Where the videos for a run live.

    Convention is ``<project>/frames/<action>`` for ``--out``, so the default is
    ``<project>/videos``. If the caller used some other layout we fall back to a
    ``videos`` folder next to the frames, which is still one obvious place.
    """
    if override:
        return os.path.abspath(override)
    out = os.path.abspath(out_dir)
    parent = os.path.dirname(out)
    root = os.path.dirname(parent) if os.path.basename(parent) == "frames" else parent
    return os.path.join(root, "videos")


def slug(action: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "-", (action or "clip").strip().lower())
    return s.strip("-") or "clip"


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

def _load(vdir: str) -> dict:
    p = os.path.join(vdir, INDEX)
    if not os.path.exists(p):
        return {"versions": []}
    try:
        with open(p, encoding="utf-8") as f:
            js = json.load(f)
        js.setdefault("versions", [])
        return js
    except (OSError, ValueError):
        return {"versions": []}


def _save(vdir: str, js: dict) -> str:
    os.makedirs(vdir, exist_ok=True)
    js["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    p = os.path.join(vdir, INDEX)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(js, f, indent=1, ensure_ascii=False)
    return p


def next_version(vdir: str) -> int:
    """One past the highest version already on disk.

    Scans the filenames as well as the index: a user who deletes index.json
    should not get a v01 that silently collides with the v01 mp4 still sitting
    there. Versions are global, not per action — "v03" then means one render
    batch, whichever action it was.
    """
    top = 0
    for e in _load(vdir)["versions"]:
        try:
            top = max(top, int(e.get("version", 0)))
        except (TypeError, ValueError):
            pass
    if os.path.isdir(vdir):
        for fn in os.listdir(vdir):
            m = re.match(r".*_v(\d{2,})_", fn) or re.match(r".*_v(\d{2,})\.", fn)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


# --------------------------------------------------------------------------
# archive
# --------------------------------------------------------------------------

def archive(vdir: str, action: str, version: int, videos: dict[str, str],
            meta: dict | None = None) -> dict:
    """Move ``{view: src_path}`` into ``vdir`` under the versioned name.

    Videos are *moved* rather than copied: the frame folder should stay frames.
    A missing source is skipped and recorded as null, so a partial render (one
    view failed) still produces a usable index entry.
    """
    os.makedirs(vdir, exist_ok=True)
    a = slug(action)
    files: dict[str, str | None] = {}
    for view, src in videos.items():
        if not src or not os.path.exists(src):
            files[view] = None
            continue
        ext = os.path.splitext(src)[1].lower()
        if ext not in VIDEO_EXT:
            ext = ".mp4"
        dst_name = f"{a}_v{version:02d}_{view}{ext}"
        dst = os.path.join(vdir, dst_name)
        if os.path.abspath(src) == os.path.abspath(dst):
            files[view] = dst_name
            continue
        shutil.move(src, dst)
        files[view] = dst_name

    js = _load(vdir)
    entry = {
        "version": version,
        "action": a,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "files": {k: v for k, v in files.items() if v},
    }
    for k, v in (meta or {}).items():
        if v is not None:
            entry[k] = v
    js["versions"] = [e for e in js["versions"] if e.get("version") != version]
    js["versions"].append(entry)
    js["versions"].sort(key=lambda e: e.get("version", 0))
    entry["_index"] = _save(vdir, js)
    return entry


def describe(vdir: str) -> list[str]:
    """Human-readable lines, used by generate.py and serve.py to print a map."""
    js = _load(vdir)
    out = []
    for e in js["versions"]:
        views = ",".join(sorted(e.get("files", {})))
        out.append(
            f"v{int(e.get('version', 0)):02d}  {e.get('action', '?'):10s} "
            f"{e.get('frames', '?'):>4}帧  views=[{views}]  "
            f"{e.get('frames_dir', '')}"
        )
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="versioned source videos for the studio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="show archived versions")
    p.add_argument("--dir", required=True)

    p = sub.add_parser("import", help="move mp4s in under a new version number")
    p.add_argument("--dir", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--frames-dir", default=None)
    p.add_argument("--frames", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--version", type=int, default=None, help="override the auto number")
    p.add_argument("--video", action="append", default=[],
                   help="view:path, repeatable (front:/tmp/a.mp4)")

    args = ap.parse_args()

    if args.cmd == "list":
        lines = describe(args.dir)
        print("\n".join(lines) if lines else f"(empty) {args.dir}")
        return 0

    vdir = os.path.abspath(args.dir)
    ver = args.version or next_version(vdir)
    vids = {}
    for spec in args.video:
        view, _, path = spec.partition(":")
        vids[view.strip()] = path.strip()
    entry = archive(vdir, args.action, ver,
                    vids,
                    {"frames": args.frames, "seed": args.seed,
                     "frames_dir": args.frames_dir})
    print(json.dumps({k: v for k, v in entry.items() if not k.startswith("_")},
                     indent=1, ensure_ascii=False))
    print(f"index -> {entry['_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
