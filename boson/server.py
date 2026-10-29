"""Read-only routes for the Boson panel (web/panel.js) and the app (web/client.js, docs/APP-API.md). Two writes, each one
commit of SCENE.json: POST /boson/use-take (a pointer) and /boson/remove-slot; every other action sets a widget on the
graph's own Boson nodes and queues the graph.

  GET /boson/studio?repo=...&ref=...   the studio's state: rounds, rules, proposals, the open round's plates, taste
                                       (the house), makes
  GET /boson/plate?repo=...&file=...   one plate file, only from beside that studio (plates_dir)
  GET /boson/studios                   every studio on the floor (studio.registry)
  GET /boson/loop?repo=...&ref=...     the studio's loop rounds (LOOP.jsonl): pieces with dots and provenance, the
                                       verdict, and what changed in STUDIO.md and TASTE.json up to the next round
  GET /boson/scenes                    every scene (scene.registry)
  GET /boson/scene?repo=...&ref=...    a scene: SCENE.json and its takes (cast, boxes, image url)
  GET /boson/take?repo=...&ref=...&take=NN   a take's image, from that commit's snapshot; &paste=1 with each flat slot's
                                             art on its located quads, as the stills and clips show it (cached)
  GET /boson/clip?repo=...&ref=...&clip=NN   a committed clip's mp4 (scene.commit_clip, node Commit Clip)
  GET /boson/motion?repo=...&take=NN&prompt=...   the motion graph for a take (tools/motion_workflow.build, API
                                       format), has_key, cost: reads only, nothing queued
  GET /boson/scene-graph?repo=...      the scene's graph from SCENE.json now (tools/scene_workflow.build, API
                                       format): reads only, nothing queued
  GET /boson/ready?repo=&take=&slot=&idea=&frame=&n=&pieces=   which swaps and Makes replay with no call (ready),
                                       and whether this box has keys for live calls (has_key, never the keys)
  POST /boson/use-take {repo, take}    the scene stands on that take (SCENE.json chosen + its cast, one commit)
  POST /boson/remove-slot {repo, slot} a slot made from the frame, while it shows the base, is part of the base again (one commit)
  GET /boson/piece?ref=studio@sha:path       a piece's image
  GET /boson/shelf                     every studio's kept pieces
  GET /boson/workflow?name=...         a shipped workflow (workflows/NAME.json)
  GET /boson/app                       the app shell (web/app/index.html)
"""
import asyncio, importlib.util, json, os, pathlib, re, sys, urllib.parse

from . import grid as gr
from . import nanobanana as nbn
from . import scene as sc
from . import studio as st

WEB = pathlib.Path(__file__).resolve().parent / "web"
WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / "workflows"
IMAGES = (".png", ".jpg", ".jpeg", ".webp")


def state(repo, ref):
    s = st.load(repo, ref)
    d = pathlib.Path(s["dir"])
    rid = st.next_round(s)
    pdir = gr.plates_dir(s.get("source") or s["repo"])
    specs = st.specs(d / "history" / f"round-{rid}") if (d / "history" / f"round-{rid}" / "specs").exists() else []
    titles = {x["id"]: x.get("title", x["id"]) for x in specs}
    rows = [r for r in nbn.stored_round(pdir, rid) if r["id"] in titles]   # only pieces this commit has drafted
    if not rows:     # plates rendered before the node existed (tools/render_nb.py): shown, labelled by renderer
        man = pdir / "manifest.jsonl"
        allr = [json.loads(l) for l in man.read_text().splitlines() if l.strip()] if man.exists() else []
        rows = [r for r in allr if str(r.get("round")).lstrip("r") == rid and r.get("id") in titles]
    waiting = st.awaiting_approval(s)
    prid, props = st.proposed(s)
    rounds = []
    for r in st.rounds(s):
        v = d / "history" / f"round-{r['round']}" / "VERDICT.md"
        rounds.append({"round": r["round"], "verdict": v.read_text().strip() if v.exists() else r.get("verdict")})
    v = d / "history" / f"round-{rid}" / "VERDICT.md"         # committed, not digested yet
    return {"studio": pathlib.Path(s["repo"]).name, "ref": s["ref"], "sha": s["sha"][:8], "round": rid,
            "verdict": v.read_text().strip() if v.exists() else None,
            "drafted": bool(specs), "rounds": rounds, "rules": st.rules(s), "taste": st.taste(s), "shelf": st.shelf(s),
            "awaiting": waiting or None, "proposed": props if waiting else {}, "proposed_round": prid,
            "plates": [{"id": r["id"], "title": titles.get(r["id"], r["id"]), "file": r["file"],
                        "renderer": r.get("renderer")} for r in rows],
            "makes": makes(s, pdir)}


def makes(s, pdir):
    """Every Make of this studio (any commit), oldest first: {key, frame, idea, like, sha, pieces[{piece, file, title}]}.
    Plates beside the studio say what was rendered; the make cache says what for (absent: frame/idea unknown)."""
    man = pdir / "manifest.jsonl"
    rows = [json.loads(l) for l in man.read_text().splitlines() if l.strip()] if man.exists() else []
    name, out = st.name_of(s), {}
    for r in rows:
        rid = str(r.get("round", ""))
        if not rid.startswith("make-"):
            continue
        key = rid[5:]
        if key not in out:
            m = st.MAKES / key / "MAKE.json"
            meta = json.loads(m.read_text()) if m.exists() else {}
            titles = {x["id"]: x["title"] for x in st.specs(st.MAKES / key)} if (st.MAKES / key / "specs").is_dir() else {}
            out[key] = {"key": key, "frame": meta.get("frame"), "idea": meta.get("idea"), "like": meta.get("like") or None,
                        "sha": r["studio_sha"][:8], "titles": titles, "pieces": {}}
        out[key]["pieces"][r["file"]] = {"piece": f"{name}@{r['studio_sha'][:8]}:{r['file']}", "file": r["file"],
                                         "title": out[key]["titles"].get(r["id"], r["id"])}
    return [{**{k: v for k, v in m.items() if k != "titles"}, "pieces": list(m["pieces"].values())} for m in out.values()]


def taste_change(a, b):
    """What the house changed between two loads: {field: {added, removed}} per list, sentence {from, to}."""
    ta, tb, out = st.taste(a), st.taste(b), {}
    if ta["sentence"] != tb["sentence"]:
        out["sentence"] = {"from": ta["sentence"], "to": tb["sentence"]}
    for k in st.TASTE_KEYS:
        key = (lambda x: x["name"]) if k == "subjects" else (lambda x: x)
        was, now = [key(x) for x in ta[k]], [key(x) for x in tb[k]]
        added, removed = [x for x in now if x not in was], [x for x in was if x not in now]
        if added or removed:
            out[k] = {"added": added, "removed": removed}
    return out


def loop_state(repo, ref="main"):
    """A studio's loop (tools/loop.py, the Dots node), oldest round first: each round's idea, pieces (title, renderer,
    plate url, dot, note), verdict, and `change` = the diff of STUDIO.md and TASTE.json from that round's studio commit
    to the next round's (the last round: to ref), as text and as a house change. `open` = the round waiting for dots."""
    s = st.load(repo, ref)
    pdir, rs, out = gr.plates_dir(s.get("source") or s["repo"]), st.loop_rounds(s), []
    for i, r in enumerate(rs):
        made = {x["file"]: x for x in nbn.stored_round(pdir, f"make-{r['make']}")}
        greens, reds, notes = r.get("greens", []), r.get("reds", []), r.get("notes") or {}
        pieces = []
        for p in r["pieces"]:
            path = p.split(":", 1)[1]
            sp = st.make_spec(r["make"], path)
            pieces.append({"piece": p, "file": path, "title": sp.get("title") or pathlib.Path(path).stem.split("__")[0],
                           "renderer": made.get(path, {}).get("renderer"),
                           "image": f"/boson/plate?repo={_q(repo)}&file={_q(path)}",
                           "dot": "green" if p in greens else "red" if p in reds else None, "note": notes.get(p)})
        a = st.resolve(s["repo"], r["studio_sha"])
        b = st.resolve(s["repo"], rs[i + 1]["studio_sha"]) if i + 1 < len(rs) else s["sha"]
        diff = st.git(s["repo"], "diff", a, b, "--", "STUDIO.md", "TASTE.json") if a != b else ""
        out.append({k: r.get(k) for k in ("round", "make", "studio_sha", "frame", "idea", "base_idea", "n", "pins")}
                   | {"pieces": pieces, "verdict": r.get("verdict"), "greens": greens, "reds": reds,
                      "brief": st.next_brief(r) if "verdict" in r else None,
                      "change": {"from": a[:8], "to": b[:8], "diff": diff,
                                 "files": st.git(s["repo"], "diff", "--name-only", a, b, "--", "STUDIO.md",
                                                       "TASTE.json").split() if diff else [],
                                 "house": taste_change(st.load(s["repo"], a), st.load(s["repo"], b))}})
    return {"studio": st.name_of(s), "repo": repo, "ref": ref, "sha": s["sha"][:8], "taste": st.taste(s),
            "open": st.open_loop_round(s), "rounds": out}


def plate_path(repo, file):
    s_src = pathlib.Path(repo).expanduser()
    pdir = gr.plates_dir(s_src).resolve()
    p = (pdir / file).resolve()
    if pdir not in p.parents or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise PermissionError(file)
    return p


def _text(p):
    return p.read_text() if p.is_file() else ""


def studio_field(text):
    """STUDIO.md -> its field in a few words ('## Field' + the next line, or '**Field:** ...'), '' if none."""
    m = re.search(r"^##\s*Field\s*\n+\s*(.+)$", text, re.M) or re.search(r"\*\*Field:\*\*\s*([^*\n]+)", text)
    return m.group(1).strip().rstrip(".").split(":")[0].strip() if m else ""


def studios():
    out = []
    for name, src in st.registry().items():
        try:
            s = st.load(src, "main")
            out.append({"name": name, "repo": src, "sha": s["sha"][:8], "rounds": len(st.rounds(s)),
                        "rules": len(st.rules(s)), "taste": st.taste(s), "shelf": len(st.shelf(s)),
                        "field": studio_field(_text(pathlib.Path(s["dir"]) / "STUDIO.md"))})
        except Exception as e:      # a broken studio is listed with its error, never hides the others
            out.append({"name": name, "repo": src, "error": f"{type(e).__name__}: {e}"})
    return out


def _q(v):
    return urllib.parse.quote(str(v), safe="")


def scene_state(repo, ref="main"):
    repo = sc.registry().get(repo, repo)
    s = sc.load(repo, ref)
    takes, flat = [], "&paste=1" if any(x["kind"] == "flat" for x in s["spec"]["slots"]) else ""
    for tid in s["takes"]:
        t = sc.take(s, tid)
        takes.append({k: t.get(k) for k in ("id", "op", "parent", "swapped", "cast", "boxes", "from", "frame", "renderer")}
                     | {"image": f"/boson/take?repo={_q(repo)}&ref={_q(s['sha'])}&take={tid}{flat}"})
    slots = [{**x, "image": f"/boson/piece?ref={_q(x['piece'])}"} for x in s["spec"]["slots"]]
    clips = [{k: c.get(k) for k in ("id", "take", "prompt", "renderer", "bytes")}
             | {"video": f"/boson/clip?repo={_q(repo)}&ref={_q(s['sha'])}&clip={c['id']}"}
             for c in (sc.clip(s, cid) for cid in s.get("clips", []))]
    return {"name": s["spec"]["name"], "repo": repo, "ref": ref, "sha": s["sha"][:8], "spec": {**s["spec"], "slots": slots},
            "takes": takes, "clips": clips}


def scenes():
    out = []
    for name, src in sc.registry().items():
        try:
            s = sc.load(src, "main")
            out.append({"name": name, "repo": src, "sha": s["sha"][:8], "takes": len(s["takes"]),
                        "base": s["spec"]["base"]["studio"],
                        "slots": [{k: x[k] for k in ("id", "role", "kind", "studio", "piece")} for x in s["spec"]["slots"]]})
        except Exception as e:
            out.append({"name": name, "repo": src, "error": f"{type(e).__name__}: {e}"})
    return out


def clip_path(repo, cid, ref="main"):
    if not re.fullmatch(r"\d{2,4}", cid):
        raise PermissionError(cid)
    p = pathlib.Path(sc.clip(sc.load(sc.registry().get(repo, repo), ref), cid)["video"])
    if p.suffix.lower() != ".mp4":
        raise PermissionError(cid)
    return p


MOTION_COST = "$0.14-0.87 per 6 s clip, Comfy credits"


_tools = {}


def _tool(name):
    """tools/NAME.py, loaded once. The tools import `scene`/`studio`/`nanobanana` bare: hand them this package's
    modules for the load, leave sys.path and sys.modules as they were."""
    if name not in _tools:
        path, mods = list(sys.path), {k: sys.modules.get(k) for k in ("scene", "studio", "nanobanana")}
        sys.modules.update(scene=sc, studio=st, nanobanana=nbn)
        sys.path.insert(0, str(WORKFLOWS.parent / "tools"))
        try:
            spec = importlib.util.spec_from_file_location(f"boson_{name}", WORKFLOWS.parent / "tools" / f"{name}.py")
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            _tools[name] = m
        finally:
            sys.path[:] = path
            for k, v in mods.items():
                sys.modules.pop(k) if v is None else sys.modules.__setitem__(k, v)
    return _tools[name]


def scene_graph(repo):
    """The scene's graph built from its SCENE.json as it is now (tools/scene_workflow.build, API format): what the
    shipped workflows/scene-NAME.json is, plus every slot made since (Add Slot). Reads only, nothing queued."""
    name, g = _tool("scene_workflow").build(sc.registry().get(repo, repo))
    return {"name": f"scene-{name}", "graph": g}


def motion(repo, take, prompt, model="Omni Flash 1.1"):
    """The motion graph for one take (tools/motion_workflow.build: Load Scene -> Load Take -> Paste Flat per flat slot
    (a committed take holds the blank panel) -> Gemini Omni -> Commit Clip,
    API format) and whether a Comfy key exists (never the key). Reads only: queueing it is the spend."""
    repo = sc.registry().get(repo, repo)
    if take not in sc.load(repo, "main")["takes"]:
        raise KeyError(f"no take {take!r}")
    m = _tool("motion_workflow")
    try:
        _, g = m.build(repo, take, prompt, model, paste=True)
    except SystemExit as e:
        raise ValueError(str(e)) from None
    try:
        has_key = bool(nbn.comfy_key())
    except RuntimeError:
        has_key = False
    return {"graph": g, "has_key": has_key, "cost": MOTION_COST}


def take_path(repo, tid, ref="main", paste="0"):
    """A take's image; paste=1: with each flat slot's art (the take's own cast) on its located quads, cached by the
    commit and take, so the set shows the poster the stills and clips carry rather than the blank panel."""
    if not re.fullmatch(r"\d{2,4}", tid):
        raise PermissionError(tid)
    s = sc.load(sc.registry().get(repo, repo), ref)
    t = sc.take(s, tid)
    img = pathlib.Path(t["image"])
    if paste != "1":
        return img
    out = sc.HOME / "pasted" / f"{s['sha'][:12]}-{tid}.jpg"
    if not out.exists():
        from PIL import Image
        pil = Image.open(img).convert("RGB")
        for x in (x for x in s["spec"]["slots"] if x["kind"] == "flat" and t["cast"].get(x["id"])):
            quads = [i["quad"] for i in ((t.get("boxes") or {}).get("slots", {}).get(x["id"]) or {}).get("items", [])
                     if i.get("quad")]
            if quads:
                pil = sc.paste(pil, quads, Image.open(sc.piece(t["cast"][x["id"]])), 0.15)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{os.getpid()}.tmp")
        pil.save(tmp, "JPEG", quality=sc.JPEG_Q)
        tmp.replace(out)
    return out


def _same_piece(a, b):
    """One piece, whichever studio commit names it (studio@sha:path)."""
    try:
        return a == b or (sc.parse_piece(a)[0::2] == sc.parse_piece(b)[0::2])
    except (ValueError, AttributeError):
        return False


def _later(scene, slot, piece, rows, shots, par):
    """No stored swap of piece into the take a Swap edits, but one into a take some branch made later (a reset scene:
    the demo swaps its corner piece after the outfit): {take, after: [{slot, piece}]}, the swaps between, else None."""
    name = pathlib.PurePosixPath(sc.parse_piece(piece)[2]).name
    for key in dict.fromkeys(str(r["round"])[5:] for r in rows
                             if str(r.get("round", "")).startswith("shot-") and name in (r.get("refs") or [])):
        hit = shots.get(key)
        if not hit:
            continue
        commit, tid = hit
        t = json.loads(st.git(scene["repo"], "show", f"{commit}:takes/{tid}/take.json"))
        cast = json.loads(st.git(scene["repo"], "show", f"{commit}:takes/{tid}/cast.json"))
        if slot not in (t.get("swapped") or []) or not _same_piece(cast.get(slot, ""), piece) or not t.get("parent"):
            continue
        was = json.loads(st.git(scene["repo"], "show", f"{commit}:takes/{t['parent']}/cast.json"))
        after = [{"slot": k, "piece": v} for k, v in was.items()
                 if k != slot and k in par["cast"] and not _same_piece(par["cast"][k], v)]
        if after:
            return {"take": t["parent"], "after": after}
    return None


def _swap_ready(scene, slot, piece, pdir, shots=None, rows=None):
    """One piece cast into slot, swapped as the app's Swap does (Compile Scene swap, close crop, Nano Banana stored,
    Locate stored): {piece, key, flat, stored, located, later?}. located: Locate's stored answer for those pixels (a
    committed take, or the Locate cache under the scene's slot list now); a close crop's pixels are known without the
    cutout pass when Uncrop put them back on this box or a branch committed them (scene.uncropped), else None.
    later: not stored for this take, but for one made after other swaps (_later)."""
    from PIL import Image
    c = sc.cast(scene, slot, piece)
    par = sc.swap_parent(c)
    if not sc.swapped_since(c, par):
        return {"piece": piece, "key": None, "flat": False, "stored": True, "located": True, "same": True}
    shot = sc.compile_shot(c, "swap", "", crop_worn=True, card="defer")
    if not shot["prompt"]:
        return {"piece": piece, "key": shot["key"], "flat": True, "stored": True, "located": True}
    got = nbn.stored_round(pdir, f"shot-{shot['key']}")
    shots = sc.shot_takes(scene) if shots is None else shots
    located = None
    if got and shot.get("crop"):
        h = sc.uncropped(c, shot["key"], shots)
        located = None if h is None else sc.locatable(c, h)
    elif got:
        located = all(sc.locatable(c, sc.image_hash(Image.open(pdir / r["file"]))) for r in got)
    out = {"piece": piece, "key": shot["key"], "flat": False, "stored": bool(got), "located": located}
    later = None if got else _later(scene, slot, piece, rows or [], shots, par)
    return out | ({"later": later} if later else {})


def keys():
    """Which keys live calls would find on this box, never the keys: {has_key, keys: {gemini, comfy}}. has_key: any, so
    a live call can start; no key at all: this copy can only replay."""
    have = {}
    for name, fn in (("gemini", nbn.key), ("comfy", nbn.comfy_key)):
        try:
            have[name] = bool(fn())
        except RuntimeError:
            have[name] = False
    return {"has_key": any(have.values()), "keys": have}


def ready(repo, take="", slot="", idea="", frame="", n="4", pieces=""):
    """What would replay with no call, read from disk (the keys the real path computes; nothing queued, no call).
    GET /boson/ready?repo=&take=&slot=&idea=&frame=&n=&pieces=  ->
      {"scene", "sha", "slots": [slot ids], "has_key", "keys" (keys()), "take": the take the Make crops (default newest),
       "parent": the take a Swap edits (swap_parent: the chosen take, or the newest shoot if newer),
       "swaps": [{"piece", "key", "flat", "stored", "located", "same"?, "later"?}],
       "makes": [{"studio", "key", "stored", "pieces": [studio@sha:path]}]}
    No slot: the slot list only. swaps: one per piece (pieces: newline- or comma-separated; default the shelf's and
    every stored make's for this spot), each cast alone into slot (other pending casts not counted); stored = Nano
    Banana's stored render exists (flats: always, no image call), located = Locate's stored boxes too (None: unknown),
    later = stored only for a take made after other swaps (_later).
    makes: one per studio, Make n for this spot (Slot Crop of take, padded 0.15, the place box when the take never saw
    the slot) with frame and idea exactly as client.js commissionNew sends them (spotIdea); no idea: no makes.
    Side effect: compile_shot caches a close crop's image under SHOTS/<key>/ (the key hashes it), as a Swap does."""
    import numpy as np
    from PIL import Image
    s = sc.load(sc.registry().get(repo, repo), "main")
    out = {"scene": s["spec"]["name"], "sha": s["sha"][:8], "slots": [x["id"] for x in s["spec"]["slots"]], **keys()}
    if not slot:
        return out
    sl = next((x for x in s["spec"]["slots"] if x["id"] == slot), None)
    if sl is None:
        raise KeyError(f"no slot {slot!r} (have {', '.join(out['slots'])})")
    par = sc.swap_parent(s)
    tid = (take.strip().zfill(2) if take.strip() else (s["takes"][-1] if s["takes"] else None))
    out.update(take=tid, parent=par["id"] if par else None, swaps=[], makes=[])
    made = []
    t = sc.take(s, tid) if tid else None
    if idea.strip() and t and t["boxes"]:
        got, place = t["boxes"]["slots"].get(slot) or {}, sl["place"]
        if got.get("visible") or place.get("box") or place.get("boxes"):
            crop = sc.crop(Image.open(t["image"]).convert("RGB"), t["boxes"], slot, 0, 0.15, place)
            wired = [np.asarray(crop.convert("RGB")).tobytes()]
            for name, src in st.registry().items():
                try:
                    studio = st.load(src, "main")
                    key = st.make_key(studio, frame, idea, int(n), "", wired)
                    rows = nbn.stored_round(gr.plates_dir(studio.get("source") or studio["repo"]), f"make-{key}")
                except Exception:
                    continue
                ps = [f"{st.name_of(studio)}@{r['studio_sha'][:8]}:{r['file']}" for r in rows]
                made += ps
                out["makes"].append({"studio": name, "key": key, "stored": bool(rows), "pieces": ps})
    want = [x.strip() for x in re.split(r"[\n,]", pieces) if x.strip()] if pieces.strip() else \
        list(dict.fromkeys([x["piece"] for x in shelf()] + made))
    if par is not None:
        bs = st.load(s["spec"]["base"]["studio"], s["spec"]["base"]["ref"])
        pdir = gr.plates_dir(bs.get("source") or bs["repo"])
        shots = sc.shot_takes(s)
        mf = pathlib.Path(pdir) / "manifest.jsonl"
        rows = [json.loads(x) for x in mf.read_text().splitlines() if x.strip()] if mf.exists() else []
        for p in want:
            try:
                out["swaps"].append(_swap_ready(s, slot, p, pdir, shots, rows))
            except Exception as e:
                out["swaps"].append({"piece": p, "error": f"{type(e).__name__}: {e}"})
    return out


def use_take(repo, take):
    """Use this take (POST /boson/use-take {repo, take}): scene.choose, one commit of SCENE.json, nothing deleted.
    The one write here: a scene's chosen take is a pointer, no node computes it. -> scene_state of the new commit."""
    repo = sc.registry().get(repo, repo)
    s = sc.load(repo, "main")
    tid = str(take).strip().zfill(2)
    if tid not in s["takes"]:
        raise KeyError(f"no take {tid}")
    sc.choose(s, tid)
    return scene_state(repo)


def remove_slot(repo, slot):
    """Remove this slot (POST /boson/remove-slot {repo, slot}): scene.unpromote, one commit of SCENE.json, nothing
    deleted; only a slot made from the frame, and only while it shows the base (scene.unpromote refuses otherwise). -> scene_state of the new commit."""
    repo = sc.registry().get(repo, repo)
    sc.unpromote(sc.load(repo, "main"), str(slot).strip())
    return scene_state(repo)


def piece_path(ref):
    p = sc.piece(ref)
    if p.suffix.lower() not in IMAGES:
        raise PermissionError(ref)
    return p


def shelf():
    out = []
    for name, src in st.registry().items():
        try:
            out += [{"studio": name, **x, "image": f"/boson/piece?ref={_q(x['piece'])}"} for x in st.shelf(st.load(src, "main"))]
        except Exception:
            continue
    return out


def private_refs():
    """{studio: [refs/ file names]} for every reference whose licence says it is a private found picture, read from
    each studio's refs/refs.jsonl. The app labels exactly these; a studio's own made pictures are not private."""
    out = {}
    for name, src in st.registry().items():
        try:
            p = pathlib.Path(st.load(src, "main")["dir"]) / "refs" / "refs.jsonl"
            rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
        except Exception:
            continue
        out[name] = [r["file"] for r in rows if str(r.get("license", "")).startswith("found reference")]
    return out


def workflow_path(name):
    if not re.fullmatch(r"[\w\-]+", name or ""):
        raise PermissionError(name)
    return WORKFLOWS / f"{name}.json"


def register(routes, web):
    def json_route(path, fn, *keys, **defaults):
        @routes.get(path)
        async def _h(request):
            q = request.rel_url.query
            try:
                args = [q[k] for k in keys] + [q.get(k, v) for k, v in defaults.items()]
                return web.json_response(await asyncio.to_thread(fn, *args))
            except Exception as e:  # shown by the caller, never a 500 page
                return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=400)

    def file_route(path, fn, *keys, **defaults):
        @routes.get(path)
        async def _h(request):
            q = request.rel_url.query
            try:
                return web.FileResponse(await asyncio.to_thread(
                    fn, *[q[k] for k in keys], *[q.get(k, v) for k, v in defaults.items()]))
            except (PermissionError, KeyError, ValueError, FileNotFoundError, RuntimeError):
                return web.Response(status=404)

    json_route("/boson/studios", studios)
    json_route("/boson/loop", loop_state, "repo", ref="main")
    json_route("/boson/scenes", scenes)
    json_route("/boson/scene", scene_state, "repo", ref="main")
    json_route("/boson/shelf", shelf)
    json_route("/boson/private-refs", private_refs)
    file_route("/boson/take", take_path, "repo", "take", ref="main", paste="0")
    file_route("/boson/clip", clip_path, "repo", "clip", ref="main")
    json_route("/boson/scene-graph", scene_graph, "repo")
    json_route("/boson/motion", motion, "repo", "take", "prompt", model="Omni Flash 1.1")
    json_route("/boson/ready", ready, "repo", take="", slot="", idea="", frame="", n="4", pieces="")

    def post_route(path, fn, *keys):
        @routes.post(path)
        async def _h(request):
            try:
                d = await request.json()
                return web.json_response(await asyncio.to_thread(fn, *(d[k] for k in keys)))
            except Exception as e:
                return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=400)

    post_route("/boson/use-take", use_take, "repo", "take")
    post_route("/boson/remove-slot", remove_slot, "repo", "slot")
    file_route("/boson/piece", piece_path, "ref")
    file_route("/boson/workflow", workflow_path, "name")

    @routes.get("/boson/app")
    async def _app(request):
        return web.FileResponse(WEB / "app" / "index.html")

    @routes.get("/boson/studio")
    async def _studio(request):
        q = request.rel_url.query
        try:
            return web.json_response(await asyncio.to_thread(state, q["repo"], q.get("ref", "main")))
        except Exception as e:      # shown in the panel, never a 500 page
            return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=400)

    @routes.get("/boson/plate")
    async def _plate(request):
        q = request.rel_url.query
        try:
            return web.FileResponse(plate_path(q["repo"], q["file"]))
        except (PermissionError, KeyError, FileNotFoundError):
            return web.Response(status=404)
