You are standing up a brand-new studio from nothing but its owner's reference works and one sentence.
This folder is the studio. It has no history yet: this is its first day.

Inputs (read all of them):
- `FORGE-INPUT.md`: the owner, the field and the owner's one sentence.
- `refs/refs.jsonl`: the owner's {K} reference works, one JSON object per line: title, maker, year,
  why the owner chose it (empty = the owner chose the set as a whole), the source URL and license, and
  `vlm`, a description of the image written by a vision model. Work from these descriptions; do not
  open the image files (the shipped writer is text-only, so this run must be too).
- `instruments.yaml`: the one instrument this studio can make work with, and what it can do.

Write, in plain markdown, in this folder:
1. `STUDIO.md`: field; the owner's sentence verbatim; the studio's ethos in your words (what it
   believes, its idiom, the moves that make a piece unmistakably this studio's, what it refuses by
   name). Ground every claim about the idiom in specific references by number (e.g. "ref 07").
   Two headings are read by code, so use them exactly: `## What makes a picture unmistakably ours` (one
   paragraph) and `## What the studio refuses, by name` (a list, each item starting with a **bold name**).
2. `JURY.md`: what this studio kills and why, as concrete checks a reviewer can apply to one image
   (not adjectives). Include the generic failures any image model drifts toward in this field.
3. Fill in the `history/` files with their headers only: `RULES.md` (binding rules, appended after
   each round once the owner approves them), `LESSONS.md` (taste lessons). Leave `rounds.jsonl`
   empty.
4. Add to `instruments.yaml` a `settings:` block for this studio (anything the studio should always
   ask of the instrument), keeping the existing keys.

Do not invent history. Do not make any work yet. Finish with a five-line summary of the studio.
