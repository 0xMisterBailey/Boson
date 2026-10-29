Make {N} pieces for this studio, now, for one frame and the owner's idea. This is not a round: no brief, no
verdict, no history. The owner is at the board and wants {N} pieces back.

The frame: {FRAME}
The owner's idea: {IDEA}{LIKE}

1. Read the studio first: `STUDIO.md`, `JURY.md`, `instruments.yaml`, `refs/refs.jsonl` (use the `vlm`
   descriptions; do not open image files), `TASTE.json` if present (the house: sentence, words, style lines,
   principles, subjects), `history/RULES.md` (binding), `history/LESSONS.md`, and the owner's words on past
   rounds (`history/round-*/VERDICT.md`).
2. Make {N} different pieces that answer the idea inside the frame, each unmistakably this studio's. Different
   means different: not one piece in {N} colours.
3. For each piece write one render spec, `make/specs/<slug>.json`, exactly this JSON shape (all keys, no others):
   {"id": "<slug>", "series": "<slug>", "title": "<title>", "concept": "<one sentence for the owner>",
   "prompt": "<the full prompt for the instrument>", "width": {W}, "height": {H}}

{INSTRUMENT}

Write only inside `make/specs/`. Do not edit any other file. Finish with one line per piece.
