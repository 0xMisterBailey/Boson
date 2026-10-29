"""A Boson scene is a git repository holding SCENE.json and its takes; this module is the only code that touches it.

Invariants (same as a studio, SPEC v3 §2): the repo is the only state (I1); a take is a commit and is never rewritten
(I3); reads go through an immutable snapshot per commit (studio.snapshot), so a graph that loaded take 03 keeps
seeing take 03 while take 04 commits. Pieces are named `studio@sha:path` (a file in that studio's tree at sha, or a
stored plate beside it whose manifest row was made at sha). Boxes are `[x, y, w, h]` frame fractions everywhere;
only Locate's raw Gemini output uses `box_2d` on 0-1000.

  SCENE.json   {name, aspect, base: {studio, ref, view, ...}, slots: [{id, role, kind: object|flat, studio, piece,
                noun, place: {anchor, line, box | boxes}, ...}], chosen?: "NN" (the take the scene stands on; the set
                opens there instead of on the newest take)}
  takes/NN/    image.jpg, cast.json {slot: piece}, boxes.json (Locate's output), take.json {op, parent, swapped, ...}

A cast change (Cast) lives only on the graph until a take commits it: swaps stay pending until a re-shoot.
"""
import contextlib, copy, functools, hashlib, io, json, os, pathlib, re, shutil, subprocess, urllib.error, urllib.request

HOME = pathlib.Path(os.environ.get("BOSON_HOME") or pathlib.Path.home() / ".cache" / "boson")   # $BOSON_HOME moves every cache (the tests point it at a tmp dir)

try:
    from . import grid as gr, studio as st
except ImportError:  # imported as a plain module (tests, tools/)
    import grid as gr, studio as st

SCENES = HOME / "scenes"
SHOTS = HOME / "shots"
LOCATE_CACHE = HOME / "locate"
ROOTS = [pathlib.Path(__file__).resolve().parents[1] / "examples", SCENES]
LOCATE_MODEL = "gemini-3.8-flash"
JPEG_Q = 92
NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
STAND_IN = {"car": "car outline", "figure": "figure", "box": "outline"}


# ---- the repo -------------------------------------------------------------------------------------------

def registry(roots=None):
    """name -> source for every scene: `*-scene.bundle` (name without -scene) and repo dirs holding SCENE.json
    under the roots ($BOSON_SCENES, os.pathsep-separated, else examples/ then the clone cache). A bundle wins."""
    env = os.environ.get("BOSON_SCENES")
    roots = roots or ([pathlib.Path(p).expanduser() for p in env.split(os.pathsep)] if env else ROOTS)
    out = {}
    for root in map(pathlib.Path, roots):
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*-scene.bundle")):
            out.setdefault(p.name[:-len("-scene.bundle")], str(p))
        for p in sorted(root.iterdir()):
            if (p / ".git").exists() and (p / "SCENE.json").exists():
                out.setdefault(p.name[:-len("-scene")] if p.name.endswith("-scene") else p.name, str(p))
    return out


def named(repo):
    """A registry name -> its source (examples/NAME on this box, examples/NAME*.bundle in a clone); a path as given."""
    s = str(repo)
    return registry().get(s, s) if s and "/" not in s and not s.endswith(".bundle") else repo


def open_repo(repo):
    """A scene repo path, or a .bundle (a shipped fixture) cloned once into the scene cache; or a registry name
    (shipped workflows name their scene, so they load in any clone)."""
    repo = pathlib.Path(named(repo)).expanduser().resolve()
    if repo.suffix == ".bundle":
        work = SCENES / repo.stem
        if not (work / ".git").exists():   # clone beside it, then rename: two first requests never race one clone
            SCENES.mkdir(parents=True, exist_ok=True)
            tmp = SCENES / f".{repo.stem}.clone-{os.getpid()}-{id(repo)}"
            subprocess.run(["git", "clone", "-q", "-b", "main", str(repo), str(tmp)], check=True)
            try:
                tmp.rename(work)
            except OSError:                 # the other request won: its clone is the same bundle
                shutil.rmtree(tmp, ignore_errors=True)
        return work
    return repo


def load(repo, ref="main"):
    """-> SCENE dict: repo, ref, sha, dir (snapshot), branch, source, spec (SCENE.json at sha, validated), takes."""
    source = str(pathlib.Path(named(repo)).expanduser())
    repo = open_repo(repo)
    sha = st.resolve(repo, ref)
    branch = ref if ref and st.git(repo, "branch", "--list", ref) else None
    d = st.snapshot(repo, sha)
    spec = validate(json.loads((d / "SCENE.json").read_text()))
    tk = sorted(p.name for p in (d / "takes").iterdir() if (p / "take.json").exists()) if (d / "takes").is_dir() else []
    cl = sorted(p.name for p in (d / "clips").iterdir() if (p / "clip.json").exists()) if (d / "clips").is_dir() else []
    return {"repo": str(repo), "ref": ref, "sha": sha, "dir": str(d), "branch": branch, "source": source,
            "spec": spec, "takes": tk, "clips": cl}


def validate(spec):
    """Refuse a SCENE.json Compile could not read unambiguously; fill the optional slot fields' defaults."""
    for k in ("name", "aspect", "base", "slots"):
        if k not in spec:
            raise ValueError(f"SCENE.json: missing {k}")
    for k in ("studio", "ref", "view"):
        if k not in spec["base"]:
            raise ValueError(f"SCENE.json base: missing {k}")
    if "chosen" in spec and not re.fullmatch(r"\d{2,4}", str(spec["chosen"])):
        raise ValueError("SCENE.json chosen: a take id like \"06\"")
    anchors, seen = spec["base"].get("anchors", {}), set()
    for s in spec["slots"]:
        miss = {"id", "role", "kind", "studio", "piece", "noun", "place"} - s.keys()
        if miss:
            raise ValueError(f"slot {s.get('id')}: missing {sorted(miss)}")
        if s["id"] in seen or s["id"] == "world" or s["id"].startswith("anchor:"):
            raise ValueError(f"slot id {s['id']!r}: duplicate or reserved")
        seen.add(s["id"])
        if s["kind"] not in ("object", "flat"):
            raise ValueError(f"slot {s['id']}: kind is object or flat")
        a = s["place"].get("anchor")
        if a and a not in anchors:
            raise ValueError(f"slot {s['id']}: anchor {a!r} is not in base.anchors")
        boxes = s["place"].get("boxes") if s["kind"] == "flat" else [s["place"].get("box")]
        if not boxes or any(not b or len(b) != 4 or not all(0 <= v <= 1 for v in b) or b[0] + b[2] > 1 or b[1] + b[3] > 1
                            for b in boxes):
            raise ValueError(f"slot {s['id']}: place.{'boxes' if s['kind'] == 'flat' else 'box'} must be [x, y, w, h] fractions")
        parse_piece(s["piece"])
        s.setdefault("short", re.sub(r"^(the|a|an) ", "", s["noun"]))
        s.setdefault("desc", s["noun"])
        if s["kind"] == "flat":
            s.setdefault("count", len(s["place"]["boxes"]))
            s.setdefault("aspect", "2:3")
            s.setdefault("plural", s["short"] + "s")
        else:
            s.setdefault("stand_in", "box")
    return spec


def create(path, spec, msg="scene: SCENE.json"):
    """A new scene repo at path from a SCENE.json dict. -> SCENE @ its first commit."""
    repo = pathlib.Path(path).expanduser()
    if (repo / ".git").exists():
        raise RuntimeError(f"{repo} is already a scene")
    validate(copy.deepcopy(spec))
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "SCENE.json").write_text(json.dumps(spec, indent=1) + "\n")
    st.git(repo, "init", "-q", "-b", "main")
    st.git(repo, "add", "SCENE.json")
    st.git(repo, "commit", "-q", "-m", msg)
    return load(repo, "main")


def spec_from_piece(name, ref, aspect=None):
    """A SCENE.json with one piece as its base view and no slots yet (+ New scene from a piece)."""
    import math
    from PIL import Image
    studio, sha, path = parse_piece(ref)
    if aspect is None:
        w, h = Image.open(piece(ref)).size
        g = math.gcd(w, h)
        aspect = f"{w // g}:{h // g}"
    return {"name": name, "aspect": aspect, "base": {"studio": studio, "ref": sha, "view": path}, "slots": []}


def view_path(scene, bs=None):
    """The base view on disk: a file in the base studio at base.ref, else a stored plate made at that ref."""
    b = scene["spec"]["base"]
    f = pathlib.Path((bs or base(scene))["dir"]) / b["view"]
    return f if f.is_file() else piece(f"{b['studio']}@{b['ref']}:{b['view']}")


# ---- a save's writes, undone when it fails (N10: a failed save never strands the scene) ---------------------------

def _mark(repo):
    return pathlib.Path(st.git(repo, "rev-parse", "--absolute-git-dir")) / "boson-saving.json"


def _dirty(repo):
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True)
    if r.returncode:                                     # raw, not st.git: its strip() eats the first line's status column
        raise RuntimeError(f"git status: {r.stderr.strip()}")
    return [ln[3:].strip('"') for ln in r.stdout.splitlines() if ln]


def _put_back(repo, paths):
    """paths (relative) as at HEAD: unstaged, a tracked file back to its bytes, a new take or clip dir gone. -> True
    once nothing is dirty (a locked index keeps them staged: the next save's clear_leftovers finishes it)."""
    try:
        st.git(repo, "reset", "-q", "--", *paths)
    except RuntimeError:                                 # the index is locked: files only, the next save finishes it
        pass
    for p in paths:
        f, r = repo / p, subprocess.run(["git", "-C", str(repo), "cat-file", "blob", f"HEAD:{p}"], capture_output=True)
        if not r.returncode:                             # tracked: its bytes at HEAD (read only, works under a lock)
            f.write_bytes(r.stdout)
        elif f.is_dir():
            shutil.rmtree(f)
        elif f.exists():
            f.unlink()
        if f.parent != repo and f.parent.is_dir() and not any(f.parent.iterdir()):
            f.parent.rmdir()                             # the takes/ or clips/ dir this save made
    try:
        return not _dirty(repo)
    except RuntimeError:
        return False


def clear_leftovers(repo):
    """What a save that was cut off left (SCENE.json, its takes/NN or clips/NN, named in the mark it wrote) is put back,
    only if nothing else in the scene is dirty: an edit the owner made is never touched (writable refuses it)."""
    m = _mark(repo)
    if not m.exists():
        return
    paths = json.loads(m.read_text())
    under = lambda f: any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths)
    if all(under(f) for f in _dirty(repo)) and _put_back(repo, paths):
        m.unlink()


@contextlib.contextmanager
def _saving(scene, *paths):
    """Around one save that writes paths (relative to the scene repo): leftovers of an earlier cut-off save cleared
    first, then writable; a mark names the paths while it runs; if the save raises before its commit lands, the working
    tree goes back as it was, so the next save is not refused for uncommitted changes. -> (repo, branch)."""
    clear_leftovers(pathlib.Path(scene["repo"]))
    repo, branch = st.writable(scene)
    m = _mark(repo)
    m.write_text(json.dumps(list(paths)))
    try:
        yield repo, branch
    except BaseException:
        if st.resolve(repo, "HEAD") == scene["sha"] and _put_back(repo, paths):
            m.unlink(missing_ok=True)
        raise
    m.unlink(missing_ok=True)


def take(scene, tid):
    """One committed take: {id, op, parent, swapped, cast, boxes, image (path in the snapshot), ...}."""
    d = pathlib.Path(scene["dir"]) / "takes" / tid
    if not (d / "take.json").exists():
        raise KeyError(f"scene {scene['spec']['name']} @ {scene['sha'][:8]} has no take {tid}")
    t = json.loads((d / "take.json").read_text())
    if t.get("renderer") is None and t.get("op") in ("shoot", "swap"):   # committed through the graph, before 10-24
        t["renderer"] = plate_renderer(scene, t.get("located_hash"))
    t.update(id=tid, cast=json.loads((d / "cast.json").read_text()),
             boxes=json.loads((d / "boxes.json").read_text()) if (d / "boxes.json").exists() else None,
             image=str(d / "image.jpg"))
    return t


def plate_renderer(scene, h):
    """The renderer on the base studio's stored shot plate with these pixels (Nano Banana's manifest line), else None:
    how a take committed through the graph (Nano Banana -> Locate -> Commit Take) knows what made it."""
    try:
        m = gr.plates_dir(st.find(scene["spec"]["base"]["studio"])) / "manifest.jsonl"
    except KeyError:
        return None
    return _shot_renderers(str(m), m.stat().st_mtime if m.exists() else 0).get(h) if h else None


@functools.lru_cache(maxsize=8)
def _shot_renderers(manifest, mtime):
    """manifest.jsonl -> {image_hash of each shot-* plate on disk: its renderer}. Cached per file and mtime."""
    from PIL import Image
    p, out = pathlib.Path(manifest), {}
    for line in (p.read_text().splitlines() if mtime else []):
        r = json.loads(line) if line.strip() else {}
        f = p.parent / r.get("file", "")
        if str(r.get("round", "")).startswith("shot-") and f.is_file():
            out[image_hash(Image.open(f))] = r.get("renderer")
    return out


def clip(scene, cid):
    """One committed clip: {id, take, prompt, renderer, hash, video (path in the snapshot)}."""
    d = pathlib.Path(scene["dir"]) / "clips" / cid
    if not (d / "clip.json").exists():
        raise KeyError(f"scene {scene['spec']['name']} @ {scene['sha'][:8]} has no clip {cid}")
    c = json.loads((d / "clip.json").read_text())
    c.update(id=cid, video=str(d / "clip.mp4"))
    return c


def commit_clip(scene, video_file, take_id, prompt, renderer=""):
    """Commit one clip made from take `take_id`: clips/NN/{clip.mp4, clip.json}. A clip is a commit, never
    rewritten; the same bytes again return the clip already committed. -> (SCENE @ new commit, clip id)."""
    data = pathlib.Path(video_file).read_bytes()
    h = hashlib.sha256(data).hexdigest()[:16]
    for cid in scene.get("clips", []):
        if clip(scene, cid).get("hash") == h:
            return scene, cid
    if take_id and take_id not in scene["takes"]:
        raise KeyError(f"no take {take_id} in scene {scene['spec']['name']}: a clip moves a committed take")
    cid = f"{len(scene.get('clips', [])) + 1:02d}"
    with _saving(scene, f"clips/{cid}") as (repo, branch):
        d = repo / "clips" / cid
        d.mkdir(parents=True)
        (d / "clip.mp4").write_bytes(data)
        meta = {"take": take_id or None, "prompt": prompt, "renderer": renderer, "hash": h, "bytes": len(data)}
        (d / "clip.json").write_text(json.dumps(meta, indent=1) + "\n")
        st.git(repo, "add", "--", str(d))
        st.git(repo, "commit", "-q", "-m", f"clip {cid}: take {take_id or '-'} set in motion", "-m", renderer or "")
    return load(repo, branch), cid


def last_shoot(scene):
    """The newest take a Swap may edit: a shoot or an imported take, never a swap (edits are never chained)."""
    for tid in reversed(scene["takes"]):
        t = take(scene, tid)
        if t["op"] in ("shoot", "import"):
            return t
    return None


def swap_parent(scene):
    """The take a Swap edits: the scene's chosen take (SCENE.json chosen, the take it stands on) or the newest shoot,
    whichever is newer. Swaps of the chosen take move chosen along (commit_take), so a run of swaps changes one thing
    each and keeps every earlier swap's pixels (round 49: the awning stayed put while the car changed); a new shoot
    starts a fresh line. No chosen take: the newest shoot, as before."""
    par, ch = last_shoot(scene), scene["spec"].get("chosen")
    if ch in scene["takes"] and (par is None or int(ch) > int(par["id"])):
        return take(scene, ch)
    return par


def choose(scene, tid):
    """Use this take: SCENE.json chosen = tid and the cast back to the one tid was shot with, so the next Swap edits
    tid (swap_parent) and changes only what is cast after. One commit, nothing deleted (every take stays history);
    Undo swap is this, pointed at the swap's parent. A slot made from the frame after tid holds the base again.
    Gap: swap_parent still prefers a shoot newer than tid. -> SCENE @ the new commit; already so: nothing committed."""
    t = take(scene, tid)
    spec = copy.deepcopy(scene["spec"])
    was = {x["id"]: x for x in t.get("slots") or []}
    for s in spec["slots"]:
        if s["id"] in was or s["id"] in t["cast"]:
            w = was.get(s["id"]) or {"piece": t["cast"][s["id"]]}
            if s["piece"] != w["piece"]:
                s["piece"] = w["piece"]
                if w["piece"] != base_piece(spec):
                    s["studio"] = parse_piece(w["piece"])[0]
                s["short"] = w.get("short") or re.sub(r"^(the|a|an) ", "", s["noun"])
                s["desc"] = w.get("desc") or " ".join(x for x in (s["noun"], s.get("where", "")) if x)
        elif s.get("from") and not uncast(spec, s):
            s["piece"], s["short"] = base_piece(spec), re.sub(r"^(the|a|an) ", "", s["noun"])
            s["desc"] = (s["base_desc"] if s["from"].startswith("anchor:")
                         else " ".join(x for x in (s["noun"], s.get("where", "")) if x))
    spec["chosen"] = t["id"]
    if spec == scene["spec"]:
        return scene
    with _saving(scene, "SCENE.json") as (repo, branch):
        (repo / "SCENE.json").write_text(json.dumps(spec, indent=1) + "\n")
        st.git(repo, "add", "--", "SCENE.json")
        st.git(repo, "commit", "-q", "-m", f"scene: chosen take {t['id']} (use this take; the cast is take {t['id']}'s)")
    return load(repo, branch)


def cast_of(spec):
    return {s["id"]: s["piece"] for s in spec["slots"]}


def cast(scene, slot, piece, desc="", short=""):
    """A new SCENE dict with `slot` cast to `piece` (nothing committed: the cast reaches the repo with the next
    take). desc/short describe the new piece for Locate and the prompt; left empty they fall back to the noun.
    A piece from another studio moves the slot to that studio (plug and play, round 49): the HUD, the shelf and the
    committed SCENE.json then name the studio that made what is in the frame."""
    piece = piece.strip()
    if not piece:
        return scene
    studio = parse_piece(piece)[0]
    new = copy.deepcopy(scene)
    s = next((x for x in new["spec"]["slots"] if x["id"] == slot), None)
    if s is None:
        raise KeyError(f"no slot {slot!r} (have {', '.join(x['id'] for x in new['spec']['slots'])})")
    if s["piece"] != piece:
        s["piece"], s["studio"] = piece, studio
        s["short"] = short.strip() or re.sub(r"^(the|a|an) ", "", s["noun"])
        s["desc"] = desc.strip() or " ".join(x for x in (s["noun"], s.get("where", "")) if x)
    return new


def _rename(text, word, called):
    """Every 'the WORD' / 'WORD' in a base prose line -> called (capitalised at a sentence start)."""
    bare = re.sub(r"^(the|a|an) ", "", called)
    text = re.sub(rf"\b[Tt]he {re.escape(word)}\b", lambda m: called[:1].upper() + called[1:] if m.group(0)[0] == "T" else called, text)
    return re.sub(rf"\b{re.escape(word)}\b", bare, text)


def promote(scene, slot, studio, noun, anchor="", box=None, where="", called="", role=""):
    """Make a slot from the frame (round 49): something the base view shows and no slot holds yet (the taqueria) becomes
    a slot another studio can fill. anchor: a base anchor; the slot takes its description and its box from the newest
    take Locate saw it in, and the anchor leaves base.anchors (a slot and an anchor never share one thing). box: [x, y,
    w, h] fractions instead. The slot holds the base's own pixels (base_piece) until a piece is cast: a Shoot draws no
    stand-in for it, a Swap edits nothing there. called: what the base prose (lock_edges, handed) calls it from now on;
    default the noun. Commits SCENE.json. -> SCENE @ the new commit; the same slot again commits nothing."""
    spec = copy.deepcopy(scene["spec"])
    b, slot = spec["base"], slot.strip()
    if any(s["id"] == slot for s in spec["slots"]):
        return scene
    anchors, desc = b.get("anchors", {}), ""
    if anchor:
        if anchor not in anchors:
            raise KeyError(f"no anchor {anchor!r} (have {', '.join(anchors) or 'none'})")
        if any(s["place"].get("anchor") == anchor for s in spec["slots"]):
            raise ValueError(f"slot {', '.join(s['id'] for s in spec['slots'] if s['place'].get('anchor') == anchor)} "
                             f"is placed by {anchor}: it stays an anchor")
        desc = anchors.pop(anchor)
        if box is None:
            for tid in reversed(scene["takes"]):
                a = ((take(scene, tid).get("boxes") or {}).get("anchors") or {}).get(anchor)
                if a and a.get("box"):
                    box = a["box"]
                    break
        called = called.strip() or noun
        for k in ("lock_edges", "lock_edges_short", "handed", "handed_short"):
            if b.get(k):
                b[k] = _rename(b[k], anchor, called)
    if not box:
        raise ValueError("where is it: an anchor Locate has seen, or a box [x, y, w, h]")
    box = [round(min(1.0, max(0.0, v)), 3) for v in box]
    noun = noun.strip()
    s = {"id": slot, "role": role.strip() or re.sub(r"^(the|a|an) ", "", noun).capitalize(), "kind": "object",
         "studio": studio.strip(), "piece": base_piece(spec), "noun": noun,
         "short": re.sub(r"^(the|a|an) ", "", noun), "where": where.strip(),
         "desc": desc or " ".join(x for x in (noun, where.strip()) if x), "base_desc": desc or noun,
         "stand_in": "box", "from": f"anchor:{anchor}" if anchor else "box",
         "place": {"line": f"in place of {desc or noun}, the same place, size and angle"
                           + (f", {where.strip()}" if where.strip() else ""), "box": box}}
    spec["slots"].append(s)
    validate(copy.deepcopy(spec))
    with _saving(scene, "SCENE.json") as (repo, branch):
        (repo / "SCENE.json").write_text(json.dumps(spec, indent=1) + "\n")
        st.git(repo, "add", "--", "SCENE.json")
        st.git(repo, "commit", "-q", "-m", f"slot {slot}: made from the frame ({s['from']}), {s['studio']} fills it")
    return load(repo, branch)


def unpromote(scene, slot):
    """Remove a slot made from the frame (promote's undo, the app's Remove this slot): it is part of the base again.
    An anchor's words come back, and the base prose as it read before the slot was made, from that commit's parent
    (exact, so Locate's prompt and every stored key read as before), unless edited since. Takes stay history. A slot
    the scene came with is refused, and so is one whose piece is in the take the scene stands on (the pixels would stay).
    Commits SCENE.json. -> SCENE @ the new commit."""
    spec = copy.deepcopy(scene["spec"])
    s = next((x for x in spec["slots"] if x["id"] == slot), None)
    if s is None:
        raise KeyError(f"no slot {slot!r} (have {', '.join(x['id'] for x in spec['slots'])})")
    if not s.get("from"):
        raise ValueError(f"the {slot} came with the scene: only a slot made from the frame can be removed")
    if s["piece"] != base_piece(spec):                    # its piece would stay in the pixels while the slot goes (N11)
        raise ValueError(f"slot {slot} holds {s['piece']} in the take the scene stands on: undo or swap it back first")
    spec["slots"].remove(s)
    repo = pathlib.Path(scene["repo"])
    made = next((ln.split(" ", 1)[0] for ln in st.git(repo, "log", "--format=%H %s", scene["sha"]).splitlines()
                 if ln.split(" ", 1)[1].startswith(f"slot {slot}: made from the frame")), None)
    if s["from"].startswith("anchor:"):
        a, b = s["from"][7:], spec["base"]
        try:
            was = json.loads(st.git(repo, "show", f"{made}^:SCENE.json"))["base"] if made else {}
            then = json.loads(st.git(repo, "show", f"{made}:SCENE.json"))["base"] if made else {}
        except (RuntimeError, ValueError):
            was, then = {}, {}
        have = {**b.get("anchors", {}), a: (was.get("anchors") or {}).get(a) or s["base_desc"]}
        order = [k for k in (was.get("anchors") or {}) if k in have] + [k for k in have if k not in (was.get("anchors") or {})]
        b["anchors"] = {k: have[k] for k in order}
        for k in ("lock_edges", "lock_edges_short", "handed", "handed_short"):
            if k in was and b.get(k) == then.get(k):
                b[k] = was[k]
    validate(copy.deepcopy(spec))
    with _saving(scene, "SCENE.json") as (repo, branch):
        (repo / "SCENE.json").write_text(json.dumps(spec, indent=1) + "\n")
        st.git(repo, "add", "--", "SCENE.json")
        st.git(repo, "commit", "-q", "-m", f"slot {slot}: removed ({s['from']}), part of the base again")
    return load(repo, branch)


def pending(scene):
    """Slot ids whose piece differs from SCENE.json at the loaded commit: cast on the graph, not yet shot."""
    d = json.loads((pathlib.Path(scene["dir"]) / "SCENE.json").read_text())
    return [i for i, p in cast_of(scene["spec"]).items() if cast_of(d).get(i) != p]


def swapped_since(scene, parent):
    """Slot ids whose piece differs from what `parent` (a take) was shot with: what one Swap edit applies."""
    spec = scene["spec"]               # a slot made from the frame after parent was shot: uncast, nothing to apply
    return [s["id"] for s in spec["slots"] if parent["cast"].get(s["id"]) != s["piece"] and
            not (s["id"] not in parent["cast"] and uncast(spec, s))]


# ---- pieces ----------------------------------------------------------------------------------------------

def parse_piece(ref):
    m = re.fullmatch(r"([\w.\-]+)@([0-9a-f]{4,40}):(.+)", ref.strip())
    if not m:
        raise ValueError(f"piece {ref!r}: write studio@sha:path")
    if m.group(3).startswith("/") or ".." in pathlib.PurePosixPath(m.group(3)).parts:
        raise ValueError(f"piece {ref!r}: the path stays inside the studio")
    return m.groups()


def piece(ref):
    """studio@sha:path -> the file on disk. A file in the studio's tree at sha, else a stored plate whose manifest
    row (file == path) was made at sha. Refuses anything else: a piece always names the commit that made it."""
    name, sha, path = parse_piece(ref)
    s = st.load(st.find(name), sha)
    f = pathlib.Path(s["dir"]) / path
    if f.is_file():
        return f
    made = st.piece_sha(s, path)
    if made != s["sha"]:
        raise ValueError(f"piece {ref}: {path} was made at {made[:8]}, not {sha}")
    src = pathlib.Path(s["source"])
    f = src.parent / f"{src.name.split('.')[0]}-plates" / path
    if not f.is_file():
        raise FileNotFoundError(f"piece {ref}: the plate is not on this machine ({f})")
    return f


def base(scene):
    b = scene["spec"]["base"]
    return st.load(st.find(b["studio"]), b["ref"])


# ---- Compile Scene: SCENE.json -> (images[], prompt), deterministic, no model ----------------------------

def _f(v):
    return f"{v:.2f}"


def _span(b):
    return f"x {_f(b[0])}-{_f(b[0] + b[2])}, y {_f(b[1])}-{_f(b[1] + b[3])}"


def _cap(s):
    return s[:1].upper() + s[1:]


def base_piece(spec):
    """The base view as a piece ref: what a slot made from the frame holds until another studio's piece is cast."""
    b = spec["base"]
    return f"{b['studio']}@{b['ref']}:{b['view']}"


def objects(spec):
    """Object slots that carry a piece of their own. A slot made from the frame and not cast yet is still the base's
    pixels (promote): the plate draws no stand-in for it and no image is sent; Locate still finds it."""
    return [s for s in spec["slots"] if s["kind"] == "object" and not uncast(spec, s)]


def uncast(spec, s):
    """A slot made from the frame (promote) that no studio has filled yet: it still holds the base's pixels."""
    return bool(s.get("from")) and s["piece"] == base_piece(spec)


def shoot_prompt(spec, house, take_text=""):
    """The Shoot prompt (v4 prompt-architecture §4): LOCK, IMAGES, SLOTS, WORLD, TAKE, REFUSE, LOCK. Everything
    outside the TAKE block is a pure function of SCENE.json and the base studio's house, so two takes of one cast
    differ only where they are meant to. An empty take_text leaves `<<TAKE>>` for the base studio's writer."""
    b = spec["base"]
    vn, subj, edges = b.get("view_noun", "model view"), b.get("subject", "building"), b.get("lock_edges", "edge")
    handed = (" " + b["handed"]) if b.get("handed") else ""
    lock = (f"Re-render image 1, the {vn}, as {b.get('medium', 'a photograph')} with its identical camera: the same "
            f"position, height, direction and lens, every {edges} at the same place and size in the frame.{handed} "
            f"Nothing added to the {subj}, no pulling back, no mirror image.")
    obj = objects(spec)
    images = f"Image 1 is the {vn} with simple grey stand-ins drawn where each cast piece goes." + "".join(
        f" Image {n} is {s['noun']}." for n, s in enumerate(obj, 2)) + " The stand-ins show only where; the pieces show what."
    slots = []
    for s in spec["slots"]:
        p = s["place"]
        if s["kind"] == "object" and s not in obj:   # made from the frame, not cast: the base shows it as it is
            continue
        if s["kind"] == "object":
            n = obj.index(s) + 2
            carrier = f"{s['carrier']}, " if s.get("carrier") else ""
            slots.append(f"{_cap(s['noun'])} in image {n}, exactly that {s['short']}, {carrier}{p['line']}, where image "
                         f"1's stand-in {STAND_IN.get(s['stand_in'], 'outline')} is ({_span(p['box'])}, about "
                         f"{round(p['box'][3] * 100)} percent of the frame height); keep its shape, colour and "
                         "proportions, photographed in this light.")
        else:
            c = s["count"]
            what = s["plural"] if c > 1 else s["short"]
            slots.append(f"{_cap(NUM[c] if c < 10 else str(c))} plain {s['aspect']} paper {what} {p['line']}, where image "
                         f"1's pale rectangle{'s are' if c > 1 else ' is'}; show {'them' if c > 1 else 'it'} blank or "
                         f"with an unreadable smudge of colour: {'their' if c > 1 else 'its'} artwork is added afterwards.")
    world = " ".join(x for x in [house["ours"], b.get("materials", ""), *house.get("style_lines", [])] if x)
    refuse = ("Not " + ", not ".join(r[:1].lower() + r[1:] for r in house["refusals"]) + ". " if house["refusals"] else "")
    refuse += "No lettering except what this names."
    hs = f" {b['handed_short']}," if b.get("handed_short") else ""
    lock2 = (f"Lock, repeated: the identical camera of image 1,{hs} every {edges} at the same place and size; the "
             f"stand-ins become the pieces, nothing else is added to the {subj}.")
    return "\n\n".join([lock, images, " ".join(slots), world, take_text.strip() or "<<TAKE>>", refuse, lock2])


def swap_prompt(spec, parent, swapped):
    """The Swap prompt (§6): an edit of the parent take, image 1, naming only the swapped object slots, each at its
    Locate box from that take (the take may have drifted from SCENE.json). Flat swaps need no call: ''."""
    b, obj = spec["base"], [s for s in objects(spec) if s["id"] in swapped]
    if not obj:
        return ""
    old = {x["id"]: x for x in parent.get("slots_spec", [])}
    parts = [f"Edit image 1, a photograph; change only what this names and keep every other pixel as it is: the same "
             f"camera, {b.get('subject', 'building')}, sky, light, shadows, people and street."]
    for n, s in enumerate(obj, 2):
        box = _parent_box(parent, s)
        if s.get("carrier"):   # a worn piece: dress the same person; "replace X with" swapped the wearer (2026-10-21)
            parts.append(f"Dress {s['desc']} (the box {_span(box)} of image 1) in {s['noun']} from image {n}, exactly that "
                         f"{s['short']}: the same person, in the same pose, facing the same way, at the same place and "
                         "size; only what they wear changes, lit by the same sun.")
            continue
        was = (old.get(s["id"]) or {}).get("desc") or s.get("base_desc") or s["desc"]
        keep = f", {s['place']['swap_line']}" if s["place"].get("swap_line") else ""   # e.g. the lane (clip 05)
        parts.append(f"Replace {was} (the box {_span(box)} of image 1) with "
                     f"{s['noun']} in image {n}, exactly that {s['short']}, at the same place, size and angle{keep}, lit "
                     "by the same sun and casting the same kind of shadow on the same ground.")
    parts.append("Nothing else changes.")
    return " ".join(parts)


def _parent_box(parent, s):
    """A slot's Locate box in the parent take, else its SCENE.json place box (the take may have drifted)."""
    lb = ((parent.get("boxes") or {}).get("slots", {}).get(s["id"]) or {})
    return lb.get("box") if lb.get("visible") else s["place"]["box"]


NB_ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")


def worn_crop(box, frame, wide=3.0, tall=1.4):
    """The close crop for a worn swap: the wearer's box widened to wide x its width and tall x its height around its
    centre, grown to the nearest aspect Nano Banana renders, shifted inside the frame. -> (box in fractions, aspect)."""
    W, H = frame
    x, y, w, h = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    cw, ch = w * wide, h * tall
    aspect = min(NB_ASPECTS, key=lambda a: abs(aspect_of(a) - cw / ch))
    a = aspect_of(aspect)
    cw, ch = (ch * a, ch) if cw / ch < a else (cw, cw / a)
    cw, ch = min(cw, W), min(ch, H)
    x0 = min(max(0, x + w / 2 - cw / 2), W - cw)
    y0 = min(max(0, y + h / 2 - ch / 2), H - ch)
    return [x0 / W, y0 / H, cw / W, ch / H], aspect


def worn_crop_prompt(s):
    """The Swap prompt for a worn slot edited on a close crop (1a, 2026-10-21): the full-frame edit let the outfit
    photo's model take over the wearer's pose and face; the crop leaves the model only the clothes to change. 'same
    pose and facing' still turned the torso to camera (takes 10-15): the side view is named outright."""
    return (f"Edit image 1, a close crop of a street photograph. The person in the middle now wears {s['noun']} from "
            f"image 2, exactly that {s['short']}, the same colours and details. They stay the same person, with the "
            "same face, hair, build and pose, at the same place and size in the frame, lit by the same sun. Keep their "
            "side view: the body, shoulders, hips and head stay turned the same way as in image 1, in profile, not "
            "toward the camera. Use image 2 only for the clothes, not its person or pose. Keep everything else as it "
            "is: background, light and shadows.")


def _box_blur(a, r):
    """Mean over a (2r+1)^2 window, edges clamped (numpy only: ComfyUI's venv has no OpenCV)."""
    import numpy as np
    p = np.pad(a, [(r + 1, r), (r + 1, r)] + [(0, 0)] * (a.ndim - 2), mode="edge").cumsum(0).cumsum(1)
    n = 2 * r + 1
    return (p[n:, n:] - p[:-n, n:] - p[n:, :-n] + p[:-n, :-n]) / (n * n)


def fill_holes(rgb, hole):
    """The parent with the hole (bool HxW) filled from the pixels around it, growing inward at widening radii
    (normalised box blur). Used under the new subject: where the old wearer was wider, background shows, never them."""
    import numpy as np
    img, known = np.asarray(rgb, dtype=np.float64).copy(), ~hole
    r = 1
    while not known.all() and r < max(hole.shape):
        k = known.astype(np.float64)
        num, den = _box_blur(img * k[..., None], r), _box_blur(k, r)
        take = ~known & (den > 0.05)
        img[take] = num[take] / den[take][:, None]
        known = known | take
        r *= 2
    return img.round().clip(0, 255).astype(np.uint8)


def pick_subject(mask, hint):
    """The mask's shapes (L > 64, 8-connected) that overlap hint, a (x0, y0, x1, y1) pixel box; the rest go to 0. No
    hint, or nothing in it: the mask as it is (BiRefNet's own pick)."""
    if not hint:
        return mask
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(mask)
    lab, n = ndimage.label(a > 64, structure=np.ones((3, 3)))
    x0, y0, x1, y1 = (max(0, v) for v in hint)
    keep = np.unique(lab[y0:y1, x0:x1])
    keep = keep[keep > 0]
    return mask if not len(keep) else Image.fromarray(np.where(np.isin(lab, keep), a, 0).astype(np.uint8))


def uncrop(parent, edit, box, feather=0.08, inner=None, mask=None, before=None, wearer=None):
    """Paste an edited crop back into the parent frame at box (fractions), resized to the crop's pixels and blended in
    over a feathered edge (feather = fraction of the crop's short side). inner (a frame box) keeps only that part of
    the edit, so drift in the crop's background is dropped. mask (an L image over the edit, 255 = subject, see
    subject_masks) pastes the subject alone: the crop's own background never shows (operator rule, takes 08-09); the
    rectangle then only guards against a stray bystander. before (an L mask of the old wearer over the parent's crop)
    fills where they were from the background around them first, so a wider old outfit can't show past the new
    one (take 17's orange sleeve). wearer (the slot's frame box) names the subject, as CorridorKey's hint does: of each
    mask, only the shapes that touch it count, so a bystander BiRefNet also found is neither pasted nor erased. With
    a mask, the edge takes the subject's own colour grown out from inside it (CorridorKey's straight foreground), so
    the crop's background can't tint the fringe. -> a new image; the parent is untouched."""
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    out = parent.convert("RGB").copy()
    W, H = out.size
    x0, y0 = round(box[0] * W), round(box[1] * H)
    pw, ph = round(box[2] * W), round(box[3] * H)
    e = edit.convert("RGB").resize((pw, ph), Image.LANCZOS)
    f = max(1, round(feather * min(pw, ph)))
    r = (f, f, pw - 1 - f, ph - 1 - f)
    if inner:
        r = (max(r[0], round(inner[0] * W) - x0), max(r[1], round(inner[1] * H) - y0),
             min(r[2], round((inner[0] + inner[2]) * W) - x0), min(r[3], round((inner[1] + inner[3]) * H) - y0))
    alpha = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(alpha).rectangle(r, fill=255)
    hint = wearer and (round(wearer[0] * W) - x0, round(wearer[1] * H) - y0,
                       round((wearer[0] + wearer[2]) * W) - x0, round((wearer[1] + wearer[3]) * H) - y0)
    if before is not None:   # 2 px past the old silhouette, inside the guard box: their edge goes too
        old = pick_subject(before.convert("L").resize((pw, ph), Image.BILINEAR), hint).point(lambda v: 255 * (v > 64))
        hole = np.asarray(ImageChops.multiply(old.filter(ImageFilter.MaxFilter(5)), alpha)) > 0
        region = out.crop((x0, y0, x0 + pw, y0 + ph))
        out.paste(Image.fromarray(fill_holes(region, hole)), (x0, y0))
    if mask is None:
        alpha = alpha.filter(ImageFilter.GaussianBlur(f / 2))
    else:   # the downscale already anti-aliases the edge; a 1 px erode keeps the edit's background out of the fringe.
        # The rectangle only guards: blurred at f/2 it faded the soles to 0.8 and let the old shoes through (take 13)
        m = pick_subject(mask.convert("L").resize((pw, ph), Image.BILINEAR), hint)
        e = Image.fromarray(fill_holes(e, np.asarray(m) < 250))   # edge colour from the subject, not its background
        if before is None:   # over a filled background the erode only thinned the soles (takes 18-19)
            m = m.filter(ImageFilter.MinFilter(3))
        alpha = ImageChops.multiply(m, alpha.filter(ImageFilter.GaussianBlur(1)))
    out.paste(e, (x0, y0), alpha)
    return out


SEGMENT = pathlib.Path(__file__).resolve().parent / "segment.py"


def comfy_dir():
    """The ComfyUI to segment with: $COMFYUI_DIR, else the one running this pack, else ~/ComfyUI."""
    import sys
    if os.environ.get("COMFYUI_DIR"):
        return pathlib.Path(os.environ["COMFYUI_DIR"]).expanduser()
    fp = sys.modules.get("folder_paths")          # ComfyUI's own top-level module: its folder is ComfyUI's
    if getattr(fp, "__file__", None):
        return pathlib.Path(fp.__file__).resolve().parent
    m = sys.modules.get("comfy")                  # a namespace package: no __file__, but a __path__
    for d in list(getattr(m, "__path__", None) or []) + ([m.__file__] if getattr(m, "__file__", None) else []):
        p = pathlib.Path(d).resolve()
        return p.parent if p.is_dir() else p.parents[1]
    return pathlib.Path.home() / "ComfyUI"


def comfy_py():
    """Its python: the running interpreter inside ComfyUI (a clone's ComfyUI lives anywhere: rehearsal 2 failed on
    ~/ComfyUI/venv), else ComfyUI's venv."""
    import sys
    return pathlib.Path(sys.executable) if "comfy" in sys.modules else comfy_dir() / "venv" / "bin" / "python"


def comfy_on_cpu():
    """Was the ComfyUI running this pack started with --cpu? Then segment.py runs on the CPU too: a GPU-less machine
    failed every outfit swap with "No CUDA GPUs are available" (fresh clone, 2026-10-27)."""
    import sys
    a = getattr(sys.modules.get("comfy.cli_args"), "args", None)
    return bool(getattr(a, "cpu", False))


def subject_masks(paths):
    """BiRefNet subject masks (ComfyUI core's background-removal model, run by segment.py under ComfyUI's venv), one
    L image per path at its size, cached under SHOTS/masks by pixels. GPU 0 unless CUDA_VISIBLE_DEVICES says else."""
    from PIL import Image
    paths = [pathlib.Path(p) for p in paths]
    outs = [SHOTS / "masks" / f"{image_hash(Image.open(p))}.png" for p in paths]
    todo = [a for p, o in zip(paths, outs) if not o.exists() for a in (str(p), str(o))]
    if todo:
        outs[0].parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "0"),
               "COMFYUI_DIR": str(comfy_dir())}
        if comfy_on_cpu():
            env.setdefault("BOSON_SEG_DEVICE", "cpu")
        r = subprocess.run([str(comfy_py()), str(SEGMENT)] + todo, env=env, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"segment.py failed ({comfy_py()}):\n{r.stderr[-2000:]}")
    return [Image.open(o).convert("L") for o in outs]


GARMENT = ("Image 1 shows a person wearing an outfit. Show only that outfit: the same clothes, shoes and bag, exactly "
           "as they are (colours, fabric, cut, prints, details), laid out flat on a plain light grey background, seen "
           "straight on. No person, no body, no face, no mannequin, no street, and no glasses or anything else worn "
           "on the face.")


def garment(ref, gen=None):
    """A worn piece as clothes alone, one cached image call (SHOTS/garments, keyed by prompt + pixels): the outfit
    photo's own model carried its pose and face into the take, crop or not (takes 06-09). gen(prompt, out, refs)
    renders; default Nano Banana 2.1, 1:1, 1K. 'accessories' carried the outfit model's glasses onto the wearer
    (take 10's card): the card asks for clothes, shoes and bag, no glasses. -> the card's path."""
    out = SHOTS / "garments" / f"garment-{_key(GARMENT, [ref])}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if gen is None:
            try:
                from . import nanobanana as nbn
            except ImportError:
                import nanobanana as nbn
            gen = lambda prompt, o, refs: nbn.generate(prompt, o, refs, nbn.MODEL, "1:1", "1K")   # noqa: E731
        gen(GARMENT, out, [str(ref)])
    return out


def render_images(shot, gen=None):
    """A shot's images as the renderer sends them: a deferred garment card is made here (one cached image call), so
    only a live render can spend on it."""
    card = (shot.get("crop") or {}).get("card")
    ims = list(shot["images"])
    if card:
        ims[card["index"]] = str(garment(card["ref"], gen))
    return ims


def compile_shot(scene, mode="shoot", take_text="", draw_plate=True, crop_worn=False, card=None):
    """-> SHOT {mode, images: [paths], labels, prompt, key, parent, swapped}. Image order: image 1 = the blocking plate
    (shoot) or the parent take (swap), then each object slot's piece in SCENE.json order (swap: the swapped ones only).
    Flat slots send no image: their artwork is pasted onto the Locate quads afterwards (Paste Flat).
    crop_worn: a swap of one worn slot edits a close crop of the wearer instead (image 1 = the crop); the shot then
    carries crop {box, aspect, parent_image, wearer, inner}; the caller renders at that aspect and uncrop()s
    (mask + inner) before Locate.
    card (with crop_worn): image 2 is the garment() card instead of the outfit photo; card is that step's gen, or True
    for Nano Banana (one cached image call, the only one compile_shot can make), or "defer": image 2 stays the outfit
    photo and crop.card {ref, index} tells the renderer to swap in garment(ref) when it renders live (render_images).
    A shoot given card (gen or True, not "defer") sends every worn slot's garment() card in place of its photo too."""
    spec, crop = scene["spec"], None
    if mode == "shoot":
        bs = base(scene)
        prompt = shoot_prompt(spec, st.house(bs), take_text)
        obj, parent, swapped = objects(spec), None, None
        labels = ["plate"] + [s["id"] for s in obj]
        pieces = [piece(s["piece"]) for s in obj]
        if card and card != "defer":   # worn slots as clothes alone: the raw photo's model replaced the wearer (austin 01)
            pieces = [garment(p, None if card is True else card) if s.get("carrier") else p for s, p in zip(obj, pieces)]
            labels = ["plate"] + ["garment" if s.get("carrier") else s["id"] for s in obj]
        key = _key(prompt, pieces, extra=spec["base"]["view"] + json.dumps([s["place"] for s in spec["slots"]]))
        first = SHOTS / key / "plate.png"
        if draw_plate and not first.exists():
            first.parent.mkdir(parents=True, exist_ok=True)
            plate(spec, view_path(scene, bs)).save(first)
    elif mode == "swap":
        par = swap_parent(scene)
        if par is None:
            raise ValueError("nothing to swap into: the scene has no shoot take yet (Shoot first)")
        par["slots_spec"] = json.loads((pathlib.Path(scene["dir"]) / "takes" / par["id"] / "take.json").read_text()
                                       ).get("slots", [])
        swapped = swapped_since(scene, par)
        if not swapped:
            raise ValueError(f"no swaps since take {par['id']}: cast a slot first")
        obj = [s for s in objects(spec) if s["id"] in swapped]
        first, parent = pathlib.Path(par["image"]), par["id"]
        if crop_worn and len(obj) == 1 and obj[0].get("carrier"):
            from PIL import Image
            pil = Image.open(first)
            cbox, aspect = worn_crop(_parent_box(par, obj[0]), pil.size)
            prompt, pieces = worn_crop_prompt(obj[0]), [piece(obj[0]["piece"])]
            key = _key(prompt, [first] + pieces, extra=parent + json.dumps(cbox))
            x, y, w, h = _parent_box(par, obj[0])   # inner: the wearer's box padded, the paste's bystander guard
            crop = {"box": cbox, "aspect": aspect, "parent_image": str(first), "wearer": [x, y, w, h],
                    "inner": [x - 0.4 * w, y - 0.06 * h, 1.8 * w, 1.12 * h]}
            W, H = pil.size
            first = SHOTS / key / "crop.png"
            if not first.exists():
                first.parent.mkdir(parents=True, exist_ok=True)
                c = pil.convert("RGB").crop((round(cbox[0] * W), round(cbox[1] * H),
                                             round((cbox[0] + cbox[2]) * W), round((cbox[1] + cbox[3]) * H)))
                c.resize((round(1024 * c.width / max(c.size)), round(1024 * c.height / max(c.size))),
                         Image.LANCZOS).save(first)
            labels = [f"take {par['id']} crop", obj[0]["id"]]
            if card == "defer":   # the renderer makes the card, live only: the key can't wait for its pixels
                crop["card"] = {"ref": str(pieces[0]), "index": 1}
                labels[1], key = "garment (made at render)", _key(prompt, [first] + pieces, extra=GARMENT)
            elif card:   # key over the crop's pixels and the card's, as the runner keyed takes 10-15
                pieces, labels[1] = [garment(pieces[0], None if card is True else card)], "garment"
                key = _key(prompt, [first] + pieces)
        else:
            prompt = swap_prompt(spec, par, swapped)
            obj = obj if prompt else []
            labels = [f"take {par['id']}"] + [s["id"] for s in obj]
            pieces = [piece(s["piece"]) for s in obj]
            key = _key(prompt, [first] + pieces, extra=parent)
    else:
        raise ValueError("mode is shoot or swap")
    return {"mode": mode, "images": [str(first)] + [str(p) for p in pieces], "labels": labels, "prompt": prompt,
            "key": key, "parent": parent, "swapped": swapped, "scene": spec["name"],
            **({"crop": crop} if crop else {})}


def _key(prompt, files, extra=""):
    h = hashlib.sha256((prompt + "\0" + extra).encode())
    for f in files:
        h.update(hashlib.sha256(pathlib.Path(f).read_bytes()).digest())
    return h.hexdigest()[:16]


def aspect_of(a):
    w, h = (float(x) for x in a.split(":"))
    return w / h


def plate(spec, view_path):
    """The blocking plate: the base view at the scene aspect with each object slot drawn as a grey line stand-in at its
    box (car outline, standing figure or plain rectangle) and each flat slot as a pale rectangle. No labels, numbers
    or colours: anything drawn on image 1 can be rendered into the photograph."""
    from PIL import Image, ImageDraw
    im = Image.open(view_path).convert("RGB")
    W, H = im.size
    ar = aspect_of(spec["aspect"])
    if abs(W / H - ar) > 1e-3:   # centre-crop to the scene aspect
        cw, ch = (round(H * ar), H) if W / H > ar else (W, round(W / ar))
        im = im.crop(((W - cw) // 2, (H - ch) // 2, (W - cw) // 2 + cw, (H - ch) // 2 + ch))
        W, H = im.size
    d, lw, ink = ImageDraw.Draw(im), max(2, round(W / 600)), (96, 96, 96)
    for s in spec["slots"]:
        if s["kind"] == "object" and s not in objects(spec):
            continue
        if s["kind"] == "flat":
            for x, y, w, h in s["place"]["boxes"]:
                d.rectangle([x * W, y * H, (x + w) * W, (y + h) * H], fill=(238, 236, 228), outline=(140, 140, 140),
                            width=max(1, lw // 2))
            continue
        x, y, w, h = (v * k for v, k in zip(s["place"]["box"], (W, H, W, H)))
        if s["stand_in"] == "car":
            body = [(x, y + .55 * h), (x + .18 * w, y + .45 * h), (x + .32 * w, y + .12 * h), (x + .72 * w, y + .1 * h),
                    (x + .86 * w, y + .42 * h), (x + w, y + .5 * h), (x + w, y + .8 * h), (x, y + .8 * h)]
            d.line(body + [body[0]], fill=ink, width=lw, joint="curve")
            r = .13 * h
            for cx in (x + .2 * w, x + .8 * w):
                d.ellipse([cx - r, y + .8 * h - r, cx + r, y + .8 * h + r], outline=ink, width=lw)
        elif s["stand_in"] == "figure":
            r, cx = .07 * h, x + w / 2
            d.ellipse([cx - r, y, cx + r, y + 2 * r], outline=ink, width=lw)
            body = [(cx - .3 * w, y + .16 * h), (cx + .3 * w, y + .16 * h), (cx + .38 * w, y + .55 * h),
                    (cx + .2 * w, y + .55 * h), (cx + .22 * w, y + h), (cx - .22 * w, y + h), (cx - .2 * w, y + .55 * h),
                    (cx - .38 * w, y + .55 * h)]
            d.line(body + [body[0]], fill=ink, width=lw, joint="curve")
        else:
            d.rectangle([x, y, x + w, y + h], outline=ink, width=lw)
    return im


# ---- Locate: one Gemini vision call per take -> boxes per slot -------------------------------------------

def locate_prompt(spec):
    b = spec["base"]
    lines = [f"This is a photograph of {b.get('subject_desc', 'a ' + b.get('subject', 'building'))}. Find these things in "
             "it and return JSON only.",
             f"- \"world\": the whole {b.get('subject', 'building')} ({b.get('lock_edges_short', 'its outer edges')}), one "
             "box from its leftmost to rightmost visible edge and from roof edge to ground line."]
    for a, desc in b.get("anchors", {}).items():
        lines.append(f"- \"anchor:{a}\": {desc}. One box.")
    for s in spec["slots"]:
        if s["kind"] == "object":
            inc = f", including {s['includes']}" if s.get("includes") else ""
            lines.append(f"- \"{s['id']}\": {s['desc']}; one box around the whole of it{inc}.")
        else:
            lines.append(f"- \"{s['id']}\": every {s['desc']} you can see, up to {s['count']}; for each, its box and its four "
                         "corners in order top-left, top-right, bottom-right, bottom-left.")
    lines += ["If something is not in the photograph, return it with \"visible\": false and no box. Do not guess.",
              "Format: {\"items\": [{\"label\": \"...\", \"visible\": true, \"box_2d\": [ymin, xmin, ymax, xmax], "
              "\"corners\": [[y,x],[y,x],[y,x],[y,x]]}]} (corners for the every-one-you-can-see items only).",
              "Coordinates are integers from 0 to 1000 on the full image."]
    return "\n".join(lines)


def _box(b2):
    y0, x0, y1, x1 = (v / 1000 for v in b2)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _centre(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def _assign(targets, items):
    """Items matched to targets (None where there are fewer items), least total centre distance; greedy past 8 items."""
    import itertools
    d = lambda t, i: sum((a - b) ** 2 for a, b in zip(_centre(_box(i["box_2d"])), _centre(t))) ** .5  # noqa: E731
    k = min(len(targets), len(items))
    if len(items) <= 8:
        best = min(itertools.permutations(items, k), key=lambda p: sum(d(t, i) for t, i in zip(targets, p)), default=())
        return list(best) + [None] * (len(targets) - k)
    pool, out = list(items), []
    for t in targets:
        it = min(pool, key=lambda i: d(t, i)) if pool else None
        pool.remove(it) if it else None
        out.append(it)
    return out


def _check_item(it):
    if not isinstance(it, dict) or not isinstance(it.get("label"), str):
        raise ValueError(f"Locate item without a label: {it!r}")
    if it.get("visible", True) is False:
        return False
    b = it.get("box_2d")
    if not (isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in b)
            and b[0] < b[2] and b[1] < b[3]):
        raise ValueError(f"Locate item {it['label']}: box_2d must be [ymin, xmin, ymax, xmax] on 0-1000")
    c = it.get("corners") or None   # [] = no corners (Qwen3.8 writes it on every non-flat item; austin B take 05)
    if c is not None and not (isinstance(c, list) and len(c) == 4 and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in p) for p in c)):
        raise ValueError(f"Locate item {it['label']}: corners must be four [y, x] on 0-1000")
    return True


def parse_locate(spec, raw, frame, model=LOCATE_MODEL):
    """Gemini's {"items": [...]} (native box_2d [ymin, xmin, ymax, xmax] 0-1000, corners [y, x]) -> Boson boxes.json:
    world, anchors, slots {id: {visible, box, target, off} | {visible, items: [{box, quad}]}}, checks. Schema-checked:
    a malformed reply raises, it never becomes a box."""
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("Locate reply has no items list")
    seen = {}
    for it in items:
        if _check_item(it):
            seen.setdefault(it["label"], []).append(it)
    out = {"model": model, "frame": list(frame), "world": None, "anchors": {}, "slots": {}, "checks": {}}
    if "world" in seen:
        out["world"] = {"box": _box(seen["world"][0]["box_2d"])}
    for a in spec["base"].get("anchors", {}):
        if f"anchor:{a}" in seen:
            out["anchors"][a] = {"box": _box(seen[f"anchor:{a}"][0]["box_2d"])}
    missing = []
    for s in spec["slots"]:
        got = seen.get(s["id"], [])
        if not got:
            missing.append(s["id"])
            out["slots"][s["id"]] = {"visible": False}
        elif s["kind"] == "object":
            box, tgt = _box(got[0]["box_2d"]), s["place"]["box"]
            (cx, cy), (tx, ty) = _centre(box), _centre(tgt)
            out["slots"][s["id"]] = {"visible": True, "box": box, "target": tgt,
                                     "off": round(((cx - tx) ** 2 + (cy - ty) ** 2) ** .5, 3)}
        else:
            tg, its = s["place"]["boxes"][:s["count"]], []
            match = _assign(tg, got)
            for tgt, it in zip(tg, match):          # each target its own item, least total distance
                if it is None:
                    continue
                q = [[round(x / 1000, 4), round(y / 1000, 4)] for y, x in it["corners"]] if it.get("corners") else None
                bx = _box(it["box_2d"])
                (cx, cy), (tx, ty) = _centre(bx), _centre(tgt)
                its.append({"box": bx, "target": tgt, "off": round(((cx - tx) ** 2 + (cy - ty) ** 2) ** .5, 3),
                            "quad": q or [[bx[0], bx[1]], [bx[0] + bx[2], bx[1]], [bx[0] + bx[2], bx[1] + bx[3]],
                                          [bx[0], bx[1] + bx[3]]]})
            pool = [i for i in got if not any(i is j for j in match)]
            out["slots"][s["id"]] = {"visible": True, "items": its, "extra": len(pool)}
    b = spec["base"]
    if b.get("handed_anchor") in out["anchors"]:
        cx = _centre(out["anchors"][b["handed_anchor"]]["box"])[0]
        out["checks"]["handed"] = (cx > .5) == (b.get("handed_side", "right") == "right")
    if b.get("world") and out["world"]:
        w, v = out["world"]["box"], b["world"]
        edges = [abs(w[0] - v[0]), abs(w[1] - v[1]), abs(w[0] + w[2] - v[0] - v[2]), abs(w[1] + w[3] - v[1] - v[3])]
        out["checks"]["world_drift"] = round(max(edges), 3)
    out["checks"]["missing"] = missing
    return out


def image_hash(pil):
    """sha256 of the RGB pixels + size: the same picture hashes the same whatever file it came from."""
    rgb = pil.convert("RGB")
    return hashlib.sha256(f"{rgb.size}".encode() + rgb.tobytes()).hexdigest()[:16]


def gemini_json(prompt, pil, model=LOCATE_MODEL, max_side=2048):
    """One Gemini vision call, JSON out, temperature 0. The image goes as a JPEG of at most max_side px."""
    import base64
    try:
        from . import nanobanana as nbn
    except ImportError:
        import nanobanana as nbn
    im = pil.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
                                    {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    req = urllib.request.Request(nbn.API.format(m=model, k=nbn.key()), json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Locate HTTP {e.code}: {e.read().decode()[:600]}") from None
    text = "".join(p.get("text", "") for c in d.get("candidates", []) for p in c.get("content", {}).get("parts", []))
    raw = json.loads(text)
    if isinstance(raw, list):   # the bare list form some models answer with
        raw = {"items": raw}
    return raw, d.get("usageMetadata")


LOCAL_LOCATE = os.environ.get("BOSON_LOCATE_BASE_URL", "http://127.0.0.1:8192").rstrip("/")


def local_json(prompt, pil, model="local:qwen3.8-27b", max_side=1536):
    """Locate on open weights: one call to a llama-server with a vision projector ($BOSON_LOCATE_BASE_URL, OpenAI
    chat, image as a data URL), JSON out, temperature 0. Picked by a model named local:..., so its answers cache
    apart from Gemini's."""
    import base64
    im = pil.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    # Qwen-VL boxes are x first: asked y first it mixed the orders item by item (take 04, 10-27), so it is asked
    # in its own order and the answer turned back into Gemini's
    prompt = prompt.replace("[ymin, xmin, ymax, xmax]", "[xmin, ymin, xmax, ymax]").replace("[y,x]", "[x,y]")
    body = {"model": model.split(":", 1)[1], "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                                      {"type": "text", "text": prompt}]}],
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(LOCAL_LOCATE + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"local Locate HTTP {e.code}: {e.read().decode()[:600]}") from None
    except OSError as e:
        raise RuntimeError(f"no vision server at {LOCAL_LOCATE} for {model} ({e}); start llama-server with --mmproj "
                           "or set BOSON_LOCATE_BASE_URL") from None
    text = d["choices"][0]["message"]["content"]
    try:
        raw = json.loads(text)
    except ValueError:                    # prose or a fence around the JSON
        raw = json.loads(text[text.find("{"):text.rfind("}") + 1])
    if isinstance(raw, list):
        raw = {"items": raw}
    for it in raw.get("items", []):
        if isinstance(it, dict) and isinstance(it.get("box_2d"), list) and len(it["box_2d"]) == 4:
            x0, y0, x1, y1 = it["box_2d"]
            it["box_2d"] = [y0, x0, y1, x1]
        if isinstance(it, dict) and isinstance(it.get("corners"), list):
            it["corners"] = [p[::-1] if isinstance(p, list) else p for p in it["corners"]]
    return raw, d.get("usage")


def locate_cache(scene, h, model=LOCATE_MODEL):
    """Where Locate keeps its answer for pixels h (image_hash) under this scene's slot list."""
    return LOCATE_CACHE / f"{hashlib.sha256((h + model + locate_prompt(scene['spec'])).encode()).hexdigest()[:16]}.json"


def locatable(scene, h, model=LOCATE_MODEL):
    """Would Locate in stored mode answer for pixels h (a committed take's, or the cache), with no call."""
    return any(h in (take(scene, t).get("hash"), take(scene, t).get("located_hash")) and take(scene, t)["boxes"]
               for t in scene["takes"]) or locate_cache(scene, h, model).exists()


def record_uncropped(key, h):
    """What Uncrop put back for shot key (a close-crop swap): the pixels' hash, the one Locate keys on next. Kept
    beside the Locate cache, so a ready read knows Locate's key without the cutout pass."""
    p = LOCATE_CACHE / "uncropped" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"hash": h}) + "\n")


def shot_takes(scene):
    """Every take any branch of the scene repo committed, by its shot key (commit_take puts the key in the message):
    {key: (commit, take id)}. A reset scene still holds the takes made after it."""
    out = {}
    log = st.git(scene["repo"], "log", "--all", "--format=%H%x1f%s%x1f%b%x1e")
    for row in log.split("\x1e"):
        parts = row.strip().split("\x1f")
        m = re.match(r"take (\d+): ", parts[1]) if len(parts) == 3 else None
        if m and parts[2].strip():
            out.setdefault(parts[2].strip(), (parts[0], m.group(1)))
    return out


def uncropped(scene, key, shots=None):
    """The hash Locate keys on after a close-crop swap with shot key, without running it: what Uncrop recorded on this
    box, else the take some branch committed from that key (its located_hash). None: never put back here."""
    p = LOCATE_CACHE / "uncropped" / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text())["hash"]
    hit = (shots if shots is not None else shot_takes(scene)).get(key)
    if not hit:
        return None
    return json.loads(st.git(scene["repo"], "show", f"{hit[0]}:takes/{hit[1]}/take.json")).get("located_hash")


def locate(scene, pil, model=LOCATE_MODEL, mode="live", call=None):
    """Boxes for one take image. stored: a committed take with these pixels, else the Locate cache, else refuse
    (no call). live: the cache, else one Gemini call (cached by pixels + prompt + model)."""
    h = image_hash(pil)
    for tid in reversed(scene["takes"]):
        t = take(scene, tid)
        if h in (t.get("hash"), t.get("located_hash")) and t["boxes"]:   # the same boxes, stamped with these pixels:
            return {k: v for k, v in t["boxes"].items() if k != "take"} | {"image_hash": h}   # the JPEG as stored hashes apart
    prompt = locate_prompt(scene["spec"])
    ck = locate_cache(scene, h, model)
    if ck.exists():
        raw = json.loads(ck.read_text())["raw"]
    elif mode == "stored":
        raise ValueError("this take was never located: run Locate in live mode once (one Gemini vision call)")
    else:
        raw, usage = (call or (local_json if model.startswith("local:") else gemini_json))(prompt, pil, model)
        ck.parent.mkdir(parents=True, exist_ok=True)
        ck.write_text(json.dumps({"model": model, "prompt": prompt, "raw": raw, "usage": usage}, indent=1) + "\n")
    out = parse_locate(scene["spec"], raw, pil.size, model)
    out["image_hash"] = h
    return out


# ---- Slot Crop, Paste Flat --------------------------------------------------------------------------------

def crop_box(boxes, slot, item=0, pad=0.15, place=None):
    """The located box of a slot (an object, or item k of a flat), padded by pad of its size, clipped to the frame.
    A slot the take's Locate never saw (added to the scene after the take) falls back to its SCENE.json place box when
    `place` (that slot's `place`) is given, as a swap's `_parent_box` does."""
    s = boxes["slots"].get(slot)
    if s and s.get("visible"):
        x, y, w, h = s["items"][item]["box"] if "items" in s else s["box"]
    elif place and (place.get("box") or place.get("boxes")):
        x, y, w, h = place["box"] if place.get("box") else place["boxes"][item]
    else:
        raise ValueError(f"slot {slot} is not visible in this take")
    x0, y0, x1, y1 = max(0, x - pad * w), max(0, y - pad * h), min(1, x + w + pad * w), min(1, y + h + pad * h)
    return [x0, y0, x1 - x0, y1 - y0]


def crop(pil, boxes, slot, item=0, pad=0.15, place=None):
    W, H = pil.size
    x, y, w, h = crop_box(boxes, slot, item, pad, place)
    return pil.crop((round(x * W), round(y * H), round((x + w) * W), round((y + h) * H)))


def _coeffs(dst, src):
    """PIL PERSPECTIVE coefficients mapping output (dst) points to input (src) points."""
    import numpy as np
    a, b = [], []
    for (X, Y), (x, y) in zip(dst, src):
        a += [[X, Y, 1, 0, 0, 0, -x * X, -x * Y], [0, 0, 0, X, Y, 1, -y * X, -y * Y]]
        b += [x, y]
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def _fit(src, aspect):
    """The art padded (never stretched) to aspect w/h, centred, the pad in the mean colour of its own border, so a
    2:3 poster in a 2:7 panel keeps its proportions (operator 2026-10-21: a stretched poster read as squashed)."""
    from PIL import Image
    sw, sh = src.size
    if abs(sw / sh - aspect) / aspect < 0.03:
        return src
    w, h = (round(sh * aspect), sh) if sw / sh < aspect else (sw, round(sw / aspect))
    edge = [src.getpixel((x, y)) for x in range(0, sw, max(1, sw // 50)) for y in (0, sh - 1)] + \
           [src.getpixel((x, y)) for y in range(0, sh, max(1, sh // 50)) for x in (0, sw - 1)]
    fill = tuple(round(sum(c[i] for c in edge) / len(edge)) for i in range(3))
    out = Image.new("RGB", (w, h), fill)
    out.paste(src, ((w - sw) // 2, (h - sh) // 2))
    return out


def paste(pil, quads, flat, glass=0.15, fit=True):
    """Warp the flat piece onto each located quad ([[x, y] x4] fractions, TL TR BR BL) of the take; glass = how much
    of the take's own pixels (reflection, tint) stays over the paste; fit pads the art to the quad's proportions
    instead of stretching it. -> a new image; the take is untouched."""
    from PIL import Image, ImageDraw
    out = pil.convert("RGB").copy()
    W, H = out.size
    for q in quads:
        pts = [(x * W, y * H) for x, y in q]
        d = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5  # noqa: E731
        qa = (d(pts[0], pts[1]) + d(pts[3], pts[2])) / max(1e-6, d(pts[0], pts[3]) + d(pts[1], pts[2]))
        src = _fit(flat.convert("RGB"), qa) if fit else flat.convert("RGB")
        sw, sh = src.size
        warped = src.transform((W, H), Image.PERSPECTIVE, _coeffs(pts, [(0, 0), (sw, 0), (sw, sh), (0, sh)]),
                               Image.BICUBIC)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        mixed = Image.blend(warped, out, glass) if glass else warped
        out.paste(mixed, (0, 0), mask)
    return out


# ---- Commit Take -------------------------------------------------------------------------------------------

def commit_take(scene, pil, boxes, shot=None, source=None):
    """Commit one take: takes/NN/{image.jpg, cast.json, boxes.json, take.json} and SCENE.json with the cast it was shot
    with (the pending swaps become the scene). Refuses boxes located on other pixels, and a branch that moved.
    Idempotent: the same pixels with the same cast again return the take already committed. -> (SCENE @ new commit, take id)."""
    h = image_hash(pil)
    if boxes and boxes.get("image_hash") not in (None, h):
        raise ValueError("these boxes were located on another image: wire Locate's input from the same take")
    for tid in scene["takes"]:            # same pixels and same cast; a flat swap keeps the pixels, its art is pasted on view
        t = take(scene, tid)
        if h in (t.get("hash"), t.get("located_hash")) and t["cast"] == cast_of(scene["spec"]):
            ch = scene["spec"].get("chosen")   # a redo after Use this take: the scene stands on it again
            if (shot or {}).get("mode") == "swap" and ch and shot.get("parent") == ch and tid != ch:
                return choose(scene, tid), tid
            return scene, tid
    tid = f"{len(scene['takes']) + 1:02d}"
    with _saving(scene, "SCENE.json", f"takes/{tid}") as (repo, branch):
        d = repo / "takes" / tid
        d.mkdir(parents=True)
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, "JPEG", quality=JPEG_Q)
        (d / "image.jpg").write_bytes(buf.getvalue())
        from PIL import Image
        stored = Image.open(io.BytesIO(buf.getvalue()))
        spec = copy.deepcopy(scene["spec"])
        op = (shot or {}).get("mode") or ("import" if source else "shoot")
        if op == "swap" and (shot or {}).get("parent") and shot["parent"] == spec.get("chosen"):
            spec["chosen"] = tid               # a swap of the chosen take: the scene now stands on this one (swap_parent)
        meta = {"op": op, "parent": (shot or {}).get("parent"), "swapped": (shot or {}).get("swapped"),
                "prompt": (shot or {}).get("prompt"), "from": source,
                "renderer": (shot or {}).get("renderer") or (None if source else plate_renderer(scene, h)),
                "hash": image_hash(stored), "located_hash": h, "frame": list(pil.size),
                "slots": [{k: s[k] for k in ("id", "piece", "short", "desc")} for s in spec["slots"]]}
        (d / "take.json").write_text(json.dumps(meta, indent=1) + "\n")
        (d / "cast.json").write_text(json.dumps(cast_of(spec), indent=1) + "\n")
        if boxes:
            (d / "boxes.json").write_text(json.dumps({"take": f"takes/{tid}", **boxes}, indent=1) + "\n")
        (repo / "SCENE.json").write_text(json.dumps(spec, indent=1) + "\n")
        st.git(repo, "add", "--", "SCENE.json", str(d))
        swapped = f" ({', '.join(meta['swapped'])})" if meta["swapped"] else ""
        st.git(repo, "commit", "-q", "-m", f"take {tid}: {op}{swapped}", "-m", source or (shot or {}).get("key", ""))
    return load(repo, branch), tid
