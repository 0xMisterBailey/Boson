#!/usr/bin/env python3
"""Arm B of the local-vs-cloud A/B (2026-10-27): A's pictures redrawn by FLUX 3 Klein from A's own words.

Only the pictures change. Every B plate is drawn from A's logged prompt byte for byte (the round's nb-log.jsonl, checked
against the plates manifest), at A's aspect, with B's own redraw of each picture A passed as a reference (same file
name); a "Make 4 for this spot" round's commission image 1 is the same crop of B's matching take (--commission). Klein's
seed is local_render.seed_for(out), a hash of the file name, so A's names fix the seeds. B's manifest rows are A's rows
with the renderer swapped, so `studio@sha:path` pieces resolve to B's pixels under B's studio clones.

  python3 tools/ab_replay.py plan  --work ~/.cache/boson-ab                     # -> WORK/plan.jsonl (39 plates)
  python3 tools/ab_replay.py run   --work ~/.cache/boson-ab --only plain        # the plates with no commission image
  python3 tools/ab_replay.py run   --work ~/.cache/boson-ab --only make-f420fd9d2797 --commission CROP.png
  python3 tools/ab_replay.py street --work ~/.cache/boson-ab                    # B's street, 4 versions

Nothing here calls a writer or a cloud model: the only picture call is local_render.generate ($BOSON_LOCAL_COMFY).
"""
import argparse, hashlib, json, os, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
STUDIOS = ["fashion-real", "cars-real", "exotic-cars-real", "posters-real", "architecture-real"]
RENDERER = "boson-nanobanana:local:flux3-image-klein-bf16"
STREET_LOG = ROOT / "design/reforge/scene/fan-03/nb-log.jsonl"
STREET_OUT = "gold-east-cesar-chavez.png"


def _rows(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


def scene_pieces(scene_dir=EX / "austin-stop"):
    """Every piece cast in any of A's takes, streets (the base view) left out."""
    out = set()
    for c in sorted(pathlib.Path(scene_dir).glob("takes/*/cast.json")):
        out |= {p for p in json.loads(c.read_text()).values() if not p.startswith("streets@")}
    return sorted(out)


def nb_row(studio, file, ex=EX):
    """A's logged call for one plate: its round's nb-log row (the prompt the model got, refs as full paths, aspect)."""
    rows = [r for r in _rows(ex / f"{studio}-plates" / pathlib.Path(file).parent / "nb-log.jsonl")
            if r["out"] == pathlib.Path(file).name]
    if not rows:
        raise LookupError(f"{studio}:{file} has no nb-log row")
    return rows[-1]


def plan(pieces, ex=EX, studios=STUDIOS):
    """-> rows {studio, round, file, prompt, refs (A's paths), aspect, size, commission, manifest} in reference order:
    the cast pieces, every earlier plate they reference (recursively), and the full set of each in-context round."""
    man = {}
    for s in studios:
        for r in _rows(ex / f"{s}-plates" / "manifest.jsonl"):
            man[(s, pathlib.Path(r["file"]).name)] = r
    need, todo = {}, [(p.split("@")[0], p.split("/")[-1]) for p in pieces]
    while todo:
        k = todo.pop()
        if k in need:
            continue
        if k not in man:
            raise LookupError(f"{k} is not in its studio's plates manifest")
        need[k] = man[k]
        todo += [(k[0], x) for x in man[k].get("refs") or [] if not x.startswith("commission")]
    incontext = {r["round"] for r in need.values() if any(x.startswith("commission") for x in r.get("refs") or [])}
    for k, r in man.items():
        if r["round"] in incontext and k not in need:
            need[k] = r
            todo += [(k[0], x) for x in r.get("refs") or [] if not x.startswith("commission")]
    while todo:   # refs of the added round-mates
        k = todo.pop()
        if k not in need:
            need[k] = man[k]
            todo += [(k[0], x) for x in man[k].get("refs") or [] if not x.startswith("commission")]
    done, out = set(), []

    def visit(k):
        if k in done:
            return
        done.add(k)
        for x in need[k].get("refs") or []:
            if not x.startswith("commission"):
                visit((k[0], x))
        r, nb = need[k], nb_row(k[0], need[k]["file"], ex)
        if nb["prompt"] != r["prompt"]:
            raise ValueError(f"{k}: the nb-log prompt and the manifest prompt differ")
        out.append({"studio": k[0], "round": r["round"], "file": r["file"], "prompt": nb["prompt"],
                    "refs": nb["refs"], "aspect": nb.get("aspect"), "size": nb.get("size"),
                    "commission": any(x.startswith("commission") for x in r.get("refs") or []),
                    "a_model": nb.get("model"), "manifest": r})
    for k in sorted(need):
        visit(k)
    return out


def twin(ref, work, commission=None, ex=EX):
    """A's reference path -> B's: a plate under examples/ -> the same name under WORK/studios; commission-1 -> the crop."""
    if pathlib.Path(ref).name.startswith("commission"):
        if not commission:
            raise ValueError("this plate was made in context: pass --commission (the crop of B's matching take)")
        return pathlib.Path(commission)
    rel = pathlib.Path(ref).resolve().relative_to(ex.resolve())
    return pathlib.Path(work) / "studios" / rel


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def replay(rows, work, gen, commission=None, log=print, ex=EX):
    """Draw each row as B: A's prompt, B's twin refs, A's aspect; B's manifest row = A's row, renderer swapped.
    A B plate already on disk is kept (a re-run draws nothing twice). -> [(row, B path, seconds)]."""
    import local_render as lr
    work, done, t0 = pathlib.Path(work), [], time.time()
    for i, r in enumerate(rows, 1):
        out = work / "studios" / f"{r['studio']}-plates" / r["file"]
        refs = [twin(x, work, commission, ex) for x in r["refs"]]
        miss = [str(p) for p in refs if not p.is_file()]
        if miss:
            raise FileNotFoundError(f"{r['file']}: B has no twin yet for {miss} (draw references first)")
        a = nb_row(r["studio"], r["file"], ex)
        if r["prompt"] != a["prompt"]:
            raise AssertionError(f"{r['file']}: the prompt is not A's byte for byte")
        t1, fresh = time.time(), not out.exists()
        if fresh:
            gen(r["prompt"], out, [str(p) for p in refs], aspect=r["aspect"])
            row = {**r["manifest"], "renderer": RENDERER}
            with open(out.parents[1] / "manifest.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
        dt = time.time() - t1
        with open(work / "logs" / "replay.jsonl", "a") as f:
            f.write(json.dumps({"studio": r["studio"], "file": r["file"], "prompt_sha": sha(r["prompt"]),
                                "a_prompt_sha": sha(a["prompt"]), "refs": [str(p) for p in refs],
                                "seed": lr.seed_for(out), "aspect": r["aspect"], "seconds": round(dt, 1),
                                "drawn": fresh}) + "\n")
        el = time.time() - t0
        log(f"{i}/{len(rows)} done {r['studio']}:{r['file']} ({len(refs)} refs, {dt:.0f}s), "
            f"ETA {el / i * (len(rows) - i) / 60:.1f} min")
        done.append((r, out, dt))
    return done


def street_rows(log_path=STREET_LOG):
    row = next(r for r in _rows(log_path) if r["out"] == STREET_OUT)
    if row.get("refs"):
        raise ValueError("A's street had refs: this replay assumes text to image")
    stem = STREET_OUT[:-4]
    return row, [STREET_OUT] + [f"{stem}-s{k}.png" for k in (2, 3, 4)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "run", "street"])
    ap.add_argument("--work", default=str(pathlib.Path.home() / ".cache" / "boson-ab"))
    ap.add_argument("--only", default="plain", help="plain (no commission image), all, or a round id (make-KEY)")
    ap.add_argument("--commission", default="", help="B's crop for an in-context round (commission image 1)")
    a = ap.parse_args()
    work = pathlib.Path(a.work)
    (work / "logs").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "boson"))
    prog = open(work / "logs" / "progress.log", "a")

    def log(*x):
        line = " ".join(map(str, x))
        print(line, flush=True)
        prog.write(time.strftime("%H:%M:%S ") + line + "\n")
        prog.flush()

    if a.cmd == "plan":
        rows = plan(scene_pieces())
        (work / "plan.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        log(f"plan: {len(rows)} plates, {sum(r['commission'] for r in rows)} in context -> {work / 'plan.jsonl'}")
        return
    import local_render as lr
    if a.cmd == "street":
        row, names = street_rows()
        t0 = time.time()
        for i, n in enumerate(names, 1):
            out = work / "street" / n
            if not out.exists():
                lr.generate(row["prompt"], out, [], aspect=row.get("aspect") or "16:9")
            log(f"street {i}/{len(names)} done {n} seed {lr.seed_for(out)}, "
                f"ETA {(time.time() - t0) / i * (len(names) - i) / 60:.1f} min")
        return
    rows = _rows(work / "plan.jsonl")
    if a.only == "plain":
        rows = [r for r in rows if not r["commission"]]
    elif a.only != "all":
        rows = [r for r in rows if r["round"] == a.only]
    log(f"replay {a.only}: {len(rows)} plates")
    replay(rows, work, lr.generate, a.commission or None, log=log)


if __name__ == "__main__":
    main()
