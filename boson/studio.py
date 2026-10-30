"""A Boson studio is a git repository of plain files; this module is the only code that touches it.

Invariants (SPEC v3 §2): the repo is the only state (I1); a commit is never rewritten, a past verdict
changes only on a named branch (I3). Reads go through an immutable snapshot per commit, so a graph that
loads `r01` keeps seeing `r01` even while a later round commits.
"""
import io, json, os, pathlib, re, shutil, subprocess, tarfile

HOME = pathlib.Path(os.environ.get("BOSON_HOME") or pathlib.Path.home() / ".cache" / "boson")   # $BOSON_HOME moves every cache (the tests point it at a tmp dir)

CACHE = HOME / "snapshots"


FALLBACK_WHO = ["-c", "user.name=Boson", "-c", "user.email=boson@localhost"]


def who(repo):
    """[] when git can name who commits in repo (the user's own identity is never overridden); else Boson's fallback,
    so a machine with no git name still saves. A fresh clone without one failed every Undo, Cast and Swap (2026-10-27)."""
    ok = all(subprocess.run(["git", "-C", str(repo), "var", v], capture_output=True).returncode == 0
             for v in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"))
    return [] if ok else FALLBACK_WHO


def git(repo, *args, input=None):
    pre = who(repo) if args and args[0] == "commit" else []
    r = subprocess.run(["git", "-C", str(repo), *pre, *args], capture_output=True, text=True, input=input)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def resolve(repo, ref):
    """ref (tag, branch, commit, HEAD) -> full commit sha."""
    return git(repo, "rev-parse", "--verify", f"{ref or 'HEAD'}^{{commit}}")


def snapshot(repo, sha):
    """Extract the tree at sha once into the cache; return its path (read-only by convention)."""
    out = CACHE / sha
    if not (out / ".boson-snapshot").exists():
        out.mkdir(parents=True, exist_ok=True)
        data = subprocess.run(["git", "-C", str(repo), "archive", sha], capture_output=True, check=True).stdout
        tarfile.open(fileobj=io.BytesIO(data)).extractall(out, filter="data")
        (out / ".boson-snapshot").write_text(sha + "\n")
    return out


STUDIOS = HOME / "studios"


def named(repo):
    """A registry name -> its source (examples/NAME on this box, examples/NAME*.bundle in a clone); a path as given."""
    s = str(repo)
    return registry().get(s, s) if s and "/" not in s and not s.endswith(".bundle") else repo


def forge_path(path):
    """Where Forge Studio makes a studio: a bare name goes in examples/ beside the shipped ones (so the app lists it,
    wherever the repo was cloned); anything with a slash or a ~ is a path, as given."""
    s = str(path).strip()
    return ROOTS[0] / s if s and "/" not in s and not s.startswith("~") else pathlib.Path(s).expanduser()


def open_repo(repo):
    """A path to a studio repo, or to a .bundle (a shipped fixture), which is cloned once to a working repo; or a
    registry name (shipped workflows name their studios, so they load in any clone)."""
    repo = pathlib.Path(named(repo)).expanduser().resolve()
    if repo.suffix == ".bundle":
        work = STUDIOS / repo.stem
        if not (work / ".git").exists():   # clone beside it, then rename: two first requests never race one clone
            STUDIOS.mkdir(parents=True, exist_ok=True)
            tmp = STUDIOS / f".{repo.stem}.clone-{os.getpid()}-{id(repo)}"
            subprocess.run(["git", "clone", "-q", "-b", "main", str(repo), str(tmp)], check=True)
            try:
                tmp.rename(work)
            except OSError:                 # the other request won: its clone is the same bundle
                shutil.rmtree(tmp, ignore_errors=True)
        return work
    return repo


def load(repo, ref="HEAD"):
    """-> STUDIO dict: repo, ref as given, sha, snapshot dir, branch (if ref names one), source (as given:
    a .bundle path stays the bundle, so its stored plates are found beside it)."""
    source = str(pathlib.Path(named(repo)).expanduser())
    repo = open_repo(repo)
    sha = resolve(repo, ref)
    branch = ref if ref and git(repo, "branch", "--list", ref) else None
    return {"repo": str(repo), "ref": ref, "sha": sha, "dir": str(snapshot(repo, sha)), "branch": branch,
            "source": source}


def rounds(studio):
    p = pathlib.Path(studio["dir"]) / "history" / "rounds.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def rules(studio):
    p = pathlib.Path(studio["dir"]) / "history" / "RULES.md"
    return [l[2:] for l in p.read_text().splitlines() if l.startswith("- ")] if p.exists() else []


def next_round(studio):
    return f"{len(rounds(studio)) + 1:02d}"


def writable(studio):
    """-> (repo, branch) if this studio can take a commit, else raise. Checked before any writer call."""
    repo = pathlib.Path(studio["repo"])
    branch = studio["branch"] or git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        raise RuntimeError(f"studio repo is on another branch than {branch}; check it out first")
    if resolve(repo, branch) != studio["sha"]:
        raise RuntimeError(f"branch {branch} moved since this studio was loaded; reload it")
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("studio repo has uncommitted changes; commit or stash them first")
    return repo, branch


def commit(repo, branch, paths, msg, body=""):
    git(repo, "add", "--", *[str(p) for p in paths])
    git(repo, "commit", "-q", "-m", msg, *(["-m", body] if body else []))
    return load(repo, branch)


def commit_verdict(studio, round_id, verdict, keep_kill=None):
    """Write the owner's round verdict into the repo and commit it on the studio's branch.

    Refuses (I2) on an empty verdict, and refuses if the branch moved since the studio was loaded
    (someone else committed): the caller reloads instead of silently writing on top.
    """
    verdict = " ".join(verdict.split())
    if not verdict:
        raise ValueError("empty verdict: the round verdict is the signal (T12); nothing committed")
    repo, branch = writable(studio)
    rdir = repo / "history" / f"round-{round_id}"
    if (rdir / "VERDICT.md").exists():
        raise RuntimeError(f"round {round_id} already has a verdict; run Digest, or branch to change it (I3)")
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "VERDICT.md").write_text(verdict + "\n")
    if keep_kill:
        (rdir / "labels.jsonl").write_text("".join(json.dumps(x) + "\n" for x in keep_kill))
    return commit(repo, branch, [rdir], f"round {round_id}: owner verdict", verdict)


# ---- writer passes (Draft Brief, Digest) and the owner's rule approval --------------------------------

SPEC_KEYS = {"id", "series", "title", "concept", "prompt", "width", "height"}
DRAFTS = HOME / "drafts"
REFS = ("02", "08", "01")  # the grid's one ref set (SPEC v3 §4.2, T14)


def render_cfg(studio):
    """The studio's instrument for drafting: RENDER.json in the studio, else the ex-libris Klein default
    (the fixture carries no RENDER.json, so its draft task is byte-identical to before)."""
    p = pathlib.Path(studio["dir"]) / "RENDER.json"
    cfg = {"renderer": "klein", "refs": list(REFS), "width": 832, "height": 1216, "instrument_task": "instrument-klein-exlibris"}
    if p.exists():
        cfg.update(json.loads(p.read_text()))
    return cfg


def draft_task(studio, rid, n):
    wr, cfg = _writer(), render_cfg(studio)
    refs = ", ".join(f"{r}.jpg" for r in cfg["refs"])
    inst = cfg.get("instrument") or wr.task(cfg["instrument_task"], REFS=refs).rstrip("\n")
    if (pathlib.Path(studio["dir"]) / "COMMISSION.md").exists():  # absent in the fixture: its task is unchanged
        inst += ("\n\nThe commission: read `COMMISSION.md`. Every piece this round serves it; the studio's taste "
                 "decides how.")
    return wr.task("draft", NN=rid, N=n, INSTRUMENT=inst, W=cfg["width"], H=cfg["height"]), cfg


def _writer():
    try:
        from . import writer
    except ImportError:  # imported as a plain module (tools/), not as the ComfyUI package
        import writer
    return writer


def specs(round_dir):
    out = [json.loads(p.read_text()) for p in sorted((pathlib.Path(round_dir) / "specs").glob("*.json"))]
    for s in out:
        if SPEC_KEYS - s.keys():
            raise ValueError(f"spec {s.get('id')}: missing {SPEC_KEYS - s.keys()}")
    return out


def draft_cache(studio, n, draw):
    """Where a draft at a tag or commit lives: keyed by commit, round, piece count and draw, so a 4-piece
    smoke draft never stands in for a 1-piece grid cell."""
    return DRAFTS / f"{studio['sha'][:12]}-r{next_round(studio)}-n{n}-d{draw}"


def forge(path, owner, field, sentence, refs_dir, instruments, render=None, commission=None):
    """Forge Studio (SPEC v3 §3): a new studio repo at path from refs + the owner's sentence. -> STUDIO @ r00.

    refs_dir holds NN.jpg + refs.jsonl with `vlm` descriptions (tools/fetch_refs.py, describe_refs.py).
    render = RENDER.json content (the drafting instrument); commission = {"text": ..., "refs": [paths]}:
    what the rounds serve, kept apart from the studio's taste. The writer drafts STUDIO.md, JURY.md and
    the history headers in an isolated copy; only those files come back.
    """
    wr = _writer()
    repo = pathlib.Path(path).expanduser()
    if (repo / ".git").exists():
        raise RuntimeError(f"{repo} is already a studio")
    (repo / "history").mkdir(parents=True)
    shutil.copytree(refs_dir, repo / "refs")
    k = sum(1 for l in (repo / "refs" / "refs.jsonl").read_text().splitlines() if l.strip())
    (repo / "FORGE-INPUT.md").write_text(
        f"# Forge input\n\nOwner: {owner}\n\nField: {field}\n\nThe owner's sentence: \"{sentence}\"\n\n"
        f"References: `refs/refs.jsonl` ({k} pictures, license per line).\n")
    (repo / "instruments.yaml").write_text(instruments)
    if render:
        (repo / "RENDER.json").write_text(json.dumps(render, indent=1) + "\n")
    if commission:
        (repo / "commission").mkdir()
        refs = []
        for src in commission.get("refs", []):
            shutil.copy(src, repo / "commission" / pathlib.Path(src).name)
            refs.append(f"commission/{pathlib.Path(src).name}")
        (repo / "COMMISSION.md").write_text(f"# Commission\n\n{commission['text']}\n\n" + "".join(
            f"Reference image: `{r}`\n" for r in refs))
    (repo / ".gitignore").write_text("renders/\ncache/\n")
    (repo / "history" / "rounds.jsonl").touch()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "forge input")
    s = load(repo, "main")
    work, meta = wr.run(s["dir"], wr.task("forge", K=k), f"forge-{repo.name}")
    try:
        back = ["STUDIO.md", "JURY.md", "instruments.yaml", "history/RULES.md", "history/LESSONS.md"]
        missing = [b for b in back if not (work / b).exists()]
        if missing:
            raise RuntimeError(f"forge wrote no {missing} (log {meta['log']})")
        for b in back:
            shutil.copy(work / b, repo / b)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    s = commit(repo, "main", back, "forge: STUDIO.md, JURY.md", f"{meta['writer']} ${meta['cost_usd']}")
    git(repo, "tag", "r00")
    return s, meta


def draft(studio, n=8, draw=0):
    """Writer drafts the next round: BRIEF.md, specs/, SELF-ASSESSMENT.md. -> (studio, specs, meta).

    On a branch the draft is committed (the round is real). At a tag or commit (a grid's live cell) it
    goes to a cache keyed by commit + draw and the studio is untouched. Either way a re-queue reuses it.
    """
    wr = _writer()
    if awaiting_approval(studio):
        raise RuntimeError(f"round {awaiting_approval(studio)}'s proposed rules await Approve Rules")
    rid = next_round(studio)
    rel = pathlib.Path("history") / f"round-{rid}"
    have = pathlib.Path(studio["dir"]) / rel
    cache = draft_cache(studio, n, draw)
    for d in (have, None if studio["branch"] else cache):
        if d and (d / "specs").is_dir():
            meta = json.loads((d / "WRITER.json").read_text()) if (d / "WRITER.json").exists() else {}
            meta["brief"] = (d / "BRIEF.md").read_text() if (d / "BRIEF.md").exists() else ""
            return studio, specs(d), meta
    if studio["branch"]:
        repo, branch = writable(studio)  # before the paid call, not after
    prompt, cfg = draft_task(studio, rid, n)
    work, meta = wr.run(studio["dir"], prompt,
                        f"draft-{studio['sha'][:8]}-r{rid}-n{n}-d{draw}")
    try:
        got = specs(work / rel)
        if not got:
            raise RuntimeError(f"writer wrote no specs (log {meta['log']})")
        meta.update(round=rid, n=len(got), draw=draw, refs=list(cfg["refs"]), renderer=cfg["renderer"])
        keep = ["BRIEF.md", "SELF-ASSESSMENT.md", "specs"]
        dst = (pathlib.Path(repo) / rel) if studio["branch"] else cache
        dst.mkdir(parents=True, exist_ok=True)
        for k in keep:
            src = work / rel / k
            if src.is_dir():
                shutil.copytree(src, dst / k, dirs_exist_ok=True)
            elif src.exists():
                shutil.copy(src, dst / k)
        (dst / "WRITER.json").write_text(json.dumps(meta, indent=1) + "\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if studio["branch"]:
        studio = commit(repo, branch, [rel], f"round {rid}: draft", meta["writer"])
    meta["brief"] = (dst / "BRIEF.md").read_text() if (dst / "BRIEF.md").exists() else ""
    return studio, got, meta


MAKES = HOME / "makes"


def make_key(studio, frame, idea, n, like="", images=()):
    """What a make is: the studio at its sha, the frame, the idea, n, the piece it varies, the pins, and the bytes of
    any commission image. Same key = same make, so a re-queue never buys a second writer call."""
    import hashlib
    h = hashlib.sha256(json.dumps([studio["sha"], frame.strip(), " ".join(idea.split()), n, like.strip(),
                                   taste(studio)["pins"]]).encode())
    for b in images:
        h.update(hashlib.sha256(b).digest())
    return h.hexdigest()[:12]


def piece_prompt(studio, path):
    """The prompt a stored plate was rendered from (its manifest row), else its round's spec, else ""."""
    pdir = pathlib.Path(studio.get("source") or studio["repo"]).expanduser()
    man = pdir.parent / f"{pdir.name.split('.')[0]}-plates" / "manifest.jsonl"
    rows = [json.loads(l) for l in man.read_text().splitlines() if l.strip()] if man.exists() else []
    hit = [r for r in rows if r.get("file") == path and r.get("prompt")]
    if hit:
        return hit[-1]["prompt"]
    sid = pathlib.Path(path).name.split("__")[0]
    seg = path.split("/")[0]                       # rNN (a round) or rmake-KEY (a make), as render_round names them
    for d in (MAKES / seg[6:] if seg.startswith("rmake-") else None,
              pathlib.Path(studio["dir"]) / "history" / f"round-{seg[1:]}"):
        for sp in sorted((d / "specs").glob("*.json")) if d and (d / "specs").is_dir() else []:
            x = json.loads(sp.read_text())
            if x.get("id") == sid:
                return x.get("prompt", "")
    return ""


def make(studio, frame, idea, n=4, like="", images=(), key=None):
    """Make n pieces for one frame (a style line or a subject) and the owner's idea, outside the round loop: the writer
    reads the whole studio and writes n render specs (paid, minutes); nothing is committed (no round, no verdict).
    like = a piece (studio@sha:path) to make more like: its prompt reaches the writer, its image the renderer.
    Cached by make_key, so a re-queue costs nothing. -> (specs, meta)."""
    wr = _writer()
    key = key or make_key(studio, frame, idea, n, like)
    d = MAKES / key
    if (d / "specs").is_dir():
        return specs(d), json.loads((d / "MAKE.json").read_text())
    cfg = render_cfg(studio)
    like_txt = ""
    if like:
        lp = piece_prompt(studio, like.split(":", 1)[1]) if like.split("@")[0] == name_of(studio) else ""
        like_txt = ("\n\nMore like this piece (`" + like + "`), rendered from:\n\n> " + (lp or "(its prompt is not on "
                    "record: work from its title)") + "\n\nKeep what makes it work; vary the rest. The renderer gets "
                    "its image as image 1.")
    pins = taste(studio)["pins"]
    if pins:
        like_txt += "\n\nPinned for this make (the renderer gets these images too; you see names only): " + ", ".join(
            f"`{x}`" for x in pins)
    if images:
        like_txt += (f"\n\nThe commission image{'s' if len(images) > 1 else ''} (the spot in a scene these pieces are "
                     "for) reach the renderer after the pieces above.")
    inst = cfg.get("instrument") or _writer().task(cfg["instrument_task"], REFS=", ".join(
        f"{r}.jpg" for r in cfg["refs"])).rstrip("\n")
    prompt = wr.task("make", N=n, FRAME=frame.strip() or "(none: the house as a whole)",
                     IDEA=" ".join(idea.split()) or "(none given: the frame alone)", LIKE=like_txt, INSTRUMENT=inst,
                     W=cfg["width"], H=cfg["height"])
    work, meta = wr.run(studio["dir"], prompt, f"make-{studio['sha'][:8]}-{key}")
    try:
        got = specs(work / "make")
        if not got:
            raise RuntimeError(f"writer wrote no make specs (log {meta['log']})")
        d.mkdir(parents=True, exist_ok=True)
        shutil.copytree(work / "make" / "specs", d / "specs", dirs_exist_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    meta.update(key=key, frame=frame.strip(), idea=" ".join(idea.split()), n=len(got), like=like.strip(), pins=pins,
                studio_sha=studio["sha"])
    (d / "MAKE.json").write_text(json.dumps(meta, indent=1) + "\n")
    return got, meta


def digest(studio):
    """Writer digests the round the owner just judged. -> (studio @ new commit, meta).

    Refuses without a committed verdict (I2). Writes rounds.jsonl (+1 line), LESSONS.md, and the round's
    RULES-PROPOSED / CRAFT-PROPOSED / RULE-CHECK; RULES.md changes only through approve().
    """
    wr = _writer()
    rid = next_round(studio)
    base = pathlib.Path(studio["dir"])
    rel = pathlib.Path("history") / f"round-{rid}"
    if not (base / rel / "VERDICT.md").exists():
        raise ValueError(f"round {rid} has no owner verdict; nothing to digest (I2)")
    repo, branch = writable(studio)
    old = (base / "history" / "rounds.jsonl").read_text().splitlines()
    work, meta = wr.run(studio["dir"], wr.task("digest", NN=rid), f"digest-{studio['sha'][:8]}-r{rid}")
    try:
        new = (work / "history" / "rounds.jsonl").read_text().splitlines()
        added = [l for l in new[len(old):] if l.strip()]
        if new[:len(old)] != old or len(added) != 1 or json.loads(added[0]).get("round") != rid:
            raise RuntimeError(f"writer must append exactly one rounds.jsonl line for round {rid} (log {meta['log']})")
        if not (work / rel / "RULES-PROPOSED.md").exists():
            raise RuntimeError(f"writer wrote no RULES-PROPOSED.md (log {meta['log']})")
        if (work / "history" / "RULES.md").read_text() != (base / "history" / "RULES.md").read_text():
            meta["note"] = "writer edited RULES.md; edit discarded (owner approves rules)"
        paths = [pathlib.Path("history") / "rounds.jsonl", pathlib.Path("history") / "LESSONS.md"]
        paths += [rel / f for f in ("RULES-PROPOSED.md", "CRAFT-PROPOSED.md", "RULE-CHECK.md")
                  if (work / rel / f).exists()]
        for p in paths:
            shutil.copy(work / p, repo / p)
        meta["round"] = rid
        (repo / rel / "DIGEST.json").write_text(json.dumps(meta, indent=1) + "\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return commit(repo, branch, paths + [rel / "DIGEST.json"], f"round {rid}: digest", meta["writer"]), meta


def parse_proposed(text):
    """RULES-PROPOSED.md -> {n: rule}. Rules run 1, 2, ... in order; a rule the writer wrapped onto following lines is
    joined, up to its "evidence:" line or a blank line. A wrapped evidence line that starts with a number ("1941. Only
    ...") is not a rule: a rule's number runs on from the last one."""
    rules, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[.)]\s+(.+)$", line)
        if m and int(m.group(1)) == len(rules) + 1:
            cur = m.group(1)
            rules[cur] = m.group(2).strip()
        elif not line.strip() or line.strip().lower().startswith("evidence"):
            cur = None
        elif cur:
            rules[cur] += " " + line.strip()
    return rules


def proposed(studio):
    """-> (round id, {n: rule}) for the last digested round, or (None, {})."""
    rs = rounds(studio)
    if not rs:
        return None, {}
    rid = rs[-1]["round"]
    p = pathlib.Path(studio["dir"]) / "history" / f"round-{rid}" / "RULES-PROPOSED.md"
    return rid, parse_proposed(p.read_text() if p.exists() else "")


def awaiting_approval(studio):
    """Round id whose proposed rules the owner has not approved yet, else None. Keyed on DIGEST.json, so
    T12-era rounds (digested outside the pack) never block."""
    rs = rounds(studio)
    if not rs:
        return None
    rd = pathlib.Path(studio["dir"]) / "history" / f"round-{rs[-1]['round']}"
    return rs[-1]["round"] if (rd / "DIGEST.json").exists() and not (rd / "APPROVED").exists() else None


def approve(studio, picks):
    """The owner approves proposed rules by number ("1,3") or "none". Appends to RULES.md; idempotent."""
    rid, props = proposed(studio)
    if rid is None:
        raise ValueError("no digested round to approve rules from")
    rd = pathlib.Path(studio["dir"]) / "history" / f"round-{rid}"
    if (rd / "APPROVED").exists():
        return studio, []
    nums = [] if picks.strip().lower() == "none" else [x.strip() for x in picks.split(",") if x.strip()]
    bad = [x for x in nums if x not in props]
    if bad:
        raise ValueError(f"no proposed rule {bad} in round {rid} (have {sorted(props)})")
    repo, branch = writable(studio)
    rules_md = repo / "history" / "RULES.md"
    with rules_md.open("a") as f:
        for x in nums:
            f.write(f"- (round {rid}) {props[x].strip()}\n")
    (repo / "history" / f"round-{rid}" / "APPROVED").write_text((",".join(nums) or "none") + "\n")
    new = commit(repo, branch, [rules_md, repo / "history" / f"round-{rid}" / "APPROVED"],
                 f"round {rid}: owner approved rules {','.join(nums) or 'none'}")
    return new, [props[x] for x in nums]


# ---- the studio floor: where studios live, their taste fields, the shared shelf --------------------------

ROOTS = [pathlib.Path(__file__).resolve().parents[1] / "examples", STUDIOS]
TASTE_KEYS = ("words", "style_lines", "subjects", "principles", "pictures", "pins")
HOUSE_FIELDS = ("sentence",) + TASTE_KEYS


def registry(roots=None):
    """name -> source (a .bundle or a repo dir) for every studio under the roots ($BOSON_STUDIOS, os.pathsep-separated,
    else examples/ then the clone cache). A bundle wins over its own working clone; scene bundles (*-scene.bundle)
    and folders holding SCENE.json are not studios."""
    import os
    env = os.environ.get("BOSON_STUDIOS")
    roots = roots or ([pathlib.Path(p).expanduser() for p in env.split(os.pathsep)] if env else ROOTS)
    out = {}
    for root in map(pathlib.Path, roots):
        for p in sorted(root.glob("*.bundle")) if root.is_dir() else []:
            if not p.name.endswith("-scene.bundle"):
                out.setdefault(p.stem, str(p))
        for p in sorted(root.iterdir()) if root.is_dir() else []:
            if (p / ".git").exists() and not (p / "SCENE.json").exists():
                out.setdefault(p.name, str(p))
    return out


def find(name):
    """A studio's source by name (see registry), or a path given as is."""
    if "/" in name or name.endswith(".bundle"):
        return name
    reg = registry()
    if name not in reg:
        raise KeyError(f"no studio named {name!r} (have {', '.join(sorted(reg))})")
    return reg[name]


def name_of(studio):
    """The studio's registry name: its bundle or repo folder name."""
    return pathlib.Path(studio.get("source") or studio["repo"]).name.split(".")[0]


def forge_sentence(studio):
    p = pathlib.Path(studio["dir"]) / "FORGE-INPUT.md"
    m = re.search(r'^The owner\'s sentence: "(.*)"\s*$', p.read_text(), re.M) if p.exists() else None
    return m.group(1) if m else ""


def taste(studio):
    """The studio's house, owner-editable (Edit House), from its optional TASTE.json: sentence (the house sentence;
    absent = the forge sentence in FORGE-INPUT.md), words (descriptor words), style_lines (one-line style
    principles), principles (beliefs), subjects ([{name, ...}]), pictures (house pictures) and pins (pinned for the
    next make), both lists of `studio@sha:path` pieces. Absent file or key -> empty, so studios forged before these
    fields load unchanged. Refuses a malformed file rather than guessing."""
    p = pathlib.Path(studio["dir"]) / "TASTE.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    out = {k: d.get(k, []) for k in TASTE_KEYS}
    for k in ("words", "style_lines", "principles", "pictures", "pins"):
        if not all(isinstance(x, str) for x in out[k]):
            raise ValueError(f"TASTE.json {k}: a list of strings")
    if not all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in out["subjects"]):
        raise ValueError("TASTE.json subjects: a list of {name, ...}")
    if not isinstance(d.get("sentence", ""), str):
        raise ValueError("TASTE.json sentence: a string")
    return {"sentence": d.get("sentence") or forge_sentence(studio), **out}


def _piece_ref(v):
    if not re.fullmatch(r"[\w.\-]+@[0-9a-f]{4,40}:[^/].*", v) or ".." in v.split(":", 1)[1].split("/"):
        raise ValueError(f"{v!r}: a piece is studio@sha:path")
    return v


def edit_house(studio, field, op, value):
    """An owner edit of the house (Edit House): one commit to TASTE.json, or none when nothing changes (a re-queue).
    field: sentence (op set) | words, style_lines, principles (set: one per line; add; remove) | subjects (add or
    remove by name) | pictures, pins (add or remove a piece studio@sha:path). -> (studio, changed)."""
    if field not in HOUSE_FIELDS:
        raise ValueError(f"no house field {field!r} (have {', '.join(HOUSE_FIELDS)})")
    if op not in ("set", "add", "remove"):
        raise ValueError("op is set, add or remove")
    value = value.strip()
    cur = taste(studio)
    p = pathlib.Path(studio["dir"]) / "TASTE.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    if field == "sentence":
        if op != "set":
            raise ValueError("the house sentence is set, not added or removed")
        new = " ".join(value.split())
        if not new:
            raise ValueError("an empty house sentence: write one")
    elif field == "subjects":
        names = [x["name"] for x in cur["subjects"]]
        if op == "set":
            raise ValueError("subjects are added or removed one at a time")
        new = (cur["subjects"] + [{"name": value}] if op == "add" and value not in names else
               [x for x in cur["subjects"] if not (op == "remove" and x["name"] == value)])
    else:
        items = [" ".join(x.split()) for x in value.splitlines() if x.strip()] if op == "set" else [" ".join(value.split())]
        if field in ("pictures", "pins"):
            items = [_piece_ref(x) for x in items]
        if not items and op != "set":
            raise ValueError(f"nothing to {op}")
        new = (items if op == "set" else cur[field] + [x for x in items if x not in cur[field]] if op == "add"
               else [x for x in cur[field] if x not in items])
    if new == cur[field]:
        return studio, False
    repo, branch = writable(studio)
    d[field] = new
    (repo / "TASTE.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    what = value if len(value) <= 60 else value[:57] + "..."
    return commit(repo, branch, [repo / "TASTE.json"], f"house: {op} {field}: {what}"), True


# ---- the loop's rounds (LOOP.jsonl): tools/loop.py and the Dots node write them, the room reads them -------------

def loop_rows(studio):
    """LOOP.jsonl at the studio's commit: one {"round", "make", ...} row per round, then its {"round", "verdict", ...}
    row once dotted."""
    p = pathlib.Path(studio["dir"]) / "LOOP.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def loop_rounds(studio):
    """The loop's rounds, oldest first, each make row merged with its verdict row (greens, reds, notes, verdict)."""
    out = {}
    for r in loop_rows(studio):
        out.setdefault(r["round"], {}).update(r)
    return [out[k] for k in sorted(out)]


def open_loop_round(studio):
    """The loop round still waiting for the owner's dots and verdict, else None."""
    rs = loop_rounds(studio)
    return rs[-1]["round"] if rs and "verdict" not in rs[-1] else None


def make_spec(key, path):
    """The render spec a make wrote for one of its plates (rmake-KEY/ID__d0__nbn.png), {} if the cache is gone."""
    p = MAKES / key / "specs" / f"{pathlib.Path(path).name.split('__')[0]}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def next_brief(r):
    """The next make's idea after a judged loop round: the owner's own idea, then the verdict and dots in plain words."""
    def say(p):
        sp = make_spec(r["make"], p.split(":", 1)[1])
        note = (r.get("notes") or {}).get(p)
        return f'"{sp.get("title") or pathlib.Path(p).stem}"' + (f" (owner's note: {note})" if note else "")
    out = [r["base_idea"], "", f"The owner's verdict on round {r['round']}: \"{r['verdict']}\""]
    if r["greens"]:
        out.append("Green-dotted, make more like these (pinned; the renderer sees them): " +
                   "; ".join(say(p) for p in r["greens"]) + ".")
    if r["reds"]:
        out.append("Red-dotted, not like these: " + "; ".join(say(p) for p in r["reds"]) + ".")
    return "\n".join(out)


def commit_dots(studio, round_no, greens, reds, verdict, notes=None):
    """The owner's dots and verdict on the open loop round: exactly what `tools/loop.py next` commits before it makes
    (and what the Dots node commits): the greens join the house pins, newest first, and the reds leave them (a TASTE.json
    commit, none when the pins do not change; operator 2a, 2026-10-24); then the verdict row in LOOP.jsonl and the
    owner's sentence, verbatim, as a rule line under STUDIO.md's "From your verdicts" (one commit; operator 1a). Never makes the next round. Refuses an empty verdict, no dots, a piece
    not in the round, a dot both green and red, a round that is not the open one. The same verdict again commits
    nothing; a different one on a judged round is refused (I3). -> (studio, verdict row, changed)."""
    said = " ".join((verdict or "").split())
    if not said:
        raise ValueError("empty verdict: the round verdict is the signal; nothing committed")
    rs = loop_rounds(studio)
    if not rs:
        raise ValueError("no loop round yet: nothing to judge")
    round_no = int(round_no)
    done = next((x for x in rs if x["round"] == round_no and "verdict" in x), None)
    if done:
        if done["verdict"] == said:
            return studio, {k: done[k] for k in ("round", "verdict", "greens", "reds", "notes")}, False
        raise RuntimeError(f"round {round_no} already has a verdict ({done['verdict']!r}); branch to change it (I3)")
    r = rs[-1]
    if round_no != r["round"]:
        raise ValueError(f"round {round_no} is not the open round (open: {r['round']})")
    greens, reds = list(dict.fromkeys(greens)), list(dict.fromkeys(reds))
    stray = [p for p in greens + reds if p not in r["pieces"]]
    if stray:
        raise ValueError(f"not a piece of round {round_no}: {stray[0]}")
    if set(greens) & set(reds):
        raise ValueError(f"a piece is both green and red: {sorted(set(greens) & set(reds))[0]}")
    if not (greens or reds):
        raise ValueError(f"round {round_no} has no dots yet: green what to make more of, red what to stop")
    writable(studio)                    # checked before the first commit, so a moved branch commits nothing
    # the pins build up: this round's greens first (Make keeps the first refs when it caps them), then the older pins,
    # minus anything dotted red. The writer reads their names, the renderer sees them.
    old = taste(studio)["pins"]
    pins = greens + [x for x in old if x not in greens and x not in reds]
    if pins != old:
        studio, _ = edit_house(studio, "pins", "set", "\n".join(pins))
    row = {"round": round_no, "verdict": said, "greens": greens, "reds": reds, "notes": dict(notes or {})}
    repo, branch = writable(studio)
    with (repo / "LOOP.jsonl").open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    add_verdict_rule(repo / "STUDIO.md", round_no, said)
    studio = commit(repo, branch, [repo / "LOOP.jsonl", repo / "STUDIO.md"],
                    f"loop: round {round_no} verdict ({len(greens)} green, {len(reds)} red)")
    return studio, row, True


VERDICTS = "## From your verdicts"


def add_verdict_rule(path, round_no, said):
    """Append the owner's verdict, word for word, as a rule line of STUDIO.md's last section (made on first use). No
    model rewrites it: the next make's writer reads the studio's rules, so this line binds it."""
    text = path.read_text() if path.exists() else ""
    line = f'- Round {round_no}: "{said}"'
    if VERDICTS not in text:
        text = text.rstrip("\n") + f"\n\n{VERDICTS}\nThe owner's round verdicts, verbatim. Each one binds every make after it.\n"
    path.write_text(text.rstrip("\n") + "\n" + line + "\n")


def section(text, title):
    """The body of a `## ...` section of a markdown file whose heading starts with title (case-insensitive)."""
    m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M | re.I)
    return m.group(1).strip() if m else ""


def _section_with(text, *words):
    """The body of the first `## ...` section whose heading holds any of words (case-insensitive)."""
    for m in re.finditer(r"^## ([^\n]*)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        if any(w in m.group(1).lower() for w in words):
            return m.group(2).strip()
    return ""


def house(studio):
    """What a scene needs from a studio's house, read straight from STUDIO.md (no model in between):
    `ours` = its "What makes a picture unmistakably ours" paragraph, `refusals` = the bold names of its
    "refuses, by name" list, `style_lines` from TASTE.json."""
    p = pathlib.Path(studio["dir"]) / "STUDIO.md"
    text = p.read_text() if p.exists() else ""
    ours = " ".join((section(text, "What makes a picture unmistakably ours")    # the heading the forge task names;
                     or _section_with(text, "unmistakabl", "idiom")).split())   # older forges chose their own
    ref = re.search(r"^## [^\n]*\brefuses\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M | re.I)
    names = [m.strip().rstrip(":.").strip() for m in re.findall(r"^\s*-\s+\*\*(.+?)\*\*", ref.group(1) if ref else "", re.M)]
    return {"ours": ours, "refusals": names, "style_lines": taste(studio)["style_lines"]}


def shelf(studio):
    """The studio's kept pieces (SHELF.jsonl), oldest first: {piece: "name@sha:path", note}."""
    p = pathlib.Path(studio["dir"]) / "SHELF.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def keep(studio, path, note=""):
    """Put one of the studio's pieces on the shared shelf: a line in SHELF.jsonl, committed. The piece is named
    `studio@sha:path` with the sha of the commit that made it (the manifest's studio_sha for a stored plate),
    so the shelf never points at a moving branch. Idempotent per piece."""
    name = name_of(studio)
    made = piece_sha(studio, path)
    ref = f"{name}@{made[:8]}:{path}"
    if any(x["piece"] == ref for x in shelf(studio)):
        return studio, ref
    repo, branch = writable(studio)
    with (repo / "SHELF.jsonl").open("a") as f:
        f.write(json.dumps({"piece": ref, "note": " ".join(note.split())}) + "\n")
    return commit(repo, branch, [repo / "SHELF.jsonl"], f"shelf: keep {path}"), ref


def unkeep(studio, piece):
    """Take a piece off the shelf (its SHELF.jsonl line), committed. piece: studio@sha:path, or the path alone.
    Idempotent: a piece not on the shelf commits nothing. -> (studio, removed refs)."""
    rows = shelf(studio)
    gone = [x["piece"] for x in rows if x["piece"] == piece or x["piece"].split(":", 1)[1] == piece]
    if not gone:
        return studio, []
    repo, branch = writable(studio)
    (repo / "SHELF.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows if x["piece"] not in gone))
    return commit(repo, branch, [repo / "SHELF.jsonl"], f"shelf: unkeep {piece}"), gone


def piece_sha(studio, path):
    """The commit that made `path`: the last commit up to the studio's sha that changed a file in the repo, the
    manifest's studio_sha for a stored plate beside it. Raises if the studio has no such piece."""
    if (pathlib.Path(studio["dir"]) / path).is_file():
        return git(studio["repo"], "log", "-1", "--format=%H", studio["sha"], "--", path)
    pdir = pathlib.Path(studio.get("source") or studio["repo"]).expanduser()
    man = pdir.parent / f"{pdir.name.split('.')[0]}-plates" / "manifest.jsonl"
    rows = [json.loads(l) for l in man.read_text().splitlines() if l.strip()] if man.exists() else []
    hit = [r for r in rows if r.get("file") == path]
    if not hit:
        raise FileNotFoundError(f"{path} is neither in the studio nor in its plates manifest")
    return hit[-1]["studio_sha"]
