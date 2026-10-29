"""Boson core nodes for ComfyUI: Load Studio, Studio Info, Draft Brief, Nano Banana, Verdict, Digest, Approve Rules
(the scene nodes live in scene_nodes.py).

STUDIO travels between nodes as a plain dict (see studio.load). Nothing here holds state: the studio's
git repo does (SPEC v3 I1). A round on the canvas: Load Studio -> Draft Brief -> prompts into stock
CLIPTextEncode / KSampler (workflows/klein-mi2i.api.json) -> Verdict -> Digest -> Approve Rules.
"""
from comfy_execution.graph_utils import ExecutionBlocker

from . import grid as gr
from . import nanobanana as nbn
from . import scene as sc
from . import studio as st


class LoadStudio:
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO",)
    FUNCTION = "load"
    DESCRIPTION = "A studio is a git repo. ref = a round tag (r00, r01, ...), a branch or a commit; r00 = no history."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "repo": ("STRING", {"default": "~/Boson/tests/fixtures/poc/ex-libris.bundle"}),
            "ref": ("STRING", {"default": "main"}),
        }}

    @classmethod
    def IS_CHANGED(cls, repo, ref):
        # re-run when the ref points somewhere new (a branch after a commit), never otherwise
        try:
            return st.resolve(st.open_repo(repo), ref)
        except Exception as e:
            return str(e)

    def load(self, repo, ref):
        return (st.load(repo, ref),)


class StudioInfo:
    CATEGORY = "boson"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("rules", "summary")
    FUNCTION = "info"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"studio": ("STUDIO",)}}

    def info(self, studio):
        rs = st.rounds(studio)
        rules = "\n".join(f"- {r}" for r in st.rules(studio)) or "(no binding rules yet)"
        summary = f"{studio['ref']} @ {studio['sha'][:8]}: {len(rs)} rounds; next round {st.next_round(studio)}"
        return {"ui": {"text": [summary + "\n\n" + rules]}, "result": (rules, summary)}


class DraftBrief:
    """The writer drafts the next round from the whole studio. Prompts go out as a list, so one stock
    CLIPTextEncode -> KSampler chain renders every piece."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO", "STRING", "STRING", "STRING", "BOSON_DRAFT")
    RETURN_NAMES = ("studio", "prompts", "brief", "writer", "draft")
    OUTPUT_IS_LIST = (False, True, False, False, False)
    FUNCTION = "draft"
    OUTPUT_NODE = True
    DESCRIPTION = ("Writer call (paid, minutes). On a branch the draft is committed as the round; at a tag "
                   "or commit it is cached by draw. Re-queue reuses it.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "pieces": ("INT", {"default": 8, "min": 1, "max": 16}),
            "draw": ("INT", {"default": 0, "min": 0, "max": 99,
                             "tooltip": "another independent draft at a tag (grid live cells); ignored on a branch"}),
            "lead": ("STRING", {"default": "In the engraving style and composition of the reference prints: ",
                                "tooltip": "prefixed to every prompt (the Klein mi2i rung, T14)"}),
        }}

    def draft(self, studio, pieces, draw, lead):
        waiting = st.awaiting_approval(studio)
        if waiting:
            # never buy the next draft before the owner has ruled on the last round's proposed rules
            return {"ui": {"text": [f"round {waiting}'s proposed rules await Approve Rules"]},
                    "result": (ExecutionBlocker(None),) * 5}
        if st.open_loop_round(studio):
            # nor before the owner has dotted the open round (I2: wait quietly; I4: Run in stored mode calls no writer)
            return {"ui": {"text": [f"round {st.open_loop_round(studio)} waits for your dots and verdict (Dots)"]},
                    "result": (ExecutionBlocker(None),) * 5}
        new, sp, meta = st.draft(studio, pieces, draw)
        brief = meta.get("brief", "")
        w = meta.get("writer", "writer unknown")
        txt = f"round {st.next_round(new)}: {len(sp)} pieces, {w}\n" + "\n".join(f"- {x['title']}" for x in sp)
        info = {"studio": studio, "round": st.next_round(studio), "draw": None if studio["branch"] else draw,
                "writer": w, "ids": [x["id"] for x in sp]}  # what a Grid Row needs to label its cells
        return {"ui": {"text": [txt]}, "result": (new, [lead + x["prompt"] for x in sp], brief, w, info)}


FORGE_TEMPLATE = st.pathlib.Path(__file__).resolve().parents[1] / "tools" / "forge-template"


class ForgeStudio:
    """Forge a new studio from ~20 references and one sentence: a git repo with STUDIO.md (its practice), JURY.md
    (its checks) and an empty history, at r00. The writer drafts it (paid, minutes); a re-queue loads it."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO",)
    FUNCTION = "forge"
    OUTPUT_NODE = True
    DESCRIPTION = ("refs: a folder of NN.jpg + refs.jsonl with vlm descriptions (tools/fetch_refs.py, describe_refs.py). "
                   "instrument: a folder with instruments.yaml + render.json (how its rounds are drafted and rendered).")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "path": ("STRING", {"default": "~/Boson/examples/new-studio"}),
            "owner": ("STRING", {"default": "", "placeholder": "who the studio is (one line)"}),
            "field": ("STRING", {"default": "", "placeholder": "the field, named plainly"}),
            "sentence": ("STRING", {"multiline": True, "default": "",
                                    "placeholder": "The owner's one sentence: what this studio's work must be"}),
            "refs": ("STRING", {"default": "", "placeholder": "folder with NN.jpg + refs.jsonl"}),
            "instrument": ("STRING", {"default": "", "placeholder": "folder with instruments.yaml + render.json "
                                                                   "(empty = tools/forge-template, Nano Banana)"}),
        }, "optional": {
            "commission": ("STRING", {"multiline": True, "default": "", "placeholder": "what the rounds serve"}),
            **{f"image_{i}": ("IMAGE", {"tooltip": "commission images in order"}) for i in range(1, 5)},
        }}

    def forge(self, path, owner, field, sentence, refs, instrument, commission="", **images):
        repo = st.pathlib.Path(path).expanduser()
        if (repo / ".git").exists():
            if not st.git(repo, "tag", "--list", "r00"):
                raise RuntimeError(f"{repo} holds a forge that never finished (no r00 tag): move it aside first")
            s = st.load(repo, "main")
            r00 = st.git(repo, "rev-parse", "--short=8", "r00")
            by = st.git(repo, "log", "-1", "--format=%b", "r00").strip().splitlines()
            return {"ui": {"text": [f"forged {repo.name} @ {r00}" + (f" by {by[0]}" if by else "")
                                    + ": STUDIO.md, JURY.md, r00 (on disk: loaded, not forged again)"]},
                    "result": (s,)}
        if not sentence.strip() or not field.strip() or not refs.strip():
            return {"ui": {"text": ["waiting for the field, the owner's sentence and the refs folder"]},
                    "result": (ExecutionBlocker(None),)}
        inst = st.pathlib.Path(instrument).expanduser() if instrument.strip() else FORGE_TEMPLATE
        import json as _json, tempfile
        from PIL import Image
        com = None
        wired = [images[k] for k in sorted(images) if images[k] is not None]
        if commission.strip() or wired:
            tmp = st.pathlib.Path(tempfile.mkdtemp(prefix="boson-forge-"))
            paths = []
            for i, t in enumerate(x[0] for x in wired):
                p = tmp / f"commission-{i + 1}.png"
                Image.fromarray((t.cpu().numpy() * 255).clip(0, 255).astype("uint8")).save(p)
                paths.append(p)
            com = {"text": commission.strip(), "refs": paths}
        render = _json.loads((inst / "render.json").read_text()) if (inst / "render.json").exists() else None
        if render and com and com["refs"]:
            render["commission_refs"] = [f"commission/{p.name}" for p in com["refs"]]
        s, meta = st.forge(repo, owner, field, sentence, st.pathlib.Path(refs).expanduser(),
                           (inst / "instruments.yaml").read_text(), render=render, commission=com)
        txt = f"forged {repo.name} @ {s['sha'][:8]} by {meta.get('writer', 'writer')}: STUDIO.md, JURY.md, r00"
        return {"ui": {"text": [txt]}, "result": (s,)}


def _tensor(path):
    import numpy as np, torch
    from PIL import Image
    return torch.from_numpy(np.asarray(Image.open(path).convert("RGB")).astype(np.float32) / 255.0)[None]


class NanoBanana:
    """Renders the studio's drafted round on Nano Banana (Gemini), per the studio's RENDER.json: its refs, then the
    commission images (the ones wired in, else the studio's own), then lead + each piece's prompt."""
    CATEGORY = "boson"
    RETURN_TYPES = ("IMAGE", "STUDIO")
    RETURN_NAMES = ("images", "studio")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "render"
    OUTPUT_NODE = True
    DESCRIPTION = ("live: one Gemini call per piece (needs GEMINI_API_KEY; plates already on disk are reused). "
                   "stored: the committed plates beside the studio, no key, no call. Not seed-reproducible.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "mode": (["stored", "live"], {"tooltip": "stored: the plates this node rendered before, no key"}),
            "draws": ("INT", {"default": 1, "min": 1, "max": 4, "tooltip": "renders per piece (same brief)"}),
        }, "optional": {"backend": (nbn.BACKENDS, {"tooltip": "api: the Gemini API key. comfy-api: the same model on Comfy "
                                                             "credits (COMFY_API_KEY). antigravity: the box's signed-in "
                                                             "Antigravity (agy), ~1K. local: FLUX 3 Klein on a ComfyUI "
                                                             "server (BOSON_LOCAL_COMFY), open weights"}),
                        **{f"image_{i}": ("IMAGE", {"tooltip": "commission images in order (e.g. a Crop Image of the "
                                                           "world); wired ones replace the studio's commission_refs"})
                           for i in range(1, 5)},
                        "shot": ("BOSON_SHOT", {"tooltip": "Compile Scene's shot: its images and prompt replace the "
                                                           "studio's refs and the pieces' prompts (a <<TAKE>> in it is "
                                                           "filled with each drafted piece's prompt)"})}}

    @classmethod
    def IS_CHANGED(cls, studio, mode, draws, backend="api", shot=None, **images):
        return f"{studio['sha']}:{mode}:{draws}:{backend}:{shot['key'] if shot else ''}"

    def render(self, studio, mode, draws, backend="api", shot=None, **images):
        if shot is not None:
            return self.shoot(studio, mode, draws, backend, shot)
        rid = st.next_round(studio)
        pdir = gr.plates_dir(studio.get("source") or studio["repo"])
        if mode == "stored":
            rows = nbn.stored_round(pdir, rid)
            if not rows:
                raise ValueError(f"no stored Nano Banana plates for round {rid} in {pdir}: run once in live mode")
        else:
            specs = st.specs(st.pathlib.Path(studio["dir"]) / "history" / f"round-{rid}")
            if not specs:
                raise ValueError(f"round {rid} has no pieces yet: wire Draft Brief's studio output in")
            commission, wired = None, [images[k] for k in sorted(images) if images[k] is not None]
            if wired:
                from PIL import Image
                import tempfile
                tmp = st.pathlib.Path(tempfile.mkdtemp(prefix="boson-commission-"))
                commission = []
                for i, t in enumerate(x[0] for x in wired):     # first image of each wired batch
                    p = tmp / f"commission-{i + 1}.png"
                    Image.fromarray((t.cpu().numpy() * 255).clip(0, 255).astype("uint8")).save(p)
                    commission.append(p)
            rows = nbn.render_round(studio, pdir, rid, specs, st.render_cfg(studio), draws, commission, backend=backend)
        model = rows[0]["renderer"].split(":", 1)[-1]
        txt = f"round {rid}: {len(rows)} plates, {model} ({mode})"
        return {"ui": {"text": [txt]}, "result": ([_tensor(pdir / r["file"]) for r in rows], studio)}


    def shoot(self, studio, mode, draws, backend, shot):
        """A scene take on the base studio: Compile Scene's images in its order, its prompt (per drafted piece when it
        holds <<TAKE>>). Stored under the plates as round `shot-<key>`, so a re-queue of the same shot costs nothing."""
        pdir, rid = gr.plates_dir(studio.get("source") or studio["repo"]), f"shot-{shot['key']}"
        if not shot["prompt"]:          # a flat-only swap: no call, the parent take goes on to Paste Flat
            return {"ui": {"text": [f"{shot['mode']}: flat swap, no image call"]},
                    "result": ([_tensor(shot["images"][0])], studio)}
        rows = nbn.stored_round(pdir, rid)
        if not rows and mode == "stored":
            return {"ui": {"text": [f"{shot['mode']} {shot['key']} not rendered yet: run in live mode (one image call)"]},
                    "result": (ExecutionBlocker(None),) * 2}
        if not rows:
            if "<<TAKE>>" in shot["prompt"]:
                specs = st.specs(st.pathlib.Path(studio["dir"]) / "history" / f"round-{st.next_round(studio)}")
                if not specs:
                    raise ValueError("the shot leaves <<TAKE>> to the writer: wire Draft Brief's studio output in, "
                                     "or write the take in Compile Scene")
                jobs = [{"id": sp["id"], "prompt": shot["prompt"].replace("<<TAKE>>", sp["prompt"])} for sp in specs]
            else:
                jobs = [{"id": shot["mode"], "prompt": shot["prompt"]}]
            cfg = {**st.render_cfg(studio), "refs": [], "lead": "",
                   **({"aspect": shot["crop"]["aspect"]} if shot.get("crop") else {})}   # a close crop's own aspect
            card = (lambda p, o, r: nbn._local().generate(p, o, r, aspect="1:1")) if backend == "local" else None
            rows = nbn.render_round(studio, pdir, rid, jobs, cfg, draws,   # a local take draws its clothes card locally too
                                    [st.pathlib.Path(p) for p in sc.render_images(shot, card)], backend=backend)
        txt = f"{shot['mode']} {shot['key']}: {len(rows)} take(s), {rows[0]['renderer'].split(':', 1)[-1]} ({mode})"
        return {"ui": {"text": [txt]}, "result": ([_tensor(pdir / r["file"]) for r in rows], studio)}


class Verdict:
    """The owner's one-line round verdict. Empty = the graph stops here, quietly, until the owner writes it."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO",)
    FUNCTION = "commit"
    OUTPUT_NODE = True
    INPUT_IS_LIST = True  # one call for the whole round, however many images came in
    DESCRIPTION = ("Write one sentence on the round as a whole, then queue again. "
                   "It is committed to the studio and binds the next round.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "images": ("IMAGE",),
            "verdict": ("STRING", {"multiline": True, "default": "",
                                   "placeholder": "One sentence on the whole round (required)"}),
        }}

    def commit(self, studio, images, verdict):
        studio, verdict = studio[0], verdict[0]
        if not verdict.strip():
            # SPEC v3 I2: no red error, the graph just waits at review
            return {"ui": {"text": ["waiting for your verdict"]}, "result": (ExecutionBlocker(None),)}
        rid = st.next_round(studio)
        hist = st.pathlib.Path(studio["dir"]) / "history"
        said = " ".join(verdict.split())
        done = hist / f"round-{rid}" / "VERDICT.md"
        if done.exists() and done.read_text().strip() == said:
            # re-queued after the commit: same sentence, nothing to do
            return {"ui": {"text": [f"round {rid} verdict already committed"]}, "result": (studio,)}
        old = [p.parent.name[6:] for p in hist.glob("round-*/VERDICT.md") if p.read_text().strip() == said]
        if old:
            # the widget still holds an earlier round's sentence: never commit it to a round nobody judged
            return {"ui": {"text": [f"waiting for a new verdict (that sentence is round {old[0]}'s)"]},
                    "result": (ExecutionBlocker(None),)}
        new = st.commit_verdict(studio, rid, verdict)
        return {"ui": {"text": [f"committed round {rid} verdict @ {new['sha'][:8]}"]}, "result": (new,)}


class Digest:
    """The writer turns the verdict into the round's history line, lessons and proposed rules.
    Nothing it writes binds a round until the owner approves it (Approve Rules)."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO", "STRING")
    RETURN_NAMES = ("studio", "proposed")
    FUNCTION = "digest"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"studio": ("STUDIO",)}}

    def digest(self, studio):
        new, meta = st.digest(studio)
        rid, props = st.proposed(new)
        txt = "\n".join(f"{n}. {r}" for n, r in props.items()) or "(no rules proposed)"
        head = f"round {rid} digested by {meta['writer']} (${meta['cost_usd']}) @ {new['sha'][:8]}"
        return {"ui": {"text": [head + "\n\n" + txt]}, "result": (new, txt)}


class ApproveRules:
    """The owner picks which proposed rules bind from now on: "05: 1,3" or "05: none". Wire it from Load
    Studio; Draft Brief waits until it has run."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO",)
    FUNCTION = "approve"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "picks": ("STRING", {"default": "", "placeholder": "round: picks, e.g. 05: 1,3 or 05: none"}),
        }}

    def approve(self, studio, picks):
        rid, props = st.proposed(studio)
        listing = "\n".join(f"{n}. {r}" for n, r in props.items()) or "(no rules proposed)"
        if not st.awaiting_approval(studio):
            return {"ui": {"text": [f"no round awaits approval (last: {rid})"]}, "result": (studio,)}
        head, _, rest = picks.partition(":")
        if head.strip() != rid or not rest.strip():
            # picks name their round, so a widget left over from an earlier round never approves this one
            return {"ui": {"text": [f"round {rid} proposes:\n{listing}\n\nwrite  {rid}: 1,3  or  {rid}: none"]},
                    "result": (ExecutionBlocker(None),)}
        new, chosen = st.approve(studio, rest)
        return {"ui": {"text": [f"round {rid}: {len(chosen)} rule(s) now bind @ {new['sha'][:8]}"]}, "result": (new,)}


class Grid:
    """One row per studio revision, same renderer + ref set in every cell; readout between the rows."""
    CATEGORY = "boson"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("grid", "readout")
    FUNCTION = "grid"
    OUTPUT_NODE = True
    DESCRIPTION = ("Row at ref X = the round the studio drafted from X (r00 = the forge alone). stored: plates "
                   "beside the fixture, no key, no LLM call (SPEC v3 I4).")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "refs": ("STRING", {"default": "r00,r01,r02"}),
            "cells": ("INT", {"default": 4, "min": 1, "max": 16}),
            "variant": ("STRING", {"default": "-v1", "tooltip": "only specs whose id contains this (seed variant)"}),
            "mode": (["stored", "live"], {"tooltip": "stored: plates beside the fixture. live: only the Grid Rows "
                                                     "wired below (writer draws rendered on the canvas); the two "
                                                     "never share a grid (I4)"}),
            "arm": (["orig", "stripped"], {"tooltip": "stored prompts as written, or with the T14 template strip "
                                                      "(an altered history, labelled in the readout)"}),
        }, "optional": {f"row_{i}": ("GRIDROW",) for i in range(1, 9)}}

    def grid(self, studio, refs, cells, variant, mode, arm, **live):
        import numpy as np, torch
        if mode == "live":
            rs = gr.merge_live([live[k] for k in sorted(live) if live[k]])
            if not rs:
                raise ValueError("live mode composes Grid Rows only: wire a Grid Row into row_1")
            for r in rs:
                r["plates"] = r["plates"][:cells]
        else:
            rs = gr.rows(studio["source"], refs, cells, variant, arm)
        img = gr.compose(rs)
        t = torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None]
        text = gr.readout(rs)
        return {"ui": {"text": [text]}, "result": (t, text)}


class StudioRefs:
    """The grid's one ref set (02, 08, 01; SPEC v3 §4.2, I6) from the studio itself, for ReferenceMultiLatent.
    No copy into ComfyUI's input folder: the studio stays the only state (I1)."""
    CATEGORY = "boson"
    RETURN_TYPES = ("IMAGE",) * len(st.REFS)
    RETURN_NAMES = tuple(f"ref{r}" for r in st.REFS)
    FUNCTION = "refs"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"studio": ("STUDIO",)}}

    def refs(self, studio):
        import numpy as np, torch
        from PIL import Image
        load = lambda r: torch.from_numpy(np.asarray(  # noqa: E731
            Image.open(st.pathlib.Path(studio["dir"]) / "refs" / f"{r}.jpg").convert("RGB"),
            dtype=np.float32) / 255.0)[None]
        return tuple(load(r) for r in st.REFS)


class GridRow:
    """One live row for Grid: a Draft Brief draw at a tag, its pieces rendered at seed a (and b).
    Wire the same seed primitives into the KSamplers and here, so the readout names the seeds used."""
    CATEGORY = "boson"
    RETURN_TYPES = ("GRIDROW",)
    FUNCTION = "row"
    INPUT_IS_LIST = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "draft": ("BOSON_DRAFT",),
            "images_a": ("IMAGE",),
            "seed_a": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "renderer": ("STRING", {"default": "on FLUX 3 Klein mi2i, refs 02 08 01"}),
        }, "optional": {
            "images_b": ("IMAGE",),
            "seed_b": ("INT", {"default": 1, "min": 0, "max": 0xffffffffffffffff}),
        }}

    def row(self, draft, images_a, seed_a, renderer, images_b=None, seed_b=None):
        import numpy as np
        from PIL import Image
        draft = draft[0]
        if draft["draw"] is None:
            raise ValueError("Grid Row shows draws at a tag; this draft was committed on a branch (a real round)")
        pil = lambda t: Image.fromarray((t[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8))  # noqa: E731
        cells = []
        for i, sid in enumerate(draft["ids"]):
            for imgs, seed in ((images_a, seed_a), (images_b, seed_b)):
                if imgs and i < len(imgs):
                    cells.append((pil(imgs[i]), sid, seed[0]))
        return (gr.live_row(draft, cells, renderer[0]),)


from .scene_nodes import NODES as _SCENE  # noqa: E402
from .house_nodes import NODES as _HOUSE  # noqa: E402
from .round_nodes import NODES as _ROUND  # noqa: E402

NODE_CLASS_MAPPINGS = {"BosonStudioRefs": StudioRefs, "BosonGridRow": GridRow, "BosonGrid": Grid, "BosonLoadStudio": LoadStudio, "BosonStudioInfo": StudioInfo, "BosonDraftBrief": DraftBrief,
                       "BosonNanoBanana": NanoBanana, "BosonForgeStudio": ForgeStudio,
                       "BosonVerdict": Verdict, "BosonDigest": Digest, "BosonApproveRules": ApproveRules}
NODE_DISPLAY_NAME_MAPPINGS = {"BosonStudioRefs": "Studio Refs", "BosonGridRow": "Grid Row", "BosonGrid": "Grid", "BosonLoadStudio": "Load Studio", "BosonStudioInfo": "Studio Info",
                              "BosonDraftBrief": "Draft Brief", "BosonNanoBanana": "Nano Banana (Boson)", "BosonForgeStudio": "Forge Studio", "BosonVerdict": "Verdict",
                              "BosonDigest": "Digest", "BosonApproveRules": "Approve Rules"}
for _n in (_SCENE, _HOUSE, _ROUND):
    NODE_CLASS_MAPPINGS.update({k: c for k, (c, _) in _n.items()})
    NODE_DISPLAY_NAME_MAPPINGS.update({k: n for k, (_, n) in _n.items()})
