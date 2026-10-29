"""Boson house nodes: Make (n pieces for a frame and an idea, outside the round loop) and Edit House (an owner edit of
the studio's house: sentence, words, style lines, principles, subjects, pictures, pins).

The designer's path through a studio (IDEAS round 33): the house is front and centre and moldable; Make answers an
idea now. Rounds (Draft Brief -> Verdict -> Digest) stay as the studio running on its own. Nothing here holds state:
Edit House commits TASTE.json, Make keeps its specs in a cache and its plates beside the studio (SPEC v3 I1).
"""
from comfy_execution.graph_utils import ExecutionBlocker

from . import grid as gr
from . import nanobanana as nbn
from . import scene as sc
from . import studio as st

MAX_REFS = 10   # images per make call: pieces it varies, house pictures, pins, commission images


def _u8(t):
    import numpy as np
    return (t[0].cpu().numpy() * 255).round().clip(0, 255).astype(np.uint8)


def _tensor(path):
    import numpy as np, torch
    from PIL import Image
    return torch.from_numpy(np.asarray(Image.open(path).convert("RGB")).astype(np.float32) / 255.0)[None]


class Make:
    """Make n pieces for one frame (a style line or a subject) and the owner's idea: the writer reads the whole studio
    and writes n render specs (one paid call, minutes), Nano Banana renders them with the studio's refs plus the piece
    it varies (like), the house pictures, the pins and any wired commission image. Not a round: nothing is committed,
    no verdict waits. Same inputs again = the same make, no second call."""
    CATEGORY = "boson"
    RETURN_TYPES = ("IMAGE", "STRING", "STUDIO")
    RETURN_NAMES = ("images", "pieces", "studio")
    OUTPUT_IS_LIST = (True, False, False)
    FUNCTION = "make"
    OUTPUT_NODE = True
    DESCRIPTION = ("live: one writer call + one image call per piece (made once, then stored). stored: what this "
                   "make rendered before, no key, no call. pieces: one studio@sha:path per line, for Keep, Pin, Cast.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "frame": ("STRING", {"default": "", "placeholder": "a style line or a subject (empty = the house)"}),
            "idea": ("STRING", {"multiline": True, "default": "", "placeholder": "the owner's idea, in their words"}),
            "n": ("INT", {"default": 4, "min": 1, "max": 8}),
            "mode": (["stored", "live"], {"tooltip": "stored: this make's plates from before, no key, no call"}),
        }, "optional": {
            "like": ("STRING", {"default": "", "placeholder": "studio@sha:path: make more like this piece"}),
            "backend": (nbn.BACKENDS, {"tooltip": "who draws: api (Gemini key), comfy-api (Comfy credits), "
                                                  "antigravity (agy), local (FLUX 3 Klein, open weights)"}),
            **{f"image_{i}": ("IMAGE", {"tooltip": "commission images (e.g. a Slot Crop of a scene)"}) for i in range(1, 5)},
        }}

    @classmethod
    def IS_CHANGED(cls, studio, frame, idea, n, mode, like="", backend="api", **images):
        wired = [_u8(images[k]).tobytes() for k in sorted(images) if images[k] is not None]
        return f"{st.make_key(studio, frame, idea, n, like, wired)}:{mode}:{backend}"

    def make(self, studio, frame, idea, n, mode, like="", backend="api", **images):
        like = like.strip()
        if not (idea.strip() or frame.strip() or like):
            return {"ui": {"text": ["waiting for an idea (or a frame, or a piece to make more like)"]},
                    "result": (ExecutionBlocker(None),) * 3}
        wired = [images[k] for k in sorted(images) if images[k] is not None]
        key = st.make_key(studio, frame, idea, n, like, [_u8(t).tobytes() for t in wired])
        rid, pdir = f"make-{key}", gr.plates_dir(studio.get("source") or studio["repo"])
        rows = nbn.stored_round(pdir, rid)
        if not rows and mode == "stored":
            return {"ui": {"text": [f"make {key} not made yet: run in live mode (a writer call + {n} image calls)"]},
                    "result": (ExecutionBlocker(None),) * 3}
        if not rows:
            specs, _ = st.make(studio, frame, idea, n, like, images=wired, key=key)
            house = st.taste(studio)
            refs = [sc.piece(x) for x in ([like] if like else []) + house["pictures"] + house["pins"]]
            if wired:
                import tempfile
                from PIL import Image
                tmp = st.pathlib.Path(tempfile.mkdtemp(prefix="boson-make-"))
                for i, t in enumerate(wired):
                    Image.fromarray(_u8(t)).save(tmp / f"commission-{i + 1}.png")
                    refs.append(tmp / f"commission-{i + 1}.png")
            rows = nbn.render_round(studio, pdir, rid, specs, st.render_cfg(studio), 1, refs[:MAX_REFS] or None,
                                    backend=backend)
        name = st.name_of(studio)
        pieces = [f"{name}@{r['studio_sha'][:8]}:{r['file']}" for r in rows]
        txt = f"make {key}: {len(rows)} pieces ({mode})\n" + "\n".join(pieces)
        return {"ui": {"text": [txt]}, "result": ([_tensor(pdir / r["file"]) for r in rows], "\n".join(pieces), studio)}


class EditHouse:
    """An owner edit of the studio's house, one commit to TASTE.json: the house sentence, descriptor words, style
    lines, principles, subjects, house pictures and pins (pieces, studio@sha:path). Re-queued, it commits nothing."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO", "STRING")
    RETURN_NAMES = ("studio", "house")
    FUNCTION = "edit"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "field": (list(st.HOUSE_FIELDS),),
            "op": (["add", "remove", "set"], {"tooltip": "set: the sentence, or a whole list one per line"}),
            "value": ("STRING", {"multiline": True, "default": "", "placeholder": "a word, a line, a subject, a piece"}),
        }}

    def edit(self, studio, field, op, value):
        if not value.strip():
            return {"ui": {"text": [f"nothing to {op}: write the {field}"]}, "result": (ExecutionBlocker(None),) * 2}
        new, changed = st.edit_house(studio, field, op, value)
        cur = st.taste(new)[field]
        shown = cur if isinstance(cur, str) else "; ".join(x if isinstance(x, str) else x["name"] for x in cur)
        txt = f"house {field} @ {new['sha'][:8]}{'' if changed else ' (no change)'}: {shown}"
        return {"ui": {"text": [txt]}, "result": (new, shown)}


NODES = {"BosonMake": (Make, "Make"), "BosonEditHouse": (EditHouse, "Edit House")}
