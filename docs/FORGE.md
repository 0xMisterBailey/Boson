# Forging from scratch: a new studio from pictures + a sentence, then a new scene on it

Real references the owner found (round 39): `tools/loop.py` runs steps 1-5 and the dot rounds as one CLI, pictures
kept out of git; runbook `docs/REAL-REFS.md`.

No proof-of-concept studio is needed (tests/test_house.py does all of it in tmp). Run from `~/Boson` with
`COMFY=http://127.0.0.1:8188` (the GPU ComfyUI; it lists the Boson nodes since 2026-10-21). Forged studios land in
`~/Boson/examples/<name>` (operator 2026-10-21: they ship with the entry; gitignored as repos, bundled to
`examples/<name>.bundle` at milestones), scenes in `~/.cache/boson/scenes/<name>-scene`: both registries find them by name.

## A studio (per green-dot set; field named plainly, memory feedback--seed-sentence-names-genre-plainly)

1. **Refs from the pictures** (free): `python3 tools/forge_refs.py ~/.cache/boson/forge-in/<name>/refs
   design/reforge/<the green dots>/*.png --why "what the owner loves in them"`. License per line: "owner's own (made
   for this studio)"; refuses a folder that already has refs.jsonl.
2. **Describe them** (one Gemini vision call per picture, a few cents each; `--agy` = the box's Antigravity, no
   key spend): `python3 tools/describe_refs.py ~/.cache/boson/forge-in/<name>/refs --field "<the field>"`.
   Resume-safe. The writer reads only these descriptions.
3. **Forge** (one writer call, Opus via `claude -p`, minutes; a re-queue loads, never forges twice). Either the app,
   `boson.forgeStudio({name, field, sentence, owner, refs})`, or the graph:
   ```
   python3 -c "import sys; sys.path.insert(0,'tests'); from comfy_smoke import run; print(run({'1': {'class_type':
   'BosonForgeStudio', 'inputs': {'path': '~/Boson/examples/<name>', 'owner': '<who, one line>',
   'field': '<the field>', 'sentence': '<the owner sentence>', 'refs': '~/.cache/boson/forge-in/<name>/refs',
   'instrument': '', 'commission': ''}}})['outputs']['1']['text'])"
   ```
   `instrument` "" = `tools/forge-template/` (Nano Banana, 1:1, 2K). For another aspect or a field-specific
   instrument, copy that folder, edit `render.json` (`aspect`, `width`, `height`, `instrument` text) and pass its path.
4. **Check**: `curl -s 127.0.0.1:8188/boson/studios` lists `<name>` with no `error`; `STUDIO.md` has the sections
   "What makes a picture unmistakably ours" and "What the studio refuses, by name" (a scene's WORLD and REFUSE
   blocks read them; missing = empty blocks, no error).
5. **House + first pieces** (app or graph `workflows/studio.json`): `editHouse` words / style_lines / subjects;
   `make(name, frame, idea, 4)` = one writer call + 4 image calls; pieces come back as `<name>@<sha8>:rmake-<key>/...`.

## The scene

6. **The base view**: the architecture studio makes it (`make(arch, "", "the scene's view: <one line>", 4)`); pick one
   piece `arch@<sha8>:rmake-<key>/<id>__d0__nbn.png`. Base `ref` must be r00 or later (its STUDIO.md is read there).
7. **SCENE.json** (shape: docs/APP-API.md): `base` = `{"studio": "arch", "ref": "<sha8>", "view": "rmake-<key>/..."}`
   plus `view_noun`, `medium`, `subject`, `anchors`; each slot's `studio` = the studio that makes it, `piece` = one of
   its made pieces, `place.box` / `place.boxes` as frame fractions. Then `boson.newScene({name, spec})` or a
   `BosonNewScene` prompt as in step 3 (`name`, `spec` as JSON text, `from_piece` "", `path` ""). Only a piece:
   `newScene({name, fromPiece})` = that view, no slots (add slots by a new scene from the full spec; takes never move).
8. **Its workflow** (free): `python3 tools/scene_workflow.py ~/.cache/boson/scenes/<name>-scene` writes
   `workflows/scene-<name>.json` (+ `.api.json`): one Cast per slot, the base studio's shot, Locate, Commit Take,
   per object slot a Slot Crop -> Make (commission new). App: `ensureScene(repo, "scene-<name>")`.
9. **First take**: `shoot({take: "<hour, weather, street life>"})` = one image call + one Locate vision call.
   Swaps after that: `stage` then `swap()` (one edit call, none for flat slots) or `reshoot`.

## Spend summary
Free: steps 1, 4, 7 (git), 8. Paid: describe (vision, per picture), forge and every make (writer, minutes), each
make's n images, each shoot/swap (one image) + Locate (one vision call per take).

Round 1 of the reforge ran steps 1-5 for six studios in one script: `design/reforge/forge/run.py`.
