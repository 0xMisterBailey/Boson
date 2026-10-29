#!/usr/bin/env python3
"""Nano Banana (Gemini image) client: prompt + optional reference images -> one PNG.

Top rung of the image ladder (IDEAS round 27). Key: $GEMINI_API_KEY or ~/.config/gemini/api_key.
Every call appends a line to <out dir>/nb-log.jsonl (model, prompt, refs, usage, seconds).

  python3 tools/nb.py --prompt "..." --out a.png [--ref crop.png ...] [--aspect 16:9] [--size 2K]
"""
import argparse, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "boson"))
import nanobanana  # noqa: E402  (the one client: the pack's Nano Banana node uses it too)


def generate(prompt, out, refs=(), model=nanobanana.MODEL, aspect=None, size="2K"):
    try:
        return nanobanana.generate(prompt, out, refs, model, aspect, size)
    except RuntimeError as e:
        sys.exit(str(e))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--model", default="gemini-nano-banana-2.1")
    ap.add_argument("--aspect")
    ap.add_argument("--size", default="2K", choices=["1K", "2K", "4K"])
    a = ap.parse_args()
    generate(a.prompt, a.out, a.ref, a.model, a.aspect, a.size)
