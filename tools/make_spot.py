#!/usr/bin/env python3
"""Make n for this spot, from a terminal: the app's in-context Make (Load Take -> Slot Crop -> Make, the crop wired in
as commission image 1, idea = the slot's place line) with the local backend, which can't queue onto the ComfyUI it
runs in. Same key as the app (server.ready): the studio at main, frame = the slot's role, idea = client.js spotIdea,
n, the crop's bytes; the pieces land where the Make node stores them, so the app replays them.

  python3 tools/make_spot.py SCENE_REPO SLOT --studio STUDIO_REPO [--take 01] [--n 4] [--words "..."]

Two passes, as a local round: the writer pass (writer loaded) writes the specs (cached by key) and stops at the draw
when no ComfyUI answers; the Klein pass (ComfyUI up) draws them. --write-only stops after the specs on purpose.
"""
import argparse, pathlib, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
import grid as gr, nanobanana as nbn, scene as sc, studio as st  # noqa: E402

MAX_REFS = 10   # as the Make node


def spot_idea(slot, words=""):
    """client.js spotIdea: what the app sends as the idea of a Make for a slot's spot (part of the stored key)."""
    spot = f"for the spot in commission image 1: {slot['place'].get('line', '')}".strip()
    return f"{words.strip()} It goes {spot}" if words.strip() else f"A new {slot.get('short') or slot['noun']} {spot}"


def spot(scene, slot_id, tid=None, pad=0.15):
    """-> (slot, the take, the crop PIL) as Slot Crop cuts it for the app's Make (server.ready)."""
    from PIL import Image
    sl = next((x for x in scene["spec"]["slots"] if x["id"] == slot_id), None)
    if sl is None:
        raise KeyError(f"no slot {slot_id!r}")
    tid = tid.zfill(2) if tid else scene["takes"][-1]
    t = sc.take(scene, tid)
    crop = sc.crop(Image.open(t["image"]).convert("RGB"), t["boxes"], slot_id, 0, pad, sl["place"])
    return sl, t, crop


def make(scene, slot_id, studio, tid=None, n=4, words="", backend="local", write_only=False, log=print):
    import numpy as np
    sl, t, crop = spot(scene, slot_id, tid)
    wired = [np.asarray(crop.convert("RGB")).tobytes()]
    frame, idea = sl.get("role", ""), spot_idea(sl, words)
    key = st.make_key(studio, frame, idea, n, "", wired)
    rid, pdir = f"make-{key}", gr.plates_dir(studio.get("source") or studio["repo"])
    rows = nbn.stored_round(pdir, rid)
    log(f"make {key} for {slot_id} on take {t['id']} ({st.name_of(studio)}): idea {idea!r}")
    if not rows:
        t0 = time.time()
        specs, meta = st.make(studio, frame, idea, n, "", images=wired, key=key)
        log(f"specs: {len(specs)} ({time.time() - t0:.0f}s, {meta.get('writer')})")
        if write_only:
            return key, []
        house = st.taste(studio)
        refs = [sc.piece(x) for x in house["pictures"] + house["pins"]]
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="boson-make-"))
        crop.save(tmp / "commission-1.png")
        refs.append(tmp / "commission-1.png")
        t0 = time.time()
        rows = nbn.render_round(studio, pdir, rid, specs, st.render_cfg(studio), 1, refs[:MAX_REFS] or None,
                                backend=backend)
        log(f"drawn: {len(rows)} ({time.time() - t0:.0f}s)")
    pieces = [f"{st.name_of(studio)}@{r['studio_sha'][:8]}:{r['file']}" for r in rows]
    return key, pieces


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("slot")
    ap.add_argument("--studio", required=True, help="the slot studio's repo (or a registered name)")
    ap.add_argument("--take", default="", help="the take to crop (default the newest)")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--words", default="", help="the owner's words for the make (default none: the place line)")
    ap.add_argument("--backend", default="local", choices=nbn.BACKENDS)
    ap.add_argument("--write-only", action="store_true")
    a = ap.parse_args()
    if a.backend != "local":
        sys.exit("this driver is for the local backend; the app's Make node runs the others")
    scene = sc.load(a.scene, "main")
    studio = st.load(a.studio, "main")
    key, pieces = make(scene, a.slot, studio, a.take, a.n, a.words, a.backend, a.write_only,
                       log=lambda *x: print(*x, flush=True))
    print("\n".join(pieces) or f"make {key}: specs written, not drawn", flush=True)


if __name__ == "__main__":
    main()
