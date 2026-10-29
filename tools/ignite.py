#!/usr/bin/env python3
"""Ignition (2026-10-24): one blind round that starts a studio's feedback from zero, before the owner has a single
reference or dot. Every judgment a model makes comes from its weights; the Japan Theorem's measured case is country
preference (a model asked for a favourite country says Japan; told to avoid the obvious, it says the Netherlands).
So the round shows the owner where the weights would land, and what declared noise offers instead, on one brief:

  default        the genre named plainly, nothing else: the image model's own pick (resolved by WEIGHTS)
  anti-default   the writer names that default and writes a prompt that avoids it (WEIGHTS, told to dodge)
  seed-N         the same plain brief + references a seed drew from the pool (NOISE, tools/seed.py's pick)

The cards are blind (shuffled, unlabelled) so a rung's name cannot sway a dot. `read` reveals which rung each card
was, and the green seeds' pictures become the studio's starting references, with IGNITION.json beside them for the
forge to commit. A green default is an honest answer, not a failure: it is the owner's call, now on record.

  python3 tools/ignite.py cars run --field "Car photography" [--seeds 3] [--n 2] [--k 6] [--backend comfy-api]
  python3 tools/ignite.py cars dots [--port 8773]       # dot blind, write the verdict, Ctrl-C when done
  python3 tools/ignite.py cars read                     # reveal, then the forge command
  python3 tools/ignite.py cars fan                      # or the next blind round, grown from the greens

Ignition fans out (operator 10-24): a round's green seeds get fresh draws on the same lanes, untried lane pairs fill
the rest, the default stays as the control, and every verdict so far rides verbatim on every prompt. Fan until the
owner wants to start; then forge from the round whose greens they like.

Pool = refs-private/candidates/FIELD (as seed.py). State = $BOSON_HOME/ignite/FIELD-iN/ (IGNITION.json, plates,
deck/ for the grid; the key stays outside deck/, which the grid serves). Rerun-safe: nothing on disk is bought twice.
"""
import argparse, json, pathlib, random, secrets, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
sys.path.insert(0, str(ROOT / "tools"))
import studio as st, nanobanana as nbn, writer as wr, seed  # noqa: E402

BASE = st.HOME / "ignite"
ENGINE = pathlib.Path("~/feedback-engine/engine.py").expanduser()
SIZE = {"1:1", "3:2", "2:3", "4:5", "16:9"}
IMAGE_USD = 0.06
VERDICT = "verdict"
WEIGHTS = "WEIGHTS (the image model's own pick: the genre named, nothing else)"
DODGE = "WEIGHTS, told to dodge (the writer named the default and wrote a prompt that avoids it)"


def log(*a):
    print(*a, flush=True)


def brief(genre):
    return f"{genre.strip().rstrip('.')}."


def seed_brief(genre):
    """Anchored (operator 10-24: "ignition seeds need some sort of real basis"): each card re-shoots one real
    photograph, so the place is real and only the camera and the light are new; the seed's other pictures set the
    look. A seed that only set a mood let the model invent the buildings (architecture-i200)."""
    return (f"{brief(genre)} The first reference picture is a real place: re-photograph that exact place, keeping its "
            "buildings, street, vehicles and layout as they are. Change only the camera position, lens, light and time "
            "of day, toward the look of the other reference pictures. A real photograph, not an illustration.")


def anchors(picks, n):
    """The real photograph each draw re-shoots: one per draw, in pick order."""
    return [picks[d % len(picks)] for d in range(n)]


def lane_seeds(field, number, n):
    """n seeds whose lane pairs all differ (as far as the pool allows), derived from the ignition number."""
    _, pics, lane_of = seed.pool(field)
    lanes = len(set(lane_of.values()))
    pairs, out = set(), []
    for i in range(400):
        s = random.Random(f"boson-ignite:{field}:{number}:{i}").randrange(10000)
        _, rec = seed.pick(field, s, k=1)
        key = tuple(rec["lanes"])
        if key in pairs and len(pairs) < lanes * (lanes - 1) // 2:
            continue
        pairs.add(key)
        out.append(s)
        if len(out) == n:
            break
    return out


def anti_default(genre):
    """One writer call: name the default picture for the plain brief, then a prompt that avoids it."""
    snap = pathlib.Path(tempfile.mkdtemp(prefix="boson-ignite-"))
    prompt = (f"An image model is given only this prompt: \"{brief(genre)}\". Write ANSWER.json in the working folder "
              "with two keys: \"default\": one sentence naming the picture it makes by default, and \"prompt\": one "
              f"image prompt (under 60 words) for a {genre.lower()} picture that avoids that default. Write nothing else.")
    work, meta = wr.run(snap, prompt, f"ignite-{int(time.time())}")
    try:
        ans = json.loads((work / "ANSWER.json").read_text())
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(snap, ignore_errors=True)
    return {"default_named": " ".join(ans["default"].split()), "prompt": " ".join(ans["prompt"].split())}, meta


class Ignition:
    def __init__(self, field, number=None):
        self.field = field
        have = [json.loads(p.read_text()) for p in BASE.glob(f"{field}-i*/IGNITION.json")]
        if number is None and have:             # the latest one, unless asked for another
            number = max(have, key=lambda r: r.get("created", 0))["number"]
        self.number = number if number is not None else secrets.randbelow(10000)
        self.dir = BASE / f"{field}-i{self.number}"
        self.path = self.dir / "IGNITION.json"

    def rec(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def save(self, rec):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")

    def spend(self, row):
        with (self.dir / "spend.jsonl").open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **row}) + "\n")

    # ---- plan -----------------------------------------------------------------------------------------------
    def plan(self, genre, n_seeds, n, k, aspect, backend, write=anti_default):
        rec = self.rec()
        if rec:
            return rec
        if not genre.strip():
            sys.exit("run needs --field: the genre, named plainly (\"Car photography\")")
        rungs = [{"rung": "default", "prompt": brief(genre), "refs": [], "resolved_by": WEIGHTS}]
        log("1/3 the anti-default: one writer call")
        t = time.time()
        ans, meta = write(genre)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.spend({"step": "anti-default", "writer": meta.get("writer"), "usd": meta.get("cost_usd") or 0,
                    "s": round(time.time() - t)})
        rungs.append({"rung": "anti-default", "prompt": ans["prompt"], "default_named": ans["default_named"],
                      "refs": [], "resolved_by": DODGE})
        for s in lane_seeds(self.field, self.number, n_seeds):
            _, pk = seed.pick(self.field, s, k=k)
            rungs.append({"rung": f"seed-{s}", "seed": s, "lanes": pk["lanes"], "prompt": seed_brief(genre),
                          "refs": pk["picks"], "anchors": anchors(pk["picks"], n), "resolved_by": pk["resolved_by"]})
        return self.finish(rungs, genre, n, k, aspect, backend, {"round": 1})

    def finish(self, rungs, genre, n, k, aspect, backend, extra):
        cards = [(r["rung"], d) for r in rungs for d in range(n)]
        random.Random(f"boson-ignite-deck:{self.field}:{self.number}").shuffle(cards)
        _, pics, _ = seed.pool(self.field)
        rec = {"number": self.number, "field": self.field, "genre": genre.strip(), "made": time.strftime("%Y-%m-%d"),
               "pool": f"refs-private/candidates/{self.field}", "pool_size": len(pics), "n": n, "k": k,
               "aspect": aspect, "backend": backend, "renderer": nbn.renderer(backend, nbn.MODEL), "rungs": rungs,
               "blind": {f"card-{i + 1:02d}": {"rung": r, "draw": d} for i, (r, d) in enumerate(cards)},
               "created": time.time(), **extra}
        self.save(rec)
        return rec

    # ---- fan: the next blind round, grown from the last one's greens ----------------------------------------
    def fan(self, parent, n_seeds=3):
        """Round k+1 of the same ignition. Each green seed's lanes get a fresh draw (more like it, other pictures),
        the rest goes to lane pairs no round has tried yet, and the default stays as the control: the weights' pick,
        now with the owner's words. Every verdict so far rides verbatim on every prompt (USER, never reworded)."""
        rec = self.rec()
        if rec:
            return rec
        if "verdict" not in parent:
            sys.exit(f"round {parent.get('round', 1)} is not read yet: python3 tools/ignite.py {self.field} read")
        said = parent.get("said", []) + ([parent["verdict"]] if parent["verdict"] else [])
        clause = (" The owner said of the earlier rounds: " + " / ".join(f'"{v}"' for v in said) + ".") if said else ""
        genre, k = parent["genre"], parent["k"]
        rungs = [{"rung": "default", "prompt": brief(genre) + clause, "refs": [],
                  "resolved_by": WEIGHTS + "; with the owner's words" * bool(clause)}]
        used = set(parent.get("seeds_used", [])) | {r["seed"] for r in parent["rungs"] if r.get("seed") is not None}
        tried = {tuple(x) for x in parent.get("lanes_tried", [])} | {tuple(r["lanes"]) for r in parent["rungs"] if r.get("lanes")}
        greens = sorted((r for r in parent["rungs"] if r.get("seed") is not None and r["dots"]["green"]),
                        key=lambda r: (-r["dots"]["green"], r["dots"]["red"]))
        _, _, lane_of = seed.pool(self.field)
        lanes = len(set(lane_of.values()))
        want = [(tuple(g["lanes"]), g["rung"]) for g in greens][:n_seeds - 1]
        rng = random.Random(f"boson-ignite-fan:{self.field}:{self.number}")
        for i in range(4000):
            if len(rungs) - 1 == n_seeds:
                break
            s = rng.randrange(10000)
            if s in used:
                continue
            _, pk = seed.pick(self.field, s, k=k)
            pair = tuple(pk["lanes"])
            if want and pair == want[0][0]:
                why = f"NOISE near {want.pop(0)[1]} (the owner's green kept its lanes; the seed drew new pictures)"
            elif not want and (pair not in tried or len(tried) >= lanes * (lanes - 1) // 2):
                why = pk["resolved_by"]
            else:
                continue
            used.add(s)
            tried.add(pair)
            rungs.append({"rung": f"seed-{s}", "seed": s, "lanes": pk["lanes"], "prompt": seed_brief(genre) + clause,
                          "refs": pk["picks"], "anchors": anchors(pk["picks"], parent["n"]), "resolved_by": why})
        return self.finish(rungs, genre, parent["n"], k, parent["aspect"], parent["backend"],
                           {"round": parent.get("round", 1) + 1, "parent": parent["number"], "said": said,
                            "seeds_used": sorted(used), "lanes_tried": sorted(map(list, tried))})

    # ---- render ---------------------------------------------------------------------------------------------
    def plate(self, rung, draw):
        return self.dir / "plates" / f"{rung}__d{draw}.png"

    def render(self, rec, gen=None):
        backend = rec["backend"]
        gen = gen or ({"antigravity": nbn.generate_agy, "comfy-api": nbn.generate_comfy, "api": nbn.generate}.get(backend)
                      or nbn._local().generate)
        src = ROOT / rec["pool"]
        jobs = [(r, d) for r in rec["rungs"] for d in range(rec["n"]) if not self.plate(r["rung"], d).exists()]
        if not jobs:
            return 0
        log(f"2/3 render: {len(jobs)} pictures on {backend} (~${len(jobs) * IMAGE_USD:.2f} at 1K if billed)")
        (self.dir / "plates").mkdir(parents=True, exist_ok=True)
        t = time.time()

        def one(j):
            r, d = j
            refs = r["refs"]
            if r.get("anchors"):                  # the anchor goes first: the prompt names it as the place
                refs = [r["anchors"][d]] + [p for p in refs if p != r["anchors"][d]]
            gen(r["prompt"], self.plate(r["rung"], d), [src / p for p in refs], nbn.MODEL, rec["aspect"], "1K")
            return j
        errors = []
        with ThreadPoolExecutor(5) as ex:
            for f in [ex.submit(one, j) for j in jobs]:
                try:
                    f.result()
                except Exception as e:          # a failed picture never costs the ones that rendered
                    errors.append(e)
        done = len(jobs) - len(errors)
        self.spend({"step": "render", "images": done, "backend": backend, "est": True, "s": round(time.time() - t),
                    "usd": 0 if backend in ("antigravity", "local") else round(done * IMAGE_USD, 2)})
        if errors:
            sys.exit(f"{len(errors)} of {len(jobs)} pictures did not render (the rest are kept; rerun): {errors[0]}")
        return done

    # ---- the blind deck -------------------------------------------------------------------------------------
    def deck(self, rec):
        from PIL import Image
        sys.path.insert(0, str(ROOT / "tools"))
        from loop import placard
        d = self.dir / "deck"
        (d / "cards").mkdir(parents=True, exist_ok=True)
        board = f"ignition {rec['number']} · round {rec.get('round', 1)} · {rec['genre']}"
        cards = []
        for cid, b in rec["blind"].items():
            dst = d / "cards" / f"{cid}.jpg"
            if not dst.exists():
                im = Image.open(self.plate(b["rung"], b["draw"])).convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(dst, quality=88)
            cards.append({"id": cid, "board": board, "row": "pieces", "col": cid[-2:], "caption": f"piece {cid[-2:]}",
                          "image": f"cards/{dst.name}", "detail": "Blind: what made this picture is shown after the round.",
                          "gold": None})
        placard(d / "cards" / "verdict.jpg", 0)
        cards.append({"id": VERDICT, "board": board, "row": "your verdict", "col": "verdict", "caption": "ROUND VERDICT",
                      "image": "cards/verdict.jpg", "gold": None,
                      "detail": "One or two sentences in the note box: what you want more of, what you never want."})
        deck = {"config": {"title": f"BOSON · IGNITION · ROUND {rec.get('round', 1)} · {rec['genre'].upper()}",
                           "question": "No studio yet. Green = I want work like this. Red = not this. Then the verdict.",
                           "yes": {"label": "GREEN DOT"}, "no": {"label": "RED DOT"},
                           "tags": ["not its genre", "AI look", "bland", "cliche", "cluttered"],
                           "fields": {"meta": "row", "top": "caption", "body": "detail", "image": "image"},
                           "field_labels": {"top": "PIECE", "body": "SOURCE"}},
                "cards": cards}
        (d / "DECK.json").write_text(json.dumps(deck, indent=1, ensure_ascii=False) + "\n")
        return d / "DECK.json"

    # ---- read: reveal, then the starting references ---------------------------------------------------------
    def read(self, rec, labels=None, notes=None):
        if labels is None:
            sys.path.insert(0, str(ENGINE.parent))
            import engine
            p = self.dir / "deck" / "DECK.labels.jsonl"
            labels = {k: v.get("label") for k, v in engine.current_labels(p).items()}
            notes = engine.current_notes(p)
        notes = notes or {}
        verdict = " ".join(notes.get(VERDICT, "").split())
        tally = {r["rung"]: {"green": 0, "red": 0} for r in rec["rungs"]}
        for cid, b in rec["blind"].items():
            got = labels.get(cid)
            if got in (0, 1):
                tally[b["rung"]]["green" if got == 1 else "red"] += 1
        if not any(t["green"] + t["red"] for t in tally.values()):
            sys.exit(f"no dots yet: python3 tools/ignite.py {self.field} dots")
        for r in rec["rungs"]:
            r["dots"] = tally[r["rung"]]
        rec["verdict"] = verdict
        rec["read"] = time.strftime("%Y-%m-%d")
        greens = [r for r in rec["rungs"] if r.get("seed") is not None and r["dots"]["green"]]
        greens.sort(key=lambda r: (-r["dots"]["green"], r["dots"]["red"]))
        picks = sorted({p for r in greens for p in r["refs"]})
        rec["start"] = {"from": [r["rung"] for r in greens], "refs": picks,
                        "resolved_by": "USER (the owner's blind dots chose which noise to keep)" if picks else None}
        self.save(rec)
        out = None
        if picks:
            out = ROOT / "refs-private" / f"{self.field}-i{self.number}"
            out.mkdir(parents=True, exist_ok=True)
            src = ROOT / rec["pool"]
            for p in picks:
                shutil.copy2(src / p, out / p)
            if (src / "urls.txt").exists():
                keep = [l for l in (src / "urls.txt").read_text().splitlines() if l.split(" ", 1)[0] in picks]
                (out / "urls.txt").write_text("".join(l + "\n" for l in keep))
            shutil.copy2(self.path, out / "IGNITION.json")
        return rec, out


def report(rec, out):
    log(f"ignition {rec['number']} · {rec['genre']} · revealed")
    for r in rec["rungs"]:
        d = r["dots"]
        what = r.get("default_named") and f"  (named default: {r['default_named']})" or ""
        lanes = f"  lanes {', '.join(r['lanes'])}" if r.get("lanes") else ""
        log(f"  {r['rung']:<14} {d['green']} green  {d['red']} red{lanes}{what}")
    log(f"  verdict: {rec['verdict'] or '(none written)'}")
    if out:
        sentence = seed.sentence(rec["genre"], sorted({l for r in rec["rungs"] if r["rung"] in rec["start"]["from"]
                                                       for l in r["lanes"]}))
        if rec["verdict"]:
            sentence = f"{sentence[:-1]}; the owner's first verdict: {rec['verdict']}"
        log(f"{len(rec['start']['refs'])} starting references -> {out}\nnext: python3 tools/loop.py {out.name} forge "
            f"--field \"{rec['genre']}\" --sentence \"{sentence}\"")
        log(f"or fan out another blind round from these greens: python3 tools/ignite.py {rec['field']} fan")
    else:
        log(f"no seed got a green: the record stands (IGNITION.json keeps the dots), and a fresh roll is how references come: "
            f"python3 tools/ignite.py {rec['field']} run --field \"{rec['genre']}\" --new")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("field", help="the pool: refs-private/candidates/FIELD")
    ap.add_argument("step", choices=["run", "fan", "dots", "read", "show"])
    ap.add_argument("--field", dest="genre", default="", help="run: the genre, named plainly (\"Car photography\")")
    ap.add_argument("--number", type=int, help="the ignition number (default: the latest; run --new rolls one)")
    ap.add_argument("--new", action="store_true", help="run: a fresh ignition number")
    ap.add_argument("--seeds", type=int, default=3, help="seeded rungs (default 3)")
    ap.add_argument("--n", type=int, default=2, help="pictures per rung (default 2)")
    ap.add_argument("--k", type=int, default=6, help="references per seed (default 6)")
    ap.add_argument("--aspect", default="3:2", choices=sorted(SIZE))
    ap.add_argument("--backend", default="comfy-api", choices=nbn.BACKENDS)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8773)
    a = ap.parse_args()
    ig = Ignition(a.field, secrets.randbelow(10000) if a.new else a.number)
    if a.step == "run":
        rec = ig.plan(a.genre, a.seeds, a.n, a.k, a.aspect, a.backend)
        ig.render(rec)
        deck = ig.deck(rec)
        log(f"3/3 blind deck: {len(rec['blind'])} cards -> {deck}\nnext: python3 tools/ignite.py {a.field} dots")
    elif a.step == "fan":
        parent = ig.rec() or sys.exit(f"no ignition yet: python3 tools/ignite.py {a.field} run --field \"...\"")
        if "verdict" not in parent:
            report(*ig.read(parent))
            parent = ig.rec()
        child = Ignition(a.field, secrets.randbelow(10000))
        rec = child.fan(parent, a.seeds)
        child.render(rec)
        deck = child.deck(rec)
        log(f"round {rec['round']}: {len(rec['blind'])} blind cards -> {deck}\nnext: python3 tools/ignite.py {a.field} dots")
    elif a.step == "dots":
        rec = ig.rec() or sys.exit(f"no ignition yet: python3 tools/ignite.py {a.field} run --field \"...\"")
        deck = ig.deck(rec)
        log(f"open http://{a.host}:{a.port}/ on the remote desktop: left-click green, right-click red, the verdict "
            f"under the last card. Ctrl-C when done, then python3 tools/ignite.py {a.field} read")
        try:
            subprocess.run([sys.executable, str(ENGINE), str(deck), "--matrix", "--host", a.host, "--port", str(a.port)])
        except KeyboardInterrupt:
            pass
    elif a.step == "read":
        rec = ig.rec() or sys.exit("no ignition yet")
        report(*ig.read(rec))
    else:
        log(json.dumps(ig.rec(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
