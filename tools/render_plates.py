#!/usr/bin/env python3
"""Re-render a studio's stored round specs on the grid's one renderer (SPEC v3 §4.2): FLUX 3 Klein mi2i
with a fixed ref set on a wire, the same for every cell (I6). Stored prompts go in verbatim, behind the
T14 lead line; no stripping (the T14 regex was a probe tool, not the product).

usage: render_plates.py export                    write workflows/klein-mi2i.api.json (stock nodes only)
                                                  and workflows/grid-live.api.json (Boson nodes + stock Klein)
       render_plates.py live REPO REF [REF ...]    queue the live grid at those refs (2 draws x 2 seeds,
                                                  1 piece per draw; writer only if a draw is not cached)
       render_plates.py round REPO BRANCH OUT       the next round in-graph on BRANCH: Draft Brief (8 pieces,
                                                  committed) -> Klein at seeds 901201/901202 -> Verdict
                                                  (empty: the graph stops there); plates into OUT/rNN
       render_plates.py run REPO OUT r01 r02 ...  render every spec of those rounds at their tags
                                                  (ComfyUI must be up on COMFY); skips plates on disk
       ARM=stripped render_plates.py run ...       same, with the T14 strip applied to each stored prompt
                                                  (operator 1b, 2026-10-19): an altered arm, labelled so

Plates: OUT/<round>/<spec-id>__s<seed>__<arm>.png (arm klein | klein-stripped), one line each in
OUT/manifest.jsonl with "prompt_arm".
"""
import hashlib, json, os, pathlib, re, shutil, sys, time, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "boson"))
import studio as st  # noqa: E402  (not the package: its __init__ needs ComfyUI)

BOSON = pathlib.Path(__file__).resolve().parents[1]
COMFY = os.environ.get("COMFY", "http://127.0.0.1:8188")
COMFY_DIR = pathlib.Path(os.environ.get("COMFY_DIR", pathlib.Path.home() / "launchpad-engines/ComfyUI"))
REFS = ["02", "08", "01"]  # T14: first ref defining symmetry, enclosure, juxtaposition
LEAD = "In the engraving style and composition of the reference prints: "
RENDERER = {"name": "klein", "unet": "flux3-image-klein-bf16.safetensors", "clip": "qwen3vl_4b_bf16.safetensors",
            "vae": "flux2-vae.safetensors", "steps": 16, "sampler": "euler", "scheduler": "simple",
            "shift": 2.77259, "megapixels": 1.0, "lead": LEAD, "refs": REFS}


ARM = os.environ.get("ARM", "orig")
TEMPLATE = re.compile(r"ruled|band across the top|tablet|filling the frame|straight edges|"
                      r"nothing surrounds|perfectly flat|margin of clean|only words|enclosed by|"
                      r"underside of that band", re.I)


def strip(prompt):
    """T14's strip (experiments/t14/probe.py), verbatim: drop every sentence that fixes the plate template,
    keep the words the plate must carry. Alters history, so its plates carry prompt_arm=stripped."""
    prompt = re.sub(r" up to just below the top band", " up to the top", prompt)
    sents = re.split(r"(?<=[.!?])\s+", prompt)
    kept = [s for s in sents if not TEMPLATE.search(s)]
    name = re.findall(r'name "([^"]+)"', prompt)
    words = 'The words "EX LIBRIS"' + (f' and the name "{name[0]}"' if name else "")
    return " ".join(kept) + f" {words} appear somewhere in the design, placed as the composition needs."


def klein_graph(prompt, seed, width, height, ref_images, prefix="boson/plate"):
    """T14's working Klein graph (experiments/t14/probe.py), stock ComfyUI nodes only."""
    R = RENDERER
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
    for i, name in enumerate(ref_images, 1):
        g[f"2{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["7"]["inputs"][f"images.image{i}"] = [f"2{i}", 0]
    return g


def stage_refs(studio, name):
    """Copy the fixed refs into ComfyUI's input/ (a cache: the studio repo stays the only state, I1)."""
    out = []
    for r in REFS:
        dst = COMFY_DIR / "input" / "boson" / name / f"ref{r}.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pathlib.Path(studio["dir"]) / "refs" / f"{r}.jpg", dst)
        out.append(f"boson/{name}/ref{r}.jpg")
    return out


def http(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(COMFY + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def queue(graph):
    """Submit, wait, return the first output image's path on disk."""
    pid = http("/prompt", {"prompt": graph})["prompt_id"]
    while True:
        h = http(f"/history/{pid}")
        if pid in h:
            s = h[pid].get("status", {})
            if s.get("status_str") == "error":
                raise RuntimeError(json.dumps(s.get("messages"))[:800])
            imgs = [i for o in h[pid]["outputs"].values() for i in o.get("images", [])]
            if imgs:
                return COMFY_DIR / "output" / imgs[0]["subfolder"] / imgs[0]["filename"]
        time.sleep(1)


LIVE_SEEDS = (4201, 4202)  # the live cells' two seeds, fixed (SPEC v3 §4.2)


def live_graph(repo, refs, draws=(0, 1), seeds=LIVE_SEEDS, pieces=1, prefix="boson/grid-live"):
    """Grid in live mode on the canvas: per ref, Draft Brief draws -> stock Klein chain at each seed ->
    Grid Row; one Grid composes the rows (live only, I4). Refs on the wire from Studio Refs (I6)."""
    R = RENDERER
    g = {"m": {"class_type": "UNETLoader", "inputs": {"unet_name": R["unet"], "weight_dtype": "default"}},
         "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": R["clip"], "type": "flux3", "device": "default"}},
         "v": {"class_type": "VAELoader", "inputs": {"vae_name": R["vae"]}},
         "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": ""}},
         "ms": {"class_type": "ModelSamplingFlux", "inputs": {"model": ["m", 0], "max_shift": R["shift"],
                "base_shift": R["shift"], "width": 832, "height": 1216}},
         "lat": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}}}
    for j, sd in enumerate(seeds):
        g[f"seed{j}"] = {"class_type": "PrimitiveInt", "inputs": {"value": sd}}
    rows = []
    for i, ref in enumerate(refs):
        g[f"s{i}"] = {"class_type": "BosonLoadStudio", "inputs": {"repo": repo, "ref": ref}}
        g[f"refs{i}"] = {"class_type": "BosonStudioRefs", "inputs": {"studio": [f"s{i}", 0]}}
        for d in draws:
            k = f"{i}d{d}"
            g[f"db{k}"] = {"class_type": "BosonDraftBrief", "inputs": {"studio": [f"s{i}", 0], "pieces": pieces,
                           "draw": d, "lead": LEAD}}
            g[f"pos{k}"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": [f"db{k}", 1]}}
            g[f"rml{k}"] = {"class_type": "ReferenceMultiLatent", "inputs": {
                "positive": [f"pos{k}", 0], "negative": ["neg", 0], "vae": ["v", 0], "resolution": "resize",
                "resolution.megapixels": R["megapixels"],
                **{f"images.image{n}": [f"refs{i}", n - 1] for n in range(1, len(REFS) + 1)}}}
            row = {"draft": [f"db{k}", 4], "renderer": f"on FLUX 3 Klein mi2i, refs {' '.join(REFS)}"}
            for j, ab in enumerate("ab"[:len(seeds)]):
                g[f"ks{k}{ab}"] = {"class_type": "KSampler", "inputs": {
                    "model": ["ms", 0], "positive": [f"rml{k}", 0], "negative": [f"rml{k}", 1],
                    "latent_image": ["lat", 0], "seed": [f"seed{j}", 0], "steps": R["steps"], "cfg": 1.0,
                    "sampler_name": R["sampler"], "scheduler": R["scheduler"], "denoise": 1.0}}
                g[f"vd{k}{ab}"] = {"class_type": "VAEDecode", "inputs": {"samples": [f"ks{k}{ab}", 0], "vae": ["v", 0]}}
                row[f"images_{ab}"] = [f"vd{k}{ab}", 0]
                row[f"seed_{ab}"] = [f"seed{j}", 0]
            g[f"row{k}"] = {"class_type": "BosonGridRow", "inputs": row}
            rows.append(f"row{k}")
    if len(rows) > 8:
        raise ValueError("Grid takes 8 rows: 4 refs x 2 draws per graph")
    g["grid"] = {"class_type": "BosonGrid", "inputs": {"studio": ["s0", 0], "refs": ",".join(refs), "cells": 4,
                 "variant": "-v1", "mode": "live", "arm": "orig",
                 **{f"row_{n}": [r, 0] for n, r in enumerate(rows, 1)}}}
    g["save"] = {"class_type": "SaveImage", "inputs": {"images": ["grid", 0], "filename_prefix": prefix}}
    return g


def live(repo, *refs):
    h = queue_history(live_graph(repo, list(refs)))
    print(h["outputs"].get("grid", {}).get("text", ["(no readout)"])[0])
    imgs = h["outputs"]["save"]["images"]
    print(COMFY_DIR / "output" / imgs[0]["subfolder"] / imgs[0]["filename"])


ROUND_SEEDS = (901201, 901202)  # v1, v2: the seeds rounds 01-03 were rendered at


def round_graph(repo, branch, pieces=8, seeds=ROUND_SEEDS, prefix="boson/round"):
    """A round on the canvas: the graph a user runs, with the verdict left empty (SPEC v3 §5 scene 3)."""
    g = live_graph(repo, [branch], draws=(0,), seeds=seeds, pieces=pieces, prefix=prefix)
    for k in ("grid", "save", "row0d0"):
        del g[k]
    imgs = []
    for ab in "ab"[:len(seeds)]:
        g[f"save{ab}"] = {"class_type": "SaveImage", "inputs": {"images": [f"vd0d0{ab}", 0], "filename_prefix": f"{prefix}-{ab}"}}
        imgs.append(f"vd0d0{ab}")
    g["verdict"] = {"class_type": "BosonVerdict", "inputs": {"studio": ["db0d0", 0], "images": [imgs[0], 0], "verdict": ""}}
    return g


def round_(repo, branch, out):
    import grid
    out = pathlib.Path(out)
    line = grid.line_of(st.open_repo(repo), st.load(repo, branch)["sha"])
    t0 = time.time()
    h = queue_history(round_graph(repo, branch))
    print("verdict node:", h["outputs"].get("verdict", {}).get("text"), f"{(time.time() - t0) / 60:.1f} min")
    s = st.load(repo, branch)  # now at the round's draft commit
    rid = f"{len(st.rounds(s)) + 1:02d}"
    sp = st.specs(pathlib.Path(s["dir"]) / "history" / f"round-{rid}")
    for ab, seed in zip("ab", ROUND_SEEDS):
        got = h["outputs"][f"save{ab}"]["images"]
        assert len(got) == len(sp), (len(got), len(sp))
        for x, im in zip(sp, got):  # list order = Draft Brief's prompt order = sorted specs
            dst = out / ("" if line == "main" else line) / f"r{rid}" / f"{x['id']}-v{'ab'.index(ab) + 1}__s{seed}__klein.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(COMFY_DIR / "output" / im["subfolder"] / im["filename"], dst)
            rec = {"round": f"r{rid}", "commit": s["sha"], "spec": f"{x['id']}-v{'ab'.index(ab) + 1}", "series": x["series"],
                   "seed": seed, "file": str(dst.relative_to(out)),
                   "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(), "renderer": RENDERER,
                   "prompt_arm": "orig", "line": line, "drafted": f"drafted in-graph on branch {branch}"}
            with (out / "manifest.jsonl").open("a") as f:
                f.write(json.dumps(rec) + "\n")
    print(f"{2 * len(sp)} plates -> {dst.parent}")
    return dst.parent


def queue_history(graph):
    pid = http("/prompt", {"prompt": graph})["prompt_id"]
    while True:
        h = http(f"/history/{pid}")
        if pid in h and h[pid].get("status", {}).get("completed") is not None:
            if h[pid]["status"].get("status_str") == "error":
                raise RuntimeError(json.dumps(h[pid]["status"].get("messages"))[:1500])
            return h[pid]
        time.sleep(2)


def export():
    p = BOSON / "workflows" / "klein-mi2i.api.json"
    p.parent.mkdir(exist_ok=True)
    g = klein_graph(LEAD + "<prompt from Draft Brief or a stored spec>", 0, 832, 1216,
                    [f"boson/<studio>/ref{r}.jpg" for r in REFS])
    p.write_text(json.dumps(g, indent=1) + "\n")
    q = p.parent / "grid-live.api.json"
    q.write_text(json.dumps(live_graph("~/Boson/tests/fixtures/poc/ex-libris.bundle", ["r00", "r03"]), indent=1) + "\n")
    print(p, q)


def run(repo, out, *rounds):
    out = pathlib.Path(out)
    todo = []
    for tag in rounds:
        s = st.load(repo, tag)
        specs = sorted((pathlib.Path(s["dir"]) / "history" / f"round-{tag[1:]}" / "specs").glob("*.json"))
        todo += [(tag, s, json.loads(p.read_text())) for p in specs]
    refs = stage_refs(todo[0][1], pathlib.Path(repo).stem.split(".")[0])
    arm = "klein" if ARM == "orig" else f"klein-{ARM}"
    fix = strip if ARM == "stripped" else (lambda p: p)
    todo = [t for t in todo if not (out / t[0] / f"{t[2]['id']}__s{t[2]['seed']}__{arm}.png").exists()]
    print(f"{len(todo)} plates to render", flush=True)
    t0 = time.time()
    for k, (tag, s, sp) in enumerate(todo, 1):
        dst = out / tag / f"{sp['id']}__s{sp['seed']}__{arm}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = queue(klein_graph(LEAD + fix(sp["prompt"]), sp["seed"], sp["width"], sp["height"], refs))
        shutil.copy(src, dst)
        rec = {"round": tag, "commit": s["sha"], "spec": sp["id"], "series": sp["series"], "seed": sp["seed"],
               "file": str(dst.relative_to(out)), "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
               "renderer": RENDERER, "prompt_arm": ARM}
        with (out / "manifest.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        el = time.time() - t0
        print(f"{k}/{len(todo)} {tag} {sp['id']} {el:.0f}s, ETA {el / k * (len(todo) - k) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:] or ["-h"]
    if cmd not in ("export", "run", "live", "round"):
        sys.exit(__doc__)
    {"export": export, "run": run, "live": live, "round": round_}[cmd](*a)
