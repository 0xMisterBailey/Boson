#!/usr/bin/env python3
"""A taste seed (round 41): a number picks a studio's starting references from a candidate pool, the way a Midjourney
--sref number picks a style. The pick is declared noise (Japan Theorem v1.3, D9: NOISE resolves without grounds, and
says so); what makes it a taste is what follows: the forge reads it, the owner dots the first round, every verdict
binds the next (D5). The same pool + seed always gives the same pictures. A script picks, never a model: asked to
"be random" or "avoid the cliche", a model falls into a shared anti-mode (Exp. 3: Netherlands 12/20).

  python3 tools/seed.py roll cars --field "Car photography" [--seed 4471] [--k 12] [--lanes 2]
  python3 tools/seed.py show cars --seed 4471                          # the picks, no copy

Pool = refs-private/candidates/FIELD/ (pictures, urls.txt, why.tsv "file<TAB>lane<TAB>why"; tools/curate.py's shape).
The seed first draws LANES lanes (a coherent starting point, not a scatter of the whole pool), then K pictures from
them. No --seed = a fresh random one, printed. The forge sentence is assembled here, never written by an agent: the
field named plainly plus the drawn lanes' names (memory: seed sentences name the genre plainly). Then forge with the
printed command; SEED.json is committed into the studio.
"""
import argparse, hashlib, json, pathlib, random, secrets, shutil, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "refs-private"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pool(field):
    src = PRIVATE / "candidates" / field
    if not src.is_dir():
        sys.exit(f"{src}: no candidate pool (agents gather into it, round 40)")
    pics = sorted(p.name for p in src.iterdir() if p.suffix.lower() in EXTS)
    lanes = {}
    if (src / "why.tsv").exists():
        for line in (src / "why.tsv").read_text().splitlines():
            f = line.split("\t")
            if len(f) >= 2 and f[0] in pics:
                lanes[f[0]] = f[1].strip() or "unsorted"
    return src, pics, {p: lanes.get(p, "unsorted") for p in pics}


def sentence(genre, lanes):
    return f"{genre.strip().rstrip('.')}, from the {' and '.join(l.replace('-', ' ') for l in lanes)} references this seed drew."


def pick(field, seed, k=12, n_lanes=2):
    src, pics, lane_of = pool(field)
    if not pics:
        sys.exit(f"{src}: no pictures")
    rng = random.Random(f"boson-seed:{field}:{seed}")       # str seeds hash stably across runs and Python versions
    by_lane = {}
    for p in pics:
        by_lane.setdefault(lane_of[p], []).append(p)
    lanes = sorted(by_lane)
    chosen = rng.sample(lanes, min(n_lanes, len(lanes)))
    cands = sorted(p for l in chosen for p in by_lane[l])
    picks = sorted(rng.sample(cands, min(k, len(cands))))
    digest = hashlib.sha256("\n".join(pics).encode()).hexdigest()[:12]
    return src, {"seed": seed, "field": field, "pool": f"refs-private/candidates/{field}", "pool_sha": digest,
                 "pool_size": len(pics), "k": k, "lanes": sorted(chosen), "picks": picks,
                 "resolved_by": "NOISE (a seed picked these references; the owner's dots and verdicts decide after)"}


def roll(field, seed, k, n_lanes, genre=""):
    src, rec = pick(field, seed, k, n_lanes)
    if genre:
        rec["genre"], rec["sentence"] = genre, sentence(genre, rec["lanes"])
    dst = PRIVATE / f"{field}-s{seed}"
    if (dst / "SEED.json").exists():
        old = json.loads((dst / "SEED.json").read_text())
        if old["picks"] != rec["picks"]:
            sys.exit(f"{dst}: rolled before from a different pool (pool_sha {old['pool_sha']} vs {rec['pool_sha']}); "
                     "move it aside to re-roll")
        print(f"{dst}: already rolled (same picks)", flush=True)
        return dst, rec
    dst.mkdir(parents=True, exist_ok=True)
    for p in rec["picks"]:
        shutil.copy2(src / p, dst / p)
    urls = src / "urls.txt"
    if urls.exists():
        keep = [l for l in urls.read_text().splitlines() if l.split(" ", 1)[0] in rec["picks"]]
        (dst / "urls.txt").write_text("".join(l + "\n" for l in keep))
    (dst / "SEED.json").write_text(json.dumps(rec, indent=1) + "\n")
    return dst, rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["roll", "show"])
    ap.add_argument("field", help="the pool: refs-private/candidates/FIELD")
    ap.add_argument("--seed", type=int, help="the taste seed (default: a fresh random one, printed)")
    ap.add_argument("--k", type=int, default=12, help="pictures per seed (default 12)")
    ap.add_argument("--lanes", type=int, default=2, help="lanes the seed draws from first (default 2)")
    ap.add_argument("--field", dest="genre", default="", help="roll: the genre, named plainly (\"Car photography\")")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else secrets.randbelow(10000)
    if a.step == "show":
        _, rec = pick(a.field, seed, a.k, a.lanes)
        print(json.dumps(rec, indent=1))
        return
    if not a.genre.strip():
        sys.exit("roll needs --field: the genre, named plainly (it starts the forge sentence)")
    dst, rec = roll(a.field, seed, a.k, a.lanes, a.genre)
    print(f"seed {seed}: {len(rec['picks'])} of {rec['pool_size']} from lanes {', '.join(rec['lanes'])} -> {dst}\n"
          f"next: python3 tools/loop.py {dst.name} forge --field \"{a.genre}\" --sentence \"{rec['sentence']}\"",
          flush=True)


if __name__ == "__main__":
    main()
