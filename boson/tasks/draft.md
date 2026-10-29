Make round {NN}'s draft for this studio.

1. Read the studio first: `STUDIO.md`, `JURY.md`, `instruments.yaml`, `refs/refs.jsonl` (use the `vlm`
   descriptions; do not open image files), and the whole history: `history/rounds.jsonl`,
   `history/RULES.md` (binding), `history/LESSONS.md`, and every earlier `history/round-*/` folder
   (`VERDICT.md` or `OWNER-NOTE.md` = the owner's words on that round; `labels.jsonl` if present).
2. Write `history/round-{NN}/BRIEF.md`: a name for the round; its fingerprint (one line: what this round
   is, so it can be told apart from every other round); for every binding rule in RULES.md, quote it and
   say exactly how this round obeys it; what this round refuses by name and why; then **{N} pieces**,
   each with a short slug, a title, and the concept in one or two sentences.
3. For each piece write one render spec, `history/round-{NN}/specs/<slug>.json`, exactly this JSON shape
   (all keys, no others):
   {"id": "<slug>-r{NN}", "series": "<slug>", "title": "<title>", "concept": "<one sentence for the
   reviewer>", "prompt": "<the full prompt for the instrument>", "width": {W}, "height": {H}}
4. Write `history/round-{NN}/SELF-ASSESSMENT.md`: score idea and execution separately per piece (1-10),
   name the weakest two and why. The owner's eye is the judge, not you.

{INSTRUMENT}

Write only inside `history/round-{NN}/`. Do not edit any other file. Finish with a three-line summary.
