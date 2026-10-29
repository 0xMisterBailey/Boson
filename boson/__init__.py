"""Boson: a studio is a git repo, your round verdict binds the next round. ComfyUI node pack."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"  # boson.js: each node's status line (ui.text) on the canvas; panel.js: the Boson sidebar

try:                      # the panel's read-only routes; absent outside a ComfyUI server (tests, CLI)
    from aiohttp import web as _web
    from server import PromptServer as _PS
    from .server import register as _register
    _register(_PS.instance.routes, _web)
except ImportError:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
