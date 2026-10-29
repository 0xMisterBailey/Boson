Round {NN} has been made and the owner has written their verdict on it. Digest it into the studio's history.

Read: `STUDIO.md`, `JURY.md`, `history/RULES.md` (binding), `history/LESSONS.md`, `history/rounds.jsonl`,
and `history/round-{NN}/`: `VERDICT.md` (the owner's one sentence on the round as a whole: this is the
signal, weigh it above everything else), `BRIEF.md`, `specs/`, `SELF-ASSESSMENT.md`, and if present
`labels.jsonl` (per image: kept true/false, reason, note) and `ARGON-READ.md` or `OPEN-READ.md` (an
outside aesthetic read: input, not a verdict). Earlier rounds' folders too.

Then:
1. Append exactly one JSON line to `history/rounds.jsonl`:
   {"round": "{NN}", "name": ..., "fingerprint": ..., "verdict": "<VERDICT.md verbatim>", "kept": <n or
   null>, "total": <n or null>, "pieces": [{"series", "title", "kept": [...] or null, "tags": [...],
   "notes": [...]}], "reasons": "<one sentence: what the owner's verdict says>"}
   kept/total/pieces[].kept are null when there is no labels.jsonl. Change no earlier line.
2. Write `history/round-{NN}/RULES-PROPOSED.md`: up to 5 candidate binding rules for every later round,
   numbered `1.` `2.` ..., each one line starting "Must" or "Must not", concrete enough that a reviewer can
   check one image against it, each followed by an indented "evidence:" line quoting the verdict words
   (and the pieces) it comes from. Propose a rule only where the verdict supports it; zero is allowed.
   The owner approves rules; do NOT edit `history/RULES.md`.
3. Append to `history/LESSONS.md` a dated section for round {NN}: taste lessons (what this owner wants
   and refuses), each tied to the verdict and to pieces.
4. Write `history/round-{NN}/CRAFT-PROPOSED.md`: lessons about the instrument itself that would hold for
   any studio using it, or "none".
5. Write `history/round-{NN}/RULE-CHECK.md`: for each rule that was in RULES.md when the round was drafted,
   obeyed yes/no/partly, with evidence from the brief and specs.

Edit nothing else. Finish with a three-line summary.
