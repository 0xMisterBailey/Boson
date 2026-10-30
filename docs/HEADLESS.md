# Headless: a script or an agent in the judge's seat

The curation loop does not care who judges. In the app you dot pictures with the mouse; from a terminal,
`tools/loop.py` runs every step and `dot` takes the judgment as arguments. Whoever runs those commands, a person, a
script or an AI agent, sits in the judge's seat, and the studio records it the same way: greens become pins, the
sentence becomes a rule, every step a commit.

Two of the three shipped scenes were made this way on 2026-10-29, with no human in any seat:

- **Airless landing** (terrain, rockets, robots, skybox studios) and **mystic forest** (forest, temple, ancient tree,
  wizard). For each, four agents each gathered real open-licence photos from Wikimedia Commons (and NASA's public-
  domain imagery there), chose its references by looking at each one, forged a studio from them and one sentence,
  and ran three rounds: make, look, dot, verdict. One more agent then wrote the scene, placed its slots, cast a piece
  from each studio and shot the take (the forest scene also has one swap: the wizard).
- Every picture was drawn by FLUX 3 Klein on one RTX 4090, and the boxes were found by Qwen3.8 on the same card. The
  words (each studio's text, the photo descriptions) came from cloud models (Claude, Gemini). The forest run took
  about 80 minutes for four studios and the scene; its billed cloud calls (photo descriptions) came to about $0.93,
  and the writer ran on a Claude login.
- Every dot and verdict in those studios is an agent's judgment, not the author's taste, and says so: each verdict in
  their `LOOP.jsonl` and `STUDIO.md` starts with `AGENT verdict (<studio> worker):`.

## The steps

`NAME` is a folder of reference pictures in `refs-private/NAME/` (gitignored, never committed). The studio becomes
`examples/NAME-real`, a git repo of its own.

```bash
# 0. references: candidate photos from Wikimedia Commons, in lanes you design, licence per file (no NC, no ND)
python3 tools/gather_commons.py --out refs-private/candidates/NAME --lanes lanes.json --per-lane 6
#    keep the ones you choose in refs-private/NAME/ with their urls.txt and credits.jsonl

# 1. forge: the studio's practice (STUDIO.md), its checks (JURY.md), its references described; one writer call
python3 tools/loop.py NAME forge --field "Lunar surface photography" --aspect 3:2 \
    --sentence "Photographs of an airless surface: black sky, one hard sun, razor shadows." \
    --owner "AGENT terrain worker (not a human)"

# 2. make round 1: the writer reads the whole studio and writes n render specs; the backend draws them
python3 tools/loop.py NAME make --idea "the landing site at low sun" --n 4 --backend local

# 3. look: status lists the open round's piece ids and each picture's file
python3 tools/loop.py NAME status

# 4. judge: greens (more like these), reds (not this), one sentence on the whole round
python3 tools/loop.py NAME dot --green ID1,ID3 --red ID2 --verdict "AGENT verdict: keep the hard shadows; stop the haze."

# 5. next: greens become pins, the sentence a rule under STUDIO.md "From your verdicts", the next round is made
python3 tools/loop.py NAME next --backend local

# repeat 3-5; then prove no private reference picture reached any studio repo or bundle
python3 tools/loop.py NAME check
```

Each step is resume-safe: what is already on disk or in the studio's git is never bought twice, and a re-run of
`next` after its round was made shows the open round instead of making another. For a person at the terminal,
`loop.py NAME dots` serves the same judgment as a one-keypress grid in the browser.

`--backend` picks who draws: `local` (FLUX 3 Klein on `BOSON_LOCAL_COMFY`, open weights, $0), `api` (Nano Banana
2.1 on a Gemini key), `comfy-api` (the same on Comfy credits). The writer is `claude -p`, or an open model behind a
gateway (`BOSON_WRITER_BASE_URL`). See [CONFIG.md](CONFIG.md).

## The scene

A scene is a git repo too: `SCENE.json` (the base view, and the slots any studio can fill) and its takes.
`tools/scene_local.py` runs the scene graph's steps from a terminal on open weights (the picture model and the vision
model take turns on one 24 GB card), and blocks every cloud call in its process:

```bash
python3 tools/scene_local.py SCENE_REPO render shoot --take "Late afternoon, mist in the valley"   # Klein up
python3 tools/scene_local.py SCENE_REPO commit shoot --take "Late afternoon, mist in the valley"   # vision model up
python3 tools/scene_local.py SCENE_REPO render swap --cast wizard=STUDIO@SHA:PATH
python3 tools/scene_local.py SCENE_REPO commit swap --cast wizard=STUDIO@SHA:PATH
```

The result opens in the app like any scene, with each studio's three dotted rounds beside it.

## Guards worth copying into an agent's brief

- Gather only from open APIs with plain HTTP. Never route around a bot check, a login or a captcha: skip the site.
- Record a licence per photo (public domain, CC0, CC BY, CC BY-SA); refuse NC and ND. On the local backend each
  studio picture is drawn from two of the studio's own photos whose licence is public domain, CC0 or CC BY, so no
  plate is a share-alike derivative; CC BY-SA photos are used for descriptions only.
- Look at every picture before keeping or judging it.
- Name the seat: `--owner "AGENT ..."` and verdicts that start `AGENT verdict`, so nobody mistakes an agent's taste
  for a person's.
- Name the field's genre plainly in the sentence; an anti-cliche sentence with no genre washed out an early studio.
- End with `loop.py NAME check`.
