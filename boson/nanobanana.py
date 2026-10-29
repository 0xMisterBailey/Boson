"""Nano Banana (Gemini image) client and the round renderer behind the Nano Banana node.

Backends: `api` = Google's Gemini API ($GEMINI_API_KEY, else ~/.config/gemini/api_key); `comfy-api` = the same
model through Comfy's partner API (the proxy ComfyUI's own Nano Banana node calls; $COMFY_API_KEY, else
~/.config/comfy-tokens/api-key; billed in Comfy credits); `antigravity` = the signed-in Gemini plan; `local` = FLUX 3
Klein on a ComfyUI server (boson/local_render.py). Every call appends a line to <out dir>/nb-log.jsonl (model,
prompt, refs, usage, seconds). Nano Banana is not seed-reproducible (tested 2026-10-20: same seed, mean pixel diff
10/255), so its plates are a keyed `live` render, stored on their own manifest line and never in a Klein grid row.
"""
import base64, json, mimetypes, os, pathlib, shutil, subprocess, tempfile, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}"
COMFY_API = os.environ.get("BOSON_COMFY_API_BASE", "https://api.comfy.org").rstrip("/") + "/proxy/vertexai/gemini/{m}"
BACKENDS = ["api", "comfy-api", "antigravity", "local"]
MODEL = "gemini-nano-banana-2.1"
TAG = "nbn"
AGY_MODEL = "gemini-3.1-flash-image"   # what Antigravity's generate_image runs (its quota error names it, 2026-10-20)            # plates rendered by the node: <spec-id>__d<k>__nbn.png (tools/render_nb.py wrote __nb)


def key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    p = pathlib.Path("~/.config/gemini/api_key").expanduser()
    if not k and p.exists():
        k = p.read_text().strip()
    if not k:
        raise RuntimeError("Nano Banana needs a Gemini key: set GEMINI_API_KEY (stored mode needs none)")
    return k


def comfy_key():
    k = os.environ.get("COMFY_API_KEY", "").strip()
    p = pathlib.Path("~/.config/comfy-tokens/api-key").expanduser()
    if not k and p.exists():
        k = p.read_text().strip()
    if not k:
        raise RuntimeError("the comfy-api backend needs a Comfy API key (platform.comfy.org): set COMFY_API_KEY "
                           "or write it to ~/.config/comfy-tokens/api-key (stored mode needs none)")
    return k


def request(prompt, refs, model, aspect, size, via="api"):
    """The generateContent request for one picture: (url, body, headers).
    api: refs then text, snake_case: the request every stored round so far was rendered with (part order changes
    how the model weighs refs against the brief, so it stays). comfy-api: text then refs, camelCase, role user, as
    ComfyUI's own Nano Banana node sends them to Comfy's Vertex proxy."""
    data = [((mimetypes.guess_type(str(r))[0] or "image/png"), base64.b64encode(pathlib.Path(r).read_bytes()).decode())
            for r in refs]
    img_cfg = {"imageSize": size}
    if aspect:
        img_cfg["aspectRatio"] = aspect
    gen_cfg = {"responseModalities": ["IMAGE"], "imageConfig": img_cfg}
    if via == "comfy-api":
        parts = [{"text": prompt}] + [{"inlineData": {"mimeType": m, "data": d}} for m, d in data]
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen_cfg}
        return COMFY_API.format(m=model), body, {"Content-Type": "application/json", "X-API-KEY": comfy_key()}
    parts = [{"inline_data": {"mime_type": m, "data": d}} for m, d in data] + [{"text": prompt}]
    return API.format(m=model, k=key()), {"contents": [{"parts": parts}], "generationConfig": gen_cfg}, \
        {"Content-Type": "application/json"}


def generate(prompt, out, refs=(), model=MODEL, aspect=None, size="2K", via="api"):
    url, body, headers = request(prompt, refs, model, aspect, size, via)
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        hint = " (Comfy credits: platform.comfy.org)" if via == "comfy-api" and e.code in (401, 402, 403) else ""
        raise RuntimeError(f"Nano Banana ({via}) HTTP {e.code}{hint}: {e.read().decode()[:800]}") from None
    dt = time.time() - t0
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = None
    for c in d.get("candidates", []):
        for p in c.get("content", {}).get("parts", []):
            if "inlineData" in p:
                img = base64.b64decode(p["inlineData"]["data"])
    if img is None:
        raise RuntimeError("Nano Banana returned no image: " + json.dumps(d)[:800])
    out.write_bytes(img)
    with open(out.parent / "nb-log.jsonl", "a") as f:
        f.write(json.dumps({"out": out.name, "model": model if via == "api" else f"{via}:{model}", "prompt": prompt, "refs": list(map(str, refs)),
                            "aspect": aspect, "size": size, "usage": d.get("usageMetadata"),
                            "seconds": round(dt, 1)}) + "\n")
    print(f"{out} {dt:.1f}s ({via})", flush=True)
    return out


def generate_comfy(prompt, out, refs=(), model=MODEL, aspect=None, size="2K"):
    return generate(prompt, out, refs, model, aspect, size, via="comfy-api")


AGY_TASK = """Call your generate_image tool exactly once, with these arguments and nothing else:
- Prompt: the full text of the file {pfile}, verbatim (read it; do not shorten, rephrase or add to it)
- ImagePaths: {refs}
- AspectRatio: {aspect}
- ImageName: {name}
Then copy the generated image to {out}. Finally print one line: ARGS <the JSON of the arguments you passed>."""


def generate_agy(prompt, out, refs=(), model=MODEL, aspect=None, size="2K"):
    """The same render through Google Antigravity's generate_image (the box's signed-in Gemini plan, `agy -p`):
    for when the API key has no credit. About 1K output whatever `size` asks; logged as such. The Prompt the
    agent passed is checked against ours, so a paraphrase never gets recorded as this piece."""
    agy = os.environ.get("BOSON_AGY", str(pathlib.Path("~/dotfiles/launchpad/agy-cloud").expanduser()))
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="boson-agy-"))
    pfile = work / "prompt.txt"
    pfile.write_text(prompt)
    rl = [str(pathlib.Path(r).resolve()) for r in refs]
    task = AGY_TASK.format(pfile=pfile, refs=json.dumps(rl), aspect=aspect or "1:1", name=out.stem, out=work / "out.png")
    t0 = time.time()
    got = work / "out.png"
    for _ in range(2):                    # the agent sometimes ends without calling the tool: one retry
        r = subprocess.run([agy, "-p", task], cwd=work, capture_output=True, text=True, timeout=900)
        if got.exists():
            break
    dt = time.time() - t0
    line = next((l for l in r.stdout.splitlines()[::-1] if l.startswith("ARGS ")), "")
    try:
        args = json.loads(line[5:]) if line else {}
    except json.JSONDecodeError:
        args = {}
    if not got.exists():
        raise RuntimeError(f"Antigravity made no image ({r.returncode}): {(r.stdout + r.stderr)[-600:]}")
    if " ".join(str(args.get("Prompt", "")).split()) != " ".join(prompt.split()):
        raise RuntimeError("Antigravity changed the prompt it passed to generate_image: not recorded as this piece")
    from PIL import Image
    Image.open(got).convert("RGB").save(out)
    with open(out.parent / "nb-log.jsonl", "a") as f:
        f.write(json.dumps({"out": out.name, "model": f"antigravity:generate_image:{AGY_MODEL}", "prompt": prompt, "refs": rl,
                            "aspect": aspect, "size": f"{Image.open(out).size[0]}px wide (asked {size})",
                            "passed": {k: args.get(k) for k in ("AspectRatio", "ImagePaths")},
                            "seconds": round(dt, 1)}) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    print(f"{out} {dt:.1f}s (antigravity)", flush=True)
    return out


def _local():
    try:                                   # inside ComfyUI the modules are the `boson` package; loop.py loads them flat
        from . import local_render
    except ImportError:
        import local_render
    return local_render


def renderer(backend, model):
    """The manifest's renderer tag. Every tag starts `boson-nanobanana` so stored_round finds the plate whichever
    backend made it; the rest names what actually drew it."""
    if backend == "antigravity":
        return f"boson-nanobanana:antigravity:{AGY_MODEL}"
    if backend == "comfy-api":
        return f"boson-nanobanana:comfy-api:{model}"
    if backend == "local":
        return f"boson-nanobanana:local:{_local().MODEL}"
    return f"boson-nanobanana:{model}"


def render_round(studio, pdir, rid, specs, cfg, draws=1, commission=None, gen=None, backend="api"):
    """Render round `rid` of `studio` (its specs, its RENDER.json) into pdir/rNN, appending manifest lines.
    commission: image paths that replace RENDER.json's commission_refs (the images wired into the node), or a
    function spec index -> those paths, when each piece gets its own refs (loop.py's local rounds).
    Plates already on disk are reused, so a re-queue costs nothing. -> manifest rows, in spec order."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}: one of {BACKENDS}")
    if gen is None and backend == "local":
        gen = _local().generate
    gen = gen or {"antigravity": generate_agy, "comfy-api": generate_comfy}.get(backend, generate)
    d = pathlib.Path(studio["dir"])
    refs = [d / "refs" / f"{r}.jpg" for r in cfg.get("refs", [])]
    each = commission if callable(commission) else None
    refs += [] if each else list(commission) if commission is not None else [d / r for r in cfg.get("commission_refs", [])]
    model = cfg.get("model", MODEL)
    out = pathlib.Path(pdir) / f"r{rid}"
    jobs = [(i, sp, k, out / f"{sp['id']}__d{k}__{TAG}.png") for i, sp in enumerate(specs) for k in range(draws)]

    def run(j):
        i, sp, k, p = j
        refs_ = refs + list(each(i)) if each else refs
        fresh = not p.exists()
        if fresh:
            gen(cfg.get("lead", "") + sp["prompt"], p, refs_, model, cfg.get("aspect"), cfg.get("size", "2K"))
        return fresh, {"round": rid, "id": sp["id"], "draw": k, "file": str(p.relative_to(pdir)),
                       "renderer": renderer(backend, model),
                       "mode": "live", "studio_sha": studio["sha"], "prompt": cfg.get("lead", "") + sp["prompt"],
                       "refs": [str(r.relative_to(d)) if str(r).startswith(str(d)) else pathlib.Path(r).name
                                for r in refs_]}

    with ThreadPoolExecutor({"antigravity": 3, "local": 2}.get(backend, 6)) as ex:
        futs = [ex.submit(run, j) for j in jobs]
    done, errors = [], []
    for f in futs:                        # a failed piece never costs the record of the pieces that rendered
        try:
            done.append(f.result())
        except Exception as e:
            errors.append(e)
    new = [r for fresh, r in done if fresh]
    if new:
        with open(pathlib.Path(pdir) / "manifest.jsonl", "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in new)
    if errors:
        raise RuntimeError(f"{len(errors)} of {len(jobs)} pieces did not render (the rest are kept): {errors[0]}")
    return [r for _, r in done]


def stored_round(pdir, rid):
    """The node's committed plates for round `rid` (latest line per spec and draw), no key, no call."""
    p = pathlib.Path(pdir) / "manifest.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    latest = {}
    for r in rows:
        if str(r.get("round")).lstrip("r") == rid and str(r.get("renderer", "")).startswith("boson-nanobanana"):
            latest[(r["id"], r.get("draw", 0))] = r
    return [latest[k] for k in sorted(latest)]
