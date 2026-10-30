#!/usr/bin/env python3
"""The real-refs loop (round 39): a folder of real references -> a studio -> a make -> dots on the grid -> the next make,
run by the owner from a terminal, no agent. Runbook: docs/REAL-REFS.md.

  python3 tools/loop.py NAME forge --field "Fashion photography" --sentence "..." [--aspect 4:5] [--agy]
  python3 tools/loop.py NAME make --idea "..." [--frame ""] [--n 6]
  python3 tools/loop.py NAME dots [--port 8772]          # the grid; dot, write the verdict, Ctrl-C when done
  python3 tools/loop.py NAME dot --green 1,3 --red 2 --verdict "..."   # the same, headless (a script or an agent)
  python3 tools/loop.py NAME next [--n 6]                # greens -> pins, verdict -> the next make
  python3 tools/loop.py NAME status | check

NAME = a folder of pictures in refs-private/ (gitignored). The studio is examples/NAME-real (--studio, --root), so it
stands beside the studio forged from AI mockups. Every step mirrors a node (Forge Studio, Make, Edit House) and is
resume-safe: what is on disk or in the studio's git is never bought twice. The studio repo commits refs.jsonl (urls +
descriptions) and never the pictures; `check` proves it. Spend lands in $BOSON_HOME/loop/<studio>/spend.jsonl.
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))   # the modules, not the package (its __init__ needs ComfyUI), as the tests do
sys.path.insert(0, str(ROOT / "tools"))
import studio as st, nanobanana as nbn, grid as gr, scene as sc  # noqa: E402
import forge_refs  # noqa: E402

ENGINE = pathlib.Path(os.environ.get("BOSON_ENGINE") or ROOT / "tools" / "feedback_engine" / "engine.py").expanduser()
TEMPLATE = ROOT / "tools" / "forge-template"
SIZE = {"1:1": (1024, 1024), "3:2": (1248, 832), "2:3": (832, 1248), "4:5": (896, 1120), "16:9": (1376, 768)}
IMAGE_USD = 0.06         # one Nano Banana 2.1 picture at 1K (round 1: 100 mockups, $6.00)
DESCRIBE_USD = 0.01      # one Gemini vision description (estimate; the API bills tokens)
MAX_REFS = 10            # as the Make node: images per make call
LOCAL_PHOTOS = 2         # local rounds: the studio's real photos each piece is drawn from, in place of pins (local_refs)
OPEN = ("public domain", "cc0", "cc by ")   # licences a photo may carry to be drawn from (no SA, NC, ND)
VERDICT = "verdict"      # the deck card whose note is the round verdict


def log(*a):
    print(*a, flush=True)


class Loop:
    def __init__(self, name, studio=None, root=None, refs=None):
        self.name = name
        self.studio = studio or f"{name}-real"
        self.root = pathlib.Path(root).expanduser() if root else ROOT / "examples"
        self.refs = pathlib.Path(refs).expanduser() if refs else ROOT / "refs-private" / name
        self.repo = self.root / self.studio
        self.home = st.HOME / "loop" / self.studio
        self.fin = st.HOME / "forge-in" / self.studio / "refs"
        if root:   # a studio outside examples/: the registry must find it, and the studios its pins name, in front
            os.environ["BOSON_STUDIOS"] = os.pathsep.join(   # of the usual roots (a clone pins its source's pieces)
                [str(self.root), os.environ.get("BOSON_STUDIOS") or os.pathsep.join(map(str, st.ROOTS))])

    # ---- records -------------------------------------------------------------------------------------------
    def spend(self, row):
        self.home.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **row}
        with (self.home / "spend.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def spent(self):
        p = self.home / "spend.jsonl"
        return sum(json.loads(l).get("usd", 0) or 0 for l in p.read_text().splitlines() if l.strip()) if p.exists() else 0

    def load(self, ref="main"):
        return st.load(self.repo, ref)

    def rows(self):
        """LOOP.jsonl at main: one {"make": ...} row per round, then its {"verdict": ...} row once dotted."""
        p = self.repo / "LOOP.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def rounds(self):
        out = {}
        for r in self.rows():
            out.setdefault(r["round"], {}).update(r)
        return [out[k] for k in sorted(out)]

    def record(self, row, msg):
        with (self.repo / "LOOP.jsonl").open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return st.commit(self.repo, "main", [self.repo / "LOOP.jsonl"], msg)

    # ---- forge ---------------------------------------------------------------------------------------------
    def forge(self, field, sentence, owner, aspect, size, agy=False, port=None):
        if (self.repo / ".git").exists():
            if not st.git(self.repo, "tag", "--list", "r00"):   # a failed forge leaves only its inputs: set aside, redo
                aside = self.repo.with_name(f"{self.repo.name}.unfinished-{time.strftime('%Y%m%d-%H%M%S')}")
                self.repo.rename(aside)
                log(f"a forge that never finished (no r00) was moved aside to {aside}; forging again")
                return self.forge(field, sentence, owner, aspect, size, agy, port)
            log(f"{self.studio} is forged (r00 {st.git(self.repo, 'rev-parse', '--short=8', 'r00')}): next, "
                f"python3 tools/loop.py {self.name} make --idea \"...\"")
            return self.load()
        if not (field.strip() and sentence.strip()):
            sys.exit("waiting for --field (the genre, named plainly) and --sentence (what the studio's work must be)")
        if not (self.fin / "refs.jsonl").exists():
            pics = [p for p in sorted(self.refs.iterdir()) if p.suffix.lower() in forge_refs.EXT] if self.refs.is_dir() else []
            if len(pics) < 3:
                sys.exit(f"{self.refs}: {len(pics)} pictures; put the references there first (20-40 is the aim)")
            rows = forge_refs.build(self.fin, [self.refs], why=sentence, private=True)
            log(f"1/3 refs: {len(rows)} pictures, {sum(1 for r in rows if r['url'])} with a source url -> {self.fin}")
        rows = [json.loads(l) for l in (self.fin / "refs.jsonl").read_text().splitlines() if l.strip()]
        todo = sum(1 for r in rows if not r.get("vlm"))
        if todo and os.environ.get("BOSON_WRITER_BASE_URL") and not port:   # a local run never falls back to Gemini
            sys.exit(f"{todo} pictures have no description and the writer is local: pass --describe-port (a local "
                     "vision server) or describe them first (tools/describe_refs.py --port)")
        if todo:
            log(f"2/3 describe: {todo} pictures, one vision call each "
                f"({f'local VLM :{port}' if port else 'Antigravity' if agy else 'Gemini API'})")
            t = time.time()
            cmd = [sys.executable, "-u", str(ROOT / "tools" / "describe_refs.py"), str(self.fin), "--field", field]
            p = subprocess.run(cmd + (["--port", str(port)] if port else ["--agy"] if agy else []))
            done = sum(1 for l in (self.fin / "refs.jsonl").read_text().splitlines() if json.loads(l).get("vlm"))
            self.spend({"step": "describe", "calls": done - (len(rows) - todo), "usd": 0 if agy or port else
                        round((done - (len(rows) - todo)) * DESCRIBE_USD, 3), "est": True, "s": round(time.time() - t)})
            if p.returncode:
                sys.exit("describe stopped (re-run the same command: it resumes where it stopped)")
        log("3/3 forge: one writer call (Opus via claude -p, a few minutes)")
        render = json.loads((TEMPLATE / "render.json").read_text())
        w, h = SIZE[aspect]
        render.update(aspect=aspect, size=size, width=w, height=h)
        t = time.time()
        s, meta = st.forge(self.repo, owner, field, sentence, self.fin, (TEMPLATE / "instruments.yaml").read_text(),
                           render=render)
        self.spend({"step": "forge", "writer": meta.get("writer"), "usd": meta.get("cost_usd") or 0,
                    "s": round(time.time() - t)})
        leaked = self.leaks(s["repo"])
        if leaked:
            sys.exit(f"STOP: the studio committed pictures {leaked[:3]}: do not bundle or push it")
        if (self.refs / "SEED.json").exists():   # a seeded studio (tools/seed.py) keeps its seed in its history
            shutil.copy2(self.refs / "SEED.json", self.repo / "SEED.json")
            rec = json.loads((self.repo / "SEED.json").read_text())
            st.commit(self.repo, "main", [self.repo / "SEED.json"], f"seed {rec['seed']}: the starting refs were noise")
        if (self.refs / "IGNITION.json").exists():   # an ignited studio (tools/ignite.py) keeps its blind first round
            shutil.copy2(self.refs / "IGNITION.json", self.repo / "IGNITION.json")
            rec = json.loads((self.repo / "IGNITION.json").read_text())
            st.commit(self.repo, "main", [self.repo / "IGNITION.json"],
                      f"ignition {rec['number']}: the owner's blind dots kept {', '.join(rec['start']['from'])}")
        log(f"forged {self.studio} @ {s['sha'][:8]} (${meta.get('cost_usd')}): {self.repo}/STUDIO.md. Next: "
            f"python3 tools/loop.py {self.name} make --idea \"...\"")
        return s

    # ---- make ----------------------------------------------------------------------------------------------
    def make(self, frame, idea, n, base_idea=None, backend="api", round_no=None):
        """Mirrors the Make node: one writer call + n pictures, refs = the house pictures and pins; then the round
        is committed to LOOP.jsonl. A round whose make is on record is shown, not bought again."""
        s = self.load()
        rs = self.rounds()
        if round_no is None and rs and "verdict" not in rs[-1]:     # a re-run: the round is made, it waits for dots
            log(f"round {rs[-1]['round']} is made ({len(rs[-1]['pieces'])} pieces) and waits for its dots: "
                f"python3 tools/loop.py {self.name} dots")
            return rs[-1]
        round_no = round_no or len(rs) + 1
        have = next((r for r in rs if r["round"] == round_no), None)
        if have:
            return have
        if not (idea.strip() or frame.strip()):
            sys.exit("waiting for --idea (what to make, in your words)")
        key = st.make_key(s, frame, idea, n)
        pdir, rid = gr.plates_dir(self.repo), f"make-{key}"
        got = nbn.stored_round(pdir, rid)
        if not got:
            t = time.time()
            log(f"round {round_no}: writer call (minutes), then {n} pictures")
            specs, meta = st.make(s, frame, idea, n, key=key)
            self.spend({"step": f"make-write r{round_no}", "key": key, "usd": meta.get("cost_usd") or 0,
                        "s": round(time.time() - t)})
            house = st.taste(s)
            refs = [sc.piece(x) for x in house["pictures"] + house["pins"]]
            fed = self.local_refs(round_no, len(specs)) if backend == "local" else None
            t = time.time()
            try:
                got = nbn.render_round(s, pdir, rid, specs, st.render_cfg(s), 1, fed or refs[:MAX_REFS] or None,
                                       backend=backend)
            finally:
                fresh = len(nbn.stored_round(pdir, rid))
                self.spend({"step": f"make-render r{round_no}", "key": key, "images": fresh,
                            "refs": len(fed(0)) if fed else len(refs[:MAX_REFS]),
                            "usd": 0 if backend in ("antigravity", "local") else round(fresh * IMAGE_USD, 2), "est": True,
                            "s": round(time.time() - t),
                            **({"photos": sorted({x.name for i in range(n) for x in fed(i)})} if fed else {})})
        pieces = [f"{self.studio}@{r['studio_sha'][:8]}:{r['file']}" for r in got]
        row = {"round": round_no, "make": key, "studio_sha": s["sha"][:8], "frame": frame.strip(),
               "idea": " ".join(idea.split()) if base_idea is None else idea.strip(),
               "base_idea": " ".join((base_idea if base_idea is not None else idea).split()), "n": n,
               "pins": st.taste(s)["pins"], "pieces": pieces}
        self.record(row, f"loop: round {round_no} made ({len(pieces)} pieces, make {key})")
        self.graph(row)
        log(f"round {round_no}: {len(pieces)} pieces in {pdir}/r{rid}. Next: python3 tools/loop.py {self.name} dots")
        return row

    def open_photos(self):
        """The studio's own real photos (refs-private/<name>) whose credits.jsonl licence lets a picture be drawn from
        them: public domain, CC0, CC BY. Share-alike, NC, ND and unlicensed photos never reach the renderer."""
        p = self.refs / "credits.jsonl"
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
        return [self.refs / r["file"] for r in rows
                if (r.get("license") or "").lower().startswith(OPEN) and (self.refs / r["file"]).is_file()]

    def local_refs(self, round_no, n):
        """Local Klein redraws the picture it is shown: rounds fed their pins came back as copies of the pins, whatever
        the prompt said (sci-fi swarm, 10-29; a pin beside two photos, first or last, still won). So each local piece
        gets LOCAL_PHOTOS of the studio's open photos instead, in turn across the round's n pieces and on from round
        to round (all of them before any repeats), and the greens steer through the writer's words alone. No open photo -> None (the pins, as
        before). Local backend only: the private photos stay on this machine. -> spec index -> refs, or None."""
        photos = self.open_photos()
        if not photos:
            return None
        k = min(LOCAL_PHOTOS, len(photos))
        return lambda i: [photos[(((round_no - 1) * n + i) * k + m) % len(photos)] for m in range(k)]

    def graph(self, row):
        """The same make as a ComfyUI graph (Load Studio at the make's commit -> Make stored -> Preview): open it in
        ComfyUI (Workflow > Open) to see the round on the canvas; switch Make to live only for a new make."""
        import mkworkflow
        api = {"1": {"class_type": "BosonLoadStudio", "inputs": {"repo": _tilde(self.repo), "ref": row["studio_sha"]},
                     "_meta": {"title": f"{self.studio} @ round {row['round']}", "pos": [40, 80]}},
               "2": {"class_type": "BosonMake", "inputs": {"studio": ["1", 0], "frame": row["frame"], "idea": row["idea"],
                                                            "n": row["n"], "mode": "stored", "like": "", "backend": "api"},
                     "_meta": {"title": f"Make (round {row['round']})", "pos": [420, 80], "size": [420, 360]}},
               "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]},
                     "_meta": {"title": "pieces", "pos": [900, 80], "size": [700, 600]}}}
        d = self.home / f"r{row['round']}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "graph.api.json").write_text(json.dumps(api, indent=1, ensure_ascii=False) + "\n")
        (d / "graph.json").write_text(json.dumps(mkworkflow.ui(api), indent=1, ensure_ascii=False) + "\n")

    # ---- dots ----------------------------------------------------------------------------------------------
    def deck(self):
        rs = self.rounds()
        if not rs:
            sys.exit(f"no round yet: python3 tools/loop.py {self.name} make --idea \"...\"")
        r = rs[-1]
        d = self.home / f"r{r['round']}"
        cards_dir = d / "cards"
        cards_dir.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        pdir = gr.plates_dir(self.repo)
        cards = []
        for ref in r["pieces"]:
            path = ref.split(":", 1)[1]
            sp = self._spec(r["make"], path)
            dst = cards_dir / (pathlib.Path(path).stem + ".jpg")
            if not dst.exists():
                im = Image.open(pdir / path).convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(dst, quality=88)
            cards.append({"id": ref, "board": f"{self.studio} · round {r['round']}", "row": "pieces",
                          "col": sp.get("title") or pathlib.Path(path).stem, "caption": sp.get("title", ""),
                          "image": f"cards/{dst.name}", "detail": (sp.get("concept", "") + "\n\n" + sp.get("prompt", "")).strip(),
                          "gold": None})
        placard(cards_dir / "verdict.jpg", r["round"])
        cards.append({"id": VERDICT, "board": f"{self.studio} · round {r['round']}", "row": "your round verdict",
                      "col": "verdict", "caption": "ROUND VERDICT", "image": "cards/verdict.jpg", "gold": None,
                      "detail": "Write one or two sentences in the note box under this card: what the round got "
                                "right, what it must stop. No dot needed here."})
        deck = {"config": {"title": f"BOSON · {self.studio} · ROUND {r['round']}",
                           "question": "Green = make more like it. Red = not this. Then the verdict card's note box.",
                           "yes": {"label": "GREEN DOT"}, "no": {"label": "RED DOT"},
                           "tags": ["not its genre", "AI look", "bland", "cluttered", "wrong text", "not the refs"],
                           "fields": {"meta": "row", "top": "caption", "body": "detail", "image": "image"},
                           "field_labels": {"top": "PIECE", "body": "THE IDEA, THEN THE PROMPT"}},
                "cards": cards}
        (d / "DECK.json").write_text(json.dumps(deck, indent=1, ensure_ascii=False) + "\n")
        return d / "DECK.json", r

    def _spec(self, key, path):
        return st.make_spec(key, path)

    def dots(self, host, port, serve=True):
        deck, r = self.deck()
        n = len(r["pieces"])
        log(f"round {r['round']}: {n} pieces + the verdict card -> {deck}")
        if not serve:
            return deck
        log(f"open http://{host}:{port}/ in the browser on the remote desktop. Left-click = green, right-click = red, "
            f"type the round verdict under the last card (Enter saves). Every click is saved as you go.\n"
            f"Done: Ctrl-C here, then python3 tools/loop.py {self.name} next")
        try:
            subprocess.run([sys.executable, str(ENGINE), str(deck), "--matrix", "--host", host, "--port", str(port)])
        except KeyboardInterrupt:
            pass
        return deck

    def read_dots(self, r):
        sys.path.insert(0, str(ENGINE.parent))
        import engine
        labels = self.home / f"r{r['round']}" / "DECK.labels.jsonl"
        got, notes = engine.current_labels(labels), engine.current_notes(labels)
        greens = [p for p in r["pieces"] if got.get(p, {}).get("label") == 1]
        reds = [p for p in r["pieces"] if got.get(p, {}).get("label") == 0]
        return greens, reds, {k: v for k, v in notes.items() if k != VERDICT}, " ".join(notes.get(VERDICT, "").split())

    def dot(self, greens, reds, verdict=""):
        """Dots and the verdict without the grid: the same lines the grid appends to the round's labels file, so
        `next` reads them alike. For a script or an agent in the judge's seat; ids as `status` lists them."""
        rs = self.rounds()
        if not rs or "verdict" in rs[-1]:
            sys.exit(f"no open round to dot: python3 tools/loop.py {self.name} " + ("next" if rs else 'make --idea "..."'))
        r = rs[-1]
        unknown = [p for p in greens + reds if p not in r["pieces"]]
        if unknown or set(greens) & set(reds):
            sys.exit(f"round {r['round']}: " + (f"no piece {', '.join(unknown)}" if unknown else "a piece is both green "
                     f"and red") + f"; its pieces: {', '.join(r['pieces'])}")
        if not (greens or reds):
            sys.exit("dot at least one piece: --green ID,ID and/or --red ID,ID")
        labels = self.home / f"r{r['round']}" / "DECK.labels.jsonl"
        labels.parent.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        rows = [{"id": p, "label": 1, "ts": ts} for p in greens] + [{"id": p, "label": 0, "ts": ts} for p in reds]
        if verdict.strip():
            rows.append({"op": "note", "id": VERDICT, "note": " ".join(verdict.split()), "ts": ts})
        with labels.open("a") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
        log(f"round {r['round']}: {len(greens)} green, {len(reds)} red" + (", verdict written" if verdict.strip() else
            "") + f" -> {labels}\nnext: python3 tools/loop.py {self.name} next" + ("" if verdict.strip() else ' --verdict "..."'))
        return labels

    # ---- next ----------------------------------------------------------------------------------------------
    def next(self, n=None, verdict="", backend="api"):
        rs = self.rounds()
        if not rs:
            sys.exit(f"no round yet: python3 tools/loop.py {self.name} make --idea \"...\"")
        r = rs[-1]
        if "verdict" not in r:
            greens, reds, notes, said = self.read_dots(r)
            said = " ".join(verdict.split()) or said
            if not (greens or reds or said):         # nothing judged yet (or a re-run right after next): show, stop
                log(f"round {r['round']} is made ({len(r['pieces'])} pieces) and waits for its dots and verdict: "
                    f"python3 tools/loop.py {self.name} dots")
                return r
            if not said:
                sys.exit(f"waiting for your verdict on round {r['round']}: write it in the note box under the ROUND "
                         f"VERDICT card (python3 tools/loop.py {self.name} dots), or pass --verdict \"...\"")
            if not (greens or reds):
                sys.exit(f"round {r['round']} has no dots yet: python3 tools/loop.py {self.name} dots")
            st.commit_dots(self.load(), r["round"], greens, reds, said, notes)   # what the Dots node commits too
            log(f"round {r['round']}: {len(greens)} green -> pins, {len(reds)} red, verdict committed")
            r = self.rounds()[-1]
        idea = self.next_idea(r)
        return self.make(r["frame"], idea, n or r["n"], base_idea=r["base_idea"], backend=backend,
                         round_no=r["round"] + 1)

    def next_idea(self, r):
        """The next make's idea: the owner's own idea, then this round's verdict and dots in plain words."""
        return st.next_brief(r)

    # ---- status, check -------------------------------------------------------------------------------------
    def status(self):
        pics = [p for p in sorted(self.refs.iterdir()) if p.suffix.lower() in forge_refs.EXT] if self.refs.is_dir() else []
        log(f"refs: {len(pics)} pictures in {self.refs}")
        if not (self.repo / ".git").exists():
            log(f"studio: not forged ({self.repo})")
        for r in self.rounds():
            log(f"round {r['round']}: make {r['make']}, {len(r['pieces'])} pieces, " +
                (f"{len(r['greens'])} green / {len(r['reds'])} red, verdict: {r['verdict']}" if "verdict" in r
                 else "waiting for dots + verdict"))
            if "verdict" not in r:   # what to judge: the ids `dot` takes, and each picture's file
                pdir = gr.plates_dir(self.repo)
                for ref in r["pieces"]:
                    log(f"  {ref}\n    {pdir / ref.split(':', 1)[1]}")
        log(f"spend so far: ${self.spent():.2f} ({self.home / 'spend.jsonl'})")

    @staticmethod
    def leaks(repo):
        """Pictures a studio forged from private refs ever committed under refs/ (any commit). [] = clean."""
        return check_repo(repo)


def check_repo(repo):
    """A studio whose refs.jsonl names private references must never commit a picture under refs/, at any commit.
    -> the offending paths ([] = clean, or not a private-refs studio)."""
    repo = str(repo)

    def text(c):
        try:
            return st.git(repo, "show", f"{c}:refs/refs.jsonl")
        except RuntimeError:          # the commit that deleted it
            return ""
    if not any(forge_refs.PRIVATE in text(c) for c in st.git(repo, "rev-list", "--all", "--", "refs/refs.jsonl").split()):
        return []
    files = st.git(repo, "log", "--all", "--format=", "--name-only", "--diff-filter=A", "--", "refs/").split("\n")
    return sorted({f for f in files if f and pathlib.Path(f).suffix.lower() in forge_refs.EXT})


def check_all(roots):
    """Every studio repo and bundle under roots -> {path: leaked pictures} for the ones that leak."""
    import tempfile
    bad = {}
    for root in roots:
        for p in sorted(pathlib.Path(root).glob("*")):
            if (p / ".git").exists():
                got = check_repo(p)
            elif p.suffix == ".bundle":
                with tempfile.TemporaryDirectory() as t:
                    if subprocess.run(["git", "clone", "-q", "--mirror", str(p), t], capture_output=True).returncode:
                        continue
                    got = check_repo(t)
            else:
                continue
            if got:
                bad[str(p)] = got
    return bad


def placard(path, k):
    """The verdict card's picture: plain words, so the note box under it reads as the place for the round verdict."""
    if path.exists():
        return
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (900, 1100), (24, 24, 28))
    d = ImageDraw.Draw(im)
    big = ImageFont.truetype(gr.FONT, 64)
    small = ImageFont.truetype(gr.FONT, 34)
    d.text((70, 300), f"ROUND {k}", font=big, fill=(240, 200, 90))
    d.text((70, 390), "VERDICT", font=big, fill=(240, 240, 240))
    for i, line in enumerate(["Write one or two sentences", "in the note box below:", "what this round got right,",
                              "what it must stop.", "", "Enter saves. No dot needed."]):
        d.text((70, 540 + i * 52), line, font=small, fill=(200, 200, 200))
    im.save(path, quality=90)


def _tilde(p):
    p = str(pathlib.Path(p).resolve())
    home = str(pathlib.Path.home())
    return "~" + p[len(home):] if p.startswith(home + "/") else p


def writer_ready():
    """One tiny `claude -p` before a step that may call the writer: it fails fast on an expired login (2026-10-22:
    an expired OAuth session killed a forge and a make mid-run) and refreshes the token the writer then copies."""
    try:
        r = subprocess.run(["claude", "-p", "--model", "claude-haiku-5-5", "reply ok"], capture_output=True,
                           text=True, timeout=90)
        ok, why = r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, why = False, str(e)
    if not ok:
        sys.exit(f"the writer (claude -p) cannot run: {why}\nlog in again (`claude` then /login), then rerun this step")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="the folder in refs-private/ (fashion, posters, ...)")
    ap.add_argument("step", choices=["forge", "make", "dots", "dot", "next", "status", "check"])
    ap.add_argument("--studio", help="studio name (default NAME-real)")
    ap.add_argument("--root", help="where the studio repo lives (default examples/ in this repo)")
    ap.add_argument("--refs", help="the pictures (default refs-private/NAME in this repo, gitignored)")
    ap.add_argument("--field", default="", help="forge: the genre, named plainly (\"Fashion photography\")")
    ap.add_argument("--sentence", default="", help="forge: one sentence, what this studio's work must be")
    ap.add_argument("--owner", default=f"the operator (real references, {time.strftime('%Y-%m-%d')})")
    ap.add_argument("--aspect", default="1:1", choices=sorted(SIZE))
    ap.add_argument("--size", default="1K", choices=["1K", "2K"])
    ap.add_argument("--agy", action="store_true", help="forge: describe through Antigravity (no API key spend)")
    ap.add_argument("--describe-port", type=int, help="forge: describe through a local vision server on this port")
    ap.add_argument("--idea", default="", help="make: what to make, in your words")
    ap.add_argument("--frame", default="", help="make: a style line or subject of the house (optional)")
    ap.add_argument("--backend", default="api", choices=nbn.BACKENDS,
                    help="make/next: who draws (api = Gemini key, comfy-api = Comfy credits, local = FLUX 3 Klein on "
                         "$BOSON_LOCAL_COMFY, open weights; writer local too with $BOSON_WRITER_BASE_URL)")
    ap.add_argument("--n", type=int, help="pieces per make (default 6; next keeps the last round's)")
    ap.add_argument("--verdict", default="", help="dot/next: the round verdict, if not written on the grid")
    ap.add_argument("--green", default="", help="dot: piece ids to keep (comma-separated)")
    ap.add_argument("--red", default="", help="dot: piece ids to reject (comma-separated)")
    ap.add_argument("--host", default="127.0.0.1", help="dots: 127.0.0.1 for the remote desktop's browser")
    ap.add_argument("--port", type=int, default=8772)
    ap.add_argument("--no-serve", action="store_true", help="dots: write the deck only")
    a = ap.parse_args()
    lp = Loop(a.name, a.studio, a.root, a.refs)
    if a.step in ("forge", "make", "next") and not os.environ.get("BOSON_WRITER_BASE_URL"):
        writer_ready()                    # the login check; a local writer has no login
    if a.step == "forge":
        lp.forge(a.field, a.sentence, a.owner, a.aspect, a.size, a.agy, a.describe_port)
    elif a.step == "make":
        lp.make(a.frame, a.idea, a.n or 6, backend=a.backend)
    elif a.step == "dots":
        lp.dots(a.host, a.port, not a.no_serve)
    elif a.step == "dot":
        ids = lambda s: [x.strip() for x in s.split(",") if x.strip()]
        lp.dot(ids(a.green), ids(a.red), a.verdict)
    elif a.step == "next":
        lp.next(a.n, a.verdict, backend=a.backend)
    elif a.step == "status":
        lp.status()
    elif a.step == "check":
        bad = check_all([lp.root]) if not a.studio else ({str(lp.repo): check_repo(lp.repo)} if check_repo(lp.repo) else {})
        for k, v in bad.items():
            log(f"LEAK {k}: {v}")
        log("check: no private reference picture in any studio repo or bundle" if not bad else "check: FAILED")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
