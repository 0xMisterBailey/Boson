#!/usr/bin/env python3
"""The motion workflow: one committed take of a scene set in motion by Comfy's partner Gemini Omni node, the clip
committed back into the scene repo beside its take (SPEC §5, operator 1a 2026-10-23).

  python3 tools/motion_workflow.py SCENE_REPO --take 07 --prompt "..." [--model "Omni Flash 1.1"] [--out workflows]
      -> workflows/motion-NAME.api.json (open it in ComfyUI: Workflow > Open takes API files)
  ... --queue http://127.0.0.1:8188      also queue it, with the Comfy API key ($COMFY_API_KEY or
                                          ~/.config/comfy-tokens/api-key) in extra_data, as the frontend sends it

Load Scene -> Load Take -> Google Gemini Omni (Video), image_to_video from the take -> Commit Clip, one Text node
feeding the same words to both. Replay without a key: Load Scene -> Load Clip.
LTX 2.5 (operator 1b, 10-24): --model "LTX-2.5 (Pro)" or "LTX-2.5 (Fast)" swaps the video node for Comfy's
LtxApi25ImageToVideo (--duration, --resolution 1920x1080 ...); its badge prices per second: Pro $0.1716/s at 720p,
$0.2431/s at 1080p; Fast $0.1287 / $0.1859. --paste puts each flat slot's art on the take first (Paste Flat), as the
stills show it: a committed take holds the blank panel.
Cost (Omni): the node's price badge shows $0.1449 at 720p (ComfyUI of 2026-10-20); its unit (per second or per clip)
is unconfirmed, so a 6 s clip costs $0.14-0.87. The first charged clip settles it.
"""
import argparse, json, pathlib, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
import nanobanana as nbn  # noqa: E402
import scene as sc  # noqa: E402

MODELS = {"Omni Flash 1.1": "gemini-omni-1.1-flash", "Omni Flash": "gemini-omni-flash-preview",
          "LTX-2.5 (Pro)": "ltx-2.5-pro", "LTX-2.5 (Fast)": "ltx-2.5-fast"}
LTX_USD_S = {("LTX-2.5 (Pro)", "1280x720"): 0.1716, ("LTX-2.5 (Pro)", "1920x1080"): 0.2431,
             ("LTX-2.5 (Fast)", "1280x720"): 0.1287, ("LTX-2.5 (Fast)", "1920x1080"): 0.1859}   # the node's badge, 10-24


def price(model, resolution, duration):
    """USD for one LTX clip from the node's own badge table; None for Omni (unit unconfirmed)."""
    r = LTX_USD_S.get((model, resolution))
    return round(r * int(duration), 4) if r else None


def build(scene_repo, take, prompt, model="Omni Flash 1.1", resolution="720p", aspect="16:9", seed=42, paste=False,
          duration="6", audio=True):
    s = sc.load(scene_repo, "main")
    if take not in s["takes"]:
        raise SystemExit(f"scene {s['spec']['name']} has no take {take!r}; takes: {', '.join(s['takes'])}")
    g = {}
    add = lambda cls, inputs, title: g.__setitem__(str(len(g) + 1), {  # noqa: E731
        "class_type": cls, "inputs": inputs, "_meta": {"title": title}}) or str(len(g))
    repo = pathlib.Path(scene_repo).expanduser().resolve()
    home = pathlib.Path.home()
    repo = "~/" + str(repo.relative_to(home)) if repo.is_relative_to(home) else str(repo)   # no home path in the file
    ls = add("BosonLoadScene", {"repo": repo, "ref": "main"}, f"Load Scene ({s['spec']['name']})")
    lt = add("BosonLoadTake", {"scene": [ls, 0], "take": take}, f"Load Take ({take})")
    frame = lt
    for sl in (x for x in s["spec"]["slots"] if paste and x["kind"] == "flat"):
        frame = add("BosonPasteFlat", {"image": [frame, 0], "boxes": [lt, 1], "scene": [ls, 0], "slot": sl["id"],
                                       "glass": 0.15}, f"Paste Flat ({sl['id']})")
    words = add("PrimitiveStringMultiline", {"value": prompt}, "How it moves")
    if model.startswith("LTX"):
        video = add("LtxApi25ImageToVideo", {"image": [frame, 0], "model": model, "model.duration": str(duration),
                                             "model.resolution": resolution, "model.fps": "25",
                                             "model.generate_audio": audio, "prompt": [words, 0], "seed": seed},
                    "LTX 2.5 Image To Video via Comfy API")
    else:
        video = add("GeminiVideoOmniV2", {"model": model, "model.prompt": [words, 0], "model.resolution": resolution,
                                          "model.aspect_ratio": aspect, "model.task_type": "image_to_video",
                                          "model.seed": seed, "model.images.image_1": [frame, 0]},
                    "Google Gemini Omni (Video) via Comfy API")
    add("BosonCommitClip", {"scene": [ls, 0], "video": [video, 0], "take": take, "prompt": [words, 0],
                            "renderer": f"comfy-api:{MODELS[model]}"}, "Commit Clip")
    return s["spec"]["name"], g


def queue(url, g):
    body = {"prompt": {k: {kk: vv for kk, vv in v.items() if kk != "_meta"} for k, v in g.items()},
            "extra_data": {"api_key_comfy_org": nbn.comfy_key()}}
    req = urllib.request.Request(url.rstrip("/") + "/prompt", json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ComfyUI refused the graph (HTTP {e.code}): {e.read().decode()[:1500]}") from None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--take", required=True)
    ap.add_argument("--prompt", required=True, help='how it moves, with the length: "... a 6-second clip"')
    ap.add_argument("--model", default="Omni Flash 1.1", choices=sorted(MODELS))
    ap.add_argument("--resolution", default=None, help="Omni: 360p 720p 1080p 4k (default 720p); LTX: 1280x720, "
                    "1920x1080 (default)")
    ap.add_argument("--duration", default="6", help="LTX seconds (2-10 Pro, 2-20 Fast)")
    ap.add_argument("--no-audio", action="store_true", help="LTX: no generated sound")
    ap.add_argument("--paste", action="store_true", help="paste each flat slot's art on the take first")
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--out", default=str(ROOT / "workflows"))
    ap.add_argument("--queue", metavar="COMFY_URL", help="also queue it (spends Comfy credits)")
    a = ap.parse_args()
    res = a.resolution or ("1920x1080" if a.model.startswith("LTX") else "720p")
    name, g = build(pathlib.Path(a.scene).expanduser(), a.take, a.prompt, a.model, res, a.aspect, paste=a.paste,
                    duration=a.duration, audio=not a.no_audio)
    out = pathlib.Path(a.out) / f"motion-{name}{'-ltx' if a.model.startswith('LTX') else ''}.api.json"
    out.write_text(json.dumps(g, indent=1) + "\n")
    usd = price(a.model, res, a.duration) if a.model.startswith("LTX") else None
    print(f"{out}: {len(g)} nodes" + (f", price ${usd} ({a.model}, {res}, {a.duration} s)" if usd else ""))
    if a.queue:
        print("queued:", queue(a.queue, g))


if __name__ == "__main__":
    main()
