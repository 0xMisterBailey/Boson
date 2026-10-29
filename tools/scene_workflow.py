#!/usr/bin/env python3
"""The shoot workflow for any scene, from its SCENE.json: what workflows/scene-street.json is for the street, so a new
scene (docs/FORGE.md) can be shot and its slots commissioned from the app (client.ensureScene(repo, "scene-NAME")).

  python3 tools/scene_workflow.py SCENE_REPO [--out workflows]   -> scene-NAME.api.json + scene-NAME.json

Down: Load Scene -> one Cast per slot -> Compile Scene -> the base studio's Nano Banana (shot) -> Locate -> Commit Take.
Up: Load Take -> per object slot Slot Crop -> its studio's Make (commission new); per flat slot Paste Flat. Plus Keep
Piece, and Add Slot (something the base shows becomes a slot, round 49). Everything starts stored (no key, no call); the client sets live per verb.
"""
import argparse, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "boson"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mkworkflow as mk  # noqa: E402
import scene as sc  # noqa: E402
import studio as st  # noqa: E402


def _tilde(p):
    """A repo path as the graph stores it: ~/... under home, so no home path lands in a shipped workflow."""
    p, home = pathlib.Path(p).expanduser().resolve(), pathlib.Path.home()
    return "~/" + str(p.relative_to(home)) if p.is_relative_to(home) else str(p)


def _repo(p, registry):
    """A repo as the graph stores it: its registry name when the registry knows it (the name loads in any clone:
    examples/NAME here, the shipped bundle there), else _tilde."""
    p = pathlib.Path(p).expanduser().resolve()
    return next((n for n, src in registry.items() if pathlib.Path(src).resolve() == p), None) or _tilde(p)


def build(scene_repo):
    s = sc.load(scene_repo, "main")
    spec, g, studios = s["spec"], {}, st.registry()
    studio = lambda name: _repo(st.find(name), studios)  # noqa: E731
    add = lambda cls, inputs, title, pos: g.__setitem__(str(len(g) + 1), {  # noqa: E731
        "class_type": cls, "inputs": inputs, "_meta": {"title": title, "pos": pos, "size": [320, 140]}}) or str(len(g))
    ls = add("BosonLoadScene", {"repo": _repo(scene_repo, sc.registry()), "ref": "main"}, f"Load Scene ({spec['name']})", [0, 0])
    prev = ls
    for i, sl in enumerate(spec["slots"]):
        prev = add("BosonCast", {"scene": [prev, 0], "slot": sl["id"], "piece": "", "desc": "", "short": ""},
                   f"Cast ({sl['id']})", [380, i * 180])
    comp = add("BosonCompileScene", {"scene": [prev, 0], "mode": "swap", "take": ""}, "Compile Scene", [760, 0])
    add("PreviewImage", {"images": [comp, 1]}, "What Compile sends", [760, 300])
    base = add("BosonLoadStudio", {"repo": studio(spec["base"]["studio"]), "ref": spec["base"]["ref"]},
               f"Load Studio (base: {spec['base']['studio']})", [760, 500])
    nb = add("BosonNanoBanana", {"studio": [base, 0], "mode": "stored", "draws": 1, "backend": "comfy-api", "shot": [comp, 0]},
             "Nano Banana (the take)", [1140, 0])
    took = nb
    if any(sl.get("carrier") for sl in spec["slots"]):   # a worn swap edits a close crop: Uncrop pastes the person back
        bgm = add("LoadBackgroundRemovalModel", {"bg_removal_name": "birefnet.safetensors"}, "Load Background Removal",
                  [1140, 300])
        rb = add("RemoveBackground", {"bg_removal_model": [bgm, 0], "image": [nb, 0]}, "Remove Background (the edit)",
                 [1140, 500])
        took = add("BosonUncrop", {"image": [nb, 0], "shot": [comp, 0], "mask": [rb, 0]}, "Uncrop (worn swaps)",
                   [1520, 300])
    loc = add("BosonLocate", {"image": [took, 0], "scene": [prev, 0], "mode": "stored", "model": sc.LOCATE_MODEL},
              "Locate", [1520, 0])
    add("BosonCommitTake", {"scene": [prev, 0], "image": [took, 0], "boxes": [loc, 0], "shot": [comp, 0]}, "Commit Take",
        [1900, 0])
    lt = add("BosonLoadTake", {"scene": [ls, 0], "take": ""}, "Load Take", [0, 900])
    for i, sl in enumerate(spec["slots"]):
        y = 900 + i * 260
        if sl["kind"] == "object":
            crop = add("BosonSlotCrop", {"image": [lt, 0], "boxes": [lt, 1], "slot": sl["id"], "item": 0, "pad": 0.15,
                                           "scene": [ls, 0]},
                       f"Slot Crop ({sl['id']})", [380, y])
            who = add("BosonLoadStudio", {"repo": studio(sl["studio"]), "ref": "main"}, f"Load Studio ({sl['studio']})",
                      [760, y])
            m = add("BosonMake", {"studio": [who, 0], "frame": "", "idea": "", "n": 4, "mode": "stored", "like": "",
                                  "backend": "comfy-api", "image_1": [crop, 0]}, f"Make ({sl['studio']}, commission new)",
                    [1140, y])
            add("PreviewImage", {"images": [m, 0]}, f"New {sl['id']}", [1520, y])
        else:
            pf = add("BosonPasteFlat", {"image": [lt, 0], "boxes": [lt, 1], "scene": [ls, 0], "slot": sl["id"],
                                        "glass": 0.15}, f"Paste Flat ({sl['id']})", [380, y])
            add("PreviewImage", {"images": [pf, 0]}, f"Take with {sl['id']}", [760, y])
    y = 900 + len(spec["slots"]) * 260
    kls = add("BosonLoadStudio", {"repo": studio(spec["base"]["studio"]), "ref": "main"}, "Load Studio (keep)", [0, y])
    add("BosonKeepPiece", {"studio": [kls, 0], "path": "", "note": "", "op": "keep"}, "Keep Piece", [380, y])
    add("BosonAddSlot", {"scene": [ls, 0], "anchor": "", "slot": "", "noun": "", "studio": "", "where": "", "box": ""},
        "Add Slot (make a slot from the frame)", [760, y])
    return spec["name"], g


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "workflows"))
    a = ap.parse_args()
    name, api = build(pathlib.Path(a.scene).expanduser())
    out = pathlib.Path(a.out)
    (out / f"scene-{name}.api.json").write_text(json.dumps(api, indent=1) + "\n")
    (out / f"scene-{name}.json").write_text(json.dumps(mk.ui(api), indent=1) + "\n")
    print(f"{out}/scene-{name}.json: {len(api)} nodes; app: ensureScene(repo, \"scene-{name}\")")


if __name__ == "__main__":
    main()
