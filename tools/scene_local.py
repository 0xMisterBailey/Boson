#!/usr/bin/env python3
"""A scene on open weights, nothing leaving the box: the steps the scene graph runs (Compile Scene -> the take ->
Uncrop -> Locate -> Commit Take), driven from a terminal because the `local` backend can't queue onto the ComfyUI it
runs in. Pictures (and a worn swap's clothes-only card): FLUX 3 Klein on $BOSON_LOCAL_COMFY. Masks: BiRefNet
(segment.py). Locate: a llama-server with a vision projector on $BOSON_LOCATE_BASE_URL (--model local:NAME).

  python3 tools/scene_local.py SCENE_REPO render shoot --take "Late afternoon ..."      # Klein up
  python3 tools/scene_local.py SCENE_REPO commit shoot --take "Late afternoon ..."      # vision server up
  python3 tools/scene_local.py SCENE_REPO render swap --cast car=STUDIO@SHA:PATH        # Klein up
  python3 tools/scene_local.py SCENE_REPO commit swap --cast car=STUDIO@SHA:PATH        # vision server up
  python3 tools/scene_local.py SCENE_REPO backfill swap --cast ... [--parent 01]       # no model: replay row only

render and commit are separate runs because the picture model and the vision model each fill a 24 GB card: one is
stopped before the other starts. Both compile the shot as the app's Compile Scene does (a worn swap: close crop, the
clothes card made at render), so the key is the app's. render stores the picture as the Nano Banana node does: round
`shot-<key>` in the base studio's plates manifest (renderer boson-nanobanana:local:...), the row the app's stored
replay reads. A take drawn before that row existed ($BOSON_HOME/scene-local/<key>.png, under this key or the older
card-at-compile key) is copied in, not drawn again (backfill). --parent TAKE: Use this take first (scene.choose), so a
run of swaps each edits that take instead of chaining. Any cloud call in this process raises (a tripwire; strace is
the proof).
"""
import argparse, json, pathlib, shutil, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
import grid as gr, nanobanana as nbn, local_render as lr, scene as sc, studio as st  # noqa: E402


def _no_cloud(*a, **k):
    raise RuntimeError("a cloud call in a local scene run")


for mod, fn in ((nbn, "generate"), (nbn, "generate_comfy"), (nbn, "generate_agy"), (sc, "gemini_json")):
    setattr(mod, fn, _no_cloud)


def card(prompt, out, refs):
    return lr.generate(prompt, out, refs, aspect="1:1")


def _no_card(prompt, out, refs):
    raise LookupError("no cached clothes card")


def shot_of(repo, mode, take, casts, parent=""):
    s = sc.load(repo, "main")
    if parent:
        s = sc.choose(s, parent.zfill(2))
    for c in casts:
        slot, piece = c.split("=", 1)
        s = sc.cast(s, slot, piece)
    close = mode == "swap"
    return s, sc.compile_shot(s, mode, take, crop_worn=close, card="defer" if close else None)


def legacy_keys(scene, shot):
    """Keys a take of this shot was drawn under before the app's key was used: a worn swap keyed over its clothes card
    (round 53's runner). Only a cached card counts: nothing is drawn to find a key."""
    if not (shot.get("crop") or {}).get("card"):
        return []
    try:
        return [sc.compile_shot(scene, "swap", "", crop_worn=True, card=_no_card)["key"]]
    except LookupError:
        return []


def plates(scene):
    bs = sc.base(scene)
    return gr.plates_dir(bs.get("source") or bs["repo"]), bs


def store(scene, shot, gen=None, draw=True):
    """The take's picture as the Nano Banana node stores it (round shot-<key> in the base studio's plates manifest),
    drawn by Klein, or copied from a take drawn earlier under this key or a legacy one. -> its path, or None when
    nothing is drawn and draw is False."""
    pdir, bs = plates(scene)
    rid = f"shot-{shot['key']}"
    got = nbn.stored_round(pdir, rid)
    if got:
        return pdir / got[0]["file"]
    have = next((p for p in (sc.HOME / "scene-local" / f"{k}.png" for k in [shot["key"], *legacy_keys(scene, shot)])
                 if p.exists()), None)
    if have is None and not draw:
        return None
    gen = gen or lr.generate

    def put(prompt, out, refs, model, aspect, size):
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        if have is not None:
            shutil.copy2(have, out)
        else:
            gen(prompt, out, refs, aspect=aspect)

    try:   # the clothes card: drawn live (Klein) for a new take; a copied take only names the cached one
        images = sc.render_images(shot, card if have is None else _no_card)
    except LookupError:
        images = shot["images"]
    cfg = {**st.render_cfg(bs), "refs": [], "lead": "",
           **({"aspect": shot["crop"]["aspect"]} if shot.get("crop") else {})}
    rows = nbn.render_round(bs, pdir, rid, [{"id": shot["mode"], "prompt": shot["prompt"]}], cfg, 1,
                            [pathlib.Path(p) for p in images], gen=put, backend="local")
    return pdir / rows[0]["file"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("step", choices=["render", "commit", "backfill"])
    ap.add_argument("mode", choices=["shoot", "swap"])
    ap.add_argument("--take", default="", help="the TAKE block (hour, weather, street life) for a shoot")
    ap.add_argument("--cast", action="append", default=[], help="SLOT=PIECE, before a swap")
    ap.add_argument("--parent", default="", help="swap: the take to edit (Use this take first)")
    ap.add_argument("--model", default="local:qwen3.8-27b", help="Locate's model (local:NAME = the vision server)")
    a = ap.parse_args()
    t0 = time.time()
    scene, shot = shot_of(a.scene, a.mode, a.take, a.cast, a.parent)
    print(f"{a.mode} {shot['key']}: images {', '.join(shot['labels'])} ({time.time() - t0:.1f}s compile)", flush=True)
    if a.step in ("render", "backfill"):
        out = store(scene, shot, draw=a.step == "render")
        print(f"{a.step} {out or 'nothing drawn for this key: render it first'} ({time.time() - t0:.1f}s)", flush=True)
        sys.exit(0 if out else 1)
    out = store(scene, shot, draw=False)
    if out is None:
        sys.exit(f"{a.mode} {shot['key']} is not drawn yet: run render first (Klein up)")
    from PIL import Image
    img = Image.open(out).convert("RGB")
    crop = shot.get("crop")
    if crop:                              # Uncrop: the edited person alone, back into the parent take
        t1 = time.time()
        m, before = sc.subject_masks([out, shot["images"][0]])
        img = sc.uncrop(Image.open(crop["parent_image"]), img, crop["box"], inner=crop["inner"], mask=m,
                        before=before, wearer=crop.get("wearer"))
        sc.record_uncropped(shot["key"], sc.image_hash(img))
        print(f"uncrop ({time.time() - t1:.1f}s)", flush=True)
    t1 = time.time()
    boxes = sc.locate(scene, img, a.model, "live")
    print(f"locate ({time.time() - t1:.1f}s): " + json.dumps({k: v.get("box") for k, v in boxes["slots"].items()}),
          flush=True)
    shot["renderer"] = f"boson-nanobanana:local:{lr.MODEL}"
    scene, tid = sc.commit_take(scene, img, boxes, shot)
    print(f"take {tid} committed in {scene['repo']} ({time.time() - t0:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
