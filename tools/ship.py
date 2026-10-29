#!/usr/bin/env python3
"""Assemble the distribution a stranger clones to view Boson with zero keys (SPEC I4, rubric C2), outside ~/Boson.

  ship.py build [--out /tmp/boson-dist] [--studio NAME ...] [--scene austin-stop] [--scrub-out DIR | --no-scrub]
      the pack (boson/, workflows/, docs/, tools/ as committed at HEAD, less INTERNAL), every studio as
      examples/NAME.bundle (all refs) with its stored plates beside it (examples/NAME-plates/, home paths in the logs
      made repo-relative), the scene
      as examples/NAME-scene.bundle plus every studio it pins (its base and its cast). The dist is then one git
      commit, so `git clone` of it is the stranger's first step. Ends with `scan`; a hit removes nothing, it fails.
  ship.py scrub DIR [--out DIR-scrubbed]
      the publish identity: every commit inside every bundle replayed as the publish identity (PUBLISH_AS) with its original dates, the
      pins that name those commits (scene takes, studio TASTE/LOOP self-pins, plates manifests, pack files) remapped,
      the makes the app recomputes live re-keyed after the old key is reproduced; DIR is never written. build runs it
      by default (--no-scrub to skip), then scans the scrubbed copy. Then `scan`.
  ship.py scan DIR
      the leak check on a dist: loop.py's private-refs check on every bundle, no private reference picture (by
      content, against every studio's refs/ on this box) in any file, no denied string (this box's home path,
      hostname and git email, plus one regex per line of ~/.config/boson/ship-deny.txt, which stays
      untracked) in any file or any object inside a bundle.
  ship.py sizes DIR
      what each shipping option costs: pack, bundles, plates, the clone's .git, a tar.gz of the plates.

Defaults: the demo studios are the -real ones, the scene is austin-stop (the demo scene, 10-24).
"""
import argparse, hashlib, io, json, os, pathlib, re, shutil, socket, subprocess, sys, tarfile, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PACK = ["boson", "workflows", "docs", "tools", "refs-licences"]   # refs-licences: the credit lines CC BY needs
INTERNAL = ["docs/DEMO-SCRIPT.md"]   # tracked in ~/Boson, never shipped: the operator's recording notes
DEMO = ["architecture-real", "cars-real", "cars-s4471-real", "fashion-real", "posters-real"]
SCENE = "austin-stop"
OUT = pathlib.Path("/tmp/boson-dist")
DENY_FILE = pathlib.Path("~/.config/boson/ship-deny.txt").expanduser()
TEXT = (".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".py", ".js", ".html", ".css", ".sh", ".gitignore", "")
PICS = (".jpg", ".jpeg", ".png", ".webp")
# the publish identity (operator 10-29: 0xMisterBailey). GitHub links a commit to the account by ID+NAME@users.noreply...,
# so the final build sets BOSON_PUBLISH_AS="0xMisterBailey <ID+0xMisterBailey@users.noreply.github.com>" (notes/submission/publish.sh)
PUBLISH_AS = os.environ.get("BOSON_PUBLISH_AS", "0xMisterBailey <0xMisterBailey@users.noreply.github.com>")
_NAME, _EMAIL = re.fullmatch(r"(.+?) <(.+)>", PUBLISH_AS).groups()
WHO = ["-c", f"user.name={_NAME}", "-c", f"user.email={_EMAIL}"]


def log(*a):
    print("ship:", *a, flush=True)


def git(*a, cwd=None, out=False):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, check=True)
    return r.stdout if out else None


def scene_studios(scene_dir):
    """SCENE.json + every take's cast.json -> the studio names the scene pins: its base, every slot's studio, and the
    studio of every piece any take was shot with (a take cast from a studio the scene later dropped still replays)."""
    scene_dir = pathlib.Path(scene_dir)
    spec = json.loads((scene_dir / "SCENE.json").read_text())
    names = [spec["base"]["studio"]] + [x["studio"] for x in spec["slots"]]
    names += [x["piece"].split("@")[0] for x in spec["slots"] if x.get("piece")]
    for c in sorted(scene_dir.glob("takes/*/cast.json")):
        names += [p.split("@")[0] for p in json.loads(c.read_text()).values() if p]
    return list(dict.fromkeys(names))


def relative_paths(text, root=ROOT, home=None):
    """A plate log's absolute paths -> repo-relative ('/home/u/Boson/examples/x' -> 'examples/x'); any other path
    under home -> '~/...'. The logs stay (they are the plates' provenance), only the box's paths go."""
    home = str(home or pathlib.Path.home())
    return text.replace(str(root) + "/", "").replace(home + "/", "~/")


def copy_plates(src, dst):
    """<name>-plates/ -> dst: pictures copied as is, text files with relative_paths. -> number of pictures."""
    n = 0
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        q = dst / p.relative_to(src)
        q.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() in PICS:
            shutil.copy2(p, q)
            n += 1
        elif p.suffix.lower() in TEXT:
            q.write_text(relative_paths(p.read_text()))
    return n


# Paths dropped from a scene's shipped history (a temp clone is rewritten; the repo here keeps them). Operator 1a,
# 2026-10-24: clips 01-04 (superseded takes on the tile building, the Omni comparison) kept the bundle near GitHub's
# 100 MB file limit. Takes name studio commits only, never the scene's own, so rewriting its history breaks no pin.
DROP = {"austin-stop": ["clips/01", "clips/02", "clips/03", "clips/04"]}


def bundle(repo, out, drop=()):
    """A studio or scene repo -> one bundle of every ref (open_repo clones -b main; pieces pin shas on any branch).
    drop: paths removed from every commit first (git filter-repo on a temp clone; commits left empty are pruned)."""
    if subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
        log(f"note: {repo.name} has uncommitted changes; only commits ship")
    if not drop:
        git("-C", str(repo), "bundle", "create", str(out), "--all")
        return
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ship-drop-") as t:
        c = pathlib.Path(t) / repo.name
        git("clone", "-q", "--mirror", str(repo), str(c))
        git("-C", str(c), "filter-repo", "--force", "--quiet", "--invert-paths",
            *[a for p in drop for a in ("--path", p)])
        git("-C", str(c), "bundle", "create", str(out), "--all")
    log(f"{repo.name}: dropped {', '.join(drop)} from the shipped history")


def build(out=OUT, studios=DEMO, scene=SCENE, examples=EXAMPLES):
    out = pathlib.Path(out).resolve()
    if out == ROOT or ROOT in out.parents:
        sys.exit(f"ship: refusing to build inside the repo ({out})")
    if out.exists():
        shutil.rmtree(out)
    ex = out / "examples"
    ex.mkdir(parents=True)
    # the pack as committed (HEAD), not the working tree: other sessions' half-done edits never ship
    tar = git("archive", "HEAD", "--", *PACK, ".gitignore", "README.md", "LICENSE",
              *(f":(exclude){x}" for x in INTERNAL), cwd=ROOT, out=True)
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(out, filter="data")
    names = list(studios)
    if scene:
        names += [n for n in scene_studios(examples / scene) if n not in names]
        bundle(examples / scene, ex / f"{scene}-scene.bundle", DROP.get(scene, ()))
    report = {"studios": {}, "scene": scene}
    for n in names:
        repo = examples / n
        if not (repo / ".git").exists():
            sys.exit(f"ship: no studio repo {repo}")
        bundle(repo, ex / f"{n}.bundle")
        plates = examples / f"{n}-plates"
        report["studios"][n] = copy_plates(plates, ex / f"{n}-plates") if plates.is_dir() else 0
        if not plates.is_dir():
            log(f"note: {n} has no stored plates; it shows its rounds' text but no pictures")
    (out / "DIST.json").write_text(json.dumps(report, indent=1) + "\n")
    # one commit, so the stranger's first step is a real `git clone`; -f because .gitignore keeps these out of ~/Boson
    git("init", "-q", "-b", "main", cwd=out)
    git("add", "-A", cwd=out)
    git("add", "-f", "examples", cwd=out)
    git(*WHO, "commit", "-q", "-m", "Boson distribution: pack, demo studios and scene as bundles, stored plates", cwd=out)
    log(f"built {out}: {len(names)} studios ({', '.join(names)}), scene {scene}")
    return out


HEX = re.compile(rb"(?<![0-9a-f])[0-9a-f]{7,40}(?![0-9a-f])")
WHO_ID = PUBLISH_AS.encode()


def remapper(ids, keys=None):
    """old->new commit ids (40 chars) and make keys (12 chars) -> a bytes->bytes rewrite: every whole hex run of 7-40
    characters that is a prefix of an old id becomes the new id's prefix of the same length (so a 40-char studio_sha
    and a studio@sha8 pin both follow), a run equal to an old make key becomes the new key. One pass, so no run is
    rewritten twice. Refuses ids whose 7-char prefixes collide (a short pin would be ambiguous)."""
    look = {}
    for o, n in ids.items():
        for k in range(7, 41):
            if look.get(o[:k], n[:k]) != n[:k]:
                raise ValueError(f"two commit ids share the prefix {o[:k]}; short pins would be ambiguous")
            look[o[:k]] = n[:k]
    for o, n in (keys or {}).items():
        if look.get(o, n) != n:
            raise ValueError(f"make key {o} is also a commit id prefix")
        look[o] = n
    look = {k.encode(): v.encode() for k, v in look.items()}
    return lambda b: HEX.sub(lambda m: look.get(m.group(0), m.group(0)), b)


def _text(name, data):
    """A blob the scrub may rewrite: not a picture by name, no NUL byte, valid utf-8. Everything else is copied as is."""
    if pathlib.PurePath(name).suffix.lower() in PICS or b"\0" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _run(args, cwd, data=None):
    return subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True, check=True).stdout


def rewrite_repo(repo, ids, keys=None):
    """Replay every commit of a (mirror) repo, parents first, as PUBLISH_AS with its original dates: text blobs and
    the message through remapper(ids, keys), rebuilt per commit so a self-pin to an earlier commit here follows it;
    pictures and other binaries untouched; refs moved to the new commits. Fills ids (old -> new) as it goes."""
    memo, sub = {}, None

    def tree(t):
        if t in memo:
            return memo[t]
        rows = []
        for e in _run(["ls-tree", "-z", t], repo).split(b"\0"):
            if not e:
                continue
            meta, name = e.split(b"\t", 1)
            mode, typ, sha = meta.split()
            if typ == b"tree":
                sha = tree(sha.decode()).encode()
            elif typ == b"blob":
                key = (sha, pathlib.PurePath(name.decode()).suffix.lower() in PICS)
                if key not in memo:
                    data = _run(["cat-file", "blob", sha.decode()], repo)
                    new = sub(data) if _text(name.decode(), data) else data
                    memo[key] = _run(["hash-object", "-w", "--stdin"], repo, new).strip() if new != data else sha
                sha = memo[key]
            rows.append(mode + b" " + typ + b" " + sha + b"\t" + name)
        memo[t] = _run(["mktree", "-z"], repo, b"".join(r + b"\0" for r in rows)).strip().decode()
        return memo[t]

    for c in _run(["rev-list", "--all", "--topo-order", "--reverse"], repo).decode().split():
        if c in ids:
            continue
        sub = remapper(ids, keys)
        head, _, msg = _run(["cat-file", "commit", c], repo).partition(b"\n\n")
        out = []
        for line in head.split(b"\n"):
            k, _, v = line.partition(b" ")
            if k == b"tree":
                v = tree(v.decode()).encode()
            elif k == b"parent":
                v = ids[v.decode()].encode()
            elif k in (b"author", b"committer"):
                v = WHO_ID + b" " + b" ".join(v.rsplit(b" ", 2)[1:])   # the original date and zone, kept
            elif k != b"encoding":
                raise ValueError(f"{repo.name}: commit {c[:8]} has a {k.decode()!r} header the scrub can't carry")
            out.append(k + b" " + v)
        ids[c] = _run(["hash-object", "-t", "commit", "-w", "--stdin"], repo,
                      b"\n".join(out) + b"\n\n" + sub(msg)).strip().decode()
    for line in _run(["for-each-ref", "--format=%(objectname) %(objecttype) %(refname)"], repo).decode().splitlines():
        sha, typ, ref = line.split()
        if typ != "commit":
            raise ValueError(f"{repo.name}: {ref} is a {typ}; the scrub carries lightweight refs only")
        _run(["update-ref", ref, ids[sha]], repo)


def _checkout(repo, ref, dst):
    dst.mkdir(parents=True)
    tarfile.open(fileobj=io.BytesIO(_run(["archive", ref], repo))).extractall(dst, filter="data")
    return dst


def rekey(name, old, new, scene, makes, tmp):
    """The make keys the app recomputes live at a studio's main ("made for this spot"): every make of this studio in
    the makes cache made at the old main. make_key hashes the studio's sha and pins and the crop bytes, so the key
    moves with the scrub; the crop is reproduced the way server.ready() takes it (each take x slot of the old scene),
    and a new key is trusted only when the old studio gives back the old key from that crop.
    -> {old key: new key}, {old key: why it stays} for the ones that could not be proven."""
    sys.path.insert(0, str(ROOT / "boson"))
    import numpy as np
    from PIL import Image
    import scene as sc
    import studio as st
    main_old, main_new = (_run(["rev-parse", "main"], r).decode().strip() for r in (old, new))
    so = {"sha": main_old, "dir": str(_checkout(old, "main", tmp / f"{name}-old"))}
    sn = {"sha": main_new, "dir": str(_checkout(new, "main", tmp / f"{name}-new"))}
    crops = []
    if scene:
        d = _checkout(scene, "main", tmp / f"{name}-scene")
        spec = json.loads((d / "SCENE.json").read_text())
        for t in sorted((d / "takes").glob("*/boxes.json")):
            boxes = json.loads(t.read_text())
            pil = Image.open(t.parent / "image.jpg").convert("RGB")
            for sl in spec["slots"]:
                got, place = boxes["slots"].get(sl["id"]) or {}, sl["place"]
                if got.get("visible") or place.get("box") or place.get("boxes"):
                    crop = sc.crop(pil, boxes, sl["id"], 0, 0.15, place)
                    crops.append((f"take {t.parent.name} slot {sl['id']}", np.asarray(crop.convert("RGB")).tobytes()))
    done, left = {}, {}
    for m in sorted(pathlib.Path(makes).glob("*/MAKE.json")):
        meta = json.loads(m.read_text())
        if meta.get("studio_sha") != main_old:
            continue
        key, args = meta["key"], (meta["frame"], meta["idea"], meta["n"], meta.get("like", ""))
        hit = next((w for w, b in [("no image", None)] + crops
                    if st.make_key(so, *args, images=[b] if b else ()) == key), None)
        if hit is None:
            left[key] = "the old studio never gives back this key from any take's crop"
            continue
        b = dict(crops).get(hit)
        done[key] = st.make_key(sn, *args, images=[b] if b else ())
        log(f"{name}: make {key} -> {done[key]} (crop: {hit}; old key reproduced)")
    return done, left


def scrub(src, out=None, makes=None):
    """A built dist -> a copy whose every commit, the dist's and every bundle's, is PUBLISH_AS's (publish identity):
    each studio bundle replayed with rewrite_repo, then the make keys the app recomputes re-keyed (rekey), then the
    scene with every studio's id map, then every text file of the tree (plates manifests and logs, pack files) through
    the same map, make dirs renamed. src is never written. Ends with a check that no old id (8-char prefix) is left in
    any text blob or file. -> report {ids, keys, opaque, ...}; the id map is written beside out."""
    src = pathlib.Path(src).resolve()
    out = pathlib.Path(out or f"{src}-scrubbed").resolve()
    makes = pathlib.Path(makes or pathlib.Path(os.environ.get("BOSON_HOME") or pathlib.Path.home() / ".cache" / "boson") / "makes")
    if out == src or src in out.parents or out in src.parents or out == ROOT or ROOT in out.parents:
        sys.exit(f"ship: refusing to scrub into {out} (from {src})")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=lambda d, names: [".git"] if pathlib.Path(d) == src else [])
    ex = out / "examples"
    bundles = sorted(ex.glob("*.bundle"), key=lambda p: (p.stem.endswith("-scene"), p.name))   # studios first
    ids, keys, opaque = {}, {}, {}
    with tempfile.TemporaryDirectory(prefix="ship-scrub-") as t:
        t = pathlib.Path(t)
        old, new = {}, {}
        for b in bundles:
            old[b.stem], new[b.stem] = t / "old" / b.stem, t / "new" / b.stem
            git("clone", "-q", "--mirror", str(b), str(old[b.stem]))
            git("clone", "-q", "--mirror", str(b), str(new[b.stem]))
        every = {c for r in old.values() for c in _run(["rev-list", "--all"], r).decode().split()}
        if len({c[:8] for c in every}) != len(every):
            raise ValueError("two commit ids in the bundles share an 8-character prefix; refusing to rewrite short pins")
        scene = next((old[b.stem] for b in bundles if b.stem.endswith("-scene")), None)
        for b in bundles:
            if b.stem.endswith("-scene"):
                continue
            rewrite_repo(new[b.stem], ids)
            k, why = rekey(b.stem, old[b.stem], new[b.stem], scene, makes, t / "co")
            keys.update(k)
            opaque.update(why)
        sub = remapper(ids, keys)
        for b in bundles:
            if b.stem.endswith("-scene"):
                rewrite_repo(new[b.stem], ids, keys)
        if len({c[:8] for c in ids.values()} | {c[:8] for c in every}) != 2 * len(every):
            raise ValueError("a new commit id shares an 8-character prefix with another id; refusing")
        for b in bundles:
            b.unlink()
            git("-C", str(new[b.stem]), "bundle", "create", str(b), "--all")
            git("bundle", "verify", "-q", str(b), cwd=new[b.stem])
        for p in sorted(out.rglob("*")):   # plates manifests and logs, the pack's workflows and tools
            if p.is_file() and p.suffix != ".bundle" and _text(p.name, data := p.read_bytes()) and (n := sub(data)) != data:
                p.write_bytes(n)
        for p in sorted(ex.glob("*-plates/rmake-*")):
            if p.name[6:] in keys:
                p.rename(p.with_name("rmake-" + keys[p.name[6:]]))
        left = stale(out, every, keys, new)
    if left:
        sys.exit("ship: scrub left old ids behind:\n  " + "\n  ".join(left))
    git("init", "-q", "-b", "main", cwd=out)
    git("add", "-A", cwd=out)
    git("add", "-f", "examples", cwd=out)
    git(*WHO, "commit", "-q", "-m", "Boson distribution: pack, demo studios and scene as bundles, stored plates", cwd=out)
    pathlib.Path(f"{out}.map.json").write_text(json.dumps({"ids": ids, "keys": keys, "opaque": opaque}, indent=1) + "\n")
    log(f"scrubbed {src} -> {out}: {len(ids)} commits as {_NAME}, {len(keys)} make keys re-keyed"
        + (f", {len(opaque)} left as opaque labels ({', '.join(opaque)})" if opaque else ""))
    return {"out": out, "ids": ids, "keys": keys, "opaque": opaque}


def stale(out, old_ids, keys, repos):
    """Where an old id's 8-char prefix (or a re-keyed make's old key) still appears, as a substring: every text file
    of the tree and every text blob of every rewritten repo. -> ["where: what"], empty = none."""
    pat = re.compile("|".join([c[:8] for c in sorted(old_ids)] + sorted(keys)).encode())
    hits, seen = [], set()
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix != ".bundle" and ".git" not in p.relative_to(out).parts and _text(p.name, d := p.read_bytes()):
            hits += [f"{p.relative_to(out)}: {m.group(0).decode()}" for m in pat.finditer(d)][:3]
    for name, r in repos.items():
        for c in _run(["rev-list", "--all"], r).decode().split():
            hits += [f"{name} commit {c[:8]} message: {m.group(0).decode()}" for m in pat.finditer(_run(["cat-file", "commit", c], r))]
            for e in _run(["ls-tree", "-r", "-z", c], r).split(b"\0"):
                if e:
                    meta, path = e.split(b"\t", 1)
                    if (meta.split()[2], path) in seen:
                        continue
                    seen.add((meta.split()[2], path))
                    data = _run(["cat-file", "blob", meta.split()[2].decode()], r)
                    if _text(path.decode(), data):
                        hits += [f"{name} {c[:8]}:{path.decode()}: {m.group(0).decode()}" for m in pat.finditer(data)][:3]
    return sorted(set(hits))


def denied(extra=DENY_FILE, email=None):
    """The strings no dist may contain, as regexes: this box's home path and hostname, and the git email (any but a
    noreply one: a local-only address is still this box's identity, so a commit signed with it fails),
    and one regex per line of the untracked deny file (names that must never appear in a tracked file either)."""
    pats = [re.escape(str(pathlib.Path.home())) + "/", re.escape(socket.gethostname())]
    try:
        if email is None:
            email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True).stdout.strip()
        if email and "noreply" not in email:
            pats.append(re.escape(email))
    except OSError:
        pass
    if extra and pathlib.Path(extra).exists():
        pats += [l.strip() for l in pathlib.Path(extra).read_text().splitlines() if l.strip() and not l.startswith("#")]
    return re.compile("|".join(f"(?:{p})" for p in pats), re.I)


def private_hashes(examples=EXAMPLES):
    """sha256 of every picture in any studio's refs/ whose refs.jsonl calls it private (the -real studios)."""
    sys.path.insert(0, str(ROOT / "tools"))
    from forge_refs import PRIVATE
    out = {}
    for refs in examples.glob("*/refs"):
        j = refs / "refs.jsonl"
        if j.exists() and PRIVATE in j.read_text():
            for p in refs.iterdir():
                if p.suffix.lower() in PICS:
                    out[hashlib.sha256(p.read_bytes()).hexdigest()] = str(p.relative_to(examples))
    return out


def scan(dist, examples=EXAMPLES, deny=None):
    """-> list of problems (empty = clean)."""
    dist = pathlib.Path(dist)
    deny = deny or denied()
    sys.path.insert(0, str(ROOT / "boson"))
    sys.path.insert(0, str(ROOT / "tools"))
    import loop
    bad = [f"private refs committed: {k}: {v}" for k, v in loop.check_all([dist / "examples"]).items()]
    priv = private_hashes(examples)
    for p in sorted(dist.rglob("*")):
        if not p.is_file() or ".git" in p.relative_to(dist).parts:
            continue
        data = p.read_bytes()
        if p.suffix.lower() in PICS and hashlib.sha256(data).hexdigest() in priv:
            bad.append(f"private reference picture {priv[hashlib.sha256(data).hexdigest()]} shipped as {p.relative_to(dist)}")
        if p.suffix == ".bundle":
            with tempfile.TemporaryDirectory() as t:
                git("clone", "-q", "--mirror", str(p), t)
                blobs = git("cat-file", "--batch-all-objects", "--batch", cwd=t, out=True)
                meta = git("log", "--all", "--format=%an %ae %cn %ce %B", cwd=t, out=True)
                for kind, chunk in (("object", blobs), ("commit", meta)):
                    m = deny.search(chunk.decode("utf-8", "replace"))
                    if m:
                        bad.append(f"denied string in a {kind} of {p.relative_to(dist)}: {m.group(0)!r}")
                for sha in git("rev-list", "--all", cwd=t, out=True).decode().split():
                    for blob in git("ls-tree", "-r", sha, cwd=t, out=True).decode().splitlines():
                        _, typ, obj, path = blob.split(None, 3)
                        if pathlib.Path(path).suffix.lower() in PICS:
                            h = hashlib.sha256(git("cat-file", "blob", obj, cwd=t, out=True)).hexdigest()
                            if h in priv:
                                bad.append(f"private reference picture {priv[h]} inside {p.relative_to(dist)} at {sha[:8]}:{path}")
        elif p.suffix.lower() not in PICS:
            m = deny.search(data.decode("utf-8", "replace"))
            if m:
                bad.append(f"denied string in {p.relative_to(dist)}: {m.group(0)!r}")
    return sorted(set(bad))


def du(paths):
    return sum(f.stat().st_size for p in paths for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file())


def sizes(dist):
    """-> {part: bytes} for the shipping options (README/report numbers, measured, not estimated)."""
    dist = pathlib.Path(dist)
    ex = dist / "examples"
    plates = sorted(ex.glob("*-plates"))
    with tempfile.TemporaryDirectory() as t:
        tgz = pathlib.Path(t) / "plates.tar.gz"
        with tarfile.open(tgz, "w:gz") as tf:
            for p in plates:
                tf.add(p, arcname=f"examples/{p.name}")
        tgz_size = tgz.stat().st_size
        clone = pathlib.Path(t) / "clone"
        git("clone", "-q", str(dist), str(clone))
        git_size = du([clone / ".git"])
    return {"pack": du([dist / p for p in PACK if (dist / p).exists()]),
            "bundles": du(sorted(ex.glob("*.bundle"))),
            "plates": du(plates),
            "plates_pictures": sum(1 for p in plates for f in p.rglob("*") if f.suffix.lower() in PICS),
            "plates_tar_gz": tgz_size,
            "clone_git": git_size,
            "largest_file": max((f.stat().st_size for f in dist.rglob("*") if f.is_file() and ".git" not in f.parts), default=0)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=str(OUT))
    b.add_argument("--studio", action="append", help=f"a studio to ship (repeatable; default {', '.join(DEMO)})")
    b.add_argument("--scene", default=SCENE, help="the scene to ship with every studio it pins ('' for none)")
    b.add_argument("--scrub-out", help="where the scrubbed copy goes (default: OUT-scrubbed)")
    b.add_argument("--no-scrub", dest="scrub", action="store_false",
                   help="skip the identity scrub (the raw dist then fails scan: its bundles carry this box's identity)")
    c = sub.add_parser("scrub")
    c.add_argument("dist", nargs="?", default=str(OUT))
    c.add_argument("--out", help="default: DIST-scrubbed beside it")
    for name in ("scan", "sizes"):
        sub.add_parser(name).add_argument("dist", nargs="?", default=str(OUT))
    a = ap.parse_args()
    if a.cmd == "build":
        out = build(a.out, a.studio or DEMO, a.scene)
        a.dist = scrub(out, a.scrub_out)["out"] if a.scrub else out
    if a.cmd == "scrub":
        a.dist = scrub(a.dist, a.out)["out"]
        a.cmd = "scan"
    if a.cmd in ("build", "scan"):
        bad = scan(a.dist)
        for x in bad:
            log("LEAK", x)
        log("scan: clean" if not bad else f"scan: FAILED ({len(bad)})")
        if bad:
            sys.exit(1)
    if a.cmd in ("build", "sizes"):
        s = sizes(a.dist)
        log(json.dumps({k: (f"{v / 1e6:.1f} MB" if k != "plates_pictures" else v) for k, v in s.items()}))


if __name__ == "__main__":
    main()
