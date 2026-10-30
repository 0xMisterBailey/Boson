# Forging from scratch: a new studio from pictures + a sentence, then a new scene on it

The short way, from real reference pictures: `tools/loop.py` runs steps 1-5 and the dot rounds as one command line,
pictures kept out of git; see [REAL-REFS.md](REAL-REFS.md). This page is the long way, step by step, for a studio
forged from pictures you made yourself and a scene built on it.

Run from the repo root, with a ComfyUI that has Boson loaded at `COMFY=http://127.0.0.1:8188`. Forged studios land in
`examples/<name>` (bundle one with `git bundle create examples/<name>.bundle --all` to share it), scenes in
`~/.cache/boson/scenes/<name>-scene`: both registries find them by name.

## A studio (name its field plainly: "Car photography", not a mood)

1. **Refs from the pictures** (free): `python3 tools/forge_refs.py ~/.cache/boson/forge-in/<name>/refs
   <your pictures>/*.png --why "what the owner loves in them"`. License per line: "owner's own (made
   for this studio)"; refuses a folder that already has refs.jsonl.
2. **Describe them** (one Gemini vision call per picture, a few cents each; `--agy` = an Antigravity plan, no
   key spend): `python3 tools/describe_refs.py ~/.cache/boson/forge-in/<name>/refs --field "<the field>"`.
   Resume-safe. The writer reads only these descriptions.
3. **Forge** (one writer call, Opus via `claude -p`, minutes; a re-queue loads, never forges twice). Either the app,
   `boson.forgeStudio({name, field, sentence, owner, refs})`, or a **Forge Studio** node on the canvas
   (`workflows/real-refs.json` has one): `path` = `<name>` (a bare name lands in `examples/`), `owner` (who, one line), `field`, `sentence`
   (the owner sentence), `refs` = `~/.cache/boson/forge-in/<name>/refs`, `instrument` and `commission` empty.
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
