"""Serve a project folder over HTTP with the studio mounted inside it, and
print the URL to open.

Why a server at all: canvas cannot read pixels over file:// (the image taints
the canvas and getImageData throws), so chroma keying needs real HTTP.

Why mount instead of "just open the skill's html": the studio and the frame
folders have to be under *one* origin for ?frames=../../frames/walk to resolve.
This copies studio/ into <root>/_studio/ then serves <root>.

    python serve.py                          # serve cwd
    python serve.py --root . --frames frames/walk --open
    python serve.py --root . --frames frames/walk --print-only
    python serve.py --frames frames/walk --cmp 2x2 --bg white   # four-up on white

If <root>/videos/index.json exists (generate.py writes it), the printed URL also
carries ?videos=/videos so the studio can load a versioned source clip instead of
a frame folder. The version list is printed so you can find the folder without
guessing where the mp4s went.

--cmp / --bg just pre-set the studio's preview layout and backdrop in the URL, so
the link you hand the user already shows all four directions on the background
they asked about.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import io
import os
import re
import shutil
import socket
import socketserver
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO_SRC = os.path.join(os.path.dirname(HERE), "studio")


def free_port(start: int) -> int:
    for p in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def mount_studio(root: str) -> str:
    """Copy the studio into <root>/_studio so both live under one origin."""
    dst = os.path.join(root, "_studio")
    os.makedirs(dst, exist_ok=True)
    src = os.path.join(STUDIO_SRC, "index.html")
    if not os.path.exists(src):
        raise SystemExit(f"studio not found at {src}")
    shutil.copyfile(src, os.path.join(dst, "index.html"))
    return dst


def video_index(root: str) -> list[str]:
    """Lines describing <root>/videos/index.json, empty when there is none.

    Kept dependency-free (json only) so serve.py still runs on a bare python.
    """
    import json
    p = os.path.join(root, "videos", "index.json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            js = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for e in sorted(js.get("versions", []), key=lambda e: e.get("version", 0)):
        files = ", ".join(f"{k}→{v}" for k, v in sorted((e.get("files") or {}).items()))
        out.append(f"  v{int(e.get('version', 0)):02d}  {e.get('action', '?')}"
                   f"  {files}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--frames", help="frame folder relative to root, e.g. frames/walk")
    ap.add_argument("--videos", help="videos folder relative to root (default: videos "
                                     "when it has an index.json)")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--cmp", choices=["focus", "2x2", "1x4"],
                    help="open the studio with a preview layout already set "
                         "(2x2 / 1x4 = all four directions on screen)")
    ap.add_argument("--bg", choices=["dcheck", "lcheck", "black", "white", "gray", "magenta"],
                    help="open the studio with a preview backdrop already set")
    ap.add_argument("--print-only", action="store_true",
                    help="print the URL and exit (server already running?)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    mount_studio(root)
    port = free_port(args.port)
    base = f"http://127.0.0.1:{port}"

    rel = ""
    if args.frames:
        rel = args.frames.replace(os.sep, "/").strip("/")

    clips = video_index(root) if not args.videos else []
    vrel = ""
    if args.videos:
        vrel = args.videos.replace(os.sep, "/").strip("/")
    elif clips:
        vrel = "videos"

    qs = []
    if rel:
        qs.append(f"frames=/{rel}")
    if vrel:
        qs.append(f"videos=/{vrel}")
    if args.cmp:
        qs.append(f"cmp={args.cmp}")
    if args.bg:
        qs.append(f"bg={args.bg}")
    url = f"{base}/_studio/index.html" + ("?" + "&".join(qs) if qs else "")

    print(f"root   : {root}")
    print(f"studio : {url}")
    if clips:
        print(f"videos : {os.path.join(root, 'videos')}")
        for line in clips:
            print(line)

    if args.print_only:
        return 0

    class Quiet(http.server.SimpleHTTPRequestHandler):
        """Stdlib handler + byte ranges.

        The studio pulls a clip down as a blob and seeks inside that (object URL),
        so it does not depend on ranges. What does: opening a URL straight in the
        browser (`/videos/walk_v01_front.mp4`) and any client that streams rather
        than downloads. SimpleHTTPRequestHandler only ever answers 200 with the
        whole file, which makes scrubbing a remote video impossible.
        """

        def log_message(self, *a, **k):
            pass

        def end_headers(self):
            self.send_header("Accept-Ranges", "bytes")
            super().end_headers()

        def send_head(self):
            rng = (self.headers.get("Range") or "").strip()
            path = self.translate_path(self.path)
            if not rng.startswith("bytes=") or not os.path.isfile(path):
                return super().send_head()
            m_rng = re.match(r"bytes=(\d*)-(\d*)$", rng)
            if not m_rng:
                return super().send_head()
            size = os.path.getsize(path)
            a, b = m_rng.group(1), m_rng.group(2)
            if a:
                start = int(a)
                end = int(b) if b else size - 1
            else:                                    # bytes=-N  → last N bytes
                start = max(0, size - int(b or 0))
                end = size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_error(416, "Range Not Satisfiable")
                return None
            body = b""
            with open(path, "rb") as f:
                f.seek(start)
                body = f.read(end - start + 1)
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return io.BytesIO(body)

    os.chdir(root)
    h = functools.partial(Quiet, directory=root)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), h) as httpd:
        httpd.daemon_threads = True
        if args.open:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        print("serving (Ctrl-C to stop)", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())