"""Boson as a ComfyUI custom node pack: clone this repo into ComfyUI/custom_nodes/ (any folder name) and restart.
The pack itself is boson/; this file only lets ComfyUI load it from the repo root, so examples/ sits beside it."""
WEB_DIRECTORY = "./boson/web"   # served at /extensions/<this folder's name>/; /boson/app finds that name itself

if __package__:   # ComfyUI loads this folder as a package; pytest, run at the repo root, imports this file bare
    from .boson import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
