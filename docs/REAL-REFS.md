# Real references in, new work out

You put real pictures you love in a folder. Boson forges a studio from them and your one sentence, makes a first
round, you dot it on the grid and write one verdict, and the greens and the verdict steer the next round. One
command per step, from a terminal in the repo root. No agent needed.

**Before the first run (once):** a Claude login for `claude -p` (the writer, Opus), and the Gemini key in
`~/.config/gemini/api_key` (describing the pictures and Nano Banana renders). The pictures stay on your machine.

## The steps

**0. Collect** (your time, 30-60 min per studio). Put 20-40 pictures (jpg, png, webp) in
`refs-private/fashion/` in the repo root (or `posters/`, or a new folder). The folder is never committed. To keep where a
picture came from (the studio then ships its link, never the picture), any of these works:
- a file `urls.txt` in the folder, one line per picture: `coat.jpg https://the.page/it/came/from` (the sure way)
- a file next to the picture with the same name: a link dragged from the browser's address bar into the folder
  (`coat.desktop` or `coat.url`; rename it to match the picture), or `coat.txt` with the link in it.
- some browsers record the page on the downloaded file by themselves; check one with
  `getfattr -d coat.jpg` before relying on it (a `user.xdg.referrer.url` line = recorded).
A picture with no link still works; its line just has no url.

**0b. Or let agents gather.** Agents fill `refs-private/candidates/<name>/` (pictures, `urls.txt`, `why.tsv`
= `file<TAB>lane<TAB>why`); you pick:
```
python3 tools/curate.py cars grid --port 8773     # dot the candidates, type one direction sentence on the last card
python3 tools/curate.py cars keep                 # greens -> refs-private/cars/ with their links; prints the direction
```
Duplicates are dropped on the grid; a re-gather into the same folder keeps your earlier dots.

**0c. Or roll a taste seed** (free, no network). No pictures of your own yet? A number picks a studio's
starting references from an agent-gathered pool, the way a Midjourney `--sref` number picks a style:
```
python3 tools/seed.py roll cars --field "Car photography" --seed 4471   # -> refs-private/cars-s4471/
python3 tools/seed.py show cars --seed 4471      # the picks only, nothing copied
```
The same pool and seed always give the same pictures; no `--seed` rolls a fresh one and prints it. Forge it as in
step 1 with the command it prints (the sentence is assembled from the field and the drawn lanes, never written
by an agent); `SEED.json` is committed into the studio, so its history says its start was
noise. Your dots and verdicts decide everything after.

**0d. Or ignite** (~$0.73 on Comfy credits, ~10 min of dots). Not sure what you want either? One blind
round puts the image model's own default, the writer's dodge of it, and three seeds side by side on one plain brief;
your dots pick which seeds' pictures start the studio, and `IGNITION.json` is committed with it:
```
python3 tools/ignite.py cars run --field "Car photography"   # plan + 10 pictures + the blind deck
python3 tools/ignite.py cars dots                            # dot blind, verdict under the last card
python3 tools/ignite.py cars read                            # reveal, then the forge command
```

**1. Forge the studio** (~5-10 min, about $0.30-0.90 for 20-40 pictures):
```
python3 tools/loop.py fashion forge --field "Fashion photography" --aspect 4:5 \
  --sentence "One sentence: what this studio's work must be, naming the genre plainly."
```
It copies the pictures into a private working folder, describes each one (one vision call, about a cent each; add
`--agy` to use an Antigravity plan instead of the key), then the writer reads the descriptions and writes the
studio: `examples/fashion-real/STUDIO.md` (its practice and what it refuses) and `JURY.md`. `--aspect`: 4:5 suits fashion, 2:3 posters, 1:1 the default.
Stopped half way? Run the same command again: it resumes and never pays twice. A busy Gemini is retried by itself; a forge that died before it finished is set aside (`<name>-real.unfinished-<time>`) and redone. Every step that may call the writer first checks the Claude login (~6 s); if it says "log in again", run `claude`, type /login, then rerun the step.

**2. Make the first round** (~3-5 min, about $0.70 for 6 pictures):
```
python3 tools/loop.py fashion make --idea "an outfit for a rainy morning commute" --n 6
```
One writer call, then six Nano Banana pictures at 1K, in `examples/fashion-real-plates/`.

**3. Dot it** (your time, ~5 min):
```
python3 tools/loop.py fashion dots
```
Open the link it prints (`http://127.0.0.1:8772/`) in a browser. Left-click = green (make
more like it), right-click = red (not this), the same click again clears it, double-click enlarges. Under any picture
you can type a note. The last card says **ROUND VERDICT**: type one or two sentences in the box under it (what the round
got right, what it must stop) and press Enter. Everything saves as you click. Done: Ctrl-C in the terminal.

**4. The next round** (~3-5 min, about $0.70):
```
python3 tools/loop.py fashion next
```
Your greens become the studio's pins (the writer reads their names, the renderer sees the pictures), your verdict,
the reds and your notes go into the next make's brief, all committed to the studio's history (`LOOP.jsonl`,
`TASTE.json`). It stops and says so if the verdict is missing: the verdict is always your own words. Then step 3 again.

**Anytime:** `python3 tools/loop.py fashion status` (rounds, dots, verdicts, money spent so far, from
`~/.cache/boson/loop/fashion-real/spend.jsonl`); `python3 tools/loop.py fashion check` (proves no studio holds a
picture from refs-private; run it before bundling or publishing anything).

## The same rounds in ComfyUI

Each make also writes a small graph: `~/.cache/boson/loop/fashion-real/r1/graph.json`. In ComfyUI (Workflow > Open)
it shows that round on the canvas: Load Studio at the round's commit -> Make (stored, no cost) -> the pictures.
`workflows/real-refs.json` is the whole path as one graph (Forge Studio -> Make, then Edit House pins -> Make) for
working on the canvas instead; it needs step 1's prepared pictures folder, and its Make nodes run paid only when you
switch `mode` to `live`. The dot grid is a separate page (the feedback engine), not a node.

## Money, in one place
Describe ~$0.01 a picture (estimate). Forge: one writer call, $0.26-0.51 measured. Each make: one writer call
($0.48-1.00 measured 10-22/23; more with more pins and notes) + $0.06 a picture at 1K, so $0.85-1.40 a round of 6. Forge + a first round + two more: about $4-4.50 per studio.

## Privacy
The pictures in `refs-private/` and the working copy in `~/.cache/boson/forge-in/` never enter git. The studio's
`refs/refs.jsonl` keeps each picture's link, the description and the license line "found reference, private, not
redistributed"; its `refs/.gitignore` keeps the images out. `python3 tools/loop.py NAME check` proves it for every
studio repo and bundle in `examples/`.
