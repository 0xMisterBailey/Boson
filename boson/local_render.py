"""The `local` backend: Make's prompts drawn by FLUX 3 Klein on a ComfyUI server, the studio's refs on a wire.

T14's working graph (tools/render_plates.py klein_graph; Klein mi2i beat Krea 4 of 4 on closeness to the refs,
2026-10-19), stock ComfyUI nodes only. Open weights end to end: nothing leaves the box. Same call shape as
nanobanana.generate, so render_round swaps it in without the studio naming a model.

Server: $BOSON_LOCAL_COMFY (default http://127.0.0.1:8188). Refs go up through /upload/image and the picture comes
back through /view, so the server may be another install or another port. A Make node running inside that same
server must not queue onto it (one queue: it would wait on itself), so that case is refused with a plain message.
Klein is seed-reproducible: the seed comes from the plate's name and is logged.
"""
import hashlib, json, os, pathlib, sys, time, urllib.parse, urllib.request, uuid

COMFY = os.environ.get("BOSON_LOCAL_COMFY", "http://127.0.0.1:8188").rstrip("/")
MODEL = "flux3-image-klein-bf16"
GRAPH = {"unet": "flux3-image-klein-bf16.safetensors", "clip": "qwen3vl_4b_bf16.safetensors",
         "vae": "flux2-vae.safetensors", "steps": 16, "sampler": "euler", "scheduler": "simple",
         "shift": 2.77259, "megapixels": 1.0}
MAX_REFS = int(os.environ.get("BOSON_LOCAL_MAX_REFS", "6"))   # Klein takes up to 10; T14 ran 3
TIMEOUT = 1800


def size_for(aspect, mp=1.0):
    """'3:2' -> (w, h) near mp megapixels, multiples of 16 (Flux latents)."""
    a, b = (int(x) for x in (aspect or "1:1").split(":"))
    h = (mp * 1e6 * b / a) ** 0.5
    w = h * a / b
    return int(round(w / 16)) * 16, int(round(h / 16)) * 16


def seed_for(out):
    return int(hashlib.sha256(pathlib.Path(out).name.encode()).hexdigest()[:8], 16)


def graph(prompt, seed, width, height, ref_names, prefix="boson/local"):
    R = GRAPH
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": R["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": R["clip"], "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": R["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "6": {"class_type": "ModelSamplingFlux", "inputs": {"model": ["1", 0], "max_shift": R["shift"],
              "base_shift": R["shift"], "width": width, "height": height}},
        "7": {"class_type": "ReferenceMultiLatent", "inputs": {"positive": ["4", 0], "negative": ["5", 0],
              "vae": ["3", 0], "resolution": "resize", "resolution.megapixels": R["megapixels"]}},
        "8": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["6", 0], "positive": ["7", 0], "negative": ["7", 1],
              "latent_image": ["8", 0], "seed": seed, "steps": R["steps"], "cfg": 1.0,
              "sampler_name": R["sampler"], "scheduler": R["scheduler"], "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }
    if not ref_names:                     # Klein t2i: no reference conditioning at all
        g["9"]["inputs"]["positive"], g["9"]["inputs"]["negative"] = ["4", 0], ["5", 0]
        del g["7"]
    for i, name in enumerate(ref_names, 1):
        g[f"2{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["7"]["inputs"][f"images.image{i}"] = [f"2{i}", 0]
    return g


def _self_queue():
    """True when this code runs inside the ComfyUI server it would queue onto."""
    srv = sys.modules.get("server")
    inst = getattr(getattr(srv, "PromptServer", None), "instance", None)
    port = getattr(inst, "port", None)
    if not port:
        return False
    u = urllib.parse.urlparse(COMFY)
    return u.hostname in ("127.0.0.1", "localhost", "0.0.0.0") and (u.port or 80) == int(port)


def _http(path, data=None, headers=None, raw=False):
    req = urllib.request.Request(COMFY + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body if raw else json.loads(body or b"{}")


def _upload(path):
    """multipart POST /upload/image -> the name LoadImage takes. Same bytes, same name: the server dedupes."""
    p = pathlib.Path(path)
    data = p.read_bytes()
    name = hashlib.sha256(data).hexdigest()[:16] + p.suffix.lower()
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\nboson-refs\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    r = _http("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    return f"{r.get('subfolder')}/{r['name']}" if r.get("subfolder") else r["name"]


def generate(prompt, out, refs=(), model=MODEL, aspect=None, size="2K"):
    """One picture on the local server -> out. `model` and `size` are Nano Banana's (ignored: Klein draws ~1 MP)."""
    if _self_queue():
        raise RuntimeError(f"the local backend would queue onto the ComfyUI it runs in ({COMFY}) and wait on itself: "
                           "point BOSON_LOCAL_COMFY at a second ComfyUI, or run the round with tools/loop.py")
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        names = [_upload(r) for r in list(refs)[:MAX_REFS]]
    except OSError as e:
        raise RuntimeError(f"no ComfyUI at {COMFY} for the local backend ({e}); start one or set BOSON_LOCAL_COMFY") from None
    w, h = size_for(aspect, GRAPH["megapixels"])
    seed = seed_for(out)
    t0 = time.time()
    pid = _http("/prompt", json.dumps({"prompt": graph(prompt, seed, w, h, names)}).encode(),
                {"Content-Type": "application/json"})["prompt_id"]
    while True:
        hist = _http(f"/history/{pid}")
        if pid in hist:
            st = hist[pid].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError("local render failed: " + json.dumps(st.get("messages"))[:800])
            imgs = [i for o in hist[pid].get("outputs", {}).values() for i in o.get("images", [])]
            if imgs:
                break
        if time.time() - t0 > TIMEOUT:
            raise RuntimeError(f"local render timed out after {TIMEOUT}s (prompt {pid} on {COMFY})")
        time.sleep(1)
    im = imgs[0]
    q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                "type": im.get("type", "output")})
    out.write_bytes(_http(f"/view?{q}", raw=True))
    dt = time.time() - t0
    with open(out.parent / "nb-log.jsonl", "a") as f:
        f.write(json.dumps({"out": out.name, "model": f"local:{MODEL}", "prompt": prompt,
                            "refs": [str(r) for r in list(refs)[:MAX_REFS]], "refs_dropped": max(0, len(refs) - MAX_REFS),
                            "aspect": aspect, "size": f"{w}x{h}", "seed": seed, "graph": GRAPH,
                            "seconds": round(dt, 1)}) + "\n")
    print(f"{out} {dt:.1f}s (local {MODEL})", flush=True)
    return out
