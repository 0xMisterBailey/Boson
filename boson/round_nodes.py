"""Boson round nodes: Dots, the owner's taste loop inside the graph (round 44). The room (web/app/room.js) dots the open
round's pieces, writes the one-sentence verdict, sets this node's widgets and queues only it.

Dots commits exactly what `tools/loop.py next` commits before it makes (studio.commit_dots): greens -> the house pins,
the verdict row in LOOP.jsonl. It never makes the next round (that spends); its `brief` output is the next make's idea,
for a Make node the owner switches to live. Nothing here holds state: the studio's git repo does (SPEC v3 I1).
"""
from comfy_execution.graph_utils import ExecutionBlocker

from . import studio as st


def _lines(text):
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


class Dots:
    """The owner's dots and verdict on a loop round: greens (make more like these, they become the pins), reds (not
    this) and one sentence on the whole round. Empty verdict: the graph waits here (I2). Re-queued, it commits nothing."""
    CATEGORY = "boson"
    RETURN_TYPES = ("STUDIO", "STRING")
    RETURN_NAMES = ("studio", "brief")
    FUNCTION = "commit"
    OUTPUT_NODE = True
    DESCRIPTION = ("Green = make more like it (pinned), red = not this, then one sentence on the round. Committed to the "
                   "studio; it binds the next round. brief: the next make's idea (Make it live to spend).")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "studio": ("STUDIO",),
            "round": ("INT", {"default": 1, "min": 1, "max": 999, "tooltip": "the loop round these dots are on"}),
            "greens": ("STRING", {"multiline": True, "default": "", "placeholder": "studio@sha:path, one per line"}),
            "reds": ("STRING", {"multiline": True, "default": "", "placeholder": "studio@sha:path, one per line"}),
            "verdict": ("STRING", {"multiline": True, "default": "",
                                   "placeholder": "One sentence on the whole round (required)"}),
        }}

    def commit(self, studio, round, greens, reds, verdict):
        if not verdict.strip():          # SPEC v3 I2: no red error, the graph just waits for the owner
            return {"ui": {"text": [f"waiting for your verdict on round {round}"]},
                    "result": (ExecutionBlocker(None),) * 2}
        g, r = _lines(greens), _lines(reds)
        if not (g or r):
            return {"ui": {"text": [f"waiting for your dots on round {round}: green what to make more of, red what to stop"]},
                    "result": (ExecutionBlocker(None),) * 2}
        try:
            new, row, changed = st.commit_dots(studio, round, g, r, verdict)
        except (ValueError, RuntimeError) as e:     # a stale widget, a moved branch: shown, nothing committed
            return {"ui": {"text": [f"not committed: {e}"]}, "result": (ExecutionBlocker(None),) * 2}
        done = next(x for x in st.loop_rounds(new) if x["round"] == row["round"])
        brief = st.next_brief(done)
        head = (f"round {row['round']} verdict @ {new['sha'][:8]}: {len(row['greens'])} green -> pins, "
                f"{len(row['reds'])} red" if changed else f"round {row['round']} verdict already committed")
        return {"ui": {"text": [f"{head}\n\nnext brief:\n{brief}"]}, "result": (new, brief)}


NODES = {"BosonDots": (Dots, "Dots")}
