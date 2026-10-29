#!/usr/bin/env python3
"""Draft a SCENE.json from a base picture with the local vision model: every free-text field (medium, subject,
subject_desc, lock_edges, handed, anchors, the slots' words) and a box for a car slot and a worn-outfit slot come from
the model's answer; this tool only asks (a fixed instruction, software) and assembles. The slots start made from the
frame (scene.promote's shape: piece = the base itself, from "box"), so a Shoot draws no stand-in and the base's own
car and person stay until a piece is cast. Boxes are asked x-first, as scene.local_json asks Qwen.

  python3 tools/scene_draft.py BASE_PIECE --name NAME --out SCENE_REPO --car-studio S --outfit-studio S \
      [--raw RAW.json] [--port 8192]

BASE_PIECE is studio@sha:path (a green from a round, a stored plate). The model's raw answer goes to --raw (default
SCENE_REPO.raw.json), and the assembled spec is validated, then created as a scene repo (scene.create).
"""
import argparse, copy, json, os, pathlib, re, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
import scene as sc  # noqa: E402

ASK = """Look at this photograph closely. You are writing the scene sheet that later picture edits of it will follow.
Answer with JSON only, in exactly this shape (every value written by you, from what you see):
{
 "medium": "what kind of picture it is, a short phrase starting with 'a', e.g. the kind of photograph",
 "subject": "the whole scene in two to five words",
 "subject_desc": "one sentence: the place, the time of day and the light as they look",
 "lock_edges": "a comma list of the five or six large fixed things whose edges define the frame (buildings, shelter, track, kerb ...), with 'and' before the last",
 "lock_edges_short": "the leftmost and rightmost of those, as 'X to Y'",
 "handed": "one or two sentences: what stands on the left, in the middle and on the right of the frame",
 "handed_short": "the same in under ten words",
 "anchors": [{"id": "one lowercase word", "desc": "the thing, as one noun phrase starting with 'the'"}, "... two or three large fixed things"],
 "car": {"noun": "two words starting with 'the' naming what this slot holds", "where": "where the most visible car is in the street and which way it faces, a phrase starting with a preposition", "box": [xmin, ymin, xmax, ymax]},
 "person": {"noun": "two words starting with 'the' naming the clothes this slot holds", "carrier": "a phrase starting with 'worn by' naming the most visible standing person and where they stand, the same person, same pose and facing", "where": "where that person stands, a phrase starting with a preposition", "box": [xmin, ymin, xmax, ymax]}
}
Boxes: the whole of that car, the whole of that person from head to feet; integers 0 to 1000 on the full image,
x before y. If there is no car or no standing person, give that key the value null."""


def ask(pil, port, raw_path):
    os.environ.setdefault("BOSON_LOCATE_BASE_URL", f"http://127.0.0.1:{port}")
    sc.LOCAL_LOCATE = os.environ["BOSON_LOCATE_BASE_URL"]
    t0 = time.time()
    # local_json turns x-first boxes back into Gemini's y-first order for "items"; this answer has no items list,
    # so its boxes stay as asked: [xmin, ymin, xmax, ymax]
    raw, usage = sc.local_json(ASK, pil)
    pathlib.Path(raw_path).write_text(json.dumps({"prompt": ASK, "raw": raw, "usage": usage,
                                                  "s": round(time.time() - t0, 1)}, indent=1) + "\n")
    return raw


def frac(b):
    x0, y0, x1, y1 = (max(0, min(1000, int(v))) / 1000 for v in b)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)]


def slot(spec, sid, studio, got, role):
    """scene.promote's slot shape (from a box), filled with the model's words."""
    noun = got["noun"].strip()
    where = got.get("where", "").strip()
    desc = " ".join(x for x in (noun, where) if x)
    s = {"id": sid, "role": role, "kind": "object", "studio": studio, "piece": sc.base_piece(spec), "noun": noun,
         "short": re.sub(r"^(the|a|an) ", "", noun), "where": where, "desc": desc, "base_desc": noun,
         "stand_in": "box", "from": "box",
         "place": {"line": f"in place of {desc}, the same place, size and angle", "box": frac(got["box"])}}
    if got.get("carrier"):
        s["carrier"] = got["carrier"].strip()
    return s


def assemble(raw, name, base_piece, aspect, car_studio, outfit_studio):
    studio, ref, view = sc.parse_piece(base_piece)
    b = {"studio": studio, "ref": ref, "view": view, "view_noun": "photograph"}
    for k in ("medium", "subject", "subject_desc", "lock_edges", "lock_edges_short", "handed", "handed_short"):
        if isinstance(raw.get(k), str) and raw[k].strip():
            b[k] = raw[k].strip()
    b["anchors"] = {re.sub(r"\W+", "-", a["id"].strip().lower()): a["desc"].strip()
                    for a in raw.get("anchors") or [] if isinstance(a, dict) and a.get("id") and a.get("desc")}
    spec = {"name": name, "aspect": aspect, "base": b, "slots": []}
    for sid, studio_, key, role in (("car", car_studio, "car", "Car"), ("outfit", outfit_studio, "person", "Outfit")):
        got = raw.get(key)
        if isinstance(got, dict) and got.get("noun") and isinstance(got.get("box"), list) and len(got["box"]) == 4:
            spec["slots"].append(slot(spec, sid, studio_, got, role))
    sc.validate(copy.deepcopy(spec))
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="studio@sha:path")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--car-studio", required=True)
    ap.add_argument("--outfit-studio", required=True)
    ap.add_argument("--raw")
    ap.add_argument("--port", type=int, default=8192)
    a = ap.parse_args()
    from PIL import Image
    pil = Image.open(sc.piece(a.base)).convert("RGB")
    raw_path = a.raw or f"{a.out}.raw.json"
    raw = json.loads(pathlib.Path(raw_path).read_text())["raw"] if pathlib.Path(raw_path).exists() else ask(pil, a.port, raw_path)
    spec = assemble(raw, a.name, a.base, a.aspect, a.car_studio, a.outfit_studio)
    print(json.dumps(spec, indent=1))
    s = sc.create(a.out, spec, "scene: SCENE.json drafted by the local vision model (tools/scene_draft.py)")
    print(f"scene {a.name} @ {s['sha'][:8]}: {s['repo']}")


if __name__ == "__main__":
    main()
