"""MiniMax H3 image-to-video client for ComfyUI — the *generic* layer.

Everything project-specific (subject description, camera wording, frame count,
seed) arrives as arguments. This file only knows how to talk H3.

Frame-count rule (H3 is strict):  length % 17 == 5
    5, 22, 39, 56, 73, 90, 107, 124 ...
The upstream blueprint silently snaps UP; we snap too but say so (snap_length).

Usage as a library:
    import h3client as h3
    h3.health()                       # is the server up?
    h3.build(prompt, image, length=56, seed=42)
    pid = h3.submit(graph)
    entry = h3.wait(pid)
    n, video = h3.collect(entry, out_dir)

Usage from shell:
    python h3client.py health
    python h3client.py models
    python h3client.py run --image ref.png --prompt-file p.txt --frames 56 --out frames/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------

DEFAULT_SERVER = os.environ.get("H3_SERVER", "http://127.0.0.1:8190")

# Model filenames. Override with --models-json or the H3_MODELS env var
# (a JSON object with the same keys) when your ComfyUI has different files.
DEFAULT_MODELS = {
    "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae_video": "minimax_h3_video_vae_fp16.safetensors",
    "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
    "lora_turbo": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
}


def models() -> dict:
    raw = os.environ.get("H3_MODELS")
    if not raw:
        return dict(DEFAULT_MODELS)
    try:
        return {**DEFAULT_MODELS, **json.loads(raw)}
    except json.JSONDecodeError:
        print("warning: H3_MODELS is not valid JSON, using defaults", file=sys.stderr)
        return dict(DEFAULT_MODELS)


def comfy_input_dir(server: str = DEFAULT_SERVER) -> str | None:
    """Where ComfyUI reads LoadImage files from — best effort, filesystem only.

    Order: $H3_COMFY_INPUT, then ComfyUI's own ``--input-directory`` /
    ``--base-directory`` from ``/system_stats`` argv, then a few usual spots.

    This function is the *fallback*. ComfyUI Desktop installs a second copy of
    ComfyUI with its own input folder (``Comfy-Desktop/ComfyUI-Shared/input``)
    and nothing else distinguishes the two: guessing wrong means LoadImage
    silently reads a stale ``ref_front.png`` from a previous session and you
    render the wrong character. `stage()` therefore uploads over HTTP first and
    only lands here when that is unavailable.
    """
    env = os.environ.get("H3_COMFY_INPUT")
    if env and os.path.isdir(env):
        return env

    # Ask ComfyUI where it was started from. Desktop passes
    #   --input-directory <path> --output-directory <path>
    # and a regular install may pass --base-directory <root>.
    try:
        stats = json.loads(get(server, "/system_stats"))
        info = stats.get("system") or {}
        argv = [str(a) for a in (info.get("argv") or [])]
        for i, tok in enumerate(argv):
            for flag in ("--input-directory", "--input_directory"):
                if tok == flag and i + 1 < len(argv):
                    if os.path.isdir(argv[i + 1]):
                        return argv[i + 1]
                elif tok.startswith(flag + "="):
                    val = tok.split("=", 1)[1]
                    if os.path.isdir(val):
                        return val
        for i, tok in enumerate(argv):
            for flag in ("--base-directory", "--base_directory"):
                val = None
                if tok == flag and i + 1 < len(argv):
                    val = argv[i + 1]
                elif tok.startswith(flag + "="):
                    val = tok.split("=", 1)[1]
                if val and os.path.isdir(os.path.join(val, "input")):
                    return os.path.join(val, "input")
        for key in ("comfyui_root", "base_path", "root"):
            root = info.get(key)
            if root and os.path.isdir(os.path.join(root, "input")):
                return os.path.join(root, "input")
    except Exception:
        pass

    localapp = os.environ.get("LOCALAPPDATA", "")
    for cand in (
        os.path.join(localapp, "Comfy-Desktop", "ComfyUI-Shared", "input") if localapp else "",
        os.path.expanduser("~/AppData/Local/Comfy-Desktop/ComfyUI-Shared/input"),
        os.path.expanduser("~/Library/Application Support/Comfy-Desktop/ComfyUI-Shared/input"),
        os.path.expanduser("~/.local/share/Comfy-Desktop/ComfyUI-Shared/input"),
        os.path.expanduser("~/ComfyUI/input"),
        os.path.expanduser("~/comfyui/input"),
        "/comfyui/input",
        "D:/AI/ComfyUI-master/input",
        "C:/ComfyUI/input",
    ):
        if cand and os.path.isdir(cand):
            return cand
    return None


# --------------------------------------------------------------------------
# HTTP (never through a proxy — localhost + corporate proxies break)
# --------------------------------------------------------------------------

def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(server: str, path: str, **params) -> bytes:
    url = server + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with _opener().open(urllib.request.Request(url), timeout=120) as r:
        return r.read()


def post_json(server: str, path: str, payload: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(
        server + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener().open(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"http_status": e.code, "raw": raw[:2000]}


def health(server: str = DEFAULT_SERVER) -> dict:
    try:
        stats = json.loads(get(server, "/system_stats"))
        queue = json.loads(get(server, "/queue"))
        return {
            "ok": True,
            "server": server,
            "version": stats.get("system", {}).get("comfyui_version"),
            "running": len(queue.get("queue_running") or []),
            "pending": len(queue.get("queue_pending") or []),
        }
    except Exception as e:
        return {"ok": False, "server": server, "error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def snap_length(n: int) -> int:
    """Round n up to the nearest value with n % 17 == 5 — H3's frame grid."""
    n = max(5, int(n))
    return n + (5 - n % 17) % 17


def build(
    prompt: str,
    image: str,
    width: int = 768,
    height: int = 768,
    length: int = 56,
    fps: float = 24.0,
    steps: int = 8,
    seed: int = 1,
    turbo: bool = True,
    filename_prefix: str = "sprite/out",
    last_frame: str | None = None,
    save_frames: bool = True,
    save_video: bool = True,
    save_audio: bool = False,
    m: dict | None = None,
) -> dict:
    """ComfyUI API-format prompt dict for one H3 I2V job."""
    length = snap_length(length)
    m = m or models()
    g: dict[str, dict] = {}

    g["1"] = {"class_type": "UNETLoader",
              "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}}
    g["2"] = {"class_type": "CLIPLoader",
              "inputs": {"clip_name": m["clip"], "type": "minimax", "device": "default"}}
    g["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": m["vae_video"]}}
    g["4"] = {"class_type": "VAELoader", "inputs": {"vae_name": m["vae_audio"]}}

    model_src: list = ["1", 0]
    if turbo:
        g["5"] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": ["1", 0], "lora_name": m["lora_turbo"],
                             "strength_model": 1.0}}
        model_src = ["5", 0]

    g["6"] = {"class_type": "LoadImage", "inputs": {"image": image}}

    h3_inputs = {
        "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
        "width": width, "height": height, "length": length,
        "first_frame": ["6", 0],
    }
    if last_frame:
        g["6b"] = {"class_type": "LoadImage", "inputs": {"image": last_frame}}
        h3_inputs["last_frame"] = ["6b", 0]
    g["7"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": h3_inputs}

    g["8"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}}
    g["9"] = {"class_type": "BasicGuider",
              "inputs": {"model": model_src, "conditioning": ["7", 0]}}
    g["10"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    g["11"] = {"class_type": "BasicScheduler",
               "inputs": {"model": model_src, "scheduler": "simple",
                          "steps": 8 if turbo else max(1, steps), "denoise": 1.0}}
    g["12"] = {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["9", 0], "sampler": ["10", 0],
                          "sigmas": ["11", 0], "latent_image": ["7", 1]}}

    g["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
    g["14"] = {"class_type": "VAEDecodeAudio",
               "inputs": {"samples": ["12", 0], "vae": ["4", 0]}}

    if save_frames:
        g["15"] = {"class_type": "SaveImage",
                   "inputs": {"images": ["13", 0], "filename_prefix": filename_prefix + "_frames"}}
    if save_video:
        g["16"] = {"class_type": "CreateVideo",
                   "inputs": {"images": ["13", 0], "audio": ["14", 0], "fps": fps}}
        g["17"] = {"class_type": "SaveVideo",
                   "inputs": {"video": ["16", 0], "filename_prefix": filename_prefix,
                              "format": "auto", "codec": "auto"}}
    if save_audio:
        g["18"] = {"class_type": "SaveAudio",
                   "inputs": {"audio": ["14", 0], "filename_prefix": filename_prefix + "_audio"}}
    return g


# --------------------------------------------------------------------------
# Stage / submit / wait / collect
# --------------------------------------------------------------------------

def _md5(path: str) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_image(path: str, server: str = DEFAULT_SERVER, name: str | None = None) -> str:
    """Push a file to ComfyUI's input folder over HTTP; return the name to use.

    The server writes the bytes itself, so there is no way to land in the wrong
    input directory (a Desktop install and a portable install each have one, and
    LoadImage reads whichever belongs to the running process).
    """
    import uuid

    boundary = "----h3" + uuid.uuid4().hex
    fname = name or os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'.encode(),
        b"Content-Type: image/png\r\n\r\n", data, b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        server + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    with _opener().open(req, timeout=120) as r:
        info = json.loads(r.read())
    got = info.get("name") or fname
    sub = info.get("subfolder") or ""
    return f"{sub}/{got}" if sub else got


def stage(image_path: str, server: str = DEFAULT_SERVER, name: str | None = None,
          unique: bool = True) -> str:
    """Make a reference image readable by LoadImage; return the name it landed as.

    Uploads over HTTP (authoritative, no path guessing). Falls back to copying
    into `comfy_input_dir()` when the upload endpoint is unavailable.

    `unique` appends a short content hash to the filename. That is not cosmetic:
    with a fixed `ref_front.png`, a render queued before the copy finishes — or
    an old file the running instance can still see — gives you frames of the
    *previous* character with a perfectly valid prompt. The hash makes
    "the name says what the bytes are" true.
    """
    import shutil

    if not os.path.exists(image_path):
        raise SystemExit(f"reference image not found: {image_path}")

    fname = name or os.path.basename(image_path)
    if unique:
        stem, ext = os.path.splitext(fname)
        fname = f"{stem}_{_md5(image_path)[:8]}{ext or '.png'}"

    try:
        return upload_image(image_path, server, fname)
    except Exception as e:
        print(f"note: /upload/image unavailable ({type(e).__name__}); "
              f"copying into the input folder instead", file=sys.stderr)

    d = comfy_input_dir(server)
    if not d:
        raise SystemExit(
            "cannot find ComfyUI's input folder and /upload/image failed. Set "
            "H3_COMFY_INPUT to it, e.g.\n"
            "  export H3_COMFY_INPUT=/path/to/ComfyUI/input"
        )
    shutil.copyfile(image_path, os.path.join(d, fname))
    return fname


def submit(graph: dict, server: str = DEFAULT_SERVER) -> str:
    r = post_json(server, "/prompt", {"prompt": graph, "client_id": "AIGenerateSpriteSheet"})
    if "prompt_id" not in r:
        raise SystemExit("submit failed:\n" + json.dumps(r, indent=1, ensure_ascii=False)[:2000])
    return r["prompt_id"]


def wait(pid: str, server: str = DEFAULT_SERVER, timeout: float = 3600,
         poll: float = 3.0, quiet: bool = False) -> dict:
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        try:
            hist = json.loads(get(server, f"/history/{pid}"))
        except Exception:
            hist = {}
        if pid in hist:
            return hist[pid]
        if not quiet:
            try:
                q = json.loads(get(server, "/queue"))
                state = (f"running={len(q.get('queue_running') or [])} "
                         f"pending={len(q.get('queue_pending') or [])}")
            except Exception:
                state = "?"
            if state != last:
                print(f"    [{int(time.time() - t0):4d}s] {state}", flush=True)
                last = state
        time.sleep(poll)
    raise SystemExit(f"timed out after {timeout:.0f}s waiting for {pid}")


def collect(entry: dict, out_dir: str, server: str = DEFAULT_SERVER,
            stem: str = "frame") -> tuple[int, str | None]:
    """Download every output of a finished job into out_dir.

    PNG/JPG are saved as ``<stem>_001.png`` … and renumbered from 1, because
    ComfyUI's SaveImage counter continues across runs and would otherwise give
    you 057..112 on the second job.
    """
    os.makedirs(out_dir, exist_ok=True)
    images: list[tuple[str, bytes]] = []
    video = None

    for node_out in (entry.get("outputs") or {}).values():
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict) or "filename" not in it:
                    continue
                fn = it["filename"]
                data = get(server, "/view", filename=fn,
                           subfolder=it.get("subfolder", ""), type=it.get("type", "output"))
                low = fn.lower()
                if low.endswith((".mp4", ".webm", ".mov")):
                    video = os.path.join(out_dir, fn)
                    with open(video, "wb") as f:
                        f.write(data)
                elif low.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    images.append((fn, data))

    # keep ComfyUI's own ordering, then renumber
    images.sort(key=lambda t: t[0])
    for i, (_fn, data) in enumerate(images, 1):
        with open(os.path.join(out_dir, f"{stem}_{i:03d}.png"), "wb") as f:
            f.write(data)

    return len(images), video


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MiniMax H3 (ComfyUI) client")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    sub.add_parser("models")
    sub.add_parser("input-dir")

    r = sub.add_parser("run", help="submit one I2V job and collect frames")
    r.add_argument("--image", required=True)
    r.add_argument("--prompt-file", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--frames", type=int, default=56)
    r.add_argument("--size", type=int, default=768)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--steps", type=int, default=8)
    r.add_argument("--no-turbo", action="store_true")
    r.add_argument("--dry", action="store_true", help="print the graph, do not submit")

    a = ap.parse_args(argv)

    if a.cmd == "health":
        print(json.dumps(health(a.server), indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "models":
        print(json.dumps(models(), indent=1))
        return 0
    if a.cmd == "input-dir":
        print(comfy_input_dir(a.server) or "(not found — set H3_COMFY_INPUT)")
        return 0

    with open(a.prompt_file, encoding="utf-8") as f:
        prompt = f.read().strip()
    staged = stage(a.image, a.server)
    frames = snap_length(a.frames)
    if frames != a.frames:
        print(f"note: H3 needs length % 17 == 5, snapped {a.frames} -> {frames}")
    graph = build(prompt, staged, width=a.size, height=a.size, length=frames,
                  seed=a.seed, steps=a.steps, turbo=not a.no_turbo,
                  filename_prefix="sprite/out")
    if a.dry:
        print(json.dumps(graph, indent=1))
        return 0

    pid = submit(graph, a.server)
    print(f"queued {pid}")
    entry = wait(pid, a.server)
    n, video = collect(entry, a.out, a.server)
    print(f"frames {n} -> {a.out}")
    if video:
        print(f"video  {video}")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())