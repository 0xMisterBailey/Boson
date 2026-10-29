#!/usr/bin/env python3
"""Arms B and C of the A/B: A's twelve Austin takes replayed in A's tree on a scene clone whose pictures are local.

For take NN the scene's words are A's own SCENE.json at the commit that made A's take NN (the cast, the descs, the place
lines), with only the base view swapped (B: B's Klein street, a commit in the streets clone; C: A's cloud street as is)
and `chosen` pointed at A's parent, so Compile Scene builds A's shot. The prompt is checked against A's take.json: a
shoot and a worn swap byte for byte, an object swap byte for byte once the Locate spans (B's own boxes) are masked.
Pictures: FLUX 3 Klein (tools/scene_local.store); Uncrop masks: BiRefNet on CPU; Locate: the local vision server.

  python3 tools/ab_takes.py SCENE_REPO render 01 04        # Klein up: draw these takes (parents must be committed)
  python3 tools/ab_takes.py SCENE_REPO commit 01 04        # vision up: Uncrop, Locate, commit, in take order
  python3 tools/ab_takes.py SCENE_REPO crop 10 car OUT.png # B's Slot Crop for an in-context round (pad 0.15)
  python3 tools/ab_takes.py SCENE_REPO init --base-sha SHA  # a new scene repo from A's first SCENE.json
"""
import argparse, json, pathlib, re, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "boson"))
import scene_local as sl  # noqa: E402  (its import arms the no-cloud tripwire)
import local_render as lr, scene as sc  # noqa: E402

A = ROOT / "examples" / "austin-stop"
A_STREET = "1afd1528"
SPAN = re.compile(r"x \d\.\d\d-\d\.\d\d, y \d\.\d\d-\d\.\d\d")


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout


def a_commits(a=A):
    """take id -> the commit in A that made it."""
    out = {}
    for line in git(a, "log", "--reverse", "--format=%H %s").splitlines():
        h, s = line.split(" ", 1)
        m = re.match(r"take (\d\d): ", s)
        if m:
            out[m.group(1)] = h
    return out


def a_take(tid, a=A):
    return json.loads((a / "takes" / tid / "take.json").read_text())


def a_spec(tid, base_sha, a=A):
    """A's SCENE.json as of take tid, the base view moved to streets@base_sha, chosen = A's parent (a swap edits it)."""
    raw = git(a, "show", f"{a_commits(a)[tid]}:SCENE.json")
    if base_sha[:8] != A_STREET:
        raw = raw.replace(f"streets@{A_STREET}:", f"streets@{base_sha[:8]}:").replace(
            f'"ref": "{A_STREET}"', f'"ref": "{base_sha[:8]}"')
    spec = json.loads(raw)
    t = a_take(tid, a)
    if t["op"] == "swap":
        spec["chosen"] = t["parent"]
    return sc.validate(spec)


def take_text(spec_scene, a_prompt):
    """The TAKE block of A's shoot: A's prompt minus the template Compile Scene builds around it."""
    tpl = sc.shoot_prompt(spec_scene["spec"], sc.st.house(sc.base(spec_scene)), "")
    pre, post = tpl.split("<<TAKE>>")
    if not (a_prompt.startswith(pre) and a_prompt.endswith(post)):
        raise AssertionError("A's shoot prompt is not this scene's template around a TAKE block")
    return a_prompt[len(pre):len(a_prompt) - len(post)]


def same_words(mine, a_prompt, mode):
    """-> 'exact' or 'spans' (equal once the Locate spans are masked); raises when the words differ."""
    if mine == a_prompt:
        return "exact"
    if mode == "swap" and SPAN.sub("x _, y _", mine) == SPAN.sub("x _, y _", a_prompt):
        return "spans"
    raise AssertionError(f"the compiled prompt is not A's:\nB: {mine}\nA: {a_prompt}")


def shot_for(repo, tid, a=A):
    """-> (scene, shot, how the words match A's) for A's take tid on this scene repo."""
    scene = sc.load(repo, "main")
    t = a_take(tid, a)
    scene["spec"] = a_spec(tid, scene["spec"]["base"]["ref"], a)
    if t["op"] == "swap" and t["parent"] not in scene["takes"]:
        raise LookupError(f"take {tid}'s parent {t['parent']} is not committed here yet")
    text = take_text(scene, t["prompt"]) if t["op"] == "shoot" else ""
    shot = sc.compile_shot(scene, t["op"], text, crop_worn=t["op"] == "swap", card="defer" if t["op"] == "swap" else None)
    return scene, shot, same_words(shot["prompt"], t["prompt"], t["op"])


def log_line(work, rec):
    with open(pathlib.Path(work) / "logs" / "takes.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")


def render(repo, tids, work, log=print):
    t0 = time.time()
    for i, tid in enumerate(tids, 1):
        t1 = time.time()
        scene, shot, how = shot_for(repo, tid)
        out = sl.store(scene, shot)
        dt = time.time() - t1
        log_line(work, {"scene": pathlib.Path(repo).name, "take": tid, "step": "render", "key": shot["key"],
                        "words": how, "labels": shot["labels"], "images": shot["images"], "out": str(out),
                        "seed": lr.seed_for(out), "seconds": round(dt, 1)})
        log(f"{pathlib.Path(repo).name} render {i}/{len(tids)} done take {tid} ({how}, {dt:.0f}s), "
            f"ETA {(time.time() - t0) / i * (len(tids) - i) / 60:.1f} min")


def commit(repo, tids, work, model="local:qwen3.8-27b", log=print):
    from PIL import Image
    for tid in tids:
        t1 = time.time()
        scene, shot, how = shot_for(repo, tid)
        if f"{len(scene['takes']) + 1:02d}" != tid:
            if tid in scene["takes"]:
                log(f"{pathlib.Path(repo).name} take {tid} already committed")
                continue
            ahead = True     # an earlier number is still open: Locate now (cached by pixels), commit in a later turn
        else:
            ahead = False
        out = sl.store(scene, shot, draw=False)
        if out is None:
            raise LookupError(f"take {tid} is not drawn yet: render it first (Klein up)")
        img = Image.open(out).convert("RGB")
        crop = shot.get("crop")
        if crop:
            m, before = sc.subject_masks([out, shot["images"][0]])
            img = sc.uncrop(Image.open(crop["parent_image"]), img, crop["box"], inner=crop["inner"], mask=m,
                            before=before, wearer=crop.get("wearer"))
            sc.record_uncropped(shot["key"], sc.image_hash(img))
        boxes = sc.locate(scene, img, model, "live")
        if ahead:
            log(f"{pathlib.Path(repo).name} take {tid} located ahead ({time.time() - t1:.0f}s): commit waits for its number")
            continue
        shot["renderer"] = f"boson-nanobanana:local:{lr.MODEL}"
        scene, got = sc.commit_take(scene, img, boxes, shot)
        dt = time.time() - t1
        missed = [k for k, v in boxes["slots"].items() if not v.get("visible")]
        log_line(work, {"scene": pathlib.Path(repo).name, "take": tid, "step": "commit", "committed_as": got,
                        "words": how, "boxes": {k: v.get("box") for k, v in boxes["slots"].items()},
                        "missed": missed, "seconds": round(dt, 1)})
        log(f"{pathlib.Path(repo).name} commit take {tid} -> {got} ({dt:.0f}s), Locate missed: {missed or 'none'}")


def slot_crop(repo, tid, slot, out):
    from PIL import Image
    scene = sc.load(repo, "main")
    t = sc.take(scene, tid)
    a_now = json.loads((A / "SCENE.json").read_text())   # the place A's crops matched with (B's HEAD may predate the slot)
    place = next(s for s in a_now["slots"] if s["id"] == slot)["place"]
    c = sc.crop(Image.open(t["image"]).convert("RGB"), t["boxes"], slot, 0, 0.15, place)
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    c.save(out)
    return out


def init(repo, base_sha, a=A):
    repo = pathlib.Path(repo)
    first = git(a, "log", "--reverse", "--format=%H").split()[0]
    raw = git(a, "show", f"{first}:SCENE.json")
    if base_sha[:8] != A_STREET:
        raw = raw.replace(f'"ref": "{A_STREET}"', f'"ref": "{base_sha[:8]}"')
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "SCENE.json").write_text(raw)
    git(repo, "add", "SCENE.json")
    git(repo, "commit", "-q", "-m", f"scene: A's austin-stop SCENE.json ({first[:8]}), base view streets@{base_sha[:8]}")
    return repo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("step", choices=["render", "commit", "crop", "init"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--base-sha", default="")
    ap.add_argument("--work", default=str(pathlib.Path.home() / ".cache" / "boson-ab"))
    ap.add_argument("--model", default="local:qwen3.8-27b")
    a = ap.parse_args()
    prog = open(pathlib.Path(a.work) / "logs" / "progress.log", "a")

    def log(*x):
        line = " ".join(map(str, x))
        print(line, flush=True)
        prog.write(time.strftime("%H:%M:%S ") + line + "\n")
        prog.flush()

    if a.step == "init":
        print(init(a.scene, a.base_sha))
    elif a.step == "render":
        render(a.scene, a.args, a.work, log)
    elif a.step == "commit":
        commit(a.scene, a.args, a.work, a.model, log)
    else:
        print(slot_crop(a.scene, *a.args))


if __name__ == "__main__":
    main()
