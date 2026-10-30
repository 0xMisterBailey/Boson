# Boson app API (2026-10-20, studio side 2026-10-21, app routes 2026-10-24): the contract the visuals bind to

Boson's UI is a sidecar to ComfyUI. It reads the repos through read-only routes and acts only by setting widgets on
the graph's own Boson nodes and queueing that graph (the nodes are the only writers; SPEC v3 I1). Any skin, the v4
visuals included, binds to three things and nothing else:

1. the **read routes** below (JSON, GET, same origin as ComfyUI);
2. **`boson/web/client.js`**: `bosonClient({ base, app })`, the reads plus every write verb;
3. the **node names and widget names** the client sets (listed per verb), so a graph built by hand works too.

The app at `/boson/app` (`boson/web/app/`, round 44) is a Boson layer over the live ComfyUI canvas (a same-origin
iframe of `/` that fills the screen): a rail of studios, scenes and the shelf, a view of the picked one (`room.js`
for a studio, `set.js` for a scene), a status line, and one toggle (the Graph button or the backquote key) that brings
the real canvas forward and back. While the layer is up it covers the canvas (ComfyUI's toasts, zoom control and
minimap included); Graph shows it full screen at a readable zoom. Picking a studio or scene loads its graph into the canvas (stored
modes, nothing queued). The frame contract (render signatures, `ui.js` helpers, theme tokens) is at the top of
`boson/web/app/shell.js`.

## Words

- **studio**: a git repo of plain files (STUDIO.md, JURY.md, history/, refs/, commission/), plates stored beside it in
  `<name>-plates/` (not in git). Found by name through the registry: `examples/*.bundle`, then the clone cache
  `~/.cache/boson/studios/*` (override: `$BOSON_STUDIOS`, `:`-separated). A bundle wins over its own clone.
- **scene**: a git repo holding `SCENE.json` and `takes/`. Registry: `examples/*-scene.bundle` (name without
  `-scene`), then `~/.cache/boson/scenes/*` (override `$BOSON_SCENES`). A bundle is cloned once into the cache and
  takes commit there.
- **piece**: `studio@sha:path`. `path` is a file in the studio's tree at `sha`, or a stored plate (the manifest's
  `file`, e.g. `r02/light-line-r02__d0__nb.png`) whose manifest row has `studio_sha` = `sha`. The sha is the commit
  that *made* the piece (for a repo file: the last commit that changed it), so a reference never moves.
- **take**: one commit of a scene: `takes/NN/image.jpg`, `cast.json` (`{slot: piece}`), `boxes.json` (Locate's output),
  `take.json` (`op`: `shoot` | `swap` | `import`, `parent`, `swapped`, `prompt`, `from`, `hash`). Never rewritten.
- **pending**: a cast set on the graph (Cast node widgets) that no take has committed yet. Pending lives only in the
  graph; the read API never reports it (the client's `graphState()` reads it from the widgets).
- **box**: `[x, y, w, h]`, fractions of the frame, everywhere. A flat slot's located items also carry `quad`:
  four `[x, y]` corners, top-left, top-right, bottom-right, bottom-left.

## SCENE.json

```json
{ "name": "street", "aspect": "16:9",
  "base": { "studio": "tenfoot-photographs", "ref": "8f5006c1", "view": "commission/view.png",
            "view_noun": "architect's model view", "medium": "a photograph", "subject": "building",
            "subject_desc": "...", "lock_edges": "...", "lock_edges_short": "...",
            "handed": "one sentence fixing left/right.", "handed_short": "...", "handed_anchor": "corner-block", "handed_side": "right",
            "materials": "optional, appended to WORLD", "world": [0.0, 0.312, 0.927, 0.347],
            "anchors": { "corner-block": "the tall rust-brown corner block at the right end of the strip" } },
  "slots": [
    { "id": "car", "role": "Car", "kind": "object", "studio": "estran-cars", "piece": "estran-cars@8e9036e7:r02/light-line-r02__d0__nbn.png",
      "noun": "the car", "short": "invented coupe", "desc": "what Locate looks for", "includes": "its wheels",
      "stand_in": "car | figure | box", "carrier": "optional: worn by ...",
      "place": { "anchor": "corner-block", "line": "parked nose-out in ...", "box": [0.70, 0.65, 0.14, 0.20] } },
    { "id": "posters", "role": "Poster", "kind": "flat", "count": 3, "aspect": "2:3", "short": "bill", "plural": "bills",
      "place": { "anchor": "windows", "line": "taped inside ...", "boxes": [[0.27, 0.53, 0.02, 0.06]] }, "...": "..." } ] }
```

Required per slot: `id`, `role`, `kind`, `studio`, `piece`, `noun`, `place.line`, `place.box` (object) or
`place.boxes` (flat). `slot.studio` is who makes that slot's pieces; `slot.piece` is where the current pixels come
from (they can differ: the street's outfit is still TENFOOT's own commission crop). `base.world` is Locate's box of the
building on the view itself; takes whose building moves more than that are reported in `checks.world_drift`.

## Read routes

All JSON routes answer `{"error": "..."}` with status 400 instead of a 500 page. Image routes answer 404 for anything
that is not an image inside its repo or plates folder.

| Route | Returns |
|---|---|
| `GET /boson/studios` | `[{name, repo, sha, rounds, rules, taste: {words, style_lines, subjects}, shelf}]` (a broken studio: `{name, repo, error}`) |
| `GET /boson/loop?repo=&ref=main` | the studio's loop rounds (LOOP.jsonl; the room's history and open round), below |
| `GET /boson/studio?repo=&ref=main` | the panel's studio state: `studio, ref, sha, round, verdict, drafted, rounds, rules, awaiting, proposed, plates[{id, title, file, renderer}], taste` (the house, below), `shelf`, `makes[{key, frame, idea, like, sha, pieces[{piece, file, title}]}]` |
| `GET /boson/plate?repo=&file=` | one stored plate (image) |
| `GET /boson/scenes` | `[{name, repo, sha, takes, base, slots[{id, role, kind, studio, piece}]}]` |
| `GET /boson/scene?repo=NAME_OR_PATH&ref=main` | `{name, repo, ref, sha, spec (SCENE.json, each slot + image url), takes[{id, op, parent, swapped, cast, boxes, from, frame, renderer, image}], clips[]}` |
| `GET /boson/take?repo=&take=NN&ref=` | a take's image from that commit |
| `GET /boson/clip?repo=&clip=NN&ref=main` | a committed clip's mp4 (read-only) |
| `GET /boson/motion?repo=&take=&prompt=` | `{graph (API format, tools/motion_workflow.build), has_key, cost}`: the motion graph for a take; reads only |
| `GET /boson/piece?ref=studio@sha:path` | a piece's image |
| `GET /boson/shelf` | `[{studio, piece, note, image}]`, every studio's kept pieces |
| `GET /boson/workflow?name=scene-street` | a shipped workflow (`workflows/NAME.json`: `scene-street`, `studio`), for `loadGraphData` |
| `GET /boson/scene-graph?repo=` | `{name, graph}`: the scene's graph built from SCENE.json now (API format, `tools/scene_workflow.build`), with a Cast node per slot; reads only |
| `GET /boson/ready?repo=` | `{scene, sha, slots, has_key, keys: {gemini, comfy}}`: no slot, the slot list and which keys live calls would find (never the keys). `has_key` is true when **any** key is present; a Comfy-only box still lacks the Gemini key Locate needs, so read `keys.gemini` before offering a Swap live |
| `GET /boson/ready?repo=&take=&slot=&idea=&frame=&n=&pieces=` | the above plus `take` (the take a Make crops, default newest), `parent` (the take a Swap edits: the chosen take, or the newest shoot if newer), `swaps[{piece, key, flat, stored, located, same?, later?}]` (one per piece, cast alone; `located` null = unknown; `later` = `{take, after: [{slot, piece}]}`, stored only for a take made after those swaps) and `makes[{studio, key, stored, pieces}]` (Make n for this spot, keyed as `commissionNew` sends it; no `idea`: none). Reads only, no call |
| `GET /boson/app` | the app: the Boson layer over the live canvas |

Two writes are routes, not nodes (a scene's chosen take and its slot list are pointers no node computes); each is one
commit of SCENE.json and answers the new scene state, as `GET /boson/scene`:

| Route | Does |
|---|---|
| `POST /boson/use-take {repo, take}` | the scene stands on that take (SCENE.json `chosen` + that take's cast): the next Swap edits it. Nothing deleted. Undo swap = use-take of the swap's parent |
| `POST /boson/remove-slot {repo, slot}` | a slot made from the frame (Add Slot) is part of the base again: its anchor comes back, every take stays. Refuses a slot the scene shipped with. The slot's pixels stay in any take that already swapped it |

## client.js

```js
import { bosonClient } from "/extensions/boson/client.js";
const boson = bosonClient({ app: () => frame.contentWindow.app });   // in the canvas page: () => window.app
```

Reads: `studios()`, `studio(repo, ref)`, `loop(repo, ref)`, `scenes()`, `scene(repo, ref)`, `shelf()`,
`workflow(name)`, `hasWorkflow(name)` (true when `workflows/NAME.json` ships), and the URL helpers `pieceUrl(ref)`,
`takeUrl(repo, take, ref)`, `plateUrl(repo, file)`, `clipUrl(repo, clip, ref)`; `motion(repo, take, prompt)` reads
the motion graph for a take; `sceneGraph(repo)` = `GET /boson/scene-graph`; `ready(scene, take, slot, {words, n,
pieces})` = `GET /boson/ready` with `idea` built exactly as `commissionNew` builds it (no slot: the slot list and
`has_key` only).

Graph: `ensureScene(repo, name = "scene-street", {casts})` loads the shipped workflow when the graph has no Load
Scene node (or, with `casts: true`, no Cast node: a motion graph holds Load Scene but no Casts), then points Load
Scene at `repo`, refusing to switch scenes while casts are pending; `syncScene(repo, slots)` reloads the graph from
`GET /boson/scene-graph` when a slot has no Cast node (a slot made since the workflow shipped). Every graph handed to
the canvas is rebuilt in the canvas's own window first (ComfyUI tells a link from a value with `instanceof Array`); `ensureStudio(repo)` loads `workflows/studio.json` unless the graph already holds
Draft Brief, then aims its Load Studio at `repo` (main), refusing while casts are pending; `loadMotion(graph, name)`
loads a motion graph from `motion()` (Load Scene -> Load Take -> Gemini Omni -> Commit Clip), refusing while casts
are pending. All three queue nothing.
`graphState()` lists pending casts `[{slot, piece}]` from the Cast widgets.

Writes (each sets widgets, then queues only the output node it names, with ComfyUI's partial execution). Verbs
take a studio or scene by name (looked up in `studios()` / `scenes()`) or by repo path. Studio verbs run on the
studio graph (`workflows/studio.json`): when the graph lacks the node they need, the client loads it, and refuses
to while Cast widgets hold pending casts (pending lives only in the graph). Each verb aims its node's upstream Load
Studio at the studio (`ref` main).

Scene side (scene graph, `ensureScene`):

| Verb | Sets | Queues | Cost |
|---|---|---|---|
| `cast(slot, piece, {desc, short})` | Cast (the one whose `slot` widget = slot): `piece`, `desc`, `short` | nothing: pending | free |
| `uncast(slot)` | that Cast's `piece` = "" | nothing | free |
| `stage(scene, slot, piece)` | = `cast`; slot `world`: Compile Scene `take` = the day sentence (`piece` or `{day}`) | nothing | free |
| `shoot({take, draws})` | Compile Scene `mode`=shoot, `take`; Nano Banana (the one with `shot` wired) `mode`=live, `draws`; Locate `mode`=live | Commit Take | one image call per draw + one vision call per take |
| `reshoot(scene, take, {draws})` | = `shoot` with the staged day | Commit Take | as shoot |
| `swap(scene?, take?, slots?)` | Compile Scene `mode`=swap; Nano Banana `mode`=live; Locate `mode`=live (refuses if `slots` is not exactly what is pending) | Commit Take | one image call (none if only flat slots changed) + one vision call |
| `locate()` | Locate `mode`=live | Locate | one vision call unless cached |
| `useTake(scene, take)` | nothing on the graph (pending casts are cleared by the app first) | `POST /boson/use-take` | free (a commit) |
| `removeSlot(scene, slot)` | that slot's Cast `piece` = "" if pending | `POST /boson/remove-slot` | free (a commit) |
| `commissionNew(scene, take, slot, {n})` | Load Take `take`; the Make wired from the Slot Crop whose `slot` = slot: `frame` = the slot's role, `idea` = "A new <short> for the spot in commission image 1: <place.line>", `n`, `mode`=live | that Make | one writer call + n image calls |
| `keep(studio, path, note)` / `unkeep(studio, piece)` | Keep Piece `path`, `note`, `op` keep / unkeep; its Load Studio | Keep Piece | free (a commit) |
| `run()` | nothing | the whole graph | stored modes: free |

Studio side (studio graph):

| Verb | Sets | Queues | Cost |
|---|---|---|---|
| `make(studio, frame, idea, n=4, {like})` | Make (the one with no `image_1` wired): `frame`, `idea`, `n`, `like`, `mode`=live | Make | one writer call (minutes) + n image calls; the same inputs again: free |
| `moreLike(studio, piece, n=4)` | = `make` with `like` = piece, no frame or idea | Make | as make |
| `editHouse(studio, field, value, op)` | Edit House `field`, `op` (default `set` for sentence, else `add`), `value` | Edit House | free (a commit; none if nothing changes) |
| `pin` / `unpin(studio, piece)` | = `editHouse(studio, "pins", piece, add / remove)` | Edit House | free |
| `addPicture(studio, piece)` | = `editHouse(studio, "pictures", piece, "add")` | Edit House | free |
| `newBranch(studio, kind, name)` | = `editHouse` add to `style_lines` (kind style) or `subjects` (kind subject) | Edit House | free |
| `runRounds(studio, {pieces, draws})` | Draft Brief `pieces`; the round's Nano Banana `mode`=live, `draws` | Verdict (waits quietly for the sentence) | one writer call + one image call per piece |
| `verdict(studio, round, text)` | Verdict `verdict`; the round's Nano Banana `mode`=stored. Refuses a round that is not the open, drafted one | Verdict | free (a commit) |
| `dots(studio, round, greens, reds, text)` | Dots `round`, `greens` and `reds` (one piece per line), `verdict`. Refuses an empty verdict or no dots | Dots | free (greens -> pins, the verdict row: commits, no call) |
| `digest(studio)` | the round's Nano Banana `mode`=stored | Digest | one writer call |
| `approve(studio, round, picks)` | Approve Rules `picks` = "NN: 1,3" | Approve Rules | free (a commit) |
| `forgeStudio({refs, sentence, field, owner, name, path, instrument, commission})` | Forge Studio widgets (`path` default `<name>`: a bare name lands in `examples/`, `instrument` "" = `tools/forge-template`) | Forge Studio | one writer call (minutes); docs/FORGE.md |
| `newScene({name, fromPiece, spec, path})` | New Scene widgets (`spec` an object or SCENE.json text) | New Scene | free (a commit) |

Which buttons a UI shows is the UI's call: the engine supports both verbs. The v4 design proposes **Swap** (pending
swaps applied by one edit, nothing else moves) and **Re-shoot** (a new day on the same set) as two buttons; that is
still the operator's decision.

## Nodes (pack `boson`, category `boson/scene`)

| Node | In -> out | Widgets |
|---|---|---|
| Load Scene | -> SCENE | `repo`, `ref` |
| Load Take | SCENE -> IMAGE, BOSON_BOXES, STRING | `take` (empty = newest) |
| Cast | SCENE -> SCENE | `slot`, `piece`, `desc`, `short` |
| Compile Scene | SCENE -> BOSON_SHOT, IMAGE (list), STRING prompt | `mode` shoot / swap, `take` |
| Nano Banana (Boson) | STUDIO (the base), optional `shot` -> IMAGE (list), STUDIO | `mode` stored / live, `draws`, `backend` |
| Locate | IMAGE, SCENE -> BOSON_BOXES, STRING | `mode` stored / live, `model` (default `gemini-3.8-flash`) |
| Slot Crop | IMAGE, BOSON_BOXES -> IMAGE | `slot`, `item`, `pad` |
| Paste Flat | IMAGE, BOSON_BOXES, SCENE, optional IMAGE `flat` -> IMAGE | `slot`, `glass` |
| Commit Take | SCENE, IMAGE, BOSON_BOXES, optional BOSON_SHOT -> SCENE | |
| Keep Piece | STUDIO -> STUDIO, STRING | `path`, `note`, `op` keep / unkeep |
| New Scene | -> SCENE | `name`, `spec` (SCENE.json), `from_piece`, `path` |
| Make (pack `boson`) | STUDIO, optional IMAGE x4 (commission) -> IMAGE (list), STRING pieces, STUDIO | `frame`, `idea`, `n`, `mode` stored / live, `like`, `backend` |
| Edit House (pack `boson`) | STUDIO -> STUDIO, STRING | `field`, `op` add / remove / set, `value` |

Quiet stops (ComfyUI's ExecutionBlocker, no red error): Nano Banana `stored` with a shot never rendered; Locate
`stored` on a take never located; Compile Scene `swap` with nothing cast; Keep Piece with no path; Make with no idea,
frame or like, or `stored` and never made; Edit House with no value; New Scene with no name or no spec/piece.

### Make

Not a round: the writer (`boson/tasks/make.md`) reads the whole studio (STUDIO.md, JURY.md, refs' `vlm` text,
TASTE.json, RULES, LESSONS, past verdicts) and writes n render specs; nothing is committed, so no verdict waits and
the branch never moves. Specs are cached in `~/.cache/boson/makes/<key>/` (MAKE.json says what for); key = studio sha
+ frame + idea + n + like + pins + commission image bytes. Plates go beside the studio as
`<name>-plates/rmake-<key>/<id>__d0__nbn.png` with manifest rows (`studio_sha`, `prompt`), so a made piece is a piece
(`studio@sha:rmake-<key>/...`) that Keep, Pin, Cast and More like accept. Renderer images, in order: the `like`
piece, the house pictures, the pins, wired commission images (at most 10); none of these = the studio's own
`commission_refs`. The writer is text-only: it sees the like piece's prompt and the pins' names, not their pixels.

**Writer and cost.** Make uses the pack's one writer, `boson/writer.py`: Claude Opus 5.5 through an isolated
`claude -p` (`$BOSON_WRITER` picks another Claude model). Measured on the archived proof-of-concept rounds (same
writer, same studio reading, 4-8 specs): **$0.82-1.25 and 3-6 minutes per call**; every call's cost is in MAKE.json
(`cost_usd`). Why not the local Qwen3.8 that won the 2026-10-17 writer test: that was a one-shot slate, while this
writer works the studio's files in an agent harness, and `writer.py` drives only `claude -p` today; the operator's
model ladder (2026-10-19) says start on the best model and tune down once the capability works. A local writer
(Qwen3.8 in an open harness; T10/T11 show the harness matters) is the next rung and an open item, not built.

### What Compile Scene sends (deterministic, tested byte for byte)

- **shoot**: image 1 = the blocking plate (the base view at the scene aspect; each object slot drawn as a grey line
  stand-in at its box, each flat slot as a pale rectangle), then each object slot's piece in SCENE.json order. Flat
  slots send no image. Prompt blocks: LOCK, IMAGES, SLOTS, WORLD (the base studio's "unmistakably ours" paragraph +
  `base.materials` + its `style_lines`), TAKE, REFUSE (the bold names of its "refuses, by name" list), LOCK. An empty
  `take` leaves `<<TAKE>>`; Nano Banana then fills it with each drafted piece's prompt (wire Draft Brief).
- **swap**: image 1 = the last shoot (or imported) take, then the new pieces of the object slots swapped since it.
  The prompt names each swapped slot at its **Locate box in that take**. Only flats swapped: no prompt, no call;
  Nano Banana passes the take through, and Commit Take commits a new take with the parent's pixels and the new cast
  (the flat is drawn on its located quads when shown: `GET /boson/take` `&paste=1`).

Fixtures: `tests/fixtures/street-shoot.prompt.txt`, `street-swap.prompt.txt`, `locate-street-take.json` (one real
Gemini Locate reply).

## Studio taste fields = the house (optional, backward compatible)

`TASTE.json` at a studio's root: `{"sentence": str, "words": [str], "style_lines": [str], "principles": [str],
"subjects": [{"name": str, ...}], "pictures": [piece], "pins": [piece]}`. Every key is optional; absent reads as an
empty list, and `sentence` falls back to the owner's sentence in FORGE-INPUT.md. Edit House is the only writer (one
commit per change). `style_lines` reach a scene's WORLD block when the studio is a scene's base; `pictures` and `pins`
reach every Make as images.

## Differences from design/v4/proto/API.md (deliberate)

1. **No write routes.** The brief allowed server routes where a write needs one; none does. Every write is a node
   (SPEC I1); the server only gained reads (`makes`, the house in `taste`, the `studio` workflow).
2. **Names are camelCase** in JS: `more_like` -> `moreLike`, `edit_house` -> `editHouse`, `add_picture` ->
   `addPicture`, `new_branch` -> `newBranch`, `run_rounds` -> `runRounds`, `forge_studio` -> `forgeStudio`,
   `new_scene` -> `newScene`, `commission_new` -> `commissionNew`.
3. **`place`** (drop on the board) and **`open_graph`** are the skin's: board layout and the canvas toggle are UI
   state, not repo state. No verb.
4. **`stage(scene, "world", {day})`**: the day is a TAKE sentence for the next re-shoot, not another take's image.
5. **`swap(scene, take, slots)`** applies what is pending on the graph; `take` is ignored (always the last shoot),
   `slots` is a check. **`reshoot(scene, take)`**: `take` is ignored (the next take number is the repo's).
6. **`edit_house(field, value)`** gains `op` (add / remove / set). Removal is by value, not the proto's `remove i`.
   Fields: sentence, words, style_lines, principles, subjects, pictures, pins.
7. **`new_branch(kind)`** needs a `name`: a style line or subject is a named entry in the house.
8. **`forge_studio(pictures, sentence)`** takes a refs folder (made from pictures by `tools/forge_refs.py`, described
   by `tools/describe_refs.py`), plus the `field` Forge requires and a `name`. See docs/FORGE.md.
9. **`new_scene(from_piece)`** also takes `spec` (a whole SCENE.json); from a piece alone the scene has no slots yet.
10. **`commission_new`** renders through a Make wired from the slot's Slot Crop (`workflows/scene-street.json` nodes
    24-25); flat slots (posters) have no Slot Crop yet, so it refuses them.
11. **Added, not in the proto:** `unpin`, `digest`, `approve` (the round loop's other two steps), `uncast`, `locate`.
12. **Pending is scene-only.** A pin, a picture, a house edit is a commit at once; studios have no pending state.

## Shelf

`SHELF.jsonl` at a studio's root, one `{"piece", "note"}` per line, appended by Keep Piece (`studio.keep`), one commit
each, idempotent per piece. `/boson/shelf` merges every studio's at `main`. Dragging a shelf piece into a slot is
`cast(slot, piece)`.

## The room: the taste loop in the graph (round 44)

The owner's dots used to happen outside ComfyUI (`tools/loop.py dots` serves the grid in `tools/feedback_engine/`, and still does). Now the studio
view (`boson/web/app/room.js`) dots the open loop round and a node commits it, so every verdict binds the next round
from inside the graph.

**Dots** (`BosonDots`, `boson/round_nodes.py`; in `workflows/studio.json` as node 14, Load Studio -> Dots). Inputs:
`studio`, `round` (INT), `greens`, `reds` (one `studio@sha:path` per line), `verdict` (the one sentence). Outputs:
`studio` (after the commits) and `brief` (the next make's idea). It calls `studio.commit_dots`, the one function
`tools/loop.py next` also calls before it makes: the greens become the house pins (`edit_house(pins, set)`, one
TASTE.json commit, none without greens), then the verdict row `{round, verdict, greens, reds, notes}` is appended to
LOOP.jsonl and committed (`loop: round N verdict (g green, r red)`). An empty verdict or no dots: the node returns
`ExecutionBlocker(None)` and says what it waits for (I2). Refused, nothing committed, shown on the node: a round that
is not the open one, a piece not in it, a piece both green and red, a moved branch. Re-queued with the same sentence
it commits nothing; a judged round keeps its verdict (I3). **It never makes the next round**: that is a writer call
plus n image calls, so the room shows Next disabled with its cost; its verb would be `make(studio, frame, brief, n)`.

**`GET /boson/loop?repo=&ref=main`** -> `{studio, repo, ref, sha, taste, open, rounds[]}`. `open` = the round waiting
for dots (null when the last is judged). Each round: `round, make, studio_sha, frame, idea, base_idea, n, pins`
(what it saw), `pieces[{piece, file, title, renderer, image, dot: green|red|null, note}]`, `verdict, greens, reds`,
`brief` (the next brief, once judged), and `change = {from, to, files, diff, house}`: from the round's studio commit
to the next round's (the last round: to `ref`), `diff` = `git diff` of STUDIO.md and TASTE.json, `files` = which of
them changed, `house` = `{field: {added, removed}}` per taste list (and `sentence: {from, to}`).

**The room** (`renderStudio`): the house first and editable through Edit House (the sentence, words, style lines,
pins, house pictures: remove on each, add by typing or from a round's piece; each edit is one free commit). The open
round as a grid: click (or Space) = green, again = red, again = clear; a literal text slot for the verdict; Submit
sets Dots and queues only it, then the view reloads from the repo and the node's line lands on the status line.
History: for each judged round, its verdict sentence beside what it changed (TASTE.json pins added and removed,
STUDIO.md) and what the next round made, r1 -> r2 -> r3. Every picture carries its provenance (`studio@sha`, the
renderer); found reference photos are labelled private. Dots in progress survive a re-render (sessionStorage).
