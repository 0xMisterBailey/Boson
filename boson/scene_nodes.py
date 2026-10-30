"""Boson scene nodes: New Scene, Load Scene, Load Take, Cast, Compile Scene, Uncrop, Locate, Slot Crop, Paste Flat,
Commit Take, Keep Piece, Commit Clip, Load Clip.

SCENE travels as a plain dict (scene.load); the scene's git repo holds the state (SPEC v3 I1), the graph only holds
pending casts in its widgets. Down: Cast -> Compile Scene -> Nano Banana (its `shot` input) -> Locate -> Commit Take;
a worn swap on a close crop puts Uncrop (mask from core's Remove Background) between Nano Banana and Locate.
Up: Load Take -> Slot Crop -> a slot studio's Nano Banana image_1 (its brief); Paste Flat lays a flat piece on a take.
"""
import re
from comfy_execution.graph_utils import ExecutionBlocker

from . import scene as sc
from . import studio as st


def _pil(t):
    import numpy as np
    from PIL import Image
    return Image.fromarray((t[0].cpu().numpy() * 255).round().clip(0, 255).astype(np.uint8))


def _t(pil):
    import numpy as np, torch
    return torch.from_numpy(np.asarray(pil.convert("RGB")).astype(np.float32) / 255.0)[None]


_UNWIRED = object()


def _open(path):
    from PIL import Image
    return Image.open(path).convert("RGB")


class NewScene:
    """A new scene repo: from a SCENE.json (spec), or from one piece (from_piece: studio@sha:path) as its base view with
    no slots yet. Kept in the scene cache as <name>-scene unless path says otherwise. Already on disk: loaded."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE",)
    FUNCTION = "create"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"name": ("STRING", {"default": "", "placeholder": "the scene's name, e.g. street"}),
                             "spec": ("STRING", {"multiline": True, "default": "",
                                                 "placeholder": "SCENE.json (docs/APP-API.md); empty = from_piece"}),
                             "from_piece": ("STRING", {"default": "", "placeholder": "studio@sha:path, the base view"})},
                "optional": {"path": ("STRING", {"default": "", "placeholder": "empty = ~/.cache/boson/scenes/<name>-scene"})}}

    def create(self, name, spec, from_piece, path=""):
        import json
        name = name.strip()
        if not name or not (spec.strip() or from_piece.strip()):
            return {"ui": {"text": ["waiting for a name and a SCENE.json or a piece"]}, "result": (ExecutionBlocker(None),)}
        repo = st.pathlib.Path(path.strip() or sc.SCENES / f"{name}-scene").expanduser()
        if (repo / ".git").exists():
            s = sc.load(repo, "main")
            return {"ui": {"text": [f"scene {s['spec']['name']} @ {s['sha'][:8]} (on disk: loaded, not created again)"]},
                    "result": (s,)}
        d = json.loads(spec) if spec.strip() else sc.spec_from_piece(name, from_piece.strip())
        d["name"] = name
        s = sc.create(repo, d)
        return {"ui": {"text": [f"new scene {name} @ {s['sha'][:8]}: base {d['base']['studio']}, "
                                f"{len(d['slots'])} slots ({repo})"]}, "result": (s,)}


class LoadScene:
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE",)
    FUNCTION = "load"
    OUTPUT_NODE = True
    DESCRIPTION = "A scene is its own git repo: SCENE.json (base studio view + slots) and its takes. ref = a branch or a commit."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"repo": ("STRING", {"default": "austin-stop"}),   # a shipped scene's name, or a path
                             "ref": ("STRING", {"default": "main"})}}

    @classmethod
    def IS_CHANGED(cls, repo, ref):
        try:
            return st.resolve(sc.open_repo(repo), ref)
        except Exception as e:
            return str(e)

    def load(self, repo, ref):
        s = sc.load(repo, ref)
        cast = "\n".join(f"- {x['id']} ({x['role']}): {x['piece']}" for x in s["spec"]["slots"])
        txt = f"{s['spec']['name']} @ {s['sha'][:8]}: {len(s['takes'])} takes, base {s['spec']['base']['studio']}\n{cast}"
        return {"ui": {"text": [txt]}, "result": (s,)}


class LoadTake:
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("IMAGE", "BOSON_BOXES", "STRING")
    RETURN_NAMES = ("image", "boxes", "take")
    FUNCTION = "take"
    DESCRIPTION = "One committed take (empty = the newest) with the boxes Locate found in it."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "take": ("STRING", {"default": "", "placeholder": "01 (empty = newest)"})}}

    def take(self, scene, take):
        if not scene["takes"]:          # a quiet stop: a whole-graph Run on a new scene skips the up path
            return {"ui": {"text": [f"scene {scene['spec']['name']} has no takes yet: nothing to crop"]},
                    "result": (ExecutionBlocker(None),) * 3}
        t = sc.take(scene, take.strip() or scene["takes"][-1])
        if not t["boxes"]:
            return {"ui": {"text": [f"take {t['id']} has no slot map, so it can't be cropped"]},
                    "result": (ExecutionBlocker(None),) * 3}
        return (_t(_open(t["image"])), t["boxes"], t["id"])


class AddSlot:
    """Make a slot from the frame (round 49): something the base shows and no slot holds yet (an anchor Locate already
    boxes, e.g. the taqueria) becomes a slot a studio can fill. Commits SCENE.json; the slot holds the base's own
    pixels until a piece is cast, so nothing re-renders until a Swap. The same slot again commits nothing."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE",)
    FUNCTION = "add"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",),
                             "anchor": ("STRING", {"default": "", "placeholder": "a base anchor (Locate boxes it), e.g. taqueria"}),
                             "slot": ("STRING", {"default": "", "placeholder": "the new slot's id, e.g. building-left"}),
                             "noun": ("STRING", {"default": "", "placeholder": "what it is, e.g. the corner building"}),
                             "studio": ("STRING", {"default": "", "placeholder": "the studio that fills it"})},
                "optional": {"where": ("STRING", {"default": "", "placeholder": "where it stands, for Locate (optional)"}),
                             "box": ("STRING", {"default": "", "placeholder": "x, y, w, h fractions (no anchor)"})}}

    def add(self, scene, anchor, slot, noun, studio, where="", box=""):
        if not (slot.strip() and noun.strip() and studio.strip() and (anchor.strip() or box.strip())):
            return {"ui": {"text": ["waiting: an anchor (or a box), the slot's id, what it is and its studio"]},
                    "result": (ExecutionBlocker(None),)}
        b = [float(v) for v in re.split(r"[,\s]+", box.strip()) if v] if box.strip() else None
        new = sc.promote(scene, slot, studio, noun, anchor=anchor.strip(), box=b, where=where)
        txt = (f"slot {slot.strip()} " + ("already in the scene" if new is scene else f"made from the frame @ {new['sha'][:8]}")
               + f": {studio.strip()} fills it")
        return {"ui": {"text": [txt]}, "result": (new,)}


class Cast:
    """Cast one slot: a swap is this one widget. Nothing is committed; the cast becomes the scene with the next take,
    so swaps stay pending until a re-shoot (or one Swap edit)."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE",)
    FUNCTION = "cast"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "slot": ("STRING", {"default": "car"}),
                             "piece": ("STRING", {"default": "", "placeholder": "studio@sha:path (empty = keep the cast)"})},
                "optional": {"desc": ("STRING", {"default": "", "placeholder": "what Locate looks for (optional)"}),
                             "short": ("STRING", {"default": "", "placeholder": "the piece in a few words (optional)"})}}

    def cast(self, scene, slot, piece, desc="", short=""):
        if piece.strip() and not any(x["id"] == slot.strip() for x in scene["spec"]["slots"]):
            # the graph has a Cast for a slot this scene lacks: pass the scene on, the casts of the others still count
            return {"ui": {"text": [f"{slot.strip()} is not a slot of this scene yet: this cast is skipped"]},
                    "result": (scene,)}
        new = sc.cast(scene, slot.strip(), piece, desc, short)
        p = sc.pending(new)
        return {"ui": {"text": [f"pending: {', '.join(p)}" if p else "no pending swaps"]}, "result": (new,)}


class CompileScene:
    """SCENE -> the ordered images and the prompt for Nano Banana's `shot` input. Deterministic, no model call: a
    close-crop worn swap's clothes-only card is made by Nano Banana when it renders live (once, cached).
    shoot: image 1 = the blocking plate (stand-ins drawn on the base view). swap: image 1 = the last shoot take, edited
    so only the swapped slots change. take: the TAKE block (hour, weather, street life); empty leaves <<TAKE>> for the
    base studio's writer (Draft Brief) to fill per piece."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("BOSON_SHOT", "IMAGE", "STRING")
    RETURN_NAMES = ("shot", "images", "prompt")
    OUTPUT_IS_LIST = (False, True, False)
    FUNCTION = "compile"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "mode": (["swap", "shoot"],),
                             "take": ("STRING", {"multiline": True, "default": "",
                                                 "placeholder": "TAKE: hour, season, weather, light, street life (empty = the writer's)"})},
                "optional": {"worn": (["close crop", "whole frame"], {
                    "tooltip": "a swap of one worn slot: edit a close crop of the wearer with a clothes-only card "
                               "(Nano Banana makes it live, one cached call; wire Uncrop after it), or the whole frame"})}}

    def compile(self, scene, mode, take, worn="close crop"):
        if mode == "swap" and not (sc.swap_parent(scene) and sc.swapped_since(scene, sc.swap_parent(scene))):
            return {"ui": {"text": ["nothing to swap: cast a slot first (or Shoot)"]},
                    "result": (ExecutionBlocker(None),) * 3}
        close = worn == "close crop"
        shot = sc.compile_shot(scene, mode, take, crop_worn=close, card="defer" if close else None)
        what = ", ".join(f"{i + 1} {lab}" for i, lab in enumerate(shot["labels"]))
        txt = f"{mode} {shot['key']}: images {what}" + ("" if shot["prompt"] else " (flat swap: no image call)")
        if shot.get("crop"):
            txt += f"; close crop at {shot['crop']['aspect']}: wire Uncrop before Locate"
        return {"ui": {"text": [txt]},
                "result": (shot, [_t(_open(p)) for p in shot["images"]], shot["prompt"])}


class Uncrop:
    """Puts a close-crop edit back into its take: only the person (the mask, from core's Remove Background on the
    edit), so the crop's own background never shows; where the old wearer was wider, the take's background is filled
    in from around them. No mask wired: BiRefNet runs here (boson/segment.py), as it always does for the old wearer.
    A shot without a crop passes the image through."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "uncrop"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "shot": ("BOSON_SHOT",)},
                "optional": {"mask": ("MASK", {"lazy": True,
                                               "tooltip": "the subject in the edited crop (Remove Background)"})}}

    def check_lazy_status(self, image, shot, mask=_UNWIRED):
        """Remove Background runs only for a close-crop shot (None = wired, not yet run)."""
        return ["mask"] if shot.get("crop") and mask is None else []

    def uncrop(self, image, shot, mask=None):
        crop = shot.get("crop")
        if not crop:
            return (image,)
        from PIL import Image
        import numpy as np
        edit = _pil(image)
        if mask is None:
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                edit.save(f"{d}/edit.png")
                m = sc.subject_masks([f"{d}/edit.png"])[0]
        else:
            m = Image.fromarray((mask.reshape(-1, *mask.shape[-2:])[0].cpu().numpy() * 255).round().clip(0, 255)
                                .astype(np.uint8))
        before = sc.subject_masks([shot["images"][0]])[0]   # the old wearer, so a wider old outfit is filled
        out = _t(sc.uncrop(_open(crop["parent_image"]), edit, crop["box"], inner=crop["inner"], mask=m,
                           before=before, wearer=crop.get("wearer")))
        sc.record_uncropped(shot["key"], sc.image_hash(_pil(out)))   # what Locate keys on: the ready read's answer
        return (out,)


class Locate:
    """Finds every slot in a take: one Gemini vision call per take (a few cents), cached by pixels. stored: never
    calls (a committed take's boxes, or the cache)."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("BOSON_BOXES", "STRING")
    RETURN_NAMES = ("boxes", "readout")
    FUNCTION = "locate"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "scene": ("SCENE",), "mode": (["stored", "live"],),
                             "model": ("STRING", {"default": sc.LOCATE_MODEL})}}

    def locate(self, image, scene, mode, model):
        try:
            b = sc.locate(scene, _pil(image), model.strip() or sc.LOCATE_MODEL, mode)
        except ValueError as e:       # stored and never located: a quiet stop, not a red error
            if "never located" not in str(e):
                raise
            return {"ui": {"text": [str(e)]}, "result": (ExecutionBlocker(None),) * 2}
        lines = []
        for k, v in b["slots"].items():
            if not v.get("visible"):
                lines.append(f"{k}: not found")
            elif "items" in v:
                lines.append(f"{k}: {len(v['items'])} found, off " + " ".join(str(i["off"]) for i in v["items"]))
            else:
                lines.append(f"{k}: off {v['off']}")
        c = b["checks"]
        lines.append(f"handed {c.get('handed')}, world drift {c.get('world_drift')}")
        txt = "\n".join(lines)
        return {"ui": {"text": [txt]}, "result": (b, txt)}


class SlotCrop:
    """The slot's located box in a take (padded), as that slot studio's commission image ("ask for new")."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "crop"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "boxes": ("BOSON_BOXES",), "slot": ("STRING", {"default": "car"}),
                             "item": ("INT", {"default": 0, "min": 0, "max": 16, "tooltip": "which one, for a flat slot"}),
                             "pad": ("FLOAT", {"default": 0.15, "min": 0, "max": 1, "step": 0.01})},
                "optional": {"scene": ("SCENE", {"tooltip": "a slot this take's Locate never saw crops at its "
                                                             "SCENE.json place box"})}}

    def crop(self, image, boxes, slot, item, pad, scene=None):
        slot = slot.strip()
        if scene and not any(s["id"] == slot for s in scene["spec"]["slots"]):   # a quiet stop, as Make's "waiting"
            return {"ui": {"text": [f"{slot} is not a slot of this scene yet: skipped"]}, "result": (ExecutionBlocker(None),)}
        place = next((s["place"] for s in scene["spec"]["slots"] if s["id"] == slot), None) if scene else None
        got = boxes["slots"].get(slot) or {}
        if not got.get("visible") and not (place and (place.get("box") or place.get("boxes"))):
            return {"ui": {"text": [f"{slot} is not in this take: skipped"]}, "result": (ExecutionBlocker(None),)}
        return (_t(sc.crop(_pil(image), boxes, slot, item, pad, place)),)


class PasteFlat:
    """Perspective-warps a flat piece (a poster, a sign) onto each quad Locate found for the slot. The piece is the
    slot's cast piece unless one is wired in. glass: how much of the take shows through (reflection, tint)."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "paste"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "boxes": ("BOSON_BOXES",), "scene": ("SCENE",),
                             "slot": ("STRING", {"default": "posters"}),
                             "glass": ("FLOAT", {"default": 0.15, "min": 0, "max": 1, "step": 0.01})},
                "optional": {"flat": ("IMAGE",)}}

    def paste(self, image, boxes, scene, slot, glass, flat=None):
        s = next((x for x in scene["spec"]["slots"] if x["id"] == slot.strip()), None)
        if s is None or s["kind"] != "flat":
            txt = (f"{slot.strip()} is not a slot of this scene yet: skipped" if s is None
                   else "Paste Flat only works on posters and signs: skipped")
            return {"ui": {"text": [txt]}, "result": (ExecutionBlocker(None),)}
        got = boxes["slots"].get(s["id"]) or {}
        quads = [i["quad"] for i in got.get("items", [])]
        art = _pil(flat) if flat is not None else _open(sc.piece(s["piece"]))
        return (_t(sc.paste(_pil(image), quads, art, glass)),)


class CommitTake:
    """Commits the take: its image, the cast it was shot with, Locate's boxes. A take is a commit, never rewritten;
    the same pixels again commit nothing."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE",)
    FUNCTION = "commit"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "image": ("IMAGE",), "boxes": ("BOSON_BOXES",)},
                "optional": {"shot": ("BOSON_SHOT",)}}

    def commit(self, scene, image, boxes, shot=None):
        new, tid = sc.commit_take(scene, _pil(image), boxes, shot)
        same = new is scene
        txt = f"take {tid} {'already committed' if same else 'committed'} @ {new['sha'][:8]}"
        return {"ui": {"text": [txt]}, "result": (new,)}


class KeepPiece:
    """Puts one of the studio's pieces on the shared shelf (SHELF.jsonl, committed), named studio@sha:path; op unkeep
    takes it off again (path, or the whole studio@sha:path)."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO", "STRING")
    RETURN_NAMES = ("studio", "piece")
    FUNCTION = "keep"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"studio": ("STUDIO",),
                             "path": ("STRING", {"default": "", "placeholder": "r02/light-line-r02__d0__nb.png"}),
                             "note": ("STRING", {"default": ""})},
                "optional": {"op": (["keep", "unkeep"],)}}

    def keep(self, studio, path, note, op="keep"):
        if not path.strip():
            return {"ui": {"text": [f"nothing to {op}: name a piece"]}, "result": (ExecutionBlocker(None),) * 2}
        if op == "unkeep":
            new, gone = st.unkeep(studio, path.strip())
            return {"ui": {"text": [f"off the shelf: {', '.join(gone)}" if gone else "not on the shelf"]},
                    "result": (new, gone[0] if gone else "")}
        new, ref = st.keep(studio, path.strip(), note)
        return {"ui": {"text": [f"on the shelf: {ref}"]}, "result": (new, ref)}



class CommitClip:
    """Commits a clip made from one take: the video from any video node (Comfy's partner Gemini Omni, LTX, a local
    model) and the words it was moved by. The clip lives in the scene repo beside its take; the same bytes again
    commit nothing. Stored mode replays it with Load Clip, no key."""
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("SCENE", "STRING")
    RETURN_NAMES = ("scene", "clip")
    FUNCTION = "commit"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "video": ("VIDEO",), "take": ("STRING", {"default": ""}),
                             "prompt": ("STRING", {"multiline": True, "default": ""}),
                             "renderer": ("STRING", {"default": "comfy-api:gemini-omni-1.1-flash"})}}

    def commit(self, scene, video, take, prompt, renderer):
        import tempfile, pathlib
        from comfy_api.latest import Types
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "clip.mp4"
            video.save_to(str(f), format=Types.VideoContainer.MP4)
            new, cid = sc.commit_clip(scene, f, take.strip() or (scene["takes"][-1] if scene["takes"] else ""),
                                      prompt, renderer)
        same = new is scene
        return {"ui": {"text": [f"clip {cid} {'already committed' if same else 'committed'} @ {new['sha'][:8]}"]},
                "result": (new, cid)}


class LoadClip:
    CATEGORY = "boson/scene"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("video", "prompt")
    FUNCTION = "load"
    DESCRIPTION = "One committed clip (empty = the newest), straight from the scene repo: no key, no call."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": ("SCENE",), "clip": ("STRING", {"default": "", "placeholder": "01 (empty = newest)"})}}

    def load(self, scene, clip):
        from comfy_api.latest import InputImpl
        if not scene.get("clips"):
            raise ValueError(f"scene {scene['spec']['name']} has no clips yet: run a video node into Commit Clip")
        c = sc.clip(scene, clip.strip() or scene["clips"][-1])
        return (InputImpl.VideoFromFile(c["video"]), c.get("prompt") or "")

NODES = {"BosonNewScene": (NewScene, "New Scene"), "BosonLoadScene": (LoadScene, "Load Scene"), "BosonLoadTake": (LoadTake, "Load Take"), "BosonCast": (Cast, "Cast"), "BosonAddSlot": (AddSlot, "Add Slot"),
         "BosonCompileScene": (CompileScene, "Compile Scene"), "BosonUncrop": (Uncrop, "Uncrop"), "BosonLocate": (Locate, "Locate"),
         "BosonSlotCrop": (SlotCrop, "Slot Crop"), "BosonPasteFlat": (PasteFlat, "Paste Flat"),
         "BosonCommitTake": (CommitTake, "Commit Take"), "BosonKeepPiece": (KeepPiece, "Keep Piece"),
         "BosonCommitClip": (CommitClip, "Commit Clip"), "BosonLoadClip": (LoadClip, "Load Clip")}
